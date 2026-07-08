"""Drive Claude Code headlessly to process queued tasks."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from cq import store

DEFAULT_CLAUDE_ARGS = [
    "--allowedTools",
    "Bash,Read,Edit,Write,Glob,Grep",
    "--dangerously-skip-permissions",
    "--bare",
]


def _claude_executable() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError(
            "Could not find 'claude' executable on PATH. "
            "Make sure Claude Code CLI is installed."
        )
    return exe


def _build_claude_command(task: dict, prompt: str) -> list[str]:
    """Build the Claude Code CLI command for a task."""
    claude = _claude_executable()
    cmd = [claude]
    if task.get("context_policy") == "continue":
        cmd.append("-c")
    cmd.extend(["-p", prompt])
    cmd.extend(DEFAULT_CLAUDE_ARGS)
    return cmd


def _build_prompt(task: dict) -> str:
    prompt = (
        f"You are working through a task queue. Current task ({task['id']}): "
        f"{task['description']}. "
        "Complete the current task using any tools you need (Read, Edit, Write, Bash, etc.). "
        "Do not ask the user questions; do your best with the information available."
    )
    # Windows command-line parsing can drop characters after literal newlines,
    # so flatten the prompt to a single line.
    return " ".join(prompt.split())


def run_task(task_id: int, path: Path | str | None = None) -> dict:
    """Run a single queued task through Claude Code headless mode."""
    task = store.get_task(task_id, path=path)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    if task["status"] != "in_progress":
        # claim_next should already mark it in_progress, but be defensive.
        task = store.claim_next(path=path)
        if task is None or task["id"] != task_id:
            raise RuntimeError(f"Task {task_id} is not available to run")

    prompt = _build_prompt(task)
    cmd = _build_claude_command(task, prompt)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        output = result.stdout or ""
        if result.stderr:
            output += "\n\n[stderr]\n" + result.stderr

        if result.returncode == 0:
            completed = store.complete_task(
                task_id,
                status="completed",
                result=output,
                path=path,
            )
        else:
            completed = store.complete_task(
                task_id,
                status="failed",
                error=output,
                path=path,
            )
        return completed
    except subprocess.TimeoutExpired as exc:
        return store.complete_task(
            task_id,
            status="failed",
            error=f"Timeout after {exc.timeout} seconds",
            path=path,
        )


def _resolve_retention_hours(retention_hours: int | None) -> int:
    """Resolve retention hours from argument, env var, or default."""
    if retention_hours is not None:
        return retention_hours
    env_val = os.environ.get("CQ_COMPLETED_RETENTION_HOURS", "24")
    try:
        return int(env_val)
    except ValueError:
        return 24


def _run_cleanup(retention_hours: int, path: Path | str | None = None) -> None:
    """Purge old completed tasks and print a message if any were deleted."""
    deleted = store.cleanup_completed_tasks(retention_hours, path=path)
    if deleted:
        print(f"Cleaned up {deleted} old completed task(s).")


def run_loop(
    once: bool = False,
    path: Path | str | None = None,
    retention_hours: int | None = None,
) -> None:
    """Process queued tasks until empty (or one task if once=True)."""
    retention_hours = _resolve_retention_hours(retention_hours)

    while True:
        task = store.claim_next(path=path)
        if task is None:
            _run_cleanup(retention_hours, path=path)
            print("Queue is empty. Nothing to do.")
            break

        print(f"Running task {task['id']}: {task['description']}")
        completed = run_task(task["id"], path=path)
        print(f"Task {completed['id']} finished with status={completed['status']}")

        _run_cleanup(retention_hours, path=path)

        if once:
            break


if __name__ == "__main__":
    run_loop()
