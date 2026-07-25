from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Iterator


class CellState(Enum):
    CLOSED = auto()
    OPENED = auto()
    FLAGGED = auto()
    MINE = auto()
    EXPLODED = auto()


@dataclass
class Cell:
    row: int
    col: int
    state: CellState = CellState.CLOSED
    value: int = 0  # 0-8 for opened numbered cells, 0 for empty

    @property
    def is_mine(self) -> bool:
        return self.state in (CellState.MINE, CellState.EXPLODED)

    @property
    def is_closed(self) -> bool:
        return self.state == CellState.CLOSED

    @property
    def is_flagged(self) -> bool:
        return self.state == CellState.FLAGGED

    @property
    def is_opened(self) -> bool:
        return self.state == CellState.OPENED


class Board:
    def __init__(self, rows: int, cols: int, mine_count: int) -> None:
        self.rows = rows
        self.cols = cols
        self.mine_count = mine_count
        self.grid: list[list[Cell]] = [
            [Cell(row=r, col=c) for c in range(cols)] for r in range(rows)
        ]

    def get_cell(self, row: int, col: int) -> Cell | None:
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return self.grid[row][col]
        return None

    def get_neighbors(self, row: int, col: int) -> list[Cell]:
        neighbors = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = row + dr, col + dc
                cell = self.get_cell(nr, nc)
                if cell is not None:
                    neighbors.append(cell)
        return neighbors

    def get_closed_neighbors(self, row: int, col: int) -> list[Cell]:
        return [c for c in self.get_neighbors(row, col) if c.is_closed]

    def get_flagged_neighbors(self, row: int, col: int) -> list[Cell]:
        return [c for c in self.get_neighbors(row, col) if c.is_flagged]

    def all_cells(self) -> Iterator[Cell]:
        for r in range(self.rows):
            for c in range(self.cols):
                yield self.grid[r][c]

    def opened_cells(self) -> list[Cell]:
        return [c for c in self.all_cells() if c.is_opened]

    def closed_cells(self) -> list[Cell]:
        return [c for c in self.all_cells() if c.is_closed]

    def flagged_count(self) -> int:
        return sum(1 for c in self.all_cells() if c.is_flagged)

    def remaining_mines(self) -> int:
        return self.mine_count - self.flagged_count()

    def __str__(self) -> str:
        symbols = {
            CellState.CLOSED: ".",
            CellState.OPENED: "",  # filled below
            CellState.FLAGGED: "F",
            CellState.MINE: "M",
            CellState.EXPLODED: "X",
        }
        lines = []
        for r in range(self.rows):
            row_chars = []
            for c in range(self.cols):
                cell = self.grid[r][c]
                if cell.is_opened:
                    row_chars.append(str(cell.value))
                else:
                    row_chars.append(symbols[cell.state])
            lines.append(" ".join(row_chars))
        return "\n".join(lines)
