# Minesweeper Bot

A bot that plays [minesweeper.online](https://minesweeper.online) using a constraint-propagation solver with human-like browser interaction.

## Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Usage

### Interactive mode

Opens a visible browser. Navigate to any game in the browser, then type commands in the terminal.

```bash
python bot.py --interactive
```

Commands:
- `play` — play the current game to completion, then stop
- `playcontinuously` — play games back-to-back, starting a new game after each win/loss with a 5s pause between games. Type `stop` + Enter during the pause to stop gracefully
- `solve` — solve one step (flag mines, chord, reveal safe cells, guess)
- `status` — print the board
- `click <row> <col>` — left-click a cell
- `flag <row> <col>` — right-click to flag a cell
- `quit` — exit

The bot auto-detects board size and mine count from the page. After winning, it prints game statistics (time, efficiency, etc.) shown by the site.

### Auto mode

Play a set number of games automatically:

```bash
python bot.py -l 1 -n 5          # 5 beginner games
python bot.py -l 2 -n 3 -d 0.1   # 3 intermediate games, 0.1s delay
python bot.py -l 3 --headless     # 1 expert game, no browser window
```

Options:
- `-l, --level` — 1=beginner, 2=intermediate, 3=expert (default: 1)
- `-n, --games` — number of games to play (default: 1)
- `-d, --delay` — base delay between moves in seconds (default: 0.05)
- `--headless` — run without a visible browser window
- `--headful` — run with a visible window (default)
- `-i, --interactive` — interactive mode

## Solver

Three-phase approach applied iteratively until the board is solved or stuck:

1. **Constraint propagation** — each numbered cell becomes a constraint (exactly N of its neighbors are mines). Propagate until quiescence, using subset logic: if constraint A's cells are a subset of B's cells, derive information about B\A. This automatically handles 1-2, 1-2-1, and other subset patterns.

2. **Chording** — after flagging mines, immediately check for cells where flagged neighbors == cell value. Middle-click to reveal all unflagged neighbors. This is done aggressively after every flag batch.

3. **Probability-based guess** — when deterministic rules stall, enumerate valid mine placements on the frontier. Pick the cell with the lowest mine probability. Falls back to a random unconstrained cell if the frontier is too large.

## Anti-detection

The bot mimics human behavior to avoid being flagged:

- Patches `navigator.webdriver` and related browser fingerprints
- Moves the mouse along curved bezier paths with jitter
- Clicks at random offsets within cells (not dead center)
- Hovers briefly before clicking
- Uses variable delays between actions

## Tests

```bash
pytest -v
```

Integration tests run against the live site in headless mode.
