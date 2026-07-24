"""全局串口报文监视器。"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Deque, List, Optional

from PySide6.QtCore import QTimer, Slot
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from soft_hertz_tool.shared.observability.frame_logger import AsyncFrameLogger
from soft_hertz_tool.shared.observability.frame_record import FrameRecord


class FrameMonitorWidget(QWidget):
    MAX_LINES = 10000
    ALL_MODELS = "全部型号"
    ALL_DIRECTIONS = "全部方向"

    def __init__(self, parent=None, logger: Optional[AsyncFrameLogger] = None, max_lines: Optional[int] = None):
        super().__init__(parent)
        self.max_lines = max_lines or self.MAX_LINES
        self.records: Deque[FrameRecord] = deque(maxlen=self.max_lines)
        self._pending: List[FrameRecord] = []
        self.logger = logger or AsyncFrameLogger()
        self._logger_closed = False
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush_pending)
        self._timer.start(100)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("报文监视:"))
        self.model_filter = QComboBox()
        self.model_filter.addItem(self.ALL_MODELS)
        self.direction_filter = QComboBox()
        self.direction_filter.addItems([self.ALL_DIRECTIONS, "TX", "RX", "DROP"])
        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("筛选端口/命令/解析结果")
        self.pause_cb = QCheckBox("暂停显示")
        controls.addWidget(self.model_filter)
        controls.addWidget(self.direction_filter)
        controls.addWidget(self.text_filter, 1)
        controls.addWidget(self.pause_cb)
        for text, callback in (
            ("清空显示", self.clear_records),
            ("复制所选", self.copy_selected),
            ("复制全部", self.copy_all),
            ("另存为", self.save_as),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setMinimumHeight(120)
        layout.addWidget(self.text)

        self.model_filter.currentIndexChanged.connect(self._rerender)
        self.direction_filter.currentIndexChanged.connect(self._rerender)
        self.text_filter.textChanged.connect(self._rerender)
        self.pause_cb.toggled.connect(self._on_pause_changed)

    def _ensure_model(self, model: str) -> None:
        if self.model_filter.findText(model) >= 0:
            return
        self.model_filter.addItem(model)

    @Slot(object)
    def add_record(self, record: FrameRecord) -> None:
        self._ensure_model(record.model)
        self.records.append(record)
        self.logger.write(record)
        if not self.pause_cb.isChecked():
            self._pending.append(record)

    def _matches(self, record: FrameRecord) -> bool:
        model = self.model_filter.currentText()
        direction = self.direction_filter.currentText()
        query = self.text_filter.text().strip().lower()
        if model != self.ALL_MODELS and record.model != model:
            return False
        if direction != self.ALL_DIRECTIONS and record.direction != direction:
            return False
        return not query or query in record.to_line().lower()

    @Slot()
    def _flush_pending(self) -> None:
        if self.pause_cb.isChecked() or not self._pending:
            return
        batch = self._pending
        self._pending = []
        lines = [record.to_line() for record in batch if self._matches(record)]
        if not lines:
            return
        self.text.appendPlainText("\n".join(lines))
        excess = self.text.document().blockCount() - self.max_lines
        if excess > 0:
            cursor = QTextCursor(self.text.document())
            cursor.movePosition(QTextCursor.Start)
            for _ in range(excess):
                cursor.select(QTextCursor.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.text.setTextCursor(cursor)

    @Slot()
    def _rerender(self) -> None:
        if self.pause_cb.isChecked():
            return
        self._pending.clear()
        self.text.setPlainText("\n".join(record.to_line() for record in self.records if self._matches(record)))

    @Slot(bool)
    def _on_pause_changed(self, paused: bool) -> None:
        self._pending.clear()
        if not paused:
            self._rerender()

    @Slot()
    def clear_records(self) -> None:
        self.records.clear()
        self._pending.clear()
        self.text.clear()

    @Slot()
    def copy_selected(self) -> None:
        selected = self.text.textCursor().selectedText().replace("\u2029", "\n")
        if selected:
            QGuiApplication.clipboard().setText(selected)

    @Slot()
    def copy_all(self) -> None:
        QGuiApplication.clipboard().setText(self.text.toPlainText())

    @Slot()
    def save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存报文", "frames.log", "Log (*.log);;Text (*.txt)")
        if path:
            Path(path).write_text(self.text.toPlainText(), encoding="utf-8")

    def close_logger(self) -> None:
        if self._logger_closed:
            return
        self._logger_closed = True
        self._flush_pending()
        self.logger.close()
