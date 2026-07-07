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
    RadioButton,
    RadioSet,
    RichLog,
    Static,
)

from cq import store
from cq.wrapper import run_loop


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return ""
    return iso[:19].replace("T", " ")


def _fmt_desc(desc: str, max_len: int = 50) -> str:
    if len(desc) > max_len:
        return desc[: max_len - 3] + "..."
    return desc


class TaskTable(DataTable):
    """Data table showing queued tasks."""

    def on_mount(self) -> None:
        self.add_columns("ID", "Status", "Policy", "Created", "Description")
        self.cursor_type = "row"


class AddTaskScreen(ModalScreen[dict[str, Any] | None]):
    """Modal screen for adding a new task."""

    BINDINGS = [
        ("escape", "dismiss_none", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Container(classes="dialog"):
            yield Label("Add task", classes="dialog-title")
            yield Label("Description:")
            self.description = Input(placeholder="What should Claude do?")
            yield self.description
            self.new_policy = RadioSet(
                RadioButton("continue conversation", value=True),
                RadioButton("start new conversation"),
            )
            yield self.new_policy
            with Horizontal(classes="dialog-buttons"):
                yield Button("Add", variant="primary", id="add")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add":
            context_policy = "new" if self.new_policy.pressed_index == 1 else "continue"
            self.dismiss(
                {
                    "description": self.description.value,
                    "context_policy": context_policy,
                }
            )
        else:
            self.dismiss(None)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


class EditTaskScreen(ModalScreen[dict[str, Any] | None]):
    """Modal screen for editing an existing task."""

    BINDINGS = [
        ("escape", "dismiss_none", "Cancel"),
    ]

    def __init__(self, task: dict[str, Any]) -> None:
        super().__init__()
        self.task_data = task

    def compose(self) -> ComposeResult:
        with Container(classes="dialog"):
            yield Label(f"Edit task {self.task_data['id']}", classes="dialog-title")
            yield Label("Description:")
            self.description = Input(
                value=self.task_data["description"],
                placeholder="What should Claude do?",
            )
            yield self.description
            self.new_policy = RadioSet(
                RadioButton("continue conversation", value=self.task_data["context_policy"] == "continue"),
                RadioButton("start new conversation", value=self.task_data["context_policy"] == "new"),
            )
            yield self.new_policy
            with Horizontal(classes="dialog-buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            context_policy = "new" if self.new_policy.pressed_index == 1 else "continue"
            self.dismiss(
                {
                    "id": self.task_data["id"],
                    "description": self.description.value,
                    "context_policy": context_policy,
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

任务队列
  [b]a[/b]          添加任务
  [b]e[/b]          编辑选中任务
  [b]r[/b]          运行队列（后台 worker）
  [b]R[/b]          重置卡住/失败任务
  [b]C[/b]          清理旧 completed 任务
  [b]n[/b]          手动领取下一个任务

单任务
  [b]Enter[/b]      查看选中任务的输出详情
  [b]x[/b]          标记选中任务为 completed
  [b]d[/b]          删除选中任务
  [b]D[/b]          删除所有任务
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


class TaskDetailScreen(ModalScreen[None]):
    """Modal screen showing full task result/output."""

    BINDINGS = [
        ("escape,q", "dismiss", "Close"),
    ]

    def __init__(self, task: dict[str, Any]) -> None:
        super().__init__()
        self.task_data = task

    def compose(self) -> ComposeResult:
        with Container(classes="dialog help"):
            title = f"Task {self.task_data['id']} - {self.task_data['status']}"
            yield Label(title, classes="dialog-title")

            lines = [
                f"Description: {self.task_data['description']}",
                f"Policy: {self.task_data['context_policy']}",
                f"Created: {_fmt_time(self.task_data['created_at'])}",
                "",
            ]
            if self.task_data.get("result"):
                lines.append("[b]Result:[/b]")
                lines.append(self.task_data["result"])
            elif self.task_data.get("error"):
                lines.append("[b]Error:[/b]")
                lines.append(self.task_data["error"])
            else:
                lines.append("No output recorded yet.")

            yield Static("\n".join(lines), classes="help-text")
            yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()


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
        width: 80;
        height: auto;
    }

    .help-text {
        height: auto;
        margin-bottom: 1;
    }

    #main-layout { width: 100%; height: 100%; }

    #task-pane {
        width: 100%;
        height: 60%;
        border: solid $primary;
    }

    #log-pane {
        width: 100%;
        height: 40%;
        border: solid $primary;
        padding: 0 1;
    }

    #log-title {
        height: 1;
        text-style: bold;
    }

    #task-table { height: 100%; }
    #log { height: 100%; }
    """

    BINDINGS = [
        ("q,ctrl+c", "quit", "Quit"),
        ("?", "help", "Help"),
        ("a", "add_task", "Add task"),
        ("e", "edit_task", "Edit task"),
        ("r", "run_queue", "Run queue"),
        ("R", "reset_queue", "Reset queue"),
        ("C", "cleanup_queue", "Cleanup"),
        ("n", "next_task", "Next task"),
        ("enter", "show_detail", "Show detail"),
        ("x", "complete_task", "Complete task"),
        ("d", "delete_task", "Delete task"),
        ("D", "delete_all_tasks", "Delete all"),
    ]

    def __init__(self, db_path: Path | str | None = None) -> None:
        super().__init__()
        self.db_path = db_path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="main-layout"):
            with Vertical(id="task-pane"):
                yield TaskTable(id="task-table")
            with Vertical(id="log-pane"):
                yield Label("Output / Log", id="log-title")
                yield RichLog(id="log", highlight=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "cq TUI"
        self._ensure_db()
        self._load_tasks()
        self._log("Ready. Press 'a' to add a task, 'r' to run queue.")

    def _ensure_db(self) -> None:
        try:
            store.init_db(self.db_path)
        except Exception as exc:
            self._log(f"Database error: {exc}")

    def _log(self, message: str) -> None:
        log = self.query_one("#log", RichLog)
        log.write(message)

    def _load_tasks(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        table.clear()
        try:
            tasks = store.list_tasks(limit=100, path=self.db_path)
        except Exception as exc:
            self._log(f"Error loading tasks: {exc}")
            return

        for task in tasks:
            table.add_row(
                str(task["id"]),
                task["status"],
                task["context_policy"],
                _fmt_time(task["created_at"]),
                _fmt_desc(task["description"]),
                key=str(task["id"]),
            )

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    async def action_add_task(self) -> None:
        def on_result(result: dict[str, Any] | None) -> None:
            if result is None:
                return
            try:
                task = store.add_task(
                    result["description"],
                    context_policy=result["context_policy"],
                    path=self.db_path,
                )
                self._log(
                    f"Added task {task['id']} ({task['context_policy']}): "
                    f"{task['description']}"
                )
                self._load_tasks()
            except Exception as exc:
                self._log(f"Error adding task: {exc}")

        self.push_screen(AddTaskScreen(), callback=on_result)

    async def action_edit_task(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        if table.cursor_row is None:
            self._log("No task selected.")
            return

        row_key = table.get_row_at(table.cursor_row)[0]
        try:
            task = store.get_task(int(row_key), path=self.db_path)
        except Exception as exc:
            self._log(f"Error: {exc}")
            return

        if task is None:
            self._log(f"Task {row_key} not found.")
            return

        if task["status"] == "in_progress":
            self._log(f"Task {row_key} is in progress; cannot edit while running.")
            return

        def on_result(result: dict[str, Any] | None) -> None:
            if result is None:
                return
            try:
                updates: dict[str, Any] = {
                    "description": result["description"],
                    "context_policy": result["context_policy"],
                }
                updated = store.update_task(result["id"], path=self.db_path, **updates)
                self._log(
                    f"Updated task {updated['id']} ({updated['context_policy']}): "
                    f"{updated['description']}"
                )
                self._load_tasks()
            except Exception as exc:
                self._log(f"Error updating task: {exc}")

        self.push_screen(EditTaskScreen(task), callback=on_result)

    def action_run_queue(self) -> None:
        self._log("Starting queue runner...")

        def on_task_finished(completed: dict[str, Any]) -> None:
            status = completed["status"]
            summary = ""
            if completed.get("result"):
                summary = completed["result"][:200].replace("\n", " ")
            elif completed.get("error"):
                summary = completed["error"][:200].replace("\n", " ")
            self._log(f"Task {completed['id']} finished: {status} - {summary}")
            self._load_tasks()

        def runner() -> None:
            try:
                while True:
                    task = store.claim_next(path=self.db_path)
                    if task is None:
                        self.call_from_thread(self._log, "Queue is empty.")
                        break
                    self.call_from_thread(
                        self._log,
                        f"Running task {task['id']}: {task['description']}",
                    )
                    from cq.wrapper import run_task

                    completed = run_task(task["id"], path=self.db_path)
                    self.call_from_thread(on_task_finished, completed)

                    deleted = store.cleanup_completed_tasks(path=self.db_path)
                    if deleted:
                        self.call_from_thread(self._log, f"Cleaned up {deleted} old task(s)")
            except Exception as exc:
                self.call_from_thread(self._log, f"Run error: {exc}")

        self.run_worker(runner, thread=True)

    def action_reset_queue(self) -> None:
        try:
            reset = store.reset_tasks(path=self.db_path)
            self._log(f"Reset {len(reset)} task(s) to pending")
            self._load_tasks()
        except Exception as exc:
            self._log(f"Error: {exc}")

    def action_cleanup_queue(self) -> None:
        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                deleted = store.cleanup_completed_tasks(
                    age_hours=0,
                    path=self.db_path,
                )
                self._log(f"Cleaned up {deleted} task(s)")
                self._load_tasks()
            except Exception as exc:
                self._log(f"Error: {exc}")

        self.push_screen(
            ConfirmScreen("Delete all completed tasks?"),
            callback=on_confirm,
        )

    def action_next_task(self) -> None:
        try:
            task = store.claim_next(path=self.db_path)
            if task is None:
                self._log("No pending tasks.")
            else:
                self._log(f"Claimed task {task['id']}: {task['description']}")
                self._load_tasks()
        except Exception as exc:
            self._log(f"Error: {exc}")

    def action_show_detail(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        if table.cursor_row is None:
            self._log("No task selected.")
            return
        row_key = table.get_row_at(table.cursor_row)[0]
        try:
            task = store.get_task(int(row_key), path=self.db_path)
            if task is None:
                self._log(f"Task {row_key} not found.")
                return
            self.push_screen(TaskDetailScreen(task))
        except Exception as exc:
            self._log(f"Error: {exc}")

    def action_complete_task(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        if table.cursor_row is None:
            self._log("No task selected.")
            return
        key = table.get_row_at(table.cursor_row)[0]
        try:
            store.complete_task(int(key), status="completed", path=self.db_path)
            self._log(f"Marked task {key} as completed")
            self._load_tasks()
        except Exception as exc:
            self._log(f"Error: {exc}")

    def action_delete_task(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        if table.cursor_row is None:
            self._log("No task selected.")
            return
        key = table.get_row_at(table.cursor_row)[0]

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                if store.delete_task(int(key), path=self.db_path):
                    self._log(f"Deleted task {key}")
                    self._load_tasks()
                else:
                    self._log(f"Task {key} not found")
            except Exception as exc:
                self._log(f"Error: {exc}")

        self.push_screen(
            ConfirmScreen(f"Delete task {key}?"),
            callback=on_confirm,
        )

    def action_delete_all_tasks(self) -> None:
        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                deleted = store.delete_all_tasks(path=self.db_path)
                self._log(f"Deleted all tasks ({deleted})")
                self._load_tasks()
            except Exception as exc:
                self._log(f"Error: {exc}")

        self.push_screen(
            ConfirmScreen("Delete all tasks?"),
            callback=on_confirm,
        )
