from __future__ import annotations

import asyncio

import pytest

from browser import BOARD_SIZES, MinesweeperBrowser
from models import Board, CellState
from solver import Action, ActionType, solve_chord, solve_deterministic, solve_probability

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _rate_limit_delay():
    """Small delay between tests to avoid rate limiting."""
    yield
    await asyncio.sleep(1)


@pytest.fixture(scope="module")
async def browser():
    b = MinesweeperBrowser(headless=True)
    await b.start()
    yield b
    await b.stop()


@pytest.fixture
async def fresh_game(browser):
    await browser.open_game(1)
    await asyncio.sleep(1)
    yield browser


# ── Page load & DOM ──────────────────────────────────────────────────


async def test_page_loads_and_has_game_element(browser):
    await browser.open_game(1)
    game_el = await browser.page.query_selector("#game")
    assert game_el is not None


async def test_smiley_element_exists(browser):
    await browser.open_game(1)
    smiley = await browser.page.query_selector("#top_area_face")
    assert smiley is not None


async def test_cells_exist_for_beginner(browser):
    await browser.open_game(1)
    cells = await browser.page.query_selector_all(".cell")
    assert len(cells) == 9 * 9


async def test_cell_ids_have_expected_format(browser):
    await browser.open_game(1)
    cells = await browser.page.query_selector_all(".cell")
    for el in cells[:5]:
        cell_id = await el.get_attribute("id")
        assert cell_id is not None
        assert cell_id.startswith("cell_")
        parts = cell_id.split("_")
        assert len(parts) == 3


# ── Board dimensions ─────────────────────────────────────────────────


@pytest.mark.parametrize("level,expected", [
    (1, (9, 9, 10)),
    (2, (16, 16, 40)),
    (3, (16, 30, 99)),
])
async def test_board_sizes_are_correct(browser, level, expected):
    await browser.open_game(level)
    await asyncio.sleep(0.3)
    cells = await browser.page.query_selector_all(".cell")
    rows, cols, mines = expected
    assert len(cells) == rows * cols


# ── Board reading ────────────────────────────────────────────────────


async def test_read_board_returns_correct_dimensions(fresh_game):
    board = await fresh_game.read_board(1)
    assert board.rows == 9
    assert board.cols == 9


async def test_initial_board_all_closed(fresh_game):
    board = await fresh_game.read_board(1)
    closed = board.closed_cells()
    assert len(closed) == 9 * 9


async def test_read_board_after_click_opens_cells(fresh_game):
    await fresh_game.click_cell(4, 4)
    await asyncio.sleep(0.5)
    board = await fresh_game.read_board(1)
    opened = board.opened_cells()
    assert len(opened) > 0


async def test_opened_cells_have_valid_values(fresh_game):
    await fresh_game.click_cell(4, 4)
    await asyncio.sleep(0.5)
    board = await fresh_game.read_board(1)
    for cell in board.opened_cells():
        assert 0 <= cell.value <= 8


async def test_board_str_representation(fresh_game):
    await fresh_game.click_cell(4, 4)
    await asyncio.sleep(0.5)
    board = await fresh_game.read_board(1)
    s = str(board)
    lines = s.split("\n")
    assert len(lines) == 9
    for line in lines:
        assert len(line.split()) == 9


# ── Clicking & flagging ──────────────────────────────────────────────


async def test_flag_on_closed_cell(fresh_game):
    await fresh_game.click_cell(0, 0)
    await asyncio.sleep(0.3)
    board = await fresh_game.read_board(1)
    # Find a closed cell to flag
    closed = board.closed_cells()
    if not closed:
        pytest.skip("Board fully opened on first click")
    target = closed[0]
    await fresh_game.flag_cell(target.row, target.col)
    await asyncio.sleep(0.3)
    board2 = await fresh_game.read_board(1)
    cell = board2.get_cell(target.row, target.col)
    assert cell.is_flagged


