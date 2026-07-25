from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum, auto

from models import Board, Cell


class ActionType(Enum):
    REVEAL = auto()
    FLAG = auto()


@dataclass
class Action:
    type: ActionType
    row: int
    col: int


def solve_deterministic(board: Board) -> list[Action]:
    """Apply deterministic rules and return a list of safe actions.

    Rule 1 (Flag): If a numbered cell's value equals the number of adjacent
    closed cells, all closed neighbors are mines -> flag them.
    Rule 2 (Reveal): If a numbered cell's value equals the number of adjacent
    flagged cells, all remaining closed neighbors are safe -> reveal them.
    """
    actions: list[Action] = []
    flagged_this_turn: set[tuple[int, int]] = set()
    revealed_this_turn: set[tuple[int, int]] = set()

    for cell in board.opened_cells():
        if cell.value == 0:
            continue

        closed = board.get_closed_neighbors(cell.row, cell.col)
        flagged = board.get_flagged_neighbors(cell.row, cell.col)

        # Exclude cells we're about to flag this turn from closed count
        pending_flag = [c for c in closed if (c.row, c.col) not in flagged_this_turn]

        if cell.value - len(flagged) == len(pending_flag) and pending_flag:
            # All remaining closed neighbors are mines
            for c in pending_flag:
                if (c.row, c.col) not in flagged_this_turn:
                    actions.append(Action(ActionType.FLAG, c.row, c.col))
                    flagged_this_turn.add((c.row, c.col))

    # Re-check for reveal after flagging
    for cell in board.opened_cells():
        if cell.value == 0:
            continue

        closed = board.get_closed_neighbors(cell.row, cell.col)
        flagged = board.get_flagged_neighbors(cell.row, cell.col)
        effective_flagged = len(flagged) + sum(
            1 for c in closed if (c.row, c.col) in flagged_this_turn
        )

        if cell.value == effective_flagged:
            remaining = [
                c for c in closed if (c.row, c.col) not in flagged_this_turn
            ]
            for c in remaining:
                if (c.row, c.col) not in revealed_this_turn:
                    actions.append(Action(ActionType.REVEAL, c.row, c.col))
                    revealed_this_turn.add((c.row, c.col))

    return actions


def solve_probability(board: Board) -> Action | None:
    """When deterministic rules can't make progress, pick the safest cell.

    Uses a simple heuristic: cells adjacent to fewer numbered cells are
    likely safer (they're on the frontier edge). Among those, prefer
    corners/edges. Falls back to a random closed cell far from any
    numbered cell if all else fails.
    """
    # Collect frontier cells: closed cells adjacent to at least one opened cell
    frontier: set[tuple[int, int]] = set()
    for cell in board.opened_cells():
        for neighbor in board.get_closed_neighbors(cell.row, cell.col):
            if not neighbor.is_flagged:
                frontier.add((neighbor.row, neighbor.col))

    if not frontier:
        # No frontier means the board is mostly unopened; pick a random cell
        closed = [c for c in board.all_cells() if c.is_closed and not c.is_flagged]
        if closed:
            pick = random.choice(closed)
            return Action(ActionType.REVEAL, pick.row, pick.col)
        return None

    # Score frontier cells: lower score = fewer constraints = probably safer
    best_score = float("inf")
    best_cells: list[tuple[int, int]] = []

    for r, c in frontier:
        score = 0
        for neighbor in board.get_neighbors(r, c):
            if neighbor.is_opened and neighbor.value > 0:
                score += 1
        if score < best_score:
            best_score = score
            best_cells = [(r, c)]
        elif score == best_score:
            best_cells.append((r, c))

    if best_cells:
        r, c = random.choice(best_cells)
        return Action(ActionType.REVEAL, r, c)

    return None


def solve_chord(board: Board) -> list[Action]:
    """Find cells where chording (middle-click) would reveal safe neighbors.

    A chord action is valid when: opened cell's value == flagged neighbors,
    AND there are remaining closed (unflagged) neighbors.
    This is equivalent to rule 2 but uses chording for efficiency.
    """
    actions: list[Action] = []
    seen: set[tuple[int, int]] = set()

    for cell in board.opened_cells():
        if cell.value == 0:
            continue

        flagged = board.get_flagged_neighbors(cell.row, cell.col)
        closed = board.get_closed_neighbors(cell.row, cell.col)
        unflagged_closed = [c for c in closed if not c.is_flagged]

        if len(flagged) == cell.value and unflagged_closed:
            if (cell.row, cell.col) not in seen:
                actions.append(Action(ActionType.REVEAL, cell.row, cell.col))
                seen.add((cell.row, cell.col))

    return actions
