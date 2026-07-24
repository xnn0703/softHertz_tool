"""AFDTR 工作区：KaUDC004A + AFDT1024 + AFDR1024。"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from soft_hertz_tool.devices.afdtr1024 import RXPanel, TXPanel
from soft_hertz_tool.devices.kaudc004a import KaUDCPanel
from soft_hertz_tool.shared.lifecycle import Workspace


class AfdtrWorkspace(Workspace):
    """组合 KaUDC004A、AFDT1024 和 AFDR1024 三个独立串口 Panel。"""

    def __init__(self, parent=None):
        """创建三设备横向布局并转发统一帧事件。

        Args:
            parent: 可选 Qt 父对象。
        """

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
        """恢复三个 Panel 的前台定时器；不会自动重新连接串口。"""

        for panel in self.panels:
            panel.activate()

    def deactivate(self) -> bool:
        """停用全部 Panel 并确认串口线程退出。

        Returns:
            所有 Panel 均停用成功时返回 ``True``；任一失败时返回 ``False``，
            主窗口据此取消工作区切换。
        """

        results = [panel.deactivate() for panel in self.panels]
        return all(result is not False for result in results)

    def shutdown(self) -> bool:
        """幂等关闭全部设备 Panel。

        Returns:
            所有 Panel 均完成资源释放时返回 ``True``。
        """

        results = [panel.shutdown() for panel in self.panels]
        return all(result is not False for result in results)
