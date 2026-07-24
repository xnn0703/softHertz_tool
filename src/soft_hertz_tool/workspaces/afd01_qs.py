"""AFD01_QS 工作区。"""

from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QVBoxLayout

from soft_hertz_tool.devices.afd01_qs import QSPanel
from soft_hertz_tool.shared.lifecycle import Workspace


class Afd01QsWorkspace(Workspace):
    """承载单个 AFD01_QS Panel 的可滚动工作区。"""

    def __init__(self, parent=None):
        """创建 QS 页面并把设备帧事件转发给主窗口。

        Args:
            parent: 可选 Qt 父对象。
        """

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
        """恢复 QS 页面前台刷新；不会自动重新连接串口。"""

        self.panel.activate()

    def deactivate(self) -> bool:
        """停用 QS 页面并确认串口线程退出。

        Returns:
            页面安全停用时返回 ``True``，否则返回 ``False``。
        """

        return self.panel.deactivate()

    def shutdown(self) -> bool:
        """幂等关闭 QS 页面。

        Returns:
            页面后台资源全部释放时返回 ``True``。
        """

        return self.panel.shutdown()
