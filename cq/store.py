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

    Returns the number of deleted rows. Passing ``age_hours <= 0`` disables
    cleanup and returns 0.
    """
    if age_hours <= 0:
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    conn = _connect(path)
    try:
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
