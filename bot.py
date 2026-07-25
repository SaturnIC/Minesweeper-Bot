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
        help="Run browser in headless mode",
    )
    args = parser.parse_args()

    level_names = {1: "Beginner", 2: "Intermediate", 3: "Expert"}
    print(f"Minesweeper Bot — {level_names[args.level]}, {args.games} game(s)")

    browser = MinesweeperBrowser(headless=args.headless)
    await browser.start()

    wins = 0
    try:
        for i in range(args.games):
            if i > 0:
                await browser.new_game()
                await asyncio.sleep(0.5)
            else:
                await browser.open_game(args.level)

            print(f"Game {i + 1}/{args.games}:", end="")
            won = await play_game(browser, args.level, delay=args.delay)
            if won:
                wins += 1

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        win_rate = (wins / args.games * 100) if args.games > 0 else 0
        print(f"\nResults: {wins}/{args.games} wins ({win_rate:.0f}%)")
        await browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
