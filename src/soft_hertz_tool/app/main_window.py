"""只负责工作区注册、切换和统一生命周期的主窗口。"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QSettings, Qt, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from soft_hertz_tool.identity import (
    DEVICE_MODEL_KEY,
    PRODUCT_DISPLAY_NAME,
    create_application_settings,
    display_name_with_version,
    load_device_model,
)
from soft_hertz_tool.app.registry import WORKSPACE_SPECS
from soft_hertz_tool.shared.resources import resource_path
from soft_hertz_tool.shared.ui.frame_monitor import FrameMonitorWidget


class MainWindow(QMainWindow):
    """组装静态工作区并协调切换、报文监视和全局退出。

    主窗口只依赖 Workspace 生命周期契约，不创建或操作具体设备 Driver。
    """

    def __init__(
        self,
        settings: Optional[QSettings] = None,
        legacy_settings: Optional[QSettings] = None,
    ):
        """创建主窗口、全部工作区及共享报文监视器。

        Args:
            settings: 可选的当前产品设置对象，主要用于测试或定制存储位置。
            legacy_settings: 可选的旧产品设置对象，仅用于首次选择项迁移。
        """

        super().__init__()
        self.setWindowTitle(display_name_with_version())
        self._shutdown = False
        icon_path = resource_path("soft_hertz_logo_deepspace_blue_512.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setGeometry(100, 100, 1400, 900)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("设备型号:"))
        self.model_combo = QComboBox()
        for spec in WORKSPACE_SPECS:
            self.model_combo.addItem(spec.title, spec.key)
        model_row.addWidget(self.model_combo)
        model_row.addStretch()
        root_layout.addLayout(model_row)

        splitter = QSplitter(Qt.Vertical)
        self.pages = QStackedWidget()
        self.frame_monitor = FrameMonitorWidget()
        splitter.addWidget(self.pages)
        splitter.addWidget(self.frame_monitor)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

        self.workspaces = []
        for spec in WORKSPACE_SPECS:
            workspace = spec.factory()
            workspace.frame_signal.connect(self.frame_monitor.add_record)
            self.pages.addWidget(workspace)
            self.workspaces.append(workspace)

        self.settings = settings if settings is not None else create_application_settings()
        selected = load_device_model(self.settings, legacy_settings)
        index = self.model_combo.findData(selected)
        self.model_combo.setCurrentIndex(index if index >= 0 else 0)
        self.pages.setCurrentIndex(self.model_combo.currentIndex())
        self._active_index = self.model_combo.currentIndex()
        for workspace_index, workspace in enumerate(self.workspaces):
            if workspace_index == self._active_index:
                workspace.activate()
            else:
                workspace.deactivate()
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)

    @Slot(int)
    def _on_model_changed(self, index: int) -> None:
        """事务性切换到组合框指定的工作区。

        Args:
            index: 目标工作区在静态 registry 中的索引。

        Returns:
            无返回值。旧工作区无法安全停用时，会恢复旧选项并取消切换。
        """

        if not 0 <= index < len(self.workspaces) or index == self._active_index:
            return
        if 0 <= self._active_index < len(self.workspaces):
            if not self.workspaces[self._active_index].deactivate():
                # 切换必须先释放隐藏页资源；失败时回滚 UI，不能让仍占串口的页面隐身。
                self.workspaces[self._active_index].activate()
                self.model_combo.blockSignals(True)
                self.model_combo.setCurrentIndex(self._active_index)
                self.model_combo.blockSignals(False)
                return
        self.pages.setCurrentIndex(index)
        self._active_index = index
        self.workspaces[index].activate()
        self.settings.setValue(DEVICE_MODEL_KEY, self.model_combo.itemData(index))

    def shutdown(self) -> bool:
        """按“可恢复停用—不可逆关闭”两阶段释放全部后台资源。

        Returns:
            全部 Workspace 和日志线程均可安全关闭时返回 ``True``；任一
            Workspace 拒绝停用或关闭时返回 ``False``，调用方应取消退出。

        Notes:
            方法幂等。日志器最后关闭，确保设备停机过程中产生的末尾报文仍可落盘。
        """

        if self._shutdown:
            return True
        # 先执行仍可回滚的 deactivate；只有所有工作区准备完成才进入 shutdown。
        prepared = [workspace.deactivate() for workspace in self.workspaces]
        if not all(result is not False for result in prepared):
            if 0 <= self._active_index < len(self.workspaces):
                self.workspaces[self._active_index].activate()
            return False
        results = [workspace.shutdown() for workspace in self.workspaces]
        if not all(result is not False for result in results):
            if 0 <= self._active_index < len(self.workspaces):
                self.workspaces[self._active_index].activate()
            return False
        self.frame_monitor.close_logger()
        self._shutdown = True
        return True

    def closeEvent(self, event) -> None:
        """处理窗口关闭事件，并在后台线程未停止时拒绝退出。

        Args:
            event: Qt 传入的关闭事件；失败时调用 ``ignore()``。

        Returns:
            无返回值。
        """

        if not self.shutdown():
            event.ignore()
            return
        super().closeEvent(event)
