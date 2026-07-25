from __future__ import annotations

import argparse
import asyncio
import sys
import time

from browser import BOARD_SIZES, MinesweeperBrowser
from models import Board
from solver import Action, ActionType, solve_chord, solve_deterministic, solve_probability


async def play_game(
    browser: MinesweeperBrowser,
    level: int,
    delay: float = 0.05,
    verbose: bool = True,
) -> bool:
    """Play one game of Minesweeper. Returns True if won, False if lost."""
    rows, cols, mine_count = BOARD_SIZES[level]

    # Click center cell to start
    center_r, center_c = rows // 2, cols // 2
    await browser.click_cell(center_r, center_c)
    await asyncio.sleep(0.3)

    start_time = time.monotonic()
    move_count = 0

    while True:
        status = await browser.get_game_status()
        if status == "won":
            elapsed = time.monotonic() - start_time
            if verbose:
                print(f"\n  WON in {elapsed:.1f}s, {move_count} moves")
            return True
        if status == "lost":
            if verbose:
                print(f"\n  LOST after {move_count} moves")
            return False

        board = await browser.read_board(level)

        if verbose:
            remaining = board.remaining_mines()
            opened = len(board.opened_cells())
            total = rows * cols
            print(
                f"\r  Opened: {opened}/{total} | Mines left: {remaining} | Moves: {move_count}",
                end="",
                flush=True,
            )

        # Phase 1: deterministic solver
        actions = solve_deterministic(board)

        # Phase 2: chord opportunities
        if not actions:
            chord_actions = solve_chord(board)
            if chord_actions:
                for act in chord_actions:
                    await browser.chord_cell(act.row, act.col)
                    move_count += 1
                await asyncio.sleep(delay)
                continue

        # Phase 3: probability-based guess
        if not actions:
            guess = solve_probability(board)
            if guess:
                actions = [guess]

        if not actions:
            if verbose:
                print("\n  No moves available — board may be complete")
            break

        for act in actions:
            if act.type == ActionType.FLAG:
                await browser.flag_cell(act.row, act.col)
            else:
                await browser.click_cell(act.row, act.col)
            move_count += 1

        await asyncio.sleep(delay)

    return False


async def _detect_level(browser: MinesweeperBrowser) -> int:
    """Detect board level by counting cells on the current page."""
    cells = await browser.page.query_selector_all(".cell")
    count = len(cells)
    for level, (rows, cols, _) in BOARD_SIZES.items():
        if count == rows * cols:
            return level
    return 1


