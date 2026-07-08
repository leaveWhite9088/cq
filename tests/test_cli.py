"""Tests for cq.cli."""

from pathlib import Path

import pytest

from cq import cli, store


@pytest.fixture
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "queue.db"
    store.init_db(db_path)
    return db_path


def test_add_with_new_policy(db: Path, capsys) -> None:
    code = cli.main(["--db", str(db), "add", "hello", "--new"])
    assert code == 0

    captured = capsys.readouterr()
    assert "new conversation" in captured.out

    tasks = store.list_tasks(path=db)
    assert len(tasks) == 1
    assert tasks[0]["context_policy"] == "new"


def test_add_default_policy(db: Path, capsys) -> None:
    code = cli.main(["--db", str(db), "add", "hello"])
    assert code == 0

    captured = capsys.readouterr()
    assert "continue" in captured.out

    tasks = store.list_tasks(path=db)
    assert tasks[0]["context_policy"] == "continue"


def test_list(db: Path, capsys) -> None:
    store.add_task("A", path=db)
    store.add_task("B", path=db)

    code = cli.main(["--db", str(db), "list"])
    assert code == 0

    captured = capsys.readouterr()
    assert "A" in captured.out
    assert "B" in captured.out


def test_delete_task_command(db: Path, capsys) -> None:
    task = store.add_task("A", path=db)

    code = cli.main(["--db", str(db), "delete", str(task["id"])])
    assert code == 0

    captured = capsys.readouterr()
    assert str(task["id"]) in captured.out
    assert store.get_task(task["id"], path=db) is None


def test_edit_task_description(db: Path, capsys) -> None:
    task = store.add_task("old", path=db)

    code = cli.main(["--db", str(db), "edit", str(task["id"]), "--description", "new"])
    assert code == 0

    captured = capsys.readouterr()
    assert "Updated task" in captured.out

    updated = store.get_task(task["id"], path=db)
    assert updated["description"] == "new"


def test_edit_task_policy(db: Path, capsys) -> None:
    task = store.add_task("x", path=db)

    code = cli.main(["--db", str(db), "edit", str(task["id"]), "--new"])
    assert code == 0

    updated = store.get_task(task["id"], path=db)
    assert updated["context_policy"] == "new"


def test_edit_task_no_changes(db: Path, capsys) -> None:
    task = store.add_task("x", path=db)

    code = cli.main(["--db", str(db), "edit", str(task["id"])])
    assert code == 1

    captured = capsys.readouterr()
    assert "nothing to update" in captured.err


def test_edit_task_in_progress(db: Path, capsys) -> None:
    task = store.add_task("x", path=db)
    store.claim_next(path=db)

    code = cli.main(["--db", str(db), "edit", str(task["id"]), "--description", "y"])
    assert code == 1

    captured = capsys.readouterr()
    assert "in progress" in captured.err


def test_delete_all_tasks_command(db: Path, capsys, monkeypatch) -> None:
    store.add_task("A", path=db)
    store.add_task("B", path=db)

    monkeypatch.setattr(cli, "_confirm", lambda msg: True)
    code = cli.main(["--db", str(db), "delete", "--all"])
    assert code == 0

    captured = capsys.readouterr()
    assert "all tasks" in captured.out
    assert store.list_tasks(path=db) == []


def test_delete_all_tasks_command_cancelled(db: Path, monkeypatch) -> None:
    store.add_task("A", path=db)

    monkeypatch.setattr(cli, "_confirm", lambda msg: False)
    code = cli.main(["--db", str(db), "delete", "--all"])
    assert code == 0
    assert store.list_tasks(path=db)


def test_run_invokes_wrapper_foreground(db: Path, monkeypatch) -> None:
    store.add_task("A", path=db)

    called = {}

    def fake_run_loop(*, once, path, retention_hours):
        called["once"] = once
        called["path"] = path

    monkeypatch.setattr(cli.wrapper, "run_loop", fake_run_loop)

    code = cli.main(["--db", str(db), "run", "--once", "--foreground"])
    assert code == 0
    assert called["once"] is True
    assert called["path"] == db


def test_run_spawns_background_by_default(db: Path, monkeypatch) -> None:
    store.add_task("A", path=db)

    spawned = {}

    def fake_popen(cmd, **kwargs):
        spawned["cmd"] = cmd
        spawned["stdout"] = kwargs.get("stdout")
        return None

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)

    code = cli.main(["--db", str(db), "run", "--once"])
    assert code == 0
    assert "--foreground" in spawned["cmd"]
    assert "run" in spawned["cmd"]
    # The log file handle should be closed in the parent after Popen.
    assert spawned["stdout"] is not None
    assert spawned["stdout"].closed


def test_reset_default_resets_in_progress(db: Path, capsys) -> None:
    store.add_task("stuck", path=db)
    store.claim_next(path=db)

    code = cli.main(["--db", str(db), "reset"])
    assert code == 0

    assert store.list_tasks(status="in_progress", path=db) == []
    assert len(store.list_tasks(status="pending", path=db)) == 1


def test_reset_no_in_progress_skips_in_progress(db: Path, capsys) -> None:
    store.add_task("stuck", path=db)
    store.claim_next(path=db)
    store.add_task("waiting", path=db)

    code = cli.main(["--db", str(db), "reset", "--no-in-progress"])
    assert code == 0

    assert len(store.list_tasks(status="in_progress", path=db)) == 1
    assert len(store.list_tasks(status="pending", path=db)) == 1


def test_reset_failed(db: Path, capsys) -> None:
    task = store.add_task("broken", path=db)
    store.claim_next(path=db)
    store.complete_task(task["id"], status="failed", path=db)

    code = cli.main(["--db", str(db), "reset", "--no-in-progress", "--failed"])
    assert code == 0

    assert store.list_tasks(status="failed", path=db) == []
    assert len(store.list_tasks(status="pending", path=db)) == 1


def test_next(db: Path, capsys) -> None:
    store.add_task("A", path=db)

    code = cli.main(["--db", str(db), "next"])
    assert code == 0

    captured = capsys.readouterr()
    assert "A" in captured.out


def test_next_empty(db: Path, capsys) -> None:
    code = cli.main(["--db", str(db), "next"])
    assert code == 1

    captured = capsys.readouterr()
    assert "No pending tasks" in captured.out
