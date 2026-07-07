"""Tests for cq.cli."""

from pathlib import Path

import pytest

from cq import cli, store


@pytest.fixture
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "queue.db"
    store.init_db(db_path)
    return db_path


def test_add_with_session(db: Path, capsys) -> None:
    code = cli.main(["--db", str(db), "add", "hello", "--session", "feature-x"])
    assert code == 0

    captured = capsys.readouterr()
    assert "feature-x" in captured.out

    tasks = store.list_tasks(session="feature-x", path=db)
    assert len(tasks) == 1
    assert tasks[0]["description"] == "hello"


def test_list_with_session(db: Path, capsys) -> None:
    store.add_task("A", session="s1", path=db)
    store.add_task("B", session="s2", path=db)

    code = cli.main(["--db", str(db), "list", "--session", "s1"])
    assert code == 0

    captured = capsys.readouterr()
    assert "A" in captured.out
    assert "B" not in captured.out


def test_sessions_command(db: Path, capsys) -> None:
    store.add_task("A", session="alpha", path=db)
    store.add_task("B", session="beta", path=db)

    code = cli.main(["--db", str(db), "sessions"])
    assert code == 0

    captured = capsys.readouterr()
    assert "alpha" in captured.out
    assert "beta" in captured.out


def test_rename_session_command(db: Path, capsys) -> None:
    store.add_task("A", session="old", path=db)

    code = cli.main(["--db", str(db), "rename-session", "old", "new"])
    assert code == 0

    captured = capsys.readouterr()
    assert "new" in captured.out
    assert store.list_sessions(path=db) == ["new"]


def test_delete_session_command(db: Path, capsys) -> None:
    store.add_task("A", session="temp", path=db)

    code = cli.main(["--db", str(db), "delete-session", "temp"])
    assert code == 0

    captured = capsys.readouterr()
    assert "temp" in captured.out
    assert store.list_sessions(path=db) == []


def test_run_with_session_invokes_wrapper(db: Path, monkeypatch) -> None:
    store.add_task("A", session="s1", path=db)

    called = {}

    def fake_run_loop_session(*, session, once, path, retention_hours):
        called["session"] = session
        called["once"] = once
        called["path"] = path

    monkeypatch.setattr(cli.wrapper, "run_loop_session", fake_run_loop_session)

    code = cli.main(["--db", str(db), "run", "--session", "s1", "--once"])
    assert code == 0
    assert called["session"] == "s1"
    assert called["once"] is True
    assert called["path"] == db


def test_run_all_sessions_invokes_wrapper(db: Path, monkeypatch) -> None:
    store.add_task("A", session="s1", path=db)

    called = {}

    def fake_run_all_sessions(*, once, path, retention_hours):
        called["once"] = once
        called["path"] = path

    monkeypatch.setattr(cli.wrapper, "run_all_sessions", fake_run_all_sessions)

    code = cli.main(["--db", str(db), "run", "--all-sessions", "--once"])
    assert code == 0
    assert called["once"] is True
    assert called["path"] == db


def test_next_with_session(db: Path, capsys) -> None:
    store.add_task("A", session="s1", path=db)

    code = cli.main(["--db", str(db), "next", "--session", "s1"])
    assert code == 0

    captured = capsys.readouterr()
    assert "A" in captured.out
    assert "s1" in captured.out


def test_next_with_session_empty(db: Path, capsys) -> None:
    code = cli.main(["--db", str(db), "next", "--session", "s1"])
    assert code == 1

    captured = capsys.readouterr()
    assert "No pending tasks" in captured.out
