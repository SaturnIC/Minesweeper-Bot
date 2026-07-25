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
    "hd_opened": CellState.OPENED,
    "hd_flag": CellState.FLAGGED,
    "hd_type10": CellState.MINE,
    "hd_type11": CellState.EXPLODED,
}


def _parse_value(classes: list[str]) -> int:
    for i in range(1, 9):
        if f"hd_type{i}" in classes:
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
        self._context = await self._browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
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
        await self.page.wait_for_selector("#game", timeout=30000)
        await asyncio.sleep(0.5)

    async def read_board(self, level: int | None = None) -> Board:
        cell_elements = await self.page.query_selector_all(".cell")

        # Auto-detect dimensions from cell IDs
        max_row, max_col = 0, 0
        parsed: list[tuple[int, int, CellState, int]] = []

        for el in cell_elements:
            cell_id = await el.get_attribute("id")
            if not cell_id or not cell_id.startswith("cell_"):
                continue
            parts = cell_id.split("_")
            if len(parts) != 3:
                continue
            col_idx, row_idx = int(parts[1]), int(parts[2])
            max_row = max(max_row, row_idx)
            max_col = max(max_col, col_idx)

            class_attr = await el.get_attribute("class") or ""
            classes = class_attr.split()
            state = _parse_state(classes)
            value = _parse_value(classes) if state == CellState.OPENED else 0
            parsed.append((row_idx, col_idx, state, value))

        rows = max_row + 1
        cols = max_col + 1

        # Try to read mine counter from the page
        mine_count = await self._read_mine_counter()
        if mine_count is None:
            # Fall back to level lookup if provided
            if level is not None and level in BOARD_SIZES:
                mine_count = BOARD_SIZES[level][2]
            else:
                mine_count = 0

        board = Board(rows, cols, mine_count)
        for row_idx, col_idx, state, value in parsed:
            cell = board.get_cell(row_idx, col_idx)
            if cell:
                cell.state = state
                cell.value = value

        return board

    async def _read_mine_counter(self) -> int | None:
        """Try to read the mine counter from minesweeper.online."""
        for sel in ["#top_area_mines", ".top-area-mines", "[class*=mines]"]:
            el = await self.page.query_selector(sel)
            if el:
                text = (await el.inner_text()).strip()
                # The counter may show negative values or have leading zeros
                cleaned = text.lstrip("0") or "0"
                # Handle negative (e.g. "-01" → -1)
                if cleaned.startswith("-"):
                    try:
                        return -int(cleaned[1:])
                    except ValueError:
                        pass
                else:
                    try:
                        return int(cleaned)
                    except ValueError:
                        pass
        return None

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
        smiley_el = await self.page.query_selector("#top_area_face")
        if smiley_el:
            cls = await smiley_el.get_attribute("class") or ""
            if "win" in cls:
                return "won"
            if "lose" in cls:
                return "lost"

        return "ongoing"

    async def new_game(self) -> None:
        smiley = await self.page.query_selector("#top_area_face")
        if smiley:
            await smiley.click()
            await asyncio.sleep(0.3)
