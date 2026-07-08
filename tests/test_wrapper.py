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
    assert "--dangerously-skip-permissions" in cmd
    assert cmd[cmd.index("-p") + 1] == "prompt text"


def test_build_claude_command_new_policy(db: Path, monkeypatch) -> None:
    monkeypatch.setattr(wrapper, "_claude_executable", lambda: "/usr/bin/claude")
    task = store.add_task("new task", context_policy="new", path=db)
    cmd = wrapper._build_claude_command(task, "prompt text")

    assert cmd[0] == "/usr/bin/claude"
    assert "-c" not in cmd
    assert "-p" in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert cmd[cmd.index("-p") + 1] == "prompt text"


def test_run_loop_claims_pending_tasks(db: Path, monkeypatch) -> None:
    store.add_task("A", path=db)
    store.add_task("B", path=db)

    run_task_calls = []

    def fake_run_task(task_id, path=None):
        run_task_calls.append(task_id)
        return store.complete_task(task_id, status="completed", path=path)

    monkeypatch.setattr(wrapper, "run_task", fake_run_task)

    wrapper.run_loop(once=True, path=db)

    assert len(run_task_calls) == 1
    task = store.get_task(run_task_calls[0], path=db)
    assert task["description"] == "A"


def test_run_task_claims_pending_task_by_id(db: Path, monkeypatch) -> None:
    older = store.add_task("older", path=db)
    target = store.add_task("target", path=db)

    monkeypatch.setattr(
        wrapper, "_claude_executable", lambda: "/usr/bin/claude"
    )
    monkeypatch.setattr(
        wrapper.subprocess,
        "run",
        lambda *args, **kwargs: subprocess_result(0, "ok", ""),
    )

    completed = wrapper.run_task(target["id"], path=db)

    assert completed["status"] == "completed"
    assert completed["description"] == "target"
    # The older task should remain pending, not be claimed by mistake.
    older_task = store.get_task(older["id"], path=db)
    assert older_task is not None
    assert older_task["status"] == "pending"


def test_run_task_uses_existing_in_progress_task(db: Path, monkeypatch) -> None:
    target = store.add_task("target", path=db)
    claimed = store.claim_next(path=db)
    assert claimed["id"] == target["id"]

    monkeypatch.setattr(
        wrapper, "_claude_executable", lambda: "/usr/bin/claude"
    )
    monkeypatch.setattr(
        wrapper.subprocess,
        "run",
        lambda *args, **kwargs: subprocess_result(0, "ok", ""),
    )

    completed = wrapper.run_task(target["id"], path=db)

    assert completed["status"] == "completed"
    assert completed["description"] == "target"


def test_run_task_raises_for_completed_task(db: Path, monkeypatch) -> None:
    target = store.add_task("target", path=db)
    store.claim_next(path=db)
    store.complete_task(target["id"], status="completed", path=db)

    monkeypatch.setattr(
        wrapper, "_claude_executable", lambda: "/usr/bin/claude"
    )

    with pytest.raises(RuntimeError, match="cannot be run"):
        wrapper.run_task(target["id"], path=db)


def test_run_cleanup_disabled_for_zero_retention(db: Path, monkeypatch) -> None:
    called = []
    monkeypatch.setattr(
        store, "cleanup_completed_tasks", lambda *args, **kwargs: called.append(True) or 0
    )

    wrapper._run_cleanup(0, path=db)

    assert not called


def subprocess_result(returncode: int, stdout: str, stderr: str):
    """Build a minimal subprocess.CompletedProcess-like object for monkeypatching."""
    result = wrapper.subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
    return result
