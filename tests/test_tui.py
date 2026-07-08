"""Smoke tests for cq.tui."""

from pathlib import Path

import pytest
from textual.widgets import Button

from cq import store
from cq.tui import CqTuiApp, EditTaskScreen, TaskDetailScreen


@pytest.fixture
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "queue.db"
    store.init_db(db_path)
    store.add_task("Task A", path=db_path)
    store.add_task("Task B", context_policy="new", path=db_path)
    return db_path


@pytest.mark.asyncio
async def test_tui_mounts(db: Path) -> None:
    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        assert app.is_mounted
        await pilot.pause()


@pytest.mark.asyncio
async def test_tui_shows_tasks(db: Path) -> None:
    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        await pilot.pause()

        table = app.query_one("#task-table")
        assert table.row_count >= 2


@pytest.mark.asyncio
async def test_tui_opens_help(db: Path) -> None:
    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        await pilot.press("?")
        await pilot.pause()
        assert len(app.screen_stack) >= 2


@pytest.mark.asyncio
async def test_tui_opens_task_detail(db: Path) -> None:
    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        await pilot.pause()
        task = store.list_tasks(path=db)[0]
        app.push_screen(TaskDetailScreen(task))
        await pilot.pause()
        assert app.screen.__class__.__name__ == "TaskDetailScreen"


@pytest.mark.asyncio
async def test_tui_opens_edit_screen(db: Path) -> None:
    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        await pilot.pause()
        task = store.list_tasks(path=db)[0]
        app.push_screen(EditTaskScreen(task))
        await pilot.pause()
        assert app.screen.__class__.__name__ == "EditTaskScreen"


@pytest.mark.asyncio
async def test_tui_cleanup_queue_deletes_completed_tasks(db: Path) -> None:
    task = store.list_tasks(path=db)[0]
    store.claim_next(path=db)
    store.complete_task(task["id"], status="completed", path=db)

    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_cleanup_queue()
        await pilot.pause()
        yes_button = app.screen.query_one("#yes", Button)
        yes_button.press()
        await pilot.pause()

        assert store.get_task(task["id"], path=db) is None


@pytest.mark.asyncio
async def test_tui_empty_state_hidden_when_tasks_exist(db: Path) -> None:
    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        await pilot.pause()
        empty_state = app.query_one("#empty-state")
        assert "visible" not in empty_state.classes


@pytest.mark.asyncio
async def test_tui_empty_state_visible_when_no_tasks(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    store.init_db(db_path)

    app = CqTuiApp(db_path=db_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        empty_state = app.query_one("#empty-state")
        assert "visible" in empty_state.classes


@pytest.mark.asyncio
async def test_tui_status_bar_shows_counts(db: Path) -> None:
    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        await pilot.pause()
        status_text = app.query_one("#status-bar-content")
        rendered = str(status_text.render())
        assert "Pending: 2" in rendered


@pytest.mark.asyncio
async def test_tui_log_includes_timestamp(db: Path) -> None:
    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one("#log")
        app.write_log("test message")
        await pilot.pause()
        lines = log.lines
        assert any("test message" in str(line) for line in lines)
        assert any("[" in str(line) and "]" in str(line) for line in lines)
