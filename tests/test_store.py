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


def test_add_task_new_policy(db: Path) -> None:
    task = store.add_task("fresh", context_policy="new", path=db)
    assert task["context_policy"] == "new"


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


def test_claim_task(db: Path) -> None:
    task = store.add_task("target", path=db)
    other = store.add_task("other", path=db)

    # Can claim the specific pending task by ID.
    claimed = store.claim_task(task["id"], path=db)
    assert claimed is not None
    assert claimed["id"] == task["id"]
    assert claimed["status"] == "in_progress"

    # Other pending task remains untouched.
    other_task = store.get_task(other["id"], path=db)
    assert other_task is not None
    assert other_task["status"] == "pending"

    # Cannot claim a task that is already in_progress.
    assert store.claim_task(task["id"], path=db) is None

    # Cannot claim a non-existent task.
    assert store.claim_task(9999, path=db) is None


def test_cleanup_completed_tasks_zero_deletes_all(db: Path) -> None:
    task = store.add_task("done", path=db)
    store.claim_next(path=db)
    store.complete_task(task["id"], status="completed", path=db)

    deleted = store.cleanup_completed_tasks(age_hours=0, path=db)
    assert deleted == 1
    assert store.get_task(task["id"], path=db) is None


def test_delete_task(db: Path) -> None:
    task = store.add_task("A", path=db)
    other = store.add_task("B", path=db)

    assert store.delete_task(task["id"], path=db) is True
    assert store.get_task(task["id"], path=db) is None
    assert store.get_task(other["id"], path=db) is not None


def test_delete_all_tasks(db: Path) -> None:
    store.add_task("A", path=db)
    store.add_task("B", path=db)

    deleted = store.delete_all_tasks(path=db)
    assert deleted == 2
    assert store.list_tasks(path=db) == []


def test_migration_drops_session_column(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session TEXT NOT NULL DEFAULT 'default',
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
        "CREATE INDEX idx_tasks_session_status_created ON tasks(session, status, created_at);"
    )
    conn.execute(
        "INSERT INTO tasks (session, description, status, context_policy, created_at) VALUES (?, ?, ?, ?, ?);",
        ("legacy", "legacy task", "pending", "continue", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    store.init_db(db_path)

    migrated = store.list_tasks(path=db_path)
    assert len(migrated) == 1
    assert "session" not in migrated[0]
    assert migrated[0]["description"] == "legacy task"


def test_update_task_description_and_policy(db: Path) -> None:
    task = store.add_task("old desc", context_policy="continue", path=db)

    updated = store.update_task(
        task["id"], description="new desc", context_policy="new", path=db
    )
    assert updated["description"] == "new desc"
    assert updated["context_policy"] == "new"
    assert updated["status"] == "pending"


def test_default_db_path_uses_cwd_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    store.set_root_dir(None)
    assert store.default_db_path() == tmp_path / ".cq" / "queue.db"


def test_default_db_path_uses_root_dir_override(tmp_path: Path, monkeypatch) -> None:
    # Simulate starting the TUI in tmp_path while cwd moves elsewhere.
    monkeypatch.chdir(tmp_path)
    store.set_root_dir(str(tmp_path))
    monkeypatch.chdir(tempfile.gettempdir())
    assert store.default_db_path() == tmp_path / ".cq" / "queue.db"


def test_set_root_dir_none_clears_override(tmp_path: Path, monkeypatch) -> None:
    other = tmp_path / "other"
    other.mkdir()
    store.set_root_dir(str(other))
    assert store.default_db_path() == other / ".cq" / "queue.db"

    store.set_root_dir(None)
    monkeypatch.chdir(tmp_path)
    assert store.default_db_path() == tmp_path / ".cq" / "queue.db"


def test_update_task_resets_completed_task(db: Path) -> None:
    task = store.add_task("do thing", path=db)
    store.claim_next(path=db)
    store.complete_task(task["id"], status="completed", result="output", path=db)

    updated = store.update_task(
        task["id"], description="do thing better", path=db
    )
    assert updated["description"] == "do thing better"
    assert updated["status"] == "pending"
    assert updated["result"] is None
    assert updated["completed_at"] is None


def test_update_task_refuses_in_progress(db: Path) -> None:
    task = store.add_task("running", path=db)
    store.claim_next(path=db)

    with pytest.raises(ValueError, match="in progress"):
        store.update_task(task["id"], description="changed", path=db)


def test_update_task_no_changes(db: Path) -> None:
    task = store.add_task("noop", path=db)
    with pytest.raises(ValueError, match="Nothing to update"):
        store.update_task(task["id"], path=db)


def test_update_task_invalid_policy(db: Path) -> None:
    task = store.add_task("x", path=db)
    with pytest.raises(ValueError, match="Invalid context_policy"):
        store.update_task(task["id"], context_policy="invalid", path=db)


def test_update_task_missing_id(db: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        store.update_task(999, description="x", path=db)
