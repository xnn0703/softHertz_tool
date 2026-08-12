"""设备工作区的最小生命周期契约。"""

from __future__ import annotations

from abc import abstractmethod

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class Workspace(QWidget):
    """主窗口只依赖该契约，不了解具体设备。"""

    frame_signal = Signal(object)

    @abstractmethod
    def activate(self) -> None:
        """工作区进入前台时恢复页面级定时器。

        Returns:
            无返回值；不得隐式重连用户已经断开的串口。
        """

    @abstractmethod
    def deactivate(self) -> bool:
        """工作区被隐藏时断开设备连接并暂停页面定时器。

        Returns:
            所有可见后台活动安全停止时返回 ``True``；失败返回 ``False``，
            主窗口应取消工作区切换。
        """

    @abstractmethod
    def shutdown(self) -> bool:
        """停止串口、定时器及设备侧后台任务。

        Returns:
            所有资源释放成功时返回 ``True``。实现必须允许重复调用。
        """
