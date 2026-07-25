from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum, auto
from itertools import combinations

from models import Board, Cell


class ActionType(Enum):
    REVEAL = auto()
    FLAG = auto()


@dataclass
class Action:
    type: ActionType
    row: int
    col: int


@dataclass
class Constraint:
    """A constraint from a numbered cell: exactly `mine_count` of `cells` are mines."""
    cells: frozenset[tuple[int, int]]
    mine_count: int


def _build_constraints(board: Board) -> list[Constraint]:
    """Build constraints from all numbered opened cells."""
    constraints: list[Constraint] = []
    for cell in board.opened_cells():
        if cell.value == 0:
            continue
        closed = board.get_closed_neighbors(cell.row, cell.col)
        if not closed:
            continue
        flagged = board.get_flagged_neighbors(cell.row, cell.col)
        remaining = cell.value - len(flagged)
        if remaining < 0:
            continue
        cell_set = frozenset((c.row, c.col) for c in closed)
        constraints.append(Constraint(cell_set, remaining))
    return constraints


def _propagate(constraints: list[Constraint]) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """Propagate constraints to find guaranteed mines and safe cells.

    Returns (mines, safe_cells).
    """
    mines: set[tuple[int, int]] = set()
    safe: set[tuple[int, int]] = set()
    changed = True

    while changed:
        changed = False
        new_constraints: list[Constraint] = []

        for con in constraints:
            # Remove known cells
            remaining_cells = con.cells - mines - safe
            remaining_mines = con.mine_count - len(con.cells & mines)

            if remaining_mines < 0 or remaining_mines > len(remaining_cells):
                continue

            if not remaining_cells:
                continue

            if remaining_mines == 0:
                # All remaining cells are safe
                safe.update(remaining_cells)
                changed = True
            elif remaining_mines == len(remaining_cells):
                # All remaining cells are mines
                mines.update(remaining_cells)
                changed = True
            else:
                new_constraints.append(Constraint(frozenset(remaining_cells), remaining_mines))

        constraints = new_constraints

        # Subset logic: if A ⊆ B, then B\A has (mB - mA) mines
        if not changed and len(constraints) > 1:
            for a, b in combinations(constraints, 2):
                a_cells, b_cells = a.cells, b.cells
                a_mines, b_mines = a.mine_count, b.mine_count

                if a_cells < b_cells:
                    diff = b_cells - a_cells
                    diff_mines = b_mines - a_mines
                    if diff_mines == 0:
                        safe.update(diff)
                        changed = True
                    elif diff_mines == len(diff):
                        mines.update(diff)
                        changed = True
                elif b_cells < a_cells:
                    diff = a_cells - b_cells
                    diff_mines = a_mines - b_mines
                    if diff_mines == 0:
                        safe.update(diff)
                        changed = True
                    elif diff_mines == len(diff):
                        mines.update(diff)
                        changed = True

    return mines, safe


def solve_deterministic(board: Board) -> list[Action]:
    """Apply constraint propagation with subset logic to find safe actions."""
    constraints = _build_constraints(board)
    mines, safe = _propagate(constraints)

    actions: list[Action] = []
    for r, c in mines:
        actions.append(Action(ActionType.FLAG, r, c))
    for r, c in safe:
        actions.append(Action(ActionType.REVEAL, r, c))
    return actions