async def test_right_click_on_opened_cell_does_not_flag(fresh_game):
    await fresh_game.click_cell(4, 4)
    await asyncio.sleep(0.3)
    board = await fresh_game.read_board(1)
    opened = board.opened_cells()
    if not opened:
        pytest.skip("No opened cells")
    target = opened[0]
    await fresh_game.flag_cell(target.row, target.col)
    await asyncio.sleep(0.3)
    board2 = await fresh_game.read_board(1)
    cell = board2.get_cell(target.row, target.col)
    assert cell.is_opened  # should still be opened, not flagged


# ── Game status ──────────────────────────────────────────────────────


async def test_game_status_ongoing_after_start(fresh_game):
    status = await fresh_game.get_game_status()
    assert status == "ongoing"


async def test_game_status_lost_after_mine(fresh_game):
    await fresh_game.click_cell(0, 0)
    await asyncio.sleep(0.3)
    # Keep clicking until we hit a mine (or win)
    board = await fresh_game.read_board(1)
    for cell in board.all_cells():
        if cell.is_closed:
            await fresh_game.click_cell(cell.row, cell.col)
            await asyncio.sleep(0.1)
            status = await fresh_game.get_game_status()
            if status != "ongoing":
                break
    status = await fresh_game.get_game_status()
    assert status in ("won", "lost")


# ── Solver ───────────────────────────────────────────────────────────


async def test_solver_returns_actions_on_opened_board(fresh_game):
    await fresh_game.click_cell(4, 4)
    await asyncio.sleep(0.5)
    board = await fresh_game.read_board(1)
    actions = solve_deterministic(board)
    # Actions may be empty if board has no deterministic moves, but should be a list
    assert isinstance(actions, list)
    for act in actions:
        assert isinstance(act, Action)
        assert act.type in (ActionType.FLAG, ActionType.REVEAL)


async def test_solver_actions_are_valid_cells(fresh_game):
    await fresh_game.click_cell(4, 4)
    await asyncio.sleep(0.5)
    board = await fresh_game.read_board(1)
    actions = solve_deterministic(board)
    for act in actions:
        cell = board.get_cell(act.row, act.col)
        assert cell is not None
        if act.type == ActionType.FLAG:
            assert cell.is_closed
        elif act.type == ActionType.REVEAL:
            assert cell.is_closed


async def test_probability_solver_returns_valid_action(fresh_game):
    await fresh_game.click_cell(4, 4)
    await asyncio.sleep(0.5)
    board = await fresh_game.read_board(1)
    # Force empty deterministic to test probability fallback
    action = solve_probability(board)
    if action is not None:
        assert isinstance(action, Action)
        assert action.type == ActionType.REVEAL
        cell = board.get_cell(action.row, action.col)
        assert cell is not None
        assert cell.is_closed


async def test_chord_solver_returns_valid_actions(fresh_game):
    await fresh_game.click_cell(4, 4)
    await asyncio.sleep(0.5)
    board = await fresh_game.read_board(1)
    actions = solve_chord(board)
    assert isinstance(actions, list)
    for act in actions:
        assert isinstance(act, Action)
        cell = board.get_cell(act.row, act.col)
        assert cell is not None
        assert cell.is_opened


# ── Full game loop ───────────────────────────────────────────────────


async def test_play_full_game_completes(browser):
    from bot import play_game

    await browser.open_game(1)
    result = await play_game(browser, level=1, delay=0.02, verbose=False)
    assert isinstance(result, bool)


async def test_play_multiple_games(browser):
    from bot import play_game

    await browser.open_game(1)
    wins = 0
    for i in range(3):
        if i > 0:
            await browser.new_game()
            await asyncio.sleep(0.3)
        won = await play_game(browser, level=1, delay=0.02, verbose=False)
        if won:
            wins += 1
    assert wins >= 0  # just verify it ran without crashing
