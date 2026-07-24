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
    """汇总、筛选、展示并异步记录所有设备的帧事件。

    接收槽只更新内存与日志队列；文本控件由 100 ms 定时器批量刷新，避免
    AFD01_QS 高频上报让主线程为每帧重绘。
    """

    MAX_LINES = 10000
    ALL_MODELS = "全部型号"
    ALL_DIRECTIONS = "全部方向"

    def __init__(self, parent=None, logger: Optional[AsyncFrameLogger] = None, max_lines: Optional[int] = None):
        """创建报文控件、环形内存记录和异步日志器。

        Args:
            parent: 可选 Qt 父对象。
            logger: 可注入的日志器；为 ``None`` 时创建默认异步日志器。
            max_lines: 内存和文本区最大行数；为 ``None`` 时使用 10000。
        """

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
        """创建筛选、暂停、复制、清空、导出和文本显示控件。"""

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
        """把新出现的公开设备型号加入动态筛选列表。

        Args:
            model: ``FrameRecord.model`` 中的公开硬件型号。
        """

        if self.model_filter.findText(model) >= 0:
            return
        self.model_filter.addItem(model)

    @Slot(object)
    def add_record(self, record: FrameRecord) -> None:
        """接收一条帧事件并加入内存、日志及待显示队列。

        Args:
            record: 设备 Driver 发布的统一帧事件。

        Returns:
            无返回值。暂停只停止屏幕更新，事件仍会保留并写入日志。
        """

        self._ensure_model(record.model)
        self.records.append(record)
        self.logger.write(record)
        if not self.pause_cb.isChecked():
            # 先积累轻量对象，由定时器合并绘制，隔离串口上报速率与 UI 刷新速率。
            self._pending.append(record)

    def _matches(self, record: FrameRecord) -> bool:
        """判断记录是否同时满足型号、方向和文本筛选。

        Args:
            record: 候选帧记录。

        Returns:
            三类筛选均匹配时返回 ``True``。
        """

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
        """批量渲染尚未显示的记录并裁剪最旧文本行。

        Returns:
            无返回值。暂停、无待处理记录或筛选后为空时不改动文本。
        """

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
        """使用当前环形记录按最新筛选条件完整重绘文本区。"""

        if self.pause_cb.isChecked():
            return
        self._pending.clear()
        self.text.setPlainText("\n".join(record.to_line() for record in self.records if self._matches(record)))

    @Slot(bool)
    def _on_pause_changed(self, paused: bool) -> None:
        """处理暂停状态变化。

        Args:
            paused: ``True`` 表示停止屏幕刷新；恢复时从当前环形记录重绘。
        """

        self._pending.clear()
        if not paused:
            self._rerender()

    @Slot()
    def clear_records(self) -> None:
        """清空内存记录、待显示队列和文本区，不删除已经落盘的日志。"""

        self.records.clear()
        self._pending.clear()
        self.text.clear()

    @Slot()
    def copy_selected(self) -> None:
        """把文本区当前选中内容复制到系统剪贴板。"""

        selected = self.text.textCursor().selectedText().replace("\u2029", "\n")
        if selected:
            QGuiApplication.clipboard().setText(selected)

    @Slot()
    def copy_all(self) -> None:
        """把当前筛选后可见的全部文本复制到系统剪贴板。"""

        QGuiApplication.clipboard().setText(self.text.toPlainText())

    @Slot()
    def save_as(self) -> None:
        """让用户选择路径并导出当前可见文本。

        Returns:
            无返回值；用户取消文件对话框时不创建文件。
        """

        path, _ = QFileDialog.getSaveFileName(self, "保存报文", "frames.log", "Log (*.log);;Text (*.txt)")
        if path:
            Path(path).write_text(self.text.toPlainText(), encoding="utf-8")

    def close_logger(self) -> None:
        """幂等地刷新待显示记录并关闭异步日志器。"""

        if self._logger_closed:
            return
        self._logger_closed = True
        self._flush_pending()
        self.logger.close()
