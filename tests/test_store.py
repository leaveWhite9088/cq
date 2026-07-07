"""Tests for cq.store."""

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cq import store


@pytest.fixture
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "queue.db"
    store.init_db(db_path)
    return db_path


def test_init_db_creates_file(tmp_path: Path) -> None:
    db_path = tmp_path / "queue.db"
    assert not db_path.exists()
    store.init_db(db_path)
    assert db_path.exists()


def test_add_task(db: Path) -> None:
    task = store.add_task("hello", path=db)
    assert task["description"] == "hello"
    assert task["status"] == "pending"
    assert task["context_policy"] == "continue"
    assert task["id"] >= 1


def test_claim_next_returns_oldest_pending(db: Path) -> None:
    a = store.add_task("A", path=db)
    b = store.add_task("B", path=db)

    claimed = store.claim_next(path=db)
    assert claimed["id"] == a["id"]
    assert claimed["status"] == "in_progress"

    # Second claim returns B.
    claimed2 = store.claim_next(path=db)
    assert claimed2["id"] == b["id"]


def test_claim_next_returns_none_when_empty(db: Path) -> None:
    assert store.claim_next(path=db) is None


def test_no_double_claim(db: Path) -> None:
    store.add_task("A", path=db)

    c1 = store.claim_next(path=db)
    c2 = store.claim_next(path=db)

    assert c1 is not None
    assert c2 is None


def test_complete_task(db: Path) -> None:
    task = store.add_task("A", path=db)
    claimed = store.claim_next(path=db)

    completed = store.complete_task(
        claimed["id"], status="completed", result="done", path=db
    )
    assert completed["status"] == "completed"
    assert completed["result"] == "done"
    assert completed["completed_at"] is not None


def test_list_tasks(db: Path) -> None:
    store.add_task("A", path=db)
    store.add_task("B", path=db)
    a = store.claim_next(path=db)  # oldest pending is A
    store.complete_task(a["id"], path=db)

    all_tasks = store.list_tasks(path=db)
    assert len(all_tasks) == 2

    pending = store.list_tasks(status="pending", path=db)
    assert len(pending) == 1
    assert pending[0]["description"] == "B"

    completed = store.list_tasks(status="completed", path=db)
    assert len(completed) == 1
    assert completed[0]["description"] == "A"


def test_reset_tasks(db: Path) -> None:
    store.add_task("stuck", path=db)
    store.add_task("broken", path=db)
    stuck = store.claim_next(path=db)
    broken = store.claim_next(path=db)
    store.complete_task(broken["id"], status="failed", path=db)

    reset = store.reset_tasks(include_in_progress=True, include_failed=True, path=db)
    assert len(reset) == 2
    ids = {t["id"] for t in reset}
    assert ids == {stuck["id"], broken["id"]}
    assert all(t["status"] == "pending" for t in reset)


def test_cleanup_completed_tasks_deletes_only_old(db: Path) -> None:
    old = store.add_task("old", path=db)
    fresh = store.add_task("fresh", path=db)
    store.claim_next(path=db)
    store.claim_next(path=db)

    # Mark the old task completed, then backdate its completed_at to 48 hours ago.
    store.complete_task(old["id"], status="completed", path=db)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE tasks SET completed_at = ? WHERE id = ?;", (old_time, old["id"]))
    conn.commit()
    conn.close()

    store.complete_task(fresh["id"], status="completed", path=db)

    deleted = store.cleanup_completed_tasks(age_hours=24, path=db)
    assert deleted == 1
    assert store.get_task(old["id"], path=db) is None
    assert store.get_task(fresh["id"], path=db) is not None


def test_cleanup_completed_tasks_zero_disables(db: Path) -> None:
    task = store.add_task("done", path=db)
    store.claim_next(path=db)
    store.complete_task(task["id"], status="completed", path=db)

    deleted = store.cleanup_completed_tasks(age_hours=0, path=db)
    assert deleted == 0
    assert store.get_task(task["id"], path=db) is not None


def test_add_task_with_session(db: Path) -> None:
    task = store.add_task("hello", session="feature-x", path=db)
    assert task["session"] == "feature-x"


def test_claim_next_respects_session(db: Path) -> None:
    a = store.add_task("A", session="s1", path=db)
    b = store.add_task("B", session="s2", path=db)

    claimed = store.claim_next(session="s1", path=db)
    assert claimed["id"] == a["id"]

    claimed_s2 = store.claim_next(session="s2", path=db)
    assert claimed_s2["id"] == b["id"]


