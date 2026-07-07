"""Command-line interface for cq."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

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
    task = store.add_task(
        args.description,
        context_policy=args.context_policy,
        session=args.session,
        path=path,
    )
    print(f"Added task {task['id']} [{task['session']}]: {task['description']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    path = _db_path(args)
    tasks = store.list_tasks(
        status=args.status,
        limit=args.limit,
        session=args.session,
        path=path,
    )
    if args.json:
        print(json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2, default=str))
        return 0

    if not tasks:
        print("No tasks found.")
        return 0

    print(f"{'ID':<6} {'Session':<16} {'Status':<12} {'Created':<20} {'Description'}")
    print("-" * 86)
    for t in tasks:
        created = t["created_at"][:19] if t["created_at"] else ""
        desc = t["description"]
        if len(desc) > 40:
            desc = desc[:37] + "..."
        session = t["session"]
        if len(session) > 14:
            session = session[:11] + "..."
        print(f"{t['id']:<6} {session:<16} {t['status']:<12} {created:<20} {desc}")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    path = _db_path(args)
    task = store.claim_next(session=args.session, path=path)
    if task is None:
        print("No pending tasks.")
        return 1
    if args.json:
        print(json.dumps({"task": task}, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"Claimed task {task['id']} [{task['session']}]: {task['description']}")
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    path = _db_path(args)
    task = store.complete_task(
        args.id,
        status=args.status,
        result=args.result,
        error=args.error,
        session=args.session,
        path=path,
    )
    print(f"Marked task {task['id']} as {task['status']}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    path = _db_path(args)
    reset = store.reset_tasks(
        include_in_progress=args.in_progress,
        include_failed=args.failed,
        session=args.session,
        path=path,
    )
    if not reset:
        print("No tasks to reset.")
        return 0
    for task in reset:
        print(f"Reset task {task['id']} to pending: {task['description']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    path = _db_path(args)
    try:
        if args.all_sessions:
            wrapper.run_all_sessions(
                once=args.once,
                path=path,
                retention_hours=_retention_hours(args.retention_hours),
            )
        else:
            wrapper.run_loop_session(
                session=args.session,
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
        session=args.session,
        path=path,
    )
    print(f"Cleaned up {deleted} old completed task(s).")
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    path = _db_path(args)
    try:
        from cq.tui import CqTuiApp
    except ImportError as exc:
        print(
            "Error: textual is required for the TUI. Install it with:\n"
            "  pip install textual",
            file=sys.stderr,
        )
        return 1

    app = CqTuiApp(db_path=path)
    return app.run()


def cmd_sessions(args: argparse.Namespace) -> int:
    path = _db_path(args)
    sessions = store.list_sessions(path=path)
    if not sessions:
        print("No sessions found.")
        return 0
    for session in sessions:
        print(session)
    return 0


def cmd_rename_session(args: argparse.Namespace) -> int:
    path = _db_path(args)
    renamed = store.rename_session(args.old, args.new, path=path)
    print(f"Renamed session '{args.old}' to '{args.new}' ({renamed} task(s))")
    return 0


def cmd_delete_session(args: argparse.Namespace) -> int:
    path = _db_path(args)
    deleted = store.delete_session(args.session, path=path)
    print(f"Deleted session '{args.session}' ({deleted} task(s))")
    return 0


def _add_session_arg(
    parser: argparse.ArgumentParser,
    default: str | None = None,
) -> None:
    parser.add_argument(
        "--session",
        default=default,
        help="Session name to operate on"
        + (f" (default: {default})" if default else " (default: all sessions)"),
    )


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
        "--context-policy",
        choices=["continue", "new"],
        default="continue",
        help="Whether Claude should continue context or start fresh (default: continue)",
    )
    _add_session_arg(p_add, default=store.DEFAULT_SESSION)

    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument(
        "--status",
        choices=["pending", "in_progress", "completed", "failed"],
        help="Filter by status",
    )
    p_list.add_argument("--limit", type=int, default=50, help="Maximum tasks to show")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")
    _add_session_arg(p_list)

    p_next = sub.add_parser("next", help="Claim the next pending task")
    p_next.add_argument("--json", action="store_true", help="Output as JSON")
    _add_session_arg(p_next)

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
    _add_session_arg(p_complete)

    p_reset = sub.add_parser("reset", help="Reset in_progress/failed tasks to pending")
    p_reset.add_argument(
        "--in-progress",
        action="store_true",
        default=True,
        help="Reset in_progress tasks (default: true)",
    )
    p_reset.add_argument(
        "--failed",
        action="store_true",
        default=False,
        help="Reset failed tasks (default: false)",
    )
    _add_session_arg(p_reset)

    p_run = sub.add_parser("run", help="Run queued tasks via Claude Code headless mode")
    p_run.add_argument("--once", action="store_true", help="Process only one task")
    p_run.add_argument(
        "--all-sessions",
        action="store_true",
        help="Run tasks across all sessions instead of a single session",
    )
    p_run.add_argument(
        "--retention-hours",
        type=int,
        default=None,
        help="Hours to keep completed tasks (default: 24, from CQ_COMPLETED_RETENTION_HOURS)",
    )
    _add_session_arg(p_run)

    p_cleanup = sub.add_parser("cleanup", help="Purge old completed tasks")
    p_cleanup.add_argument(
        "--retention-hours",
        type=int,
        default=None,
        help="Hours to keep completed tasks (default: 24, from CQ_COMPLETED_RETENTION_HOURS)",
    )
    _add_session_arg(p_cleanup)

    sub.add_parser("tui", help="Launch the interactive TUI")

    sub.add_parser("sessions", help="List all sessions")

    p_rename = sub.add_parser("rename-session", help="Rename a session")
    p_rename.add_argument("old", help="Current session name")
    p_rename.add_argument("new", help="New session name")

    p_delete_session = sub.add_parser("delete-session", help="Delete all tasks in a session")
    p_delete_session.add_argument("session", help="Session name to delete")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "init": cmd_init,
        "add": cmd_add,
        "list": cmd_list,
        "next": cmd_next,
        "complete": cmd_complete,
        "reset": cmd_reset,
        "run": cmd_run,
        "cleanup": cmd_cleanup,
        "tui": cmd_tui,
        "sessions": cmd_sessions,
        "rename-session": cmd_rename_session,
        "delete-session": cmd_delete_session,
    }

    handler = handlers[args.command]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
