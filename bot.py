from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time

from browser import BOARD_SIZES, MinesweeperBrowser
from models import Board
from solver import Action, ActionType, solve_chord, solve_deterministic, solve_probability, chord_reveals


def _human_sleep(base: float) -> None:
    """Return a variable delay that feels human."""
    # Not async — caller wraps in asyncio.sleep
    pass


async def _sleep(base: float) -> None:
    """Sleep with human-like jitter."""
    await asyncio.sleep(base + random.uniform(0, base * 0.8))


class ClickError(Exception):
    """Raised when a click action fails to register."""
    pass


async def _verified_click(browser, row: int, col: int) -> None:
    """Click a cell and verify it registered. Raises ClickError if not."""
    ok = await browser.click_cell(row, col)
    if not ok:
        raise ClickError(f"Click on ({row},{col}) did not register — stopping")


async def _verified_flag(browser, row: int, col: int) -> None:
    """Flag a cell and verify it registered. Raises ClickError if not."""
    ok = await browser.flag_cell(row, col)
    if not ok:
        raise ClickError(f"Flag on ({row},{col}) did not register — stopping")


async def _verified_chord(browser, row: int, col: int) -> None:
    """Chord a cell and verify it registered. Raises ClickError if not."""
    ok = await browser.chord_cell(row, col)
    if not ok:
        raise ClickError(f"Chord on ({row},{col}) did not register — stopping")


async def play_game(
    browser: MinesweeperBrowser,
    level: int,
    delay: float = 0.05,
    verbose: bool = True,
) -> bool:
    """Play one game of Minesweeper. Returns True if won, False if lost."""
    rows, cols, mine_count = BOARD_SIZES[level]

    # Click start cell if it exists (no-guess mode), otherwise click center
    clicked = await browser.click_start_cell()
    if not clicked:
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
                await asyncio.sleep(1)
                stats = await browser.get_stats()
                for key, val in stats.items():
                    print(f"    {key}: {val}")
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
        try:
            actions = solve_deterministic(board)

            flags = [a for a in actions if a.type == ActionType.FLAG]
            reveals = [a for a in actions if a.type == ActionType.REVEAL]

            # Place flags first — they may unlock chords
            for a in flags:
                await _verified_flag(browser, a.row, a.col)
                move_count += 1

            if flags:
                await _sleep(delay)
                board = await browser.read_board(level)
                # Aggressively chord after flagging
                while True:
                    chord_actions = solve_chord(board)
                    if not chord_actions:
                        break
                    act = chord_actions[0]
                    await _verified_chord(browser, act.row, act.col)
                    move_count += 1
                    await _sleep(delay)
                    board = await browser.read_board(level)
                continue

            # Before individual reveals, check for chords globally
            chord_actions = solve_chord(board)
            if chord_actions:
                act = chord_actions[0]
                await _verified_chord(browser, act.row, act.col)
                move_count += 1
                await _sleep(delay)
                continue

            # Filter reveals: skip cells that would be revealed by any chord
            # and skip cells that are already opened
            chord_covered = chord_reveals(board)
            opened = {(c.row, c.col) for c in board.opened_cells()}
            reveals = [a for a in reveals if (a.row, a.col) not in chord_covered and (a.row, a.col) not in opened]

            # Reveal one cell at a time — clicks can cascade
            if reveals:
                await _verified_click(browser, reveals[0].row, reveals[0].col)
                move_count += 1
                await _sleep(delay)
                continue

            # Nothing deterministic — guess
            guess = solve_probability(board)
            if guess:
                if guess.type == ActionType.FLAG:
                    await _verified_flag(browser, guess.row, guess.col)
                else:
                    await _verified_click(browser, guess.row, guess.col)
                move_count += 1
                await _sleep(delay)
                continue

            if verbose:
                print("\n  No moves available — board may be complete")
            break

        except ClickError as e:
            if verbose:
                print(f"\n  ERROR: {e}")
            return False

        await _sleep(delay)

    return False


