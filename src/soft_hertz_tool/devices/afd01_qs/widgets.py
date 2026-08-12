"""AFD01_QS 专用 Qt 控件。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from soft_hertz_tool.devices.afd01_qs.protocol import get_array_level_profile


class ArrayGridWidget(QWidget):
    """16×16 客户有效子阵网格，行列编号固定为 1～16。"""

    COLORS = {
        "active": "#4f9dd9",
        "disabled": "#d6d6d6",
        "pending": "#f2c94c",
        "failed": "#eb5757",
    }

    def __init__(self, title: str, parent=None):
        """创建固定 16×16 客户子阵状态网格。

        Args:
            title: 网格标题，通常为 ``TX`` 或 ``RX``。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.cells = []
        layout = QGridLayout(self)
        layout.setSpacing(1)
        layout.addWidget(QLabel(title), 0, 0, 1, 17, Qt.AlignCenter)
        for col in range(16):
            label = QLabel(f"C{col + 1}")
            label.setStyleSheet("font-size:7pt;")
            layout.addWidget(label, 1, col + 1, alignment=Qt.AlignCenter)
        for row in range(16):
            row_label = QLabel(f"R{row + 1}")
            row_label.setStyleSheet("font-size:7pt;")
            layout.addWidget(row_label, row + 2, 0, alignment=Qt.AlignCenter)
            row_cells = []
            for col in range(16):
                cell = QLabel()
                cell.setAlignment(Qt.AlignCenter)
                cell.setFixedSize(19, 16)
                cell.setToolTip(f"R{row + 1}, C{col + 1}")
                layout.addWidget(cell, row + 2, col + 1)
                row_cells.append(cell)
            self.cells.append(row_cells)
        self.set_state(5)

    def set_state(self, level: int, state: str = "active") -> None:
        """按客户档位和请求状态刷新每个子阵单元颜色。

        Args:
            level: 客户阵列档位 1～5。
            state: ``active``、``pending`` 或 ``failed`` 状态。

        Raises:
            ValueError: level 不属于 1～5。
        """
        edge = get_array_level_profile(level).subarray_edge
        for row in range(16):
            for col in range(16):
                enabled = row < edge and col < edge
                if enabled and state in ("pending", "failed"):
                    color = self.COLORS[state]
                elif enabled:
                    color = self.COLORS["active"]
                else:
                    color = self.COLORS["disabled"]
                self.cells[row][col].setStyleSheet(
                    f"background:{color}; border:1px solid #888;"
                )
