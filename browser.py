from __future__ import annotations

import asyncio
from typing import Literal

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from models import Board, Cell, CellState

LEVEL_MAP = {
    "beginner": 1,
    "intermediate": 2,
    "expert": 3,
}

BOARD_SIZES = {
    1: (9, 9, 10),    # rows, cols, mines
    2: (16, 16, 40),
    3: (16, 30, 99),
}

CLASS_TO_STATE = {
    "hdd_opened": CellState.OPENED,
    "hdd_flag": CellState.FLAGGED,
    "hdd_type10": CellState.MINE,
    "hdd_type11": CellState.EXPLODED,
}


def _parse_value(classes: list[str]) -> int:
    for i in range(1, 9):
        if f"hdd_type{i}" in classes:
            return i
    return 0


def _parse_state(classes: list[str]) -> CellState:
    for cls, state in CLASS_TO_STATE.items():
        if cls in classes:
            return state
    return CellState.CLOSED


class MinesweeperBrowser:
    def __init__(self, headless: bool = False) -> None:
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    @property
    def page(self) -> Page:
        assert self._page is not None
        return self._page

    async def open_game(self, level: int | str = 1) -> None:
        if isinstance(level, str):
            level = LEVEL_MAP.get(level.lower(), 1)
        url = f"https://minesweeper.online/start/{level}"
        await self.page.goto(url, wait_until="networkidle")
        await self.page.wait_for_selector("#game", timeout=15000)
        await asyncio.sleep(0.5)

    async def read_board(self, level: int = 1) -> Board:
        rows, cols, mine_count = BOARD_SIZES[level]
        board = Board(rows, cols, mine_count)

        cell_elements = await self.page.query_selector_all(".cell")
        for el in cell_elements:
            cell_id = await el.get_attribute("id")
            if not cell_id or not cell_id.startswith("cell_"):
                continue

            parts = cell_id.split("_")
            if len(parts) != 3:
                continue

            col_idx, row_idx = int(parts[1]), int(parts[2])
            if row_idx >= rows or col_idx >= cols:
                continue

            class_attr = await el.get_attribute("class") or ""
            classes = class_attr.split()

            state = _parse_state(classes)
            value = _parse_value(classes) if state == CellState.OPENED else 0

            cell = board.get_cell(row_idx, col_idx)
            if cell:
                cell.state = state
                cell.value = value

        return board

    async def click_cell(self, row: int, col: int) -> None:
        selector = f"#cell_{col}_{row}"
        el = await self.page.query_selector(selector)
        if el:
            box = await el.bounding_box()
            if box:
                await self.page.mouse.click(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2,
                )
                await asyncio.sleep(0.05)

    async def flag_cell(self, row: int, col: int) -> None:
        selector = f"#cell_{col}_{row}"
        el = await self.page.query_selector(selector)
        if el:
            box = await el.bounding_box()
            if box:
                await self.page.mouse.click(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2,
                    button="right",
                )
                await asyncio.sleep(0.05)

    async def chord_cell(self, row: int, col: int) -> None:
        """Middle-click (chord) on a cell to reveal all unflagged neighbors."""
        selector = f"#cell_{col}_{row}"
        el = await self.page.query_selector(selector)
        if el:
            box = await el.bounding_box()
            if box:
                await self.page.mouse.click(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2,
                    button="middle",
                )
                await asyncio.sleep(0.05)

    async def get_game_status(self) -> Literal["ongoing", "won", "lost"]:
        game_el = await self.page.query_selector("#game")
        if game_el:
            cls = await game_el.get_attribute("class") or ""
            if "gameover" in cls:
                return "lost"

        smiley_el = await self.page.query_selector("#smiley")
        if smiley_el:
            cls = await smiley_el.get_attribute("class") or ""
            if "hd_win" in cls:
                return "won"
            if "hd_lose" in cls or "hdd_lose" in cls:
                return "lost"

        return "ongoing"

    async def new_game(self) -> None:
        smiley = await self.page.query_selector("#smiley")
        if smiley:
            await smiley.click()
            await asyncio.sleep(0.3)
