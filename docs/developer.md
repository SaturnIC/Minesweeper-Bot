# Developer Documentation

## Project Structure

```
MinesweeperBot/
├── bot.py              # CLI entry point, game loop, interactive mode
├── browser.py          # Playwright browser automation, DOM interaction
├── solver.py           # Constraint propagation solver
├── models.py           # Board, Cell, CellState data models
├── test_integration.py # Integration tests against live site
├── requirements.txt    # Python dependencies
├── pytest.ini          # Pytest configuration
└── docs/               # Documentation
```

## Architecture

The bot has three layers:

### 1. Models (`models.py`)

Pure data classes with no external dependencies.

- **`CellState`** — enum: `CLOSED`, `OPENED`, `FLAGGED`, `MINE`, `EXPLODED`
- **`Cell`** — row, col, state, value (0-8 for opened cells)
- **`Board`** — 2D grid of cells, mine count, neighbor queries

The `Board` class provides helper methods used by the solver:
- `get_neighbors(row, col)` — all 8 adjacent cells
- `get_closed_neighbors(row, col)` — unopened, unflagged neighbors
- `get_flagged_neighbors(row, col)` — flagged neighbors
- `remaining_mines()` — total mines minus flagged count

### 2. Solver (`solver.py`)

Stateless functions that take a `Board` and return `Action` lists.

- **`Action`** — type (REVEAL/FLAG) + row + col
- **`solve_deterministic(board)`** — constraint propagation with subset logic
- **`solve_chord(board)`** — find cells where chording reveals safe neighbors
- **`solve_probability(board)`** — backtracking enumeration on the frontier

#### Constraint Propagation

Each numbered cell generates a `Constraint`: exactly N of these cells are mines. The solver iterates:

1. Remove known mines/safe cells from constraints
2. If remaining mines == 0 → all remaining cells are safe
3. If remaining mines == remaining cells → all are mines
4. Subset logic: if constraint A ⊂ B, then B\A has (mB - mA) mines

This handles 1-2, 1-2-1, and other subset patterns automatically.

#### Probability Solver

When deterministic rules stall:

1. Partition frontier into connected components
2. Enumerate all valid mine placements per component (up to 24 cells)
3. Count how many solutions place a mine at each position
4. Return the cell with 0 mine-counts (guaranteed safe) or lowest probability

### 3. Browser (`browser.py`)

Playwright-based automation with anti-detection measures.

#### Key Methods

- `read_board()` — single JS evaluation to read all cells (fast)
- `click_cell(row, col)` — human-like mouse movement + left click
- `flag_cell(row, col)` — right click with human movement
- `chord_cell(row, col)` — middle click for chording
- `get_game_status()` — checks face element CSS class
- `get_stats()` — reads timer and result blocks

#### Anti-Detection

- Stealth JS injected via `add_init_script`: patches `navigator.webdriver`, `plugins`, `languages`, `chrome.runtime`
- Chromium launched with `--disable-blink-features=AutomationControlled`
- Mouse follows cubic bezier curves with jitter/tremor
- Clicks at random offset within cells (not dead center)
- Variable delays between all actions

#### Mine Counter

minesweeper.online splits the counter into 3 digit elements (`#top_area_mines_100`, `#top_area_mines_10`, `#top_area_mines_1`). Each digit is encoded in CSS class `hd_top-area-numN`. The counter shows remaining mines (total - flagged), so the bot adds flagged count back to compute total.

## Technologies

- **Python 3.10+** — async/await throughout
- **Playwright** — browser automation (chromium)
- **pytest + pytest-asyncio** — integration testing

## Data Flow

```
User CLI command
    ↓
bot.py (game loop)
    ↓
browser.py (read board from DOM via JS)
    ↓
models.py (Board object)
    ↓
solver.py (returns Actions)
    ↓
browser.py (execute actions with human-like mouse)
    ↓
repeat
```

## Testing

Integration tests in `test_integration.py` run against the live minesweeper.online site. They verify:

- Page loading and DOM structure
- Board reading (dimensions, cell states, values)
- Clicking, flagging, chording
- Game status detection (ongoing/won/lost)
- Solver output validity
- Full game completion

Tests use headless Chromium with a realistic user agent to avoid bot detection.
