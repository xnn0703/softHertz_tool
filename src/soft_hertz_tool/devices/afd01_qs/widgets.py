"""AFD01_QS 专用 Qt 控件。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from soft_hertz_tool.devices.afd01_qs.protocol import ARRAY_MASKS


class ArrayGridWidget(QWidget):
    """8x8 逻辑芯片网格，行列编号固定为 0~7。"""

    COLORS = {
        "active": "#4f9dd9",
        "cached": "#b9d7ea",
        "disabled": "#d6d6d6",
        "pending": "#f2c94c",
        "failed": "#eb5757",
    }

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.cells = []
        layout = QGridLayout(self)
        layout.setSpacing(2)
        layout.addWidget(QLabel(title), 0, 0, 1, 9, Qt.AlignCenter)
        for col in range(8):
            layout.addWidget(QLabel(f"C{col}"), 1, col + 1, alignment=Qt.AlignCenter)
        for row in range(8):
            layout.addWidget(QLabel(f"R{row}"), row + 2, 0, alignment=Qt.AlignCenter)
            row_cells = []
            for col in range(8):
                cell = QLabel(f"{row},{col}")
                cell.setAlignment(Qt.AlignCenter)
                cell.setFixedSize(38, 26)
                layout.addWidget(cell, row + 2, col + 1)
                row_cells.append(cell)
            self.cells.append(row_cells)
        self.set_state(8, powered=True, state="active")

    def set_state(self, size: int, powered: bool, state: str = "active") -> None:
        mask = ARRAY_MASKS.get(size, 0)
        for row in range(8):
            for col in range(8):
                enabled = bool(mask & (1 << row)) and bool(mask & (1 << col))
                if enabled and state in ("pending", "failed"):
                    color = self.COLORS[state]
                elif enabled:
                    color = self.COLORS["active" if powered else "cached"]
                else:
                    color = self.COLORS["disabled"]
                self.cells[row][col].setStyleSheet(
                    f"background:{color}; border:1px solid #888; font-size:8pt;"
                )
