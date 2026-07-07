"""Smoke tests for cq.tui."""

from pathlib import Path

import pytest

from cq import store
from cq.tui import CqTuiApp


@pytest.fixture
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "queue.db"
    store.init_db(db_path)
    store.add_task("Task A", session="s1", path=db_path)
    store.add_task("Task B", session="s2", path=db_path)
    return db_path


@pytest.mark.asyncio
async def test_tui_mounts(db: Path) -> None:
    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        assert app.is_mounted
        await pilot.pause()


@pytest.mark.asyncio
async def test_tui_shows_sessions_and_tasks(db: Path) -> None:
    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        await pilot.pause()

        session_list = app.query_one("#session-list")
        assert any(item.name == "s1" for item in session_list.children)
        assert any(item.name == "s2" for item in session_list.children)

        app.current_session = "s1"
        await pilot.pause()

        table = app.query_one("#task-table")
        assert table.row_count >= 1


@pytest.mark.asyncio
async def test_tui_opens_help(db: Path) -> None:
    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        await pilot.press("?")
        await pilot.pause()
        assert any(isinstance(screen, app.screen.__class__) for screen in app._screen_stack)


@pytest.mark.asyncio
async def test_tui_switch_session(db: Path) -> None:
    app = CqTuiApp(db_path=db)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.current_session = "s2"
        await pilot.pause()
        assert app.current_session == "s2"
