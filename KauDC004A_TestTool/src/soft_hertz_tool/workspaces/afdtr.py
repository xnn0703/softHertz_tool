"""AFDTR 工作区：KaUDC004A + AFDT1024 + AFDR1024。"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from soft_hertz_tool.devices.afdtr1024 import RXPanel, TXPanel
from soft_hertz_tool.devices.kaudc004a import KaUDCPanel
from soft_hertz_tool.shared.lifecycle import Workspace


class AfdtrWorkspace(Workspace):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        panels_layout = QHBoxLayout(container)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        self.panels = [KaUDCPanel(), TXPanel(), RXPanel()]
        for panel in self.panels:
            panel.setMinimumWidth(400)
            panels_layout.addWidget(panel)
            panel.frame_signal.connect(self.frame_signal.emit)

    def activate(self) -> None:
        for panel in self.panels:
            panel.activate()

    def deactivate(self) -> bool:
        results = [panel.deactivate() for panel in self.panels]
        return all(result is not False for result in results)

    def shutdown(self) -> bool:
        results = [panel.shutdown() for panel in self.panels]
        return all(result is not False for result in results)