def test_list_tasks_by_session(db: Path) -> None:
    store.add_task("A", session="s1", path=db)
    store.add_task("B", session="s2", path=db)
    store.add_task("C", session="s2", path=db)

    s1_tasks = store.list_tasks(session="s1", path=db)
    assert len(s1_tasks) == 1
    assert s1_tasks[0]["description"] == "A"

    s2_tasks = store.list_tasks(session="s2", path=db)
    assert len(s2_tasks) == 2


def test_list_sessions(db: Path) -> None:
    store.add_task("A", session="s1", path=db)
    store.add_task("B", session="s2", path=db)

    sessions = store.list_sessions(path=db)
    assert sessions == ["s1", "s2"]


def test_reset_tasks_by_session(db: Path) -> None:
    store.add_task("stuck", session="s1", path=db)
    store.add_task("other", session="s2", path=db)
    stuck = store.claim_next(session="s1", path=db)
    store.claim_next(session="s2", path=db)

    reset = store.reset_tasks(session="s1", path=db)
    assert len(reset) == 1
    assert reset[0]["id"] == stuck["id"]
    assert reset[0]["status"] == "pending"


def test_cleanup_completed_tasks_by_session(db: Path) -> None:
    old = store.add_task("old", session="s1", path=db)
    store.claim_next(session="s1", path=db)
    store.complete_task(old["id"], status="completed", path=db)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE tasks SET completed_at = ? WHERE id = ?;", (old_time, old["id"]))
    conn.commit()
    conn.close()

    deleted = store.cleanup_completed_tasks(age_hours=24, session="s1", path=db)
    assert deleted == 1
    assert store.get_task(old["id"], path=db) is None


def test_rename_session(db: Path) -> None:
    store.add_task("A", session="old", path=db)
    store.add_task("B", session="old", path=db)

    renamed = store.rename_session("old", "new", path=db)
    assert renamed == 2
    assert store.list_sessions(path=db) == ["new"]


def test_delete_all_sessions(db: Path) -> None:
    store.add_task("A", session="s1", path=db)
    store.add_task("B", session="s2", path=db)
    store.add_task("C", session="default", path=db)

    deleted = store.delete_all_sessions(path=db)
    assert deleted == 3
    assert store.list_sessions(path=db) == []


def test_delete_session(db: Path) -> None:
    store.add_task("A", session="temp", path=db)
    store.add_task("B", session="temp", path=db)
    store.add_task("C", session="default", path=db)

    deleted = store.delete_session("temp", path=db)
    assert deleted == 2
    assert store.list_sessions(path=db) == ["default"]


def test_delete_task(db: Path) -> None:
    task = store.add_task("A", session="s1", path=db)
    other = store.add_task("B", session="s2", path=db)

    assert store.delete_task(task["id"], session="s2", path=db) is False
    assert store.delete_task(task["id"], session="s1", path=db) is True
    assert store.get_task(task["id"], path=db) is None
    assert store.get_task(other["id"], path=db) is not None


def test_delete_default_session_when_only_session_fails(db: Path) -> None:
    store.add_task("A", session="default", path=db)
    with pytest.raises(ValueError):
        store.delete_session("default", path=db)


def test_migration_adds_session_column(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            context_policy TEXT NOT NULL DEFAULT 'continue',
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            result TEXT,
            error TEXT
        );
        """
    )
    conn.execute(
        "CREATE INDEX idx_tasks_status_created ON tasks(status, created_at);"
    )
    conn.execute(
        "INSERT INTO tasks (description, status, context_policy, created_at) VALUES (?, ?, ?, ?);",
        ("legacy", "pending", "continue", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    store.init_db(db_path)

    migrated = store.list_tasks(path=db_path)
    assert len(migrated) == 1
    assert migrated[0]["session"] == "default"
    sessions = store.list_sessions(path=db_path)
    assert sessions == ["default"]


def test_session_filter_on_complete_and_get(db: Path) -> None:
    task = store.add_task("A", session="s1", path=db)
    claimed = store.claim_next(session="s1", path=db)

    completed = store.complete_task(
        claimed["id"], status="completed", session="s1", path=db
    )
    assert completed["status"] == "completed"

    assert store.get_task(task["id"], session="s1", path=db) is not None
    assert store.get_task(task["id"], session="s2", path=db) is None

