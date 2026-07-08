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
