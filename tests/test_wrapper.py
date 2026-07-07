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
