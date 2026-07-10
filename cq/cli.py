"""Command-line interface for cq."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from cq import __version__, store
from cq import wrapper


def _db_path(args: argparse.Namespace) -> Path | None:
    if args and getattr(args, "db", None):
        return Path(args.db)
    env = os.environ.get("CQ_DB_PATH")
    if env:
        return Path(env)
    return None


def _retention_hours(args_value: int | None) -> int:
    """Resolve retention hours: CLI arg > env var > default 24."""
    if args_value is not None:
        return args_value
    env_val = os.environ.get("CQ_COMPLETED_RETENTION_HOURS", "24")
    try:
        return int(env_val)
    except ValueError:
        return 24


def cmd_init(args: argparse.Namespace) -> int:
    path = _db_path(args)
    db_path = store.init_db(path)
    print(f"Initialized queue database at {db_path}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    path = _db_path(args)
    context_policy = "new" if args.new else "continue"
    task = store.add_task(
        args.description,
        context_policy=context_policy,
        path=path,
    )
    policy_note = "new conversation" if context_policy == "new" else "continue"
    print(f"Added task {task['id']} ({policy_note}): {task['description']}")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    path = _db_path(args)
    updates: dict[str, Any] = {}
    if args.description is not None:
        updates["description"] = args.description
    if args.new:
        updates["context_policy"] = "new"
    elif args.continue_:
        updates["context_policy"] = "continue"

    if not updates:
        print("Error: nothing to update. Use --description, --new, or --continue.", file=sys.stderr)
        return 1

    try:
        task = store.update_task(args.id, path=path, **updates)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    policy_note = "new conversation" if task["context_policy"] == "new" else "continue"
    print(f"Updated task {task['id']} ({policy_note}): {task['description']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    path = _db_path(args)
    tasks = store.list_tasks(status=args.status, limit=args.limit, path=path)
    if args.json:
        print(json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2, default=str))
        return 0

    if not tasks:
        print("No tasks found.")
        return 0

    print(f"{'ID':<6} {'Status':<12} {'Policy':<10} {'Created':<20} {'Description'}")
    print("-" * 80)
    for t in tasks:
        created = t["created_at"][:19] if t["created_at"] else ""
        desc = t["description"]
        if len(desc) > 40:
            desc = desc[:37] + "..."
        print(
            f"{t['id']:<6} {t['status']:<12} {t['context_policy']:<10} "
            f"{created:<20} {desc}"
        )
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    path = _db_path(args)
    task = store.claim_next(path=path)
    if task is None:
        print("No pending tasks.")
        return 1
    if args.json:
        print(json.dumps({"task": task}, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"Claimed task {task['id']}: {task['description']}")
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    path = _db_path(args)
    task = store.complete_task(
        args.id,
        status=args.status,
        result=args.result,
        error=args.error,
        path=path,
    )
    print(f"Marked task {task['id']} as {task['status']}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    path = _db_path(args)
    reset = store.reset_tasks(
        include_in_progress=args.in_progress,
        include_failed=args.failed,
        path=path,
    )
    if not reset:
        print("No tasks to reset.")
        return 0
    for task in reset:
        print(f"Reset task {task['id']} to pending: {task['description']}")
    return 0


def _spawn_background_runner(args: argparse.Namespace) -> None:
    """Spawn `cq run --foreground` in a detached background process.

    Output is appended to ``.cq/run.log`` next to the database.
    """
    db_path = _db_path(args)
    log_path = Path(store.default_db_path()).parent / "run.log"
    if db_path:
        log_path = Path(db_path).parent / "run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, "-m", "cq.cli"]
    if db_path:
        cmd.extend(["--db", str(db_path)])
    cmd.append("run")
    cmd.append("--foreground")

    if args.once:
        cmd.append("--once")
    if args.retention_hours is not None:
        cmd.extend(["--retention-hours", str(args.retention_hours)])

    with open(log_path, "a", encoding="utf-8") as log_file:
        popen_kwargs: dict[str, Any] = {
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            popen_kwargs["start_new_session"] = True

        subprocess.Popen(cmd, **popen_kwargs)

    print(f"Started background runner. Logs: {log_path}")


def cmd_run(args: argparse.Namespace) -> int:
    path = _db_path(args)

    if not args.foreground:
        _spawn_background_runner(args)
        return 0

    try:
        wrapper.run_loop(
            once=args.once,
            path=path,
            retention_hours=_retention_hours(args.retention_hours),
        )
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_cleanup(args: argparse.Namespace) -> int:
    path = _db_path(args)
    deleted = store.cleanup_completed_tasks(
        age_hours=_retention_hours(args.retention_hours),
        path=path,
    )
    print(f"Cleaned up {deleted} old completed task(s).")
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    path = _db_path(args)
    # 用户可通过 --db-root 显式指定数据库根目录，优先级高于 cwd
    db_root = getattr(args, "db_root", None)
    try:
        from cq.tui import CqTuiApp
    except ImportError as exc:
        print(
            "Error: textual is required for the TUI. Install it with:\n"
            "  pip install textual",
            file=sys.stderr,
        )
        return 1

    # 固定数据库根目录：显式 --db-root > 启动时 cwd，
    # 避免 TUI 长驻期间 cwd 漂移导致数据库位置改变。
    if path is None:
        store.set_root_dir(db_root if db_root else os.getcwd())
    try:
        app = CqTuiApp(db_path=path)
        return app.run()
    finally:
        if path is None:
            store.set_root_dir(None)


def cmd_delete(args: argparse.Namespace) -> int:
    path = _db_path(args)
    if args.all:
        if not _confirm("Delete all tasks?"):
            print("Cancelled.")
            return 0
        deleted = store.delete_all_tasks(path=path)
        print(f"Deleted all tasks ({deleted})")
        return 0

    if args.id is None:
        print("Error: task ID is required (or use --all)", file=sys.stderr)
        return 1

    if store.delete_task(args.id, path=path):
        print(f"Deleted task {args.id}")
        return 0
    print(f"Task {args.id} not found", file=sys.stderr)
    return 1


def _confirm(message: str) -> bool:
    """Ask the user for confirmation in interactive mode."""
    try:
        answer = input(f"{message} [y/N]: ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in {"y", "yes"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cq",
        description="Claude Code Task Queue - a lightweight task buffer.",
    )
    parser.add_argument("--version", action="version", version=f"cq {__version__}")
    parser.add_argument(
        "--db",
        help="Path to the queue SQLite database (default: .cq/queue.db)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create the queue database")

    p_add = sub.add_parser("add", help="Add a task to the queue")
    p_add.add_argument("description", help="Task description")
    p_add.add_argument(
        "--new",
        action="store_true",
        help="Start a fresh Claude conversation for this task",
    )

    p_edit = sub.add_parser("edit", help="Edit an existing task")
    p_edit.add_argument("id", type=int, help="Task ID")
    p_edit.add_argument(
        "--description", "-d",
        help="New task description",
    )
    edit_policy = p_edit.add_mutually_exclusive_group()
    edit_policy.add_argument(
        "--new",
        action="store_true",
        help="Set context policy to start a new conversation",
    )
    edit_policy.add_argument(
        "--continue",
        dest="continue_",
        action="store_true",
        help="Set context policy to continue the previous conversation",
    )

    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument(
        "--status",
        choices=["pending", "in_progress", "completed", "failed"],
        help="Filter by status",
    )
    p_list.add_argument("--limit", type=int, default=50, help="Maximum tasks to show")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")

    p_next = sub.add_parser("next", help="Claim the next pending task")
    p_next.add_argument("--json", action="store_true", help="Output as JSON")

    p_complete = sub.add_parser("complete", help="Mark a task as completed or failed")
    p_complete.add_argument("id", type=int, help="Task ID")
    p_complete.add_argument(
        "--status",
        choices=["completed", "failed"],
        default="completed",
        help="Completion status",
    )
    p_complete.add_argument("--result", help="Result summary")
    p_complete.add_argument("--error", help="Error message")

    p_reset = sub.add_parser("reset", help="Reset in_progress/failed tasks to pending")
    p_reset.add_argument(
        "--in-progress",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reset in_progress tasks (default: true)",
    )
    p_reset.add_argument(
        "--failed",
        action="store_true",
        default=False,
        help="Reset failed tasks (default: false)",
    )

    p_run = sub.add_parser("run", help="Run queued tasks via Claude Code headless mode")
    p_run.add_argument("--once", action="store_true", help="Process only one task")
    p_run.add_argument(
        "--foreground",
        action="store_true",
        help="Run in the foreground (do not detach a background process)",
    )
    p_run.add_argument(
        "--retention-hours",
        type=int,
        default=None,
        help="Hours to keep completed tasks (default: 24, from CQ_COMPLETED_RETENTION_HOURS)",
    )

    p_cleanup = sub.add_parser("cleanup", help="Purge old completed tasks")
    p_cleanup.add_argument(
        "--retention-hours",
        type=int,
        default=None,
        help="Hours to keep completed tasks (default: 24, from CQ_COMPLETED_RETENTION_HOURS)",
    )

    p_tui = sub.add_parser("tui", help="Launch the interactive TUI")
    p_tui.add_argument(
        "--db-root",
        default=None,
        help="数据库根目录（默认：启动 TUI 时的当前工作目录）。",
    )

    p_delete = sub.add_parser("delete", help="Delete a task or all tasks")
    p_delete.add_argument("id", type=int, nargs="?", help="Task ID to delete")
    p_delete.add_argument(
        "--all",
        action="store_true",
        help="Delete all tasks",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "init": cmd_init,
        "add": cmd_add,
        "edit": cmd_edit,
        "list": cmd_list,
        "next": cmd_next,
        "complete": cmd_complete,
        "reset": cmd_reset,
        "run": cmd_run,
        "cleanup": cmd_cleanup,
        "tui": cmd_tui,
        "delete": cmd_delete,
    }

    handler = handlers[args.command]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