def solve_probability(board: Board) -> Action | None:
    """When deterministic rules can't make progress, pick the safest cell.

    Uses constraint enumeration on the frontier to find cells that are
    mines in 0 solutions (guaranteed safe) or, failing that, picks the
    cell with the lowest mine probability. Falls back to a random
    unconstrained cell if the frontier is exhausted.
    """
    constraints = _build_constraints(board)

    # Get all frontier cells (closed cells adjacent to numbered cells)
    frontier: set[tuple[int, int]] = set()
    for con in constraints:
        frontier.update(con.cells)

    if not frontier:
        closed = [c for c in board.all_cells() if c.is_closed and not c.is_flagged]
        if closed:
            pick = random.choice(closed)
            return Action(ActionType.REVEAL, pick.row, pick.col)
        return None

    # Try to solve via backtracking enumeration on the frontier
    mine_counts = _enumerate_solutions(board, constraints, frontier)

    if mine_counts is not None:
        # Find cells that are never mines
        always_safe = [pos for pos, count in mine_counts.items() if count == 0]
        if always_safe:
            r, c = random.choice(always_safe)
            return Action(ActionType.REVEAL, r, c)

        # Pick cell with lowest mine probability
        total_solutions = sum(1 for _ in [])  # not needed if we have counts
        best_pos = min(mine_counts, key=lambda p: mine_counts[p])
        if mine_counts[best_pos] < len(frontier):
            return Action(ActionType.REVEAL, best_pos[0], best_pos[1])

    # Fallback: heuristic on frontier
    best_score = float("inf")
    best_cells: list[tuple[int, int]] = []

    for r, c in frontier:
        score = sum(1 for n in board.get_neighbors(r, c) if n.is_opened and n.value > 0)
        if score < best_score:
            best_score = score
            best_cells = [(r, c)]
        elif score == best_score:
            best_cells.append((r, c))

    if best_cells:
        r, c = random.choice(best_cells)
        return Action(ActionType.REVEAL, r, c)

    return None


def _enumerate_solutions(
    board: Board,
    constraints: list[Constraint],
    frontier: set[tuple[int, int]],
) -> dict[tuple[int, int], int] | None:
    """Enumerate valid mine placements on the frontier.

    Returns a dict mapping each frontier cell to the number of solutions
    where it is a mine, or None if enumeration is too expensive.
    """
    # Partition frontier into connected components
    components = _partition_frontier(frontier, constraints)

    if not components:
        return {}

    # Only enumerate if the frontier is small enough
    total_size = sum(len(c) for c in components)
    if total_size > 24:
        return None

    result: dict[tuple[int, int], int] = {pos: 0 for pos in frontier}
    total_solutions = 0

    for component in components:
        comp_constraints = [c for c in constraints if c.cells & component]
        comp_solutions = _enumerate_component(component, comp_constraints, board.mine_count)
        if comp_solutions is None:
            return None
        for solution in comp_solutions:
            for pos in solution:
                result[pos] += 1
        total_solutions += max(len(comp_solutions), 1)

    return result


def _partition_frontier(
    frontier: set[tuple[int, int]],
    constraints: list[Constraint],
) -> list[set[tuple[int, int]]]:
    """Partition frontier into connected components via constraint overlap."""
    # Build adjacency: two cells are connected if they share a constraint
    adj: dict[tuple[int, int], set[tuple[int, int]]] = {pos: set() for pos in frontier}
    for con in constraints:
        cells = list(con.cells)
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                if cells[i] in adj and cells[j] in adj:
                    adj[cells[i]].add(cells[j])
                    adj[cells[j]].add(cells[i])

    visited: set[tuple[int, int]] = set()
    components: list[set[tuple[int, int]]] = []

    for pos in frontier:
        if pos in visited:
            continue
        component: set[tuple[int, int]] = set()
        stack = [pos]
        while stack:
            curr = stack.pop()
            if curr in visited:
                continue
            visited.add(curr)
            component.add(curr)
            for neighbor in adj.get(curr, set()):
                if neighbor not in visited:
                    stack.append(neighbor)
        components.append(component)

    return components


def _enumerate_component(
    cells: set[tuple[int, int]],
    constraints: list[Constraint],
    total_mines: int,
) -> list[frozenset[tuple[int, int]]] | None:
    """Enumerate all valid mine placements for a connected component.

    Returns a list of frozensets, where each frozenset contains the
    positions of mines in a valid solution.
    """
    cell_list = sorted(cells)
    n = len(cell_list)
    if n > 20:
        return None

    solutions: list[frozenset[tuple[int, int]]] = []

    # Try all subsets of cells
    for k in range(n + 1):
        for mine_set in combinations(cell_list, k):
            mine_set_f = frozenset(mine_set)
            valid = True
            for con in constraints:
                mines_in_con = len(con.cells & mine_set_f)
                if mines_in_con != con.mine_count:
                    valid = False
                    break
            if valid:
                solutions.append(mine_set_f)

    return solutions


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
