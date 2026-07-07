"""Tests for cq.wrapper."""

from pathlib import Path

import pytest

from cq import store, wrapper


@pytest.fixture
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "queue.db"
    store.init_db(db_path)
    return db_path


def test_build_claude_command_continue_policy(db: Path, monkeypatch) -> None:
    monkeypatch.setattr(wrapper, "_claude_executable", lambda: "/usr/bin/claude")
    task = store.add_task("continue task", context_policy="continue", path=db)
    cmd = wrapper._build_claude_command(task, "prompt text")

    assert cmd[0] == "/usr/bin/claude"
    assert "-c" in cmd
    assert "-p" in cmd
    assert cmd[cmd.index("-p") + 1] == "prompt text"


def test_build_claude_command_new_policy(db: Path, monkeypatch) -> None:
    monkeypatch.setattr(wrapper, "_claude_executable", lambda: "/usr/bin/claude")
    task = store.add_task("new task", context_policy="new", path=db)
    cmd = wrapper._build_claude_command(task, "prompt text")

    assert cmd[0] == "/usr/bin/claude"
    assert "-c" not in cmd
    assert "-p" in cmd
    assert cmd[cmd.index("-p") + 1] == "prompt text"


def test_run_loop_session_claims_only_from_session(db: Path, monkeypatch) -> None:
    store.add_task("A", session="s1", path=db)
    store.add_task("B", session="s2", path=db)

    run_task_calls = []

    def fake_run_task(task_id, path=None):
        run_task_calls.append(task_id)
        return store.complete_task(task_id, status="completed", path=path)

    monkeypatch.setattr(wrapper, "run_task", fake_run_task)

    wrapper.run_loop_session(session="s1", once=True, path=db)

    assert len(run_task_calls) == 1
    task = store.get_task(run_task_calls[0], path=db)
    assert task["description"] == "A"
    assert task["session"] == "s1"


def test_run_all_sessions_claims_across_sessions(db: Path, monkeypatch) -> None:
    store.add_task("A", session="s1", path=db)
    store.add_task("B", session="s2", path=db)

    run_task_calls = []

    def fake_run_task(task_id, path=None):
        run_task_calls.append(task_id)
        return store.complete_task(task_id, status="completed", path=path)

    monkeypatch.setattr(wrapper, "run_task", fake_run_task)

    wrapper.run_all_sessions(once=True, path=db)

    assert len(run_task_calls) == 1
    # Only one task should run in --once all-sessions mode.
    task = store.get_task(run_task_calls[0], path=db)
    assert task["session"] in {"s1", "s2"}
