"""SQLite-backed task queue store."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_DIR = Path(".cq")
DEFAULT_DB_NAME = "queue.db"

VALID_STATUSES = {"pending", "in_progress", "completed", "failed"}
VALID_POLICIES = {"continue", "new"}

# Override for the root directory used by ``default_db_path()``. When set, it
# takes precedence over ``Path.cwd()`` so that a long-running process (like the
# TUI) keeps using the directory it was started from, even if the working
# directory changes later.
_root_dir: str | None = None


def set_root_dir(path: str | None) -> None:
    """Set the root directory used by ``default_db_path()``.

    Pass ``None`` to clear the override and fall back to ``Path.cwd()``.
    """
    global _root_dir
    _root_dir = path


def default_db_path() -> Path:
    """Return the default queue database path.

    If a root directory has been set via :func:`set_root_dir`, it is used;
    otherwise the current working directory is used.
    """
    base = Path(_root_dir) if _root_dir is not None else Path.cwd()
    return base / DEFAULT_DB_DIR / DEFAULT_DB_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate_drop_session(conn: sqlite3.Connection) -> None:
    """Drop the legacy ``session`` column from older databases.

    SQLite does not support ``ALTER TABLE DROP COLUMN``, so we recreate the
    table and copy the data over.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks);")}
    if "session" not in columns:
        return

    conn.execute(
        """
        CREATE TABLE tasks_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','in_progress','completed','failed')),
            context_policy TEXT NOT NULL DEFAULT 'continue' CHECK(context_policy IN ('continue','new')),
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            result TEXT,
            error TEXT
        );
        """
    )
    conn.execute(
        """
        INSERT INTO tasks_new (
            id, description, status, context_policy, created_at,
            started_at, completed_at, result, error
        )
        SELECT
            id, description, status, context_policy, created_at,
            started_at, completed_at, result, error
        FROM tasks;
        """
    )
    conn.execute("DROP TABLE tasks;")
    conn.execute("ALTER TABLE tasks_new RENAME TO tasks;")


