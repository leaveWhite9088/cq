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

