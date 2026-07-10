"""Interactive TUI for cq using Textual."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Grid, Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    RadioButton,
    RadioSet,
    RichLog,
    Static,
    TextArea,
)

from cq import store
from cq.wrapper import run_loop


_STATUS_STYLES = {
    "pending": "status-pending",
    "in_progress": "status-in_progress",
    "completed": "status-completed",
    "failed": "status-failed",
}


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return ""
    return iso[:19].replace("T", " ")


def _fmt_desc(desc: str, max_len: int = 50) -> str:
    if len(desc) > max_len:
        return desc[: max_len - 3] + "..."
    return desc


def _fmt_duration(task: dict[str, Any]) -> str:
    """Format task duration from started_at to completed_at, or started to now."""
    started = task.get("started_at")
    completed = task.get("completed_at")
    if not started:
        return ""
    end = completed or datetime.now(timezone.utc).isoformat()
    try:
        started_dt = datetime.fromisoformat(started)
        end_dt = datetime.fromisoformat(end)
        delta = end_dt - started_dt
        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            return f"{total_seconds}s"
        minutes, seconds = divmod(total_seconds, 60)
        if minutes < 60:
            return f"{minutes}m {seconds}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m {seconds}s"
    except ValueError:
        return ""


def _status_text(status: str) -> Text:
    """Return a styled Text object for a task status."""
    style = _STATUS_STYLES.get(status, "")
    return Text(status, style=style)


class TaskTextArea(TextArea):
    """Multi-line task description input that submits on Enter."""

    class Submitted(Message, bubble=True):
        """Posted when the user presses Enter in the text area."""

        def __init__(self, text_area: "TaskTextArea") -> None:
            self.text = text_area.text
            super().__init__()

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self))
            return
        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        await super()._on_key(event)


class TaskTable(DataTable):
    """Data table showing queued tasks."""

    def on_mount(self) -> None:
        self.add_columns(
            ("ID", "6"),
            ("Status", "12"),
            ("Policy", "10"),
            ("Created", "20"),
            "Description",
        )
        self.cursor_type = "row"


class AddTaskScreen(ModalScreen[dict[str, Any] | None]):
    """Modal screen for adding a new task."""

    BINDINGS = [
        ("escape", "dismiss_none", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Container(classes="dialog"):
            yield Label("Add task", classes="dialog-title")
            yield Label("Description (Enter to save, Shift+Enter for new line):")
            self.description = TaskTextArea(
                placeholder="What should Claude do?",
                classes="task-input",
            )
            yield self.description
            self.new_policy = RadioSet(
                RadioButton("continue conversation", value=True),
                RadioButton("start new conversation"),
            )
            yield self.new_policy
            with Horizontal(classes="dialog-buttons"):
                yield Button("Add", variant="primary", id="add")
                yield Button("Cancel", id="cancel")

    def _submit(self) -> None:
        description = self.description.text.strip()
        if not description:
            return
        context_policy = "new" if self.new_policy.pressed_index == 1 else "continue"
        self.dismiss(
            {
                "description": description,
                "context_policy": context_policy,
            }
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add":
            self._submit()
        else:
            self.dismiss(None)

    def on_task_text_area_submitted(self, event: TaskTextArea.Submitted) -> None:
        self._submit()

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
            yield Label("Description (Enter to save, Shift+Enter for new line):")
            self.description = TaskTextArea(
                text=self.task_data["description"],
                placeholder="What should Claude do?",
                classes="task-input",
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

    def _submit(self) -> None:
        description = self.description.text.strip()
        if not description:
            return
        context_policy = "new" if self.new_policy.pressed_index == 1 else "continue"
        self.dismiss(
            {
                "id": self.task_data["id"],
                "description": description,
                "context_policy": context_policy,
            }
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._submit()
        else:
            self.dismiss(None)

    def on_task_text_area_submitted(self, event: TaskTextArea.Submitted) -> None:
        self._submit()

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    """Modal screen showing keyboard shortcuts."""

    BINDINGS = [
        ("escape,q", "dismiss", "Close"),
    ]

    HELP_ROWS = [
        ("q / Ctrl+C", "退出 TUI"),
        ("?", "显示本帮助"),
        ("Tab", "切换焦点"),
        ("a", "添加任务"),
        ("e", "编辑选中任务"),
        ("r", "运行队列（后台 worker）"),
        ("R", "重置卡住/失败任务"),
        ("C", "清理旧 completed 任务"),
        ("n", "手动领取下一个任务"),
        ("Enter", "查看选中任务详情 / 弹窗内保存"),
        ("Shift+Enter", "在描述输入框内换行"),
        ("Escape", "取消 / 关闭弹窗"),
        ("x", "标记选中任务为 completed"),
        ("d", "删除选中任务"),
        ("D", "删除所有任务"),
    ]

    def compose(self) -> ComposeResult:
        with Container(classes="dialog help"):
            yield Label("cq TUI 快捷键", classes="dialog-title")
            table: DataTable = DataTable(id="help-table")
            table.add_columns("按键", "功能")
            table.cursor_type = "none"
            for key, action in self.HELP_ROWS:
                table.add_row(key, action)
            yield table
            yield Static("按 Esc 或 q 关闭", classes="help-text")
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

    def _detail_row(self, label: str, value: str) -> ComposeResult:
        yield Static(label, classes="detail-label")
        yield Static(value, classes="detail-value")

    def compose(self) -> ComposeResult:
        with Container(classes="dialog help"):
            title = f"Task {self.task_data['id']} - {self.task_data['status']}"
            yield Label(title, classes="dialog-title")

            with Grid(id="detail-grid"):
                yield from self._detail_row(
                    "Description", self.task_data["description"]
                )
                yield from self._detail_row(
                    "Policy", self.task_data["context_policy"]
                )
                yield from self._detail_row(
                    "Created", _fmt_time(self.task_data["created_at"])
                )
                yield from self._detail_row(
                    "Started", _fmt_time(self.task_data.get("started_at"))
                )
                yield from self._detail_row(
                    "Completed", _fmt_time(self.task_data.get("completed_at"))
                )
                yield from self._detail_row("Duration", _fmt_duration(self.task_data))

            if self.task_data.get("result"):
                yield Static("Result:", classes="detail-label")
                yield Static(self.task_data["result"], classes="detail-result")
            elif self.task_data.get("error"):
                yield Static("Error:", classes="detail-label")
                yield Static(self.task_data["error"], classes="detail-error")
            else:
                yield Static("No output recorded yet.", classes="help-text")

            yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()


class CqTuiApp(App[None]):
    """Main cq TUI application."""

    CSS_PATH = "tui.css"

    BINDINGS = [
        ("q,ctrl+c", "quit", "Quit"),
        ("?", "help", "Help"),
        ("a", "add_task", "Add task"),
        ("e", "edit_task", "Edit task"),
        ("r", "run_queue", "Run queue"),
        ("R", "reset_queue", "Reset queue"),
        ("c", "cleanup_queue", "Cleanup"),
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
                yield Static(
                    "暂无任务。按 'a' 添加任务，'r' 运行队列。",
                    id="empty-state",
                )
            with Vertical(id="log-pane"):
                yield Label("Output / Log", id="log-title")
                yield RichLog(id="log", highlight=True, wrap=True)
        yield Horizontal(Static("", id="status-bar-content"), id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "cq TUI"
        self._ensure_db()
        self._load_tasks()
        self.write_log("Ready. Press 'a' to add a task, 'r' to run queue.")

    def _ensure_db(self) -> None:
        try:
            store.init_db(self.db_path)
        except Exception as exc:
            self.write_log(f"Database error: {exc}")

    def write_log(self, message: str) -> None:
        log = self.query_one("#log", RichLog)
        timestamp = datetime.now().strftime("%H:%M:%S")
        log.write(f"[{timestamp}] {escape(message)}")

    def _load_tasks(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        table.clear()
        empty_state = self.query_one("#empty-state", Static)
        try:
            tasks = store.list_tasks(limit=100, path=self.db_path)
        except Exception as exc:
            self.write_log(f"Error loading tasks: {exc}")
            return

        if not tasks:
            empty_state.add_class("visible")
        else:
            empty_state.remove_class("visible")

        for task in tasks:
            table.add_row(
                str(task["id"]),
                _status_text(task["status"]),
                task["context_policy"],
                _fmt_time(task["created_at"]),
                _fmt_desc(task["description"]),
                key=str(task["id"]),
            )

        self._update_status_bar(tasks)

    def _update_status_bar(self, tasks: list[dict[str, Any]]) -> None:
        counts: dict[str, int] = {
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "failed": 0,
        }
        for task in tasks:
            status = task.get("status")
            if status in counts:
                counts[status] += 1

        # 显示数据库实际位置，让用户一眼看到"根目录"落在哪里
        try:
            db_loc = store.init_db(self.db_path)
            db_dir = str(db_loc.parent)
        except Exception:
            db_dir = "?"

        status_text = self.query_one("#status-bar-content", Static)
        status_text.update(
            f"DB: {db_dir} | "
            f"Pending: {counts['pending']} | "
            f"In Progress: {counts['in_progress']} | "
            f"Completed: {counts['completed']} | "
            f"Failed: {counts['failed']}"
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
                self.write_log(
                    f"Added task {task['id']} ({task['context_policy']}): "
                    f"{task['description']}"
                )
                self._load_tasks()
            except Exception as exc:
                self.write_log(f"Error adding task: {exc}")

        self.push_screen(AddTaskScreen(), callback=on_result)

    async def action_edit_task(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        if table.cursor_row is None:
            self.write_log("No task selected.")
            return

        row_key = table.get_row_at(table.cursor_row)[0]
        try:
            task = store.get_task(int(row_key), path=self.db_path)
        except Exception as exc:
            self.write_log(f"Error: {exc}")
            return

        if task is None:
            self.write_log(f"Task {row_key} not found.")
            return

        if task["status"] == "in_progress":
            self.write_log(f"Task {row_key} is in progress; cannot edit while running.")
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
                self.write_log(
                    f"Updated task {updated['id']} ({updated['context_policy']}): "
                    f"{updated['description']}"
                )
                self._load_tasks()
            except Exception as exc:
                self.write_log(f"Error updating task: {exc}")

        self.push_screen(EditTaskScreen(task), callback=on_result)

    def action_run_queue(self) -> None:
        self.write_log("Starting queue runner...")
        self.sub_title = "Running queue..."

        def on_task_finished(completed: dict[str, Any]) -> None:
            status = completed["status"]
            self.write_log(f"Task {completed['id']} finished: {status}")
            if completed.get("result"):
                self.write_log(completed["result"])
            elif completed.get("error"):
                self.write_log(completed["error"])
            self._load_tasks()

        def runner() -> None:
            try:
                while True:
                    task = store.claim_next(path=self.db_path)
                    if task is None:
                        self.call_from_thread(self.write_log, "Queue is empty.")
                        break
                    self.call_from_thread(
                        self.write_log,
                        f"Running task {task['id']}: {task['description']}",
                    )
                    from cq.wrapper import run_task

                    completed = run_task(task["id"], path=self.db_path)
                    self.call_from_thread(on_task_finished, completed)

                    deleted = store.cleanup_completed_tasks(path=self.db_path)
                    if deleted:
                        self.call_from_thread(self.write_log, f"Cleaned up {deleted} old task(s)")
            except Exception as exc:
                self.call_from_thread(self.write_log, f"Run error: {exc}")
            finally:
                self.call_from_thread(setattr, self, "sub_title", "")

        self.run_worker(runner, thread=True)

    def action_reset_queue(self) -> None:
        try:
            reset = store.reset_tasks(path=self.db_path)
            self.write_log(f"Reset {len(reset)} task(s) to pending")
            self._load_tasks()
        except Exception as exc:
            self.write_log(f"Error: {exc}")

    def action_cleanup_queue(self) -> None:
        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                deleted = store.cleanup_completed_tasks(
                    age_hours=0,
                    path=self.db_path,
                )
                self.write_log(f"Cleaned up {deleted} task(s)")
                self._load_tasks()
            except Exception as exc:
                self.write_log(f"Error: {exc}")

        self.push_screen(
            ConfirmScreen("Delete all completed tasks?"),
            callback=on_confirm,
        )

    def action_next_task(self) -> None:
        try:
            task = store.claim_next(path=self.db_path)
            if task is None:
                self.write_log("No pending tasks.")
            else:
                self.write_log(f"Claimed task {task['id']}: {task['description']}")
                self._load_tasks()
        except Exception as exc:
            self.write_log(f"Error: {exc}")

    def action_show_detail(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        if table.cursor_row is None:
            self.write_log("No task selected.")
            return
        row_key = table.get_row_at(table.cursor_row)[0]
        try:
            task = store.get_task(int(row_key), path=self.db_path)
            if task is None:
                self.write_log(f"Task {row_key} not found.")
                return
            self.push_screen(TaskDetailScreen(task))
        except Exception as exc:
            self.write_log(f"Error: {exc}")

    def action_complete_task(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        if table.cursor_row is None:
            self.write_log("No task selected.")
            return
        key = table.get_row_at(table.cursor_row)[0]
        try:
            store.complete_task(int(key), status="completed", path=self.db_path)
            self.write_log(f"Marked task {key} as completed")
            self._load_tasks()
        except Exception as exc:
            self.write_log(f"Error: {exc}")

    def action_delete_task(self) -> None:
        table = self.query_one("#task-table", TaskTable)
        if table.cursor_row is None:
            self.write_log("No task selected.")
            return
        key = table.get_row_at(table.cursor_row)[0]

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                if store.delete_task(int(key), path=self.db_path):
                    self.write_log(f"Deleted task {key}")
                    self._load_tasks()
                else:
                    self.write_log(f"Task {key} not found")
            except Exception as exc:
                self.write_log(f"Error: {exc}")

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
                self.write_log(f"Deleted all tasks ({deleted})")
                self._load_tasks()
            except Exception as exc:
                self.write_log(f"Error: {exc}")

        self.push_screen(
            ConfirmScreen("Delete all tasks?"),
            callback=on_confirm,
        )
