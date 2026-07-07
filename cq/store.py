"""SQLite-backed task queue store."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_DIR = Path(".cq")
DEFAULT_DB_NAME = "queue.db"
DEFAULT_SESSION = "default"

VALID_STATUSES = {"pending", "in_progress", "completed", "failed"}
VALID_POLICIES = {"continue", "new"}


def default_db_path() -> Path:
    """Return the default queue database path relative to the current working directory."""
    return Path.cwd() / DEFAULT_DB_DIR / DEFAULT_DB_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(path: Path | str | None = None) -> Path:
    """Create the queue database and schema if they do not exist.

    Returns the resolved database path.
    """
    if path is None:
        db_path = default_db_path()
    else:
        db_path = Path(path)

    db_path.parent.mkdir(parents=True, exist_ok=True)

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session TEXT NOT NULL DEFAULT 'default',
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

        # Migrate older databases that lack the session column.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks);")}
        if "session" not in columns:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN session TEXT NOT NULL DEFAULT 'default';"
            )

        # Drop legacy index and create session-aware index.
        conn.execute("DROP INDEX IF EXISTS idx_tasks_status_created;")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_session_status_created "
            "ON tasks(session, status, created_at);"
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
    session: str = DEFAULT_SESSION,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Add a new pending task and return its record."""
    if context_policy not in VALID_POLICIES:
        raise ValueError(f"Invalid context_policy: {context_policy}")
    if not session:
        raise ValueError("Session name cannot be empty")

    conn = _connect(path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO tasks (description, status, context_policy, session, created_at)
            VALUES (?, 'pending', ?, ?, ?);
            """,
            (description, context_policy, session, _now()),
        )
        conn.commit()
        task_id = cursor.lastrowid
        return get_task(task_id, path=path)
    finally:
        conn.close()


def get_task(
    task_id: int,
    session: str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Return a single task by ID, or None if not found.

    If ``session`` is provided, the task must also belong to that session.
    """
    conn = _connect(path)
    try:
        row = conn.execute(
            """
            SELECT * FROM tasks
            WHERE id = ? AND (session = ? OR ? IS NULL);
            """,
            (task_id, session, session),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def claim_next(
    session: str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Atomically claim the oldest pending task and return it.

    If ``session`` is provided, only claim from that session. Returns None if
    no pending tasks exist.
    """
    conn = _connect(path)
    try:
        # Use an explicit transaction with immediate locking for atomicity.
        conn.execute("BEGIN IMMEDIATE;")
        try:
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = 'pending' AND (session = ? OR ? IS NULL)
                ORDER BY created_at ASC
                LIMIT 1;
                """,
                (session, session),
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


def complete_task(
    task_id: int,
    status: str = "completed",
    result: str | None = None,
    error: str | None = None,
    session: str | None = None,
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
            WHERE id = ? AND (session = ? OR ? IS NULL);
            """,
            (status, _now(), result, error, task_id, session, session),
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
    session: str | None = None,
    path: Path | str | None = None,
) -> int:
    """Delete completed tasks older than `age_hours` hours.

    Returns the number of deleted rows. Passing ``age_hours <= 0`` disables
    cleanup and returns 0. If ``session`` is provided, only delete from that
    session.
    """
    if age_hours <= 0:
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    conn = _connect(path)
    try:
        cursor = conn.execute(
            """
            DELETE FROM tasks
            WHERE status = 'completed' AND completed_at < ?
              AND (session = ? OR ? IS NULL);
            """,
            (cutoff, session, session),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def reset_tasks(
    include_in_progress: bool = True,
    include_failed: bool = False,
    session: str | None = None,
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
        params = statuses + [session, session]
        cursor = conn.execute(
            f"""
            UPDATE tasks
            SET status = 'pending', started_at = NULL, completed_at = NULL, result = NULL, error = NULL
            WHERE status IN ({placeholders})
              AND (session = ? OR ? IS NULL)
            RETURNING id;
            """,
            params,
        )
        ids = [row["id"] for row in cursor.fetchall()]
        conn.commit()
        return [get_task(task_id, path=path) for task_id in ids]
    finally:
        conn.close()


def list_tasks(
    status: str | None = None,
    limit: int = 50,
    session: str | None = None,
    path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return recent tasks, optionally filtered by status and session."""
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"Invalid status filter: {status}")

    conn = _connect(path)
    try:
        params: list[Any] = []
        where_clauses: list[str] = []

        if status:
            where_clauses.append("status = ?")
            params.append(status)

        where_clauses.append("(session = ? OR ? IS NULL)")
        params.extend([session, session])

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        rows = conn.execute(
            f"""
            SELECT * FROM tasks
            {where}
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            (*params, limit),
        ).fetchall()

        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def list_sessions(path: Path | str | None = None) -> list[str]:
    """Return a sorted list of distinct session names in the database."""
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT session FROM tasks ORDER BY session;"
        ).fetchall()
        return [row["session"] for row in rows]
    finally:
        conn.close()


def rename_session(
    old: str,
    new: str,
    path: Path | str | None = None,
) -> int:
    """Rename all tasks in session ``old`` to session ``new``.

    Returns the number of tasks renamed. Raises ValueError for invalid names.
    """
    if not old or not new:
        raise ValueError("Session names cannot be empty")
    if old == new:
        raise ValueError("New session name must differ from old name")

    conn = _connect(path)
    try:
        cursor = conn.execute(
            "UPDATE tasks SET session = ? WHERE session = ?;",
            (new, old),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def delete_session(
    session: str,
    path: Path | str | None = None,
) -> int:
    """Delete all tasks belonging to ``session``.

    Returns the number of deleted tasks. The implicit ``"default"`` session
    cannot be deleted if it is the only remaining session.
    """
    if not session:
        raise ValueError("Session name cannot be empty")

    conn = _connect(path)
    try:
        if session == DEFAULT_SESSION:
            sessions = list_sessions(path=path)
            if set(sessions) <= {DEFAULT_SESSION}:
                raise ValueError(
                    "Cannot delete the default session while it is the only session"
                )

        cursor = conn.execute(
            "DELETE FROM tasks WHERE session = ?;",
            (session,),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def delete_task(
    task_id: int,
    session: str | None = None,
    path: Path | str | None = None,
) -> bool:
    """Delete a single task by ID.

    If ``session`` is provided, the task must also belong to that session.
    Returns True if a row was deleted.
    """
    conn = _connect(path)
    try:
        cursor = conn.execute(
            "DELETE FROM tasks WHERE id = ? AND (session = ? OR ? IS NULL);",
            (task_id, session, session),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
