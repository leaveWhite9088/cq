"""Interactive TUI for cq using Textual."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RadioButton,
    RadioSet,
    Static,
)

from cq import store
from cq.wrapper import run_loop_session


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return ""
    return iso[:19].replace("T", " ")


def _fmt_desc(desc: str, max_len: int = 40) -> str:
    if len(desc) > max_len:
        return desc[: max_len - 3] + "..."
    return desc


class SessionList(ListView):
    """Sidebar list of sessions."""

    BINDINGS = [
        ("+", "next_session", "Next session"),
        ("-", "prev_session", "Prev session"),
    ]

    def action_next_session(self) -> None:
        self.action_cursor_down()

    def action_prev_session(self) -> None:
        self.action_cursor_up()


class TaskTable(DataTable):
    """Data table showing tasks for the current session."""

    def on_mount(self) -> None:
        self.add_columns("ID", "Status", "Created", "Description")
        self.cursor_type = "row"


class AddTaskScreen(ModalScreen[dict[str, Any] | None]):
    """Modal screen for adding a new task."""

    BINDINGS = [
        ("escape", "dismiss_none", "Cancel"),
    ]

    def __init__(self, session: str) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        with Container(classes="dialog"):
            yield Label("Add task", classes="dialog-title")
            yield Label("Description:")
            self.description = Input(placeholder="What should Claude do?")
            yield self.description
            yield Label("Session:")
            self.session_input = Input(value=self.session)
            yield self.session_input
            yield Label("Context policy:")
            self.policy = RadioSet(
                RadioButton("continue", value=True),
                RadioButton("new"),
            )
            yield self.policy
            with Horizontal(classes="dialog-buttons"):
                yield Button("Add", variant="primary", id="add")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add":
            policy = "continue" if self.policy.pressed_index == 0 else "new"
            self.dismiss(
                {
                    "description": self.description.value,
                    "session": self.session_input.value or "default",
                    "context_policy": policy,
                }
            )
        else:
            self.dismiss(None)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    """Modal screen showing keyboard shortcuts."""

    BINDINGS = [
        ("escape,q", "dismiss", "Close"),
    ]

    HELP_TEXT = """
[b]cq TUI 快捷键[/b]

全局
  [b]q / Ctrl+C[/b]  退出
  [b]?[/b]           显示帮助
  [b]Tab[/b]         切换焦点

会话
  [b]+ / -[/b]      下一个 / 上一个会话
  [b]a[/b]          添加任务到当前会话
  [b]r[/b]          运行当前会话队列
  [b]R[/b]          重置当前会话卡住/失败任务
  [b]C[/b]          清理当前会话旧 completed 任务

任务
  [b]n[/b]          手动领取下一个任务
  [b]x[/b]          标记选中任务为 completed
  [b]d[/b]          删除选中任务
  [b]D[/b]          删除所有会话的所有任务
