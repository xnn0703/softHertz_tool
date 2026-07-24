"""设备页面复用的串口连接栏。"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from soft_hertz_tool.shared.transport.ports import list_serial_ports


class SerialConnectionWidget(QWidget):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    STOPPING = "stopping"
    STOP_FAILED = "stop_failed"

    connect_requested = Signal(str, int)
    disconnect_requested = Signal()

    def __init__(self, baudrates: Iterable[int], default_baudrate: int, parent=None):
        super().__init__(parent)
        self._state = self.DISCONNECTED
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.port_combo = QComboBox()
        self.baud_combo = QComboBox()
        self.baud_combo.addItems([str(value) for value in baudrates])
        self.baud_combo.setCurrentText(str(default_baudrate))
        self.connect_button = QPushButton("打开串口")
        self.status_label = QLabel("未连接")
        layout.addWidget(QLabel("端口:"))
        layout.addWidget(self.port_combo)
        layout.addWidget(QLabel("波特率:"))
        layout.addWidget(self.baud_combo)
        layout.addWidget(self.connect_button)
        layout.addWidget(self.status_label, 1)
        self.connect_button.clicked.connect(self._toggle)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_ports)
        self._timer.start(2000)
        self.refresh_ports()

    @Slot()
    def refresh_ports(self) -> None:
        ports = list_serial_ports()
        current = self.port_combo.currentText()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        self.port_combo.addItems(ports)
        if current in ports:
            self.port_combo.setCurrentText(current)
        self.port_combo.blockSignals(False)

    @Slot()
    def _toggle(self) -> None:
        if self._state in (self.CONNECTED, self.STOP_FAILED):
            self.set_stopping()
            self.disconnect_requested.emit()
            return
        if self._state != self.DISCONNECTED:
            return
        port = self.port_combo.currentText()
        if port:
            self.set_connecting()
            self.connect_requested.emit(port, int(self.baud_combo.currentText()))

    def set_connecting(self) -> None:
        self._state = self.CONNECTING
        self.port_combo.setEnabled(False)
        self.baud_combo.setEnabled(False)
        self.connect_button.setEnabled(False)
        self.connect_button.setText("正在连接…")

    def set_connected(self, message: str) -> None:
        self._state = self.CONNECTED
        self.port_combo.setEnabled(False)
        self.baud_combo.setEnabled(False)
        self.connect_button.setEnabled(True)
        self.connect_button.setText("关闭串口")
        self.status_label.setText(message)

    def set_stopping(self) -> None:
        self._state = self.STOPPING
        self.connect_button.setEnabled(False)
        self.connect_button.setText("正在关闭…")

    def set_stop_failed(self, message: str) -> None:
        self._state = self.STOP_FAILED
        self.port_combo.setEnabled(False)
        self.baud_combo.setEnabled(False)
        self.connect_button.setEnabled(True)
        self.connect_button.setText("重试关闭")
        self.status_label.setText(message)

    def set_disconnected(self, message: str = "未连接") -> None:
        self._state = self.DISCONNECTED
        self.port_combo.setEnabled(True)
        self.baud_combo.setEnabled(True)
        self.connect_button.setEnabled(True)
        self.connect_button.setText("打开串口")
        self.status_label.setText(message)