async def _run_solve_step(browser: MinesweeperBrowser, delay: float) -> None:
    """Run the solver until it stalls or the game ends."""
    board = await browser.read_board()
    status = await browser.get_game_status()
    if status != "ongoing":
        print(f"Game already {status}.")
        return

    move_count = 0

    async def _check_status() -> bool:
        """Check if game ended. Print result and return True if so."""
        nonlocal board
        board = await browser.read_board()
        s = await browser.get_game_status()
        if s == "won":
            print("  WON!")
            return True
        if s == "lost":
            print("  LOST!")
            return True
        return False

    while True:
        try:
            actions = solve_deterministic(board)

            flags = [a for a in actions if a.type == ActionType.FLAG]
            reveals = [a for a in actions if a.type == ActionType.REVEAL]

            # Place flags first — they may unlock chords
            for a in flags:
                await _verified_flag(browser, a.row, a.col)
                move_count += 1

            if flags:
                await _sleep(delay)
                if await _check_status():
                    break
                board = await browser.read_board()

                # Aggressively chord after flagging
                while True:
                    chord_actions = solve_chord(board)
                    if not chord_actions:
                        break
                    # Execute one chord, then re-read
                    act = chord_actions[0]
                    await _verified_chord(browser, act.row, act.col)
                    move_count += 1
                    await _sleep(delay)
                    if await _check_status():
                        return
                    board = await browser.read_board()
                    print(f"  Chorded ({act.row},{act.col})")

                continue

            # Check chords globally — prioritized by most cells revealed
            chord_actions = solve_chord(board)
            if chord_actions:
                act = chord_actions[0]
                await _verified_chord(browser, act.row, act.col)
                move_count += 1
                await _sleep(delay)
                if await _check_status():
                    break
                board = await browser.read_board()
                print(f"  Chorded ({act.row},{act.col})")
                continue

            # Filter reveals: skip cells that would be revealed by any chord
            chord_covered = chord_reveals(board)
            reveals = [a for a in reveals if (a.row, a.col) not in chord_covered]

            # No chords — reveal safe cells individually
            for a in reveals:
                await _verified_click(browser, a.row, a.col)
                move_count += 1

            if reveals:
                await _sleep(delay)
                if await _check_status():
                    break
                board = await browser.read_board()
                continue

            # Nothing deterministic — guess
            guess = solve_probability(board)
            if guess:
                if guess.type == ActionType.FLAG:
                    await _verified_flag(browser, guess.row, guess.col)
                else:
                    await _verified_click(browser, guess.row, guess.col)
                move_count += 1
                await _sleep(delay)
                if await _check_status():
                    break
                board = await browser.read_board()
                print(f"  Guessing ({guess.row},{guess.col})")
                continue

            print("  No moves available")
            break

        except ClickError as e:
            print(f"\n  ERROR: {e}")
            break
            board = await browser.read_board()

            # Aggressively chord after flagging
            while True:
                chord_actions = solve_chord(board)
                if not chord_actions:
                    break
                for act in chord_actions:
                    await browser.chord_cell(act.row, act.col)
                    move_count += 1
                await _sleep(delay)
                if await _check_status():
                    return
                board = await browser.read_board()
                print(f"  Chorded {len(chord_actions)} cells")

            continue

        # Check chords globally — prioritized by most cells revealed
        chord_actions = solve_chord(board)
        if chord_actions:
            for act in chord_actions:
                await browser.chord_cell(act.row, act.col)
                move_count += 1
            await _sleep(delay)
            if await _check_status():
                break
            board = await browser.read_board()
            print(f"  Chorded {len(chord_actions)} cells")
            continue

            # Filter reveals: skip cells that would be revealed by any chord
            # and skip cells that are already opened
            chord_covered = chord_reveals(board)
            opened = {(c.row, c.col) for c in board.opened_cells()}
            reveals = [a for a in reveals if (a.row, a.col) not in chord_covered and (a.row, a.col) not in opened]

        # No chords — reveal safe cells individually
        for a in reveals:
            await browser.click_cell(a.row, a.col)
            move_count += 1

        if reveals:
            await _sleep(delay)
            if await _check_status():
                break
            board = await browser.read_board()
            continue

        # Nothing deterministic — guess
        chord_actions = solve_chord(board)
        if chord_actions:
            for act in chord_actions:
                await browser.chord_cell(act.row, act.col)
                move_count += 1
            await _sleep(delay)
            if await _check_status():
                break
            board = await browser.read_board()
            print(f"  Chorded {len(chord_actions)} cells")
            continue

        # Nothing deterministic — guess
        guess = solve_probability(board)
        if guess:
            if guess.type == ActionType.FLAG:
                await browser.flag_cell(guess.row, guess.col)
            else:
                await browser.click_cell(guess.row, guess.col)
            move_count += 1
            await _sleep(delay)
            if await _check_status():
                break
            board = await browser.read_board()
            print(f"  Guessing ({guess.row},{guess.col})")
            continue

        print("  No moves available")
        break