"""

    def compose(self) -> ComposeResult:
        with Container(classes="dialog help"):
            yield Static(self.HELP_TEXT, classes="help-text")
            yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()


class ConfirmScreen(ModalScreen[bool]):
    """Modal screen asking for confirmation."""

    BINDINGS = [
        ("escape", "dismiss_false", "Cancel"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Container(classes="dialog"):
            yield Label(self.message, classes="dialog-title")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Yes", variant="error", id="yes")
                yield Button("No", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_dismiss_false(self) -> None:
        self.dismiss(False)


class CqTuiApp(App[None]):
    """Main cq TUI application."""

    CSS = """
    Screen { align: center middle; }

    .dialog {
        width: 60;
        height: auto;
        border: thick $background 80%;
        padding: 1 2;
        background: $surface;
    }

    .dialog-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    .dialog-buttons {
        height: auto;
        margin-top: 1;
        align-horizontal: right;
    }

    .dialog-buttons Button {
        margin-left: 1;
    }

    .help {
        width: 70;
        height: auto;
    }

    .help-text {
        height: auto;
        margin-bottom: 1;
    }

    #main-layout { width: 100%; height: 100%; }

    #session-pane {
        width: 25%;
        height: 100%;
        border: solid $primary;
    }

    #task-pane {
        width: 75%;
        height: 100%;
        border: solid $primary;
    }

    #session-list { height: 100%; }
    #task-table { height: 100%; }

    #status { height: 1; content-align: center middle; }
    """

    BINDINGS = [
        ("q,ctrl+c", "quit", "Quit"),
        ("?", "help", "Help"),
        ("a", "add_task", "Add task"),
        ("r", "run_session", "Run session"),
        ("R", "reset_session", "Reset session"),
        ("C", "cleanup_session", "Cleanup"),
        ("n", "next_task", "Next task"),
        ("x", "complete_task", "Complete task"),
        ("d", "delete_task", "Delete task"),
        ("D", "delete_all_sessions", "Delete all"),
        ("+", "next_session", "Next session"),
        ("-", "prev_session", "Prev session"),
    ]

    current_session: reactive[str] = reactive("default")

    def __init__(self, db_path: Path | str | None = None) -> None:
        super().__init__()
        self.db_path = db_path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-layout"):
            with Vertical(id="session-pane"):
                yield Label("Sessions", classes="dialog-title")
                yield SessionList(id="session-list")
            with Vertical(id="task-pane"):
                yield TaskTable(id="task-table")
        yield Label("Ready", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "cq TUI"
        self._ensure_db()
        self._load_sessions()
        self._select_session("default")

    def _ensure_db(self) -> None:
        try:
            store.init_db(self.db_path)
        except Exception as exc:
            self._set_status(f"Database error: {exc}")

    def _set_status(self, message: str) -> None:
        status = self.query_one("#status", Label)
        status.update(message)

    def _load_sessions(self) -> None:
        session_list = self.query_one("#session-list", SessionList)
        session_list.clear()
        try:
            sessions = store.list_sessions(path=self.db_path)
        except Exception as exc:
            self._set_status(f"Error loading sessions: {exc}")
            return

        if not sessions:
            sessions = ["default"]

        for session in sessions:
            session_list.append(ListItem(Label(session), name=session))

    def _select_session(self, session: str) -> None:
        session_list = self.query_one("#session-list", SessionList)
        for index, child in enumerate(session_list.children):
            if isinstance(child, ListItem) and child.name == session:
                session_list.index = index
                break
        self.current_session = session
        self._load_tasks()

    def watch_current_session(self, session: str) -> None:
        self.sub_title = f"Session: {session}"
        self._load_tasks()

    def _load_tasks(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        table.clear()
        try:
            tasks = store.list_tasks(
                session=self.current_session,
                limit=100,
                path=self.db_path,
            )
        except Exception as exc:
            self._set_status(f"Error loading tasks: {exc}")
            return

        for task in tasks:
            table.add_row(
                str(task["id"]),
                task["status"],
                _fmt_time(task["created_at"]),
                _fmt_desc(task["description"]),
                key=str(task["id"]),
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ListItem) and item.name:
            self.current_session = item.name

    def action_next_session(self) -> None:
        session_list = self.query_one("#session-list", SessionList)
        session_list.action_cursor_down()

    def action_prev_session(self) -> None:
        session_list = self.query_one("#session-list", SessionList)
        session_list.action_cursor_up()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    async def action_add_task(self) -> None:
        def on_result(result: dict[str, Any] | None) -> None:
            if result is None:
                return
            try:
                store.add_task(
                    result["description"],
                    session=result["session"],
                    context_policy=result["context_policy"],
                    path=self.db_path,
                )
                self._set_status(
                    f"Added task to [{result['session']}]: {result['description']}"
                )
                self._load_sessions()
                self._select_session(result["session"])
            except Exception as exc:
                self._set_status(f"Error adding task: {exc}")

        self.push_screen(AddTaskScreen(self.current_session), callback=on_result)

    def action_run_session(self) -> None:
        self._set_status(f"Running session: {self.current_session}...")

        async def runner() -> None:
            try:
                run_loop_session(
                    session=self.current_session,
                    once=False,
                    path=self.db_path,
                    retention_hours=None,
                )
                self._set_status(f"Finished running session: {self.current_session}")
            except Exception as exc:
                self._set_status(f"Run error: {exc}")
            finally:
                self._load_tasks()
                self._load_sessions()

        self.run_worker(runner)

    def action_reset_session(self) -> None:
        try:
            reset = store.reset_tasks(session=self.current_session, path=self.db_path)
            self._set_status(f"Reset {len(reset)} task(s) in {self.current_session}")
            self._load_tasks()
        except Exception as exc:
            self._set_status(f"Error: {exc}")

    def action_cleanup_session(self) -> None:
        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                deleted = store.cleanup_completed_tasks(
                    age_hours=0,
                    session=self.current_session,
                    path=self.db_path,
                )
                self._set_status(f"Cleaned up {deleted} task(s)")
                self._load_tasks()
                self._load_sessions()
            except Exception as exc:
                self._set_status(f"Error: {exc}")

        self.push_screen(
            ConfirmScreen(
                f"Delete all completed tasks in session '{self.current_session}'?"
            ),
            callback=on_confirm,
        )

    def action_delete_all_sessions(self) -> None:
        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                deleted = store.delete_all_sessions(path=self.db_path)
                self._set_status(f"Deleted all sessions ({deleted} task(s))")
                self.current_session = store.DEFAULT_SESSION
                self._load_tasks()
                self._load_sessions()
                self._select_session(store.DEFAULT_SESSION)
            except Exception as exc:
                self._set_status(f"Error: {exc}")

        self.push_screen(
            ConfirmScreen("Delete all tasks in all sessions?"),
            callback=on_confirm,
        )

    def action_next_task(self) -> None:
        try:
            task = store.claim_next(session=self.current_session, path=self.db_path)
            if task is None:
                self._set_status("No pending tasks.")
            else:
                self._set_status(f"Claimed task {task['id']}: {task['description']}")
                self._load_tasks()
        except Exception as exc:
            self._set_status(f"Error: {exc}")

    def action_complete_task(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        if table.cursor_row is None:
            self._set_status("No task selected.")
            return
        key = table.get_row_at(table.cursor_row)[0]
        try:
            store.complete_task(int(key), status="completed", path=self.db_path)
            self._set_status(f"Marked task {key} as completed")
            self._load_tasks()
            self._load_sessions()
        except Exception as exc:
            self._set_status(f"Error: {exc}")

    def action_delete_task(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        if table.cursor_row is None:
            self._set_status("No task selected.")
            return
        key = table.get_row_at(table.cursor_row)[0]

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                store.delete_task(int(key), path=self.db_path)
                self._set_status(f"Deleted task {key}")
                self._load_tasks()
                self._load_sessions()
            except Exception as exc:
                self._set_status(f"Error: {exc}")

        self.push_screen(
            ConfirmScreen(f"Delete task {key}?"),
            callback=on_confirm,
        )