def init_db(path: Path | str | None = None) -> Path:
    """Create the queue database and schema if they do not exist.

    Returns the resolved database path.
    """
    if path is None:
        db_path = default_db_path()
    else:
        db_path = Path(path)

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','in_progress','completed','failed')),
                context_policy TEXT NOT NULL DEFAULT 'continue' CHECK(context_policy IN ('continue','new')),
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                result TEXT,
                error TEXT
            );
            """
        )
        _migrate_drop_session(conn)
        conn.execute("DROP INDEX IF EXISTS idx_tasks_session_status_created;")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at);"
        )
        conn.commit()
    finally:
        conn.close()

    return db_path


def _connect(path: Path | str | None = None) -> sqlite3.Connection:
    if path is None:
        db_path = default_db_path()
    else:
        db_path = Path(path)

    if not db_path.exists():
        raise FileNotFoundError(
            f"Queue database not found at {db_path}. Run 'cq init' first."
        )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def add_task(
    description: str,
    context_policy: str = "continue",
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Add a new pending task and return its record."""
    if context_policy not in VALID_POLICIES:
        raise ValueError(f"Invalid context_policy: {context_policy}")

    conn = _connect(path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO tasks (description, status, context_policy, created_at)
            VALUES (?, 'pending', ?, ?);
            """,
            (description, context_policy, _now()),
        )
        conn.commit()
        task_id = cursor.lastrowid
        return get_task(task_id, path=path)
    finally:
        conn.close()


def get_task(task_id: int, path: Path | str | None = None) -> dict[str, Any] | None:
    """Return a single task by ID, or None if not found."""
    conn = _connect(path)
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?;", (task_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def claim_next(path: Path | str | None = None) -> dict[str, Any] | None:
    """Atomically claim the oldest pending task and return it.

    Returns None if no pending tasks exist.
    """
    conn = _connect(path)
    try:
        # Use an explicit transaction with immediate locking for atomicity.
        conn.execute("BEGIN IMMEDIATE;")
        try:
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1;
                """
            ).fetchone()

            if row is None:
                conn.commit()
                return None

            task_id = row["id"]
            now = _now()
            conn.execute(
                """
                UPDATE tasks
                SET status = 'in_progress', started_at = ?
                WHERE id = ?;
                """,
                (now, task_id),
            )
            conn.commit()

            return get_task(task_id, path=path)
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def claim_task(
    task_id: int,
    path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Atomically claim a specific pending task by ID.

    Returns the task if it was pending and is now in_progress, otherwise None.
    """
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        try:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = 'in_progress', started_at = ?
                WHERE id = ? AND status = 'pending'
                RETURNING *;
                """,
                (_now(), task_id),
            )
            row = cursor.fetchone()
            conn.commit()
            return _row_to_dict(row) if row else None
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def complete_task(
    task_id: int,
    status: str = "completed",
    result: str | None = None,
    error: str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Mark a task as completed or failed."""
    if status not in {"completed", "failed"}:
        raise ValueError(f"Invalid completion status: {status}")

    conn = _connect(path)
    try:
        conn.execute(
            """
            UPDATE tasks
            SET status = ?, completed_at = ?, result = ?, error = ?
            WHERE id = ?;
            """,
            (status, _now(), result, error, task_id),
        )
        conn.commit()

        task = get_task(task_id, path=path)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        return task
    finally:
        conn.close()


def cleanup_completed_tasks(
    age_hours: int = 24,
    path: Path | str | None = None,
) -> int:
    """Delete completed tasks older than `age_hours` hours.

    Returns the number of deleted rows. Passing ``age_hours <= 0`` deletes
    all completed tasks.
    """
    conn = _connect(path)
    try:
        if age_hours <= 0:
            cursor = conn.execute("DELETE FROM tasks WHERE status = 'completed';")
        else:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(hours=age_hours)
            ).isoformat()
            cursor = conn.execute(
                "DELETE FROM tasks WHERE status = 'completed' AND completed_at < ?;",
                (cutoff,),
            )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def reset_tasks(
    include_in_progress: bool = True,
    include_failed: bool = False,
    path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Reset in_progress (and optionally failed) tasks back to pending."""
    statuses = []
    if include_in_progress:
        statuses.append("in_progress")
    if include_failed:
        statuses.append("failed")

    if not statuses:
        return []

    conn = _connect(path)
    try:
        placeholders = ",".join("?" for _ in statuses)
        cursor = conn.execute(
            f"""
            UPDATE tasks
            SET status = 'pending', started_at = NULL, completed_at = NULL, result = NULL, error = NULL
            WHERE status IN ({placeholders})
            RETURNING id;
            """,
            statuses,
        )
        ids = [row["id"] for row in cursor.fetchall()]
        conn.commit()
        return [get_task(task_id, path=path) for task_id in ids]
    finally:
        conn.close()


def list_tasks(
    status: str | None = None,
    limit: int = 50,
    path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return recent tasks, optionally filtered by status."""
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"Invalid status filter: {status}")

    conn = _connect(path)
    try:
        if status:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (limit,),
            ).fetchall()

        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def update_task(
    task_id: int,
    description: str | None = None,
    context_policy: str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Update a task's description and/or context policy.

    If the task was completed or failed, it is reset to pending and its
    previous output is cleared so the updated task can be run again.
    In-progress tasks cannot be edited while they are running.
    """
    task = get_task(task_id, path=path)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    if task["status"] == "in_progress":
        raise ValueError(f"Task {task_id} is in progress; wait for it to finish")

    if description is None and context_policy is None:
        raise ValueError("Nothing to update")

    if context_policy is not None and context_policy not in VALID_POLICIES:
        raise ValueError(f"Invalid context_policy: {context_policy}")

    updates: list[str] = []
    params: list[Any] = []

    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if context_policy is not None:
        updates.append("context_policy = ?")
        params.append(context_policy)

    # Reset completed/failed tasks so edits take effect on next run.
    if task["status"] in ("completed", "failed"):
        updates.extend(
            [
                "status = 'pending'",
                "started_at = NULL",
                "completed_at = NULL",
                "result = NULL",
                "error = NULL",
            ]
        )

    params.append(task_id)

    conn = _connect(path)
    try:
        conn.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?;",
            params,
        )
        conn.commit()
        updated = get_task(task_id, path=path)
        if updated is None:
            raise ValueError(f"Task {task_id} not found after update")
        return updated
    finally:
        conn.close()


def delete_task(
    task_id: int,
    path: Path | str | None = None,
) -> bool:
    """Delete a single task by ID.

    Returns True if a row was deleted.
    """
    conn = _connect(path)
    try:
        cursor = conn.execute(
            "DELETE FROM tasks WHERE id = ?;",
            (task_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_all_tasks(path: Path | str | None = None) -> int:
    """Delete all tasks from the queue.

    Returns the number of deleted tasks.
    """
    conn = _connect(path)
    try:
        cursor = conn.execute("DELETE FROM tasks;")
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
