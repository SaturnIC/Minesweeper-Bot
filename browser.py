from __future__ import annotations

import asyncio
import math
import random
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

# Stealth script: patch navigator.webdriver and related fingerprints
_STEALTH_JS = """
// Remove webdriver flag
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// Patch plugins to look like a real browser
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Patch languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// Remove automation-related properties
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

// Patch chrome runtime
window.chrome = { runtime: {} };

// Patch permissions API
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);
"""


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


def _bezier(t: float, p0: tuple[float, float], p1: tuple[float, float],
            p2: tuple[float, float], p3: tuple[float, float]) -> tuple[float, float]:
    """Cubic bezier curve point at t ∈ [0,1]."""
    u = 1 - t
    x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
    return x, y


def _human_delay(base: float = 0.05, jitter: float = 0.04) -> float:
    """Random delay that feels human."""
    return base + random.uniform(0, jitter)


class MinesweeperBrowser:
    def __init__(self, headless: bool = False) -> None:
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._mouse_x: float = 0
        self._mouse_y: float = 0

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
        )
        self._page = await self._context.new_page()

        # Inject stealth script before every navigation
        await self._page.add_init_script(_STEALTH_JS)

        # Set initial mouse position to center of viewport
        self._mouse_x = 960.0
        self._mouse_y = 540.0

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
        await asyncio.sleep(_human_delay(0.5, 0.3))

    # ── Human-like mouse ──────────────────────────────────────────────

    async def _move_mouse_to(self, target_x: float, target_y: float) -> None:
        """Move mouse to target with a curved bezier path and jitter."""
        start_x, start_y = self._mouse_x, self._mouse_y

        # Add some randomness to the path
        dist = math.hypot(target_x - start_x, target_y - start_y)
        if dist < 5:
            # Already close, just jitter
            self._mouse_x = target_x + random.uniform(-1, 1)
            self._mouse_y = target_y + random.uniform(-1, 1)
            await self.page.mouse.move(self._mouse_x, self._mouse_y)
            return

        # Control points for bezier curve — adds natural arc
        mid_x = (start_x + target_x) / 2 + random.uniform(-dist * 0.15, dist * 0.15)
        mid_y = (start_y + target_y) / 2 + random.uniform(-dist * 0.15, dist * 0.15)

        steps = max(3, int(dist / 80))
        for i in range(1, steps + 1):
            t = i / steps
            x, y = _bezier(
                t,
                (start_x, start_y),
                (mid_x, mid_y),
                (mid_x + random.uniform(-5, 5), mid_y + random.uniform(-5, 5)),
                (target_x, target_y),
            )
            # Add tiny jitter to simulate hand tremor
            x += random.uniform(-0.5, 0.5)
            y += random.uniform(-0.5, 0.5)
            await self.page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.002, 0.008))

        self._mouse_x = target_x
        self._mouse_y = target_y

    async def _human_click(
        self, box: dict, button: str = "left", hover_first: bool = True
    ) -> None:
        """Click a cell like a human — move to it with offset, hover, then click."""
        # Random offset within the cell (not dead center)
        offset_x = random.uniform(box["width"] * 0.2, box["width"] * 0.8)
        offset_y = random.uniform(box["height"] * 0.2, box["height"] * 0.8)
        target_x = box["x"] + offset_x
        target_y = box["y"] + offset_y

        # Move mouse along curved path
        await self._move_mouse_to(target_x, target_y)

        # Brief hover (human pauses before clicking)
        if hover_first:
            await asyncio.sleep(_human_delay(0.02, 0.03))

        await self.page.mouse.click(target_x, target_y, button=button)

        # Tiny post-click pause
        await asyncio.sleep(_human_delay(0.01, 0.02))

    # ── Board reading ─────────────────────────────────────────────────

    async def read_board(self, level: int | None = None) -> Board:
        # Single JS call to read all cells — much faster than individual queries
        raw = await self.page.evaluate('''() => {
            const cells = document.querySelectorAll('.cell');
            const result = [];
            for (const el of cells) {
                const id = el.id;
                if (!id || !id.startsWith('cell_')) continue;
                result.push({id: id, cls: el.className});
            }
            return result;
        }''')

        max_row, max_col = 0, 0
        parsed: list[tuple[int, int, CellState, int]] = []

        for item in raw:
            parts = item['id'].split("_")
            if len(parts) != 3:
                continue
            col_idx, row_idx = int(parts[1]), int(parts[2])
            max_row = max(max_row, row_idx)
            max_col = max(max_col, col_idx)

            classes = item['cls'].split()
            state = _parse_state(classes)
            value = _parse_value(classes) if state == CellState.OPENED else 0
            parsed.append((row_idx, col_idx, state, value))

        rows = max_row + 1
        cols = max_col + 1

        mine_count = await self._read_mine_counter()
        if mine_count is None:
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

        # The displayed counter shows remaining mines (total - flagged),
        # not total mines. Compute actual total.
        if mine_count is not None:
            board.mine_count = mine_count + board.flagged_count()

        return board

    async def _read_mine_counter(self) -> int | None:
        """Read mine counter from minesweeper.online.

        The counter is split into 3 digit elements:
          #top_area_mines_100  (hundreds)
          #top_area_mines_10   (tens)
          #top_area_mines_1    (ones)
        Each has a CSS class like 'hd_top-area-numN' where N is the digit.
        """
        digits = []
        for sel in ["#top_area_mines_100", "#top_area_mines_10", "#top_area_mines_1"]:
            el = await self.page.query_selector(sel)
            if not el:
                return None
            cls = await el.get_attribute("class") or ""
            # Extract digit from class like 'hd_top-area-num8'
            digit = None
            for part in cls.split():
                if part.startswith("hd_top-area-num"):
                    try:
                        digit = int(part[len("hd_top-area-num"):])
                    except ValueError:
                        pass
            if digit is None:
                return None
            digits.append(digit)

        return digits[0] * 100 + digits[1] * 10 + digits[2]

    # ── Cell interactions ─────────────────────────────────────────────

    async def click_cell(self, row: int, col: int) -> None:
        selector = f"#cell_{col}_{row}"
        el = await self.page.query_selector(selector)
        if el:
            box = await el.bounding_box()
            if box:
                await self._human_click(box, button="left")

    async def flag_cell(self, row: int, col: int) -> None:
        selector = f"#cell_{col}_{row}"
        el = await self.page.query_selector(selector)
        if el:
            box = await el.bounding_box()
            if box:
                await self._human_click(box, button="right")

    async def chord_cell(self, row: int, col: int) -> None:
        selector = f"#cell_{col}_{row}"
        el = await self.page.query_selector(selector)
        if el:
            box = await el.bounding_box()
            if box:
                await self._human_click(box, button="middle")

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
            box = await smiley.bounding_box()
            if box:
                await self._human_click(box, button="left")
            await asyncio.sleep(_human_delay(0.3, 0.2))
