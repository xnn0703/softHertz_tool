"""独立 AFD01 顶层工作区。"""

from PySide6.QtWidgets import QScrollArea, QVBoxLayout
from soft_hertz_tool.devices.afd01.panel import Afd01Panel
from soft_hertz_tool.shared.lifecycle import Workspace


class Afd01Workspace(Workspace):
    """静态 registry 注册的独立 AFD01 工作区。"""

    show_frame_monitor = False

    def __init__(self, parent=None) -> None:
        """组合可滚动 AFD01 Panel 并转发设备报文。"""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidgetResizable(True)
        self.panel = Afd01Panel()
        self.panel.frame_signal.connect(self.frame_signal.emit)
        scroll.setWidget(self.panel)
        layout.addWidget(scroll)

    def activate(self) -> None:
        """恢复 AFD01 页面，按用户先前连接意图重新查询。"""
        self.panel.activate()

    def deactivate(self) -> bool:
        """切换离开 AFD01，确认 socket 与轮询已停止。"""
        return self.panel.deactivate()

    def shutdown(self) -> bool:
        """幂等释放 AFD01 页面的网络资源。"""
        return self.panel.shutdown()