async def play_interactive(browser: MinesweeperBrowser, delay: float) -> None:
    """Interactive CLI mode: user drives the bot with commands."""
    print("Interactive mode — navigate to a game in the browser, then type a command.")
    print("Commands:")
    print("  play                 - play the current game to completion")
    print("  playcont     - play games back-to-back, new game after each win/loss")
    print("  solve                - solve one step (flag, chord, reveal, guess)")
    print("  status               - print the board")
    print("  click <row> <col>    - left-click a cell")
    print("  flag <row> <col>     - right-click to flag a cell")
    print("  quit                 - exit")
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
            try:
                board = await browser.read_board()
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
            try:
                board = await browser.read_board()
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
            try:
                board = await browser.read_board()
                print(board)
                print(f"Mines left: {board.remaining_mines()}")
            except Exception as e:
                print(f"Error: {e}")

        elif action == "solve":
            await _run_solve_step(browser, delay)

        elif action == "play":
            # Click start cell if present (no-guess mode)
            start_el = await browser.page.query_selector(".cell.start")
            if start_el:
                print("  Clicking start cell…")
                clicked = await browser.click_start_cell()
                if not clicked:
                    print("  Failed to click start cell")
                    continue
                await asyncio.sleep(0.5)

            status = await browser.get_game_status()
            if status != "ongoing":
                print("No ongoing game. Navigate to a game in the browser first.")
                continue

            board = await browser.read_board()
            print(f"Playing {board.rows}x{board.cols}, {board.mine_count} mines…")

            start_time = time.monotonic()
            move_count = 0

            while True:
                status = await browser.get_game_status()
                if status == "won":
                    elapsed = time.monotonic() - start_time
                    print(f"\n  WON in {elapsed:.1f}s, {move_count} moves")
                    await asyncio.sleep(1)
                    stats = await browser.get_stats()
                    for key, val in stats.items():
                        print(f"    {key}: {val}")
                    break
                if status == "lost":
                    print(f"\n  LOST after {move_count} moves")
                    break

                board = await browser.read_board()
                remaining = board.remaining_mines()
                opened = len(board.opened_cells())
                total = board.rows * board.cols
                print(
                    f"\r  Opened: {opened}/{total} | Mines left: {remaining} | Moves: {move_count}",
                    end="",
                    flush=True,
                )

                actions = solve_deterministic(board)

                flags = [a for a in actions if a.type == ActionType.FLAG]
                reveals = [a for a in actions if a.type == ActionType.REVEAL]

                # Place flags first — they may unlock chords
                for a in flags:
                    ok = await browser.flag_cell(a.row, a.col)
                    if not ok:
                        print(f"\n  Flag ({a.row},{a.col}) had no effect")
                    move_count += 1

                if flags:
                    await _sleep(delay)
                    board = await browser.read_board()
                    # Aggressively chord after flagging
                    while True:
                        chord_actions = solve_chord(board)
                        if not chord_actions:
                            break
                        act = chord_actions[0]
                        ok = await browser.chord_cell(act.row, act.col)
                        if not ok:
                            print(f"\n  Chord ({act.row},{act.col}) had no effect")
                        move_count += 1
                        await _sleep(delay)
                        board = await browser.read_board()
                    continue

                # Before individual reveals, check for chords globally
                chord_actions = solve_chord(board)
                if chord_actions:
                    act = chord_actions[0]
                    ok = await browser.chord_cell(act.row, act.col)
                    if not ok:
                        print(f"\n  Chord ({act.row},{act.col}) had no effect")
                    move_count += 1
                    await _sleep(delay)
                    continue

                # Filter reveals: skip cells that would be revealed by any chord
                # and skip cells that are already opened
                chord_covered = chord_reveals(board)
                opened = {(c.row, c.col) for c in board.opened_cells()}
                reveals = [a for a in reveals if (a.row, a.col) not in chord_covered and (a.row, a.col) not in opened]

                # Reveal one cell at a time — clicks can cascade
                if reveals:
                    a = reveals[0]
                    ok = await browser.click_cell(a.row, a.col)
                    if not ok:
                        print(f"\n  Click ({a.row},{a.col}) had no effect")
                    move_count += 1
                    await _sleep(delay)
                    continue

                # Nothing deterministic — guess
                if chord_actions:
                    for act in chord_actions:
                        await browser.chord_cell(act.row, act.col)
                        move_count += 1
                    await _sleep(delay)
                    continue

                # Nothing deterministic — guess
                guess = solve_probability(board)
                if guess:
                    if guess.type == ActionType.FLAG:
                        await browser.flag_cell(guess.row, guess.col)
                    else:
                        await browser.click_cell(guess.row, guess.col)
                    move_count += 1
                    await _sleep(delay)
                    continue

                print("\n  No moves available")
                break

            print("Bot backed off. Window is still open.")

        elif action == "playcont":
            import select

            wins = 0
            played = 0
            stop = False
            print("Continuous mode — type 's' + Enter to stop.")

            def _check_stdin() -> bool:
                """Non-blocking check for 's' on stdin."""
                try:
                    if select.select([sys.stdin], [], [], 0)[0]:
                        line = sys.stdin.readline().strip().lower()
                        return line == "s"
                except Exception:
                    pass
                return False

            try:
                while not stop:
                    status = await browser.get_game_status()
                    if status != "ongoing":
                        # Start a new game
                        if played > 0:
                            print(f"  → Waiting 5s… (type 's' to stop)")
                            for _ in range(10):
                                await asyncio.sleep(0.5)
                                if await asyncio.get_event_loop().run_in_executor(None, _check_stdin):
                                    stop = True
                                    break
                            if stop:
                                break
                        await browser.new_game()
                        await asyncio.sleep(2)

                    # Click start cell if present (no-guess mode)
                    start_el = await browser.page.query_selector(".cell.start")
                    if start_el:
                        await browser.click_start_cell()
                        await asyncio.sleep(0.5)

                    played += 1

                    board = await browser.read_board()
                    print(f"Game {played}: {board.rows}x{board.cols}, {board.mine_count} mines")

                    start_time = time.monotonic()
                    move_count = 0

                    while not stop:
                        if await asyncio.get_event_loop().run_in_executor(None, _check_stdin):
                            stop = True
                            break
                        status = await browser.get_game_status()
                        if status == "won":
                            elapsed = time.monotonic() - start_time
                            wins += 1
                            print(f"  WON in {elapsed:.1f}s, {move_count} moves  [{wins}/{played}]")
                            await asyncio.sleep(1)
                            stats = await browser.get_stats()
                            for key, val in stats.items():
                                print(f"    {key}: {val}")
                            break
                        if status == "lost":
                            print(f"  LOST after {move_count} moves  [{wins}/{played}]")
                            break

                        board = await browser.read_board()
                        remaining = board.remaining_mines()
                        opened = len(board.opened_cells())
                        total = board.rows * board.cols
                        print(
                            f"\r  Opened: {opened}/{total} | Mines left: {remaining} | Moves: {move_count}",
                            end="",
                            flush=True,
                        )

                        actions = solve_deterministic(board)
                        flags = [a for a in actions if a.type == ActionType.FLAG]
                        reveals = [a for a in actions if a.type == ActionType.REVEAL]

                        for a in flags:
                            ok = await browser.flag_cell(a.row, a.col)
                            if not ok:
                                print(f"\n  Flag ({a.row},{a.col}) had no effect")
                            move_count += 1

                        if flags:
                            await _sleep(delay)
                            board = await browser.read_board()
                            while True:
                                chord_actions = solve_chord(board)
                                if not chord_actions:
                                    break
                                act = chord_actions[0]
                                ok = await browser.chord_cell(act.row, act.col)
                                if not ok:
                                    print(f"\n  Chord ({act.row},{act.col}) had no effect")
                                move_count += 1
                                await _sleep(delay)
                                board = await browser.read_board()
                            continue

                        # Before individual reveals, check for chords globally
                        chord_actions = solve_chord(board)
                        if chord_actions:
                            act = chord_actions[0]
                            ok = await browser.chord_cell(act.row, act.col)
                            if not ok:
                                print(f"\n  Chord ({act.row},{act.col}) had no effect")
                            move_count += 1
                            await _sleep(delay)
                            continue

                        # Filter reveals: skip cells that would be revealed by any chord
                        # and skip cells that are already opened
                        chord_covered = chord_reveals(board)
                        opened = {(c.row, c.col) for c in board.opened_cells()}
                        reveals = [a for a in reveals if (a.row, a.col) not in chord_covered and (a.row, a.col) not in opened]

                        # Reveal one cell at a time — clicks can cascade
                        if reveals:
                            a = reveals[0]
                            ok = await browser.click_cell(a.row, a.col)
                            if not ok:
                                print(f"\n  Click ({a.row},{a.col}) had no effect")
                            move_count += 1
                            await _sleep(delay)
                            continue

                        guess = solve_probability(board)
                        if guess:
                            if guess.type == ActionType.FLAG:
                                await browser.flag_cell(guess.row, guess.col)
                            else:
                                await browser.click_cell(guess.row, guess.col)
                            move_count += 1
                            await _sleep(delay)
                            continue

                        print("\n  No moves available")
                        break

            except KeyboardInterrupt:
                pass
            print(f"\nStopped. Results: {wins}/{played} wins")

        else:
            print(f"Unknown command: {action}")
            print("Commands: play, playcont, solve, status, flag <row> <col>, click <row> <col>, quit")


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