async def play_interactive(browser: MinesweeperBrowser, delay: float) -> None:
    """Interactive CLI mode: user drives the bot with commands."""
    print("Interactive mode — navigate to a game in the browser, then type a command.")
    print("Commands: play, solve, status, flag <row> <col>, click <row> <col>, quit")
    print()

    loop = asyncio.get_event_loop()

    while True:
        try:
            line = await loop.run_in_executor(None, lambda: input("> "))
        except (EOFError, KeyboardInterrupt):
            print()
            break

        cmd = line.strip().lower().split()
        if not cmd:
            continue

        action = cmd[0]

        if action == "quit":
            break

        elif action == "status":
            level = await _detect_level(browser)
            try:
                board = await browser.read_board(level)
            except Exception as e:
                print(f"Error reading board: {e}")
                continue
            status = await browser.get_game_status()
            print(board)
            print(f"Game: {status} | Mines left: {board.remaining_mines()}")

        elif action == "click":
            if len(cmd) != 3:
                print("Usage: click <row> <col>")
                continue
            r, c = int(cmd[1]), int(cmd[2])
            await browser.click_cell(r, c)
            await asyncio.sleep(0.3)
            level = await _detect_level(browser)
            try:
                board = await browser.read_board(level)
                status = await browser.get_game_status()
                print(board)
                print(f"Game: {status}")
            except Exception as e:
                print(f"Error: {e}")

        elif action == "flag":
            if len(cmd) != 3:
                print("Usage: flag <row> <col>")
                continue
            r, c = int(cmd[1]), int(cmd[2])
            await browser.flag_cell(r, c)
            await asyncio.sleep(0.3)
            level = await _detect_level(browser)
            try:
                board = await browser.read_board(level)
                print(board)
                print(f"Mines left: {board.remaining_mines()}")
            except Exception as e:
                print(f"Error: {e}")

        elif action == "solve":
            level = await _detect_level(browser)
            try:
                board = await browser.read_board(level)
            except Exception as e:
                print(f"Error reading board: {e}")
                continue

            status = await browser.get_game_status()
            if status != "ongoing":
                print(f"Game already {status}. Start a new game in the browser.")
                continue

            move_count = 0
            while True:
                # Phase 1: deterministic
                actions = solve_deterministic(board)

                # Phase 2: chord
                if not actions:
                    chord_actions = solve_chord(board)
                    if chord_actions:
                        for act in chord_actions:
                            await browser.chord_cell(act.row, act.col)
                            move_count += 1
                        await asyncio.sleep(delay)
                        board = await browser.read_board(level)
                        print(f"  Chorded {len(chord_actions)} cells")
                        continue

                # Phase 3: probability guess
                if not actions:
                    guess = solve_probability(board)
                    if guess:
                        actions = [guess]
                        print(f"  Guessing ({guess.row},{guess.col})")

                if not actions:
                    print("  No moves available")
                    break

                flags = [a for a in actions if a.type == ActionType.FLAG]
                reveals = [a for a in actions if a.type == ActionType.REVEAL]

                for a in flags:
                    await browser.flag_cell(a.row, a.col)
                    move_count += 1
                for a in reveals:
                    await browser.click_cell(a.row, a.col)
                    move_count += 1

                await asyncio.sleep(delay)

                # Re-read and check status
                board = await browser.read_board(level)
                status = await browser.get_game_status()
                remaining = board.remaining_mines()
                opened = len(board.opened_cells())
                total = board.rows * board.cols
                print(
                    f"  Opened: {opened}/{total} | Mines left: {remaining} | Moves: {move_count}"
                )

                if status != "ongoing":
                    if status == "won":
                        print("  WON!")
                    else:
                        print("  LOST!")
                    break

                # Keep solving in the same step
                if not (flags or reveals):
                    break

        elif action == "play":
            level = await _detect_level(browser)
            status = await browser.get_game_status()
            if status != "ongoing":
                print("No ongoing game. Navigate to a game in the browser first.")
                continue

            print(f"Playing (level {level})…")

            rows, cols, mine_count = BOARD_SIZES[level]
            start_time = time.monotonic()
            move_count = 0

            while True:
                status = await browser.get_game_status()
                if status == "won":
                    elapsed = time.monotonic() - start_time
                    print(f"\n  WON in {elapsed:.1f}s, {move_count} moves")
                    break
                if status == "lost":
                    print(f"\n  LOST after {move_count} moves")
                    break

                board = await browser.read_board(level)
                remaining = board.remaining_mines()
                opened = len(board.opened_cells())
                total = rows * cols
                print(
                    f"\r  Opened: {opened}/{total} | Mines left: {remaining} | Moves: {move_count}",
                    end="",
                    flush=True,
                )

                actions = solve_deterministic(board)

                if not actions:
                    chord_actions = solve_chord(board)
                    if chord_actions:
                        for act in chord_actions:
                            await browser.chord_cell(act.row, act.col)
                            move_count += 1
                        await asyncio.sleep(delay)
                        continue

                if not actions:
                    guess = solve_probability(board)
                    if guess:
                        actions = [guess]

                if not actions:
                    print("\n  No moves available")
                    break

                for act in actions:
                    if act.type == ActionType.FLAG:
                        await browser.flag_cell(act.row, act.col)
                    else:
                        await browser.click_cell(act.row, act.col)
                    move_count += 1

                await asyncio.sleep(delay)

            print("Bot backed off. Window is still open.")

        else:
            print(f"Unknown command: {action}")
            print("Commands: play, solve, status, flag <row> <col>, click <row> <col>, quit")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Minesweeper.online bot")
    parser.add_argument(
        "-l", "--level",
        type=int,
        choices=[1, 2, 3],
        default=1,
        help="Difficulty: 1=beginner, 2=intermediate, 3=expert (default: 1)",
    )
    parser.add_argument(
        "-n", "--games",
        type=int,
        default=1,
        help="Number of games to play (default: 1)",
    )
    parser.add_argument(
        "-d", "--delay",
        type=float,
        default=0.05,
        help="Delay between moves in seconds (default: 0.05)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (no visible window)",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run browser in headful mode with visible window (default)",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Interactive mode: open browser, then accept CLI commands",
    )
    args = parser.parse_args()

    headless = args.headless and not args.headful

    browser = MinesweeperBrowser(headless=headless)
    await browser.start()

    try:
        if args.interactive:
            print("Opening minesweeper.online…")
            await browser.page.goto("https://minesweeper.online", wait_until="networkidle")
            print("Navigate to a game in the browser, then type a command here.")
            await play_interactive(browser, args.delay)
        else:
            level_names = {1: "Beginner", 2: "Intermediate", 3: "Expert"}
            print(f"Minesweeper Bot — {level_names[args.level]}, {args.games} game(s)")

            wins = 0
            played = 0
            for i in range(args.games):
                try:
                    if i > 0:
                        await browser.new_game()
                        await asyncio.sleep(0.5)
                    else:
                        await browser.open_game(args.level)

                    print(f"Game {i + 1}/{args.games}:", end="")
                    won = await play_game(browser, args.level, delay=args.delay)
                    played += 1
                    if won:
                        wins += 1
                except Exception as e:
                    print(f"Game {i + 1}/{args.games}: error — {e}")

            win_rate = (wins / played * 100) if played > 0 else 0
            print(f"\nResults: {wins}/{played} wins ({win_rate:.0f}%)")
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        await browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
