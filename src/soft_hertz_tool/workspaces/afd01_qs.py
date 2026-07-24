"""AFD01_QS 工作区。"""

from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QVBoxLayout

from soft_hertz_tool.devices.afd01_qs import QSPanel
from soft_hertz_tool.shared.lifecycle import Workspace


class Afd01QsWorkspace(Workspace):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.panel = QSPanel()
        self.panel.frame_signal.connect(self.frame_signal.emit)
        scroll.setWidget(self.panel)
        layout.addWidget(scroll)

    def activate(self) -> None:
        self.panel.activate()

    def deactivate(self) -> bool:
        return self.panel.deactivate()

    def shutdown(self) -> bool:
        return self.panel.shutdown()
