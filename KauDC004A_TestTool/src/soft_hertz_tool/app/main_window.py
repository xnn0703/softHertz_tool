"""只负责工作区注册、切换和统一生命周期的主窗口。"""

from __future__ import annotations

import os

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

from soft_hertz_tool.app.registry import WORKSPACE_SPECS
from soft_hertz_tool.shared.resources import resource_path
from soft_hertz_tool.shared.ui.frame_monitor import FrameMonitorWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SoftHertz AFDTR Tool")
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

        self.settings = QSettings("SoftHertz", "AFDTR_Tool")
        selected = self.settings.value("device_model", "AFDTR")
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
        if not 0 <= index < len(self.workspaces) or index == self._active_index:
            return
        if 0 <= self._active_index < len(self.workspaces):
            if not self.workspaces[self._active_index].deactivate():
                self.workspaces[self._active_index].activate()
                self.model_combo.blockSignals(True)
                self.model_combo.setCurrentIndex(self._active_index)
                self.model_combo.blockSignals(False)
                return
        self.pages.setCurrentIndex(index)
        self._active_index = index
        self.workspaces[index].activate()
        self.settings.setValue("device_model", self.model_combo.itemData(index))

    def shutdown(self) -> bool:
        if self._shutdown:
            return True
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
        if not self.shutdown():
            event.ignore()
            return
        super().closeEvent(event)
