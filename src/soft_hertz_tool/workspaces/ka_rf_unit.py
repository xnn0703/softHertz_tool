"""KA_RF_UNIT 工作区。"""

from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QVBoxLayout

from soft_hertz_tool.devices.ka_rf_unit import KaRfUnitPanel
from soft_hertz_tool.shared.lifecycle import Workspace


class KaRfUnitWorkspace(Workspace):
    """承载单个 KA_RF_UNIT Panel 的可滚动工作区。"""

    def __init__(self, parent=None) -> None:
        """创建 KA_RF_UNIT 页面并把设备帧事件转发给主窗口。"""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.panel = KaRfUnitPanel()
        self.panel.frame_signal.connect(self.frame_signal.emit)
        scroll.setWidget(self.panel)
        layout.addWidget(scroll)

    def activate(self) -> None:
        """恢复 KA_RF_UNIT 页面前台刷新；不会自动重新连接串口。"""
        self.panel.activate()

    def deactivate(self) -> bool:
        """停用 KA_RF_UNIT 页面并确认串口线程退出。"""
        return self.panel.deactivate()

    def shutdown(self) -> bool:
        """幂等关闭 KA_RF_UNIT 页面。"""
        return self.panel.shutdown()