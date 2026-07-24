"""AFD01_QS 设备页面。"""

from __future__ import annotations

import time
from typing import Callable, Dict, Optional, Union

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from soft_hertz_tool.devices.afd01_qs.driver import Afd01QsDriver
from soft_hertz_tool.devices.afd01_qs.widgets import ArrayGridWidget
from soft_hertz_tool.shared.ui.serial_connection import SerialConnectionWidget


class Afd01QsPanel(QWidget):
    """QS V1.6 控制、实时状态与 KA256 阵列页面。"""

    frame_signal = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: Optional[Afd01QsDriver] = None
        self._latest_telemetry: Dict[str, object] = {}
        self._last_a0_time = 0.0
        self._array_pending = False
        self._array_supported = True
        self._connection_generation = 0
        self._confirmed_array = {
            "tx_size": 8,
            "rx_size": 8,
            "power_flags": 0,
            "apply_flags": 0,
        }
        self._shutdown = False

        self._build_ui()

        # 只在 10 Hz 定时器中刷新表格，不让 100 Hz A0 信号直接触发 UI 重绘。
        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.timeout.connect(self._refresh_telemetry)
        self._telemetry_timer.start(100)

        self._array_timeout = QTimer(self)
        self._array_timeout.setSingleShot(True)
        self._array_timeout.timeout.connect(self._on_array_timeout)

    @staticmethod
    def _double(
        value: float,
        minimum: float,
        maximum: float,
        decimals: int = 2,
    ) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(decimals)
        widget.setValue(value)
        return widget

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        serial_group = QGroupBox("AFD01_QS 串口")
        serial_layout = QHBoxLayout(serial_group)
        self.serial_connection = SerialConnectionWidget((115200, 460800, 921600), 921600)
        self.serial_connection.connect_requested.connect(self._connect_device)
        self.serial_connection.disconnect_requested.connect(self.disconnect_device)
        serial_layout.addWidget(self.serial_connection, 1)
        self.report_rate_label = QLabel("A0 上报频率: -- Hz")
        serial_layout.addWidget(self.report_rate_label)
        layout.addWidget(serial_group)

        # 兼容原有页面对外暴露的控件名称，便于渐进迁移现有 UI 测试。
        self.port_cb = self.serial_connection.port_combo
        self.baud_cb = self.serial_connection.baud_combo
        self.connect_btn = self.serial_connection.connect_button
        self.connection_label = self.serial_connection.status_label

        command_group = QGroupBox("QS V1.6 控制 (0x01~0x0A)")
        grid = QGridLayout(command_group)

        self.snr = self._double(0, -100, 100)
        self.indicator = QSpinBox()
        self.indicator.setRange(0, 255)
        self.power = QComboBox()
        self.power.addItems(["正常", "节能关闭TX"])
        self.reboot = QComboBox()
        self.reboot.addItems(["不重启", "重启"])
        grid.addWidget(QLabel("0x01 SNR/indicator/power/reboot"), 0, 0)
        for col, widget in enumerate((self.snr, self.indicator, self.power, self.reboot), 1):
            grid.addWidget(widget, 0, col)
        self._add_button(grid, "发送", 0, 5, self._send_01)

        self.sat_lon = self._double(125, -180, 180)
        self.polar = QComboBox()
        self.polar.addItems(["LHCP(0)", "RHCP(1)"])
        self.rx_freq = self._double(19798, 0, 50000, 3)
        self.tx_freq = self._double(29797.5, 0, 50000, 3)
        grid.addWidget(QLabel("0x02 经度/极化/RX/TX MHz"), 1, 0)
        for col, widget in enumerate((self.sat_lon, self.polar, self.rx_freq, self.tx_freq), 1):
            grid.addWidget(widget, 1, col)
        self._add_button(grid, "发送", 1, 5, self._send_02)

        self.tx_enable = QComboBox()
        self.tx_enable.addItems(["关闭", "开启"])
        self.scan_angle = self._double(360, 0, 360)
        self.track_mode = QComboBox()
        self.track_mode.addItems(["自动", "手动"])
        self.align_angle = self._double(0, 0, 360)
        grid.addWidget(QLabel("0x03/04/05/06"), 2, 0)
        for col, widget in enumerate(
            (self.tx_enable, self.scan_angle, self.track_mode, self.align_angle), 1
        ):
            grid.addWidget(widget, 2, col)
        buttons = QHBoxLayout()
        for text, callback in (
            ("03", self._send_03),
            ("04", self._send_04),
            ("05", self._send_05),
            ("06", self._send_06),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        grid.addLayout(buttons, 2, 5)

        self.beam_theta = self._double(0, 0, 90)
        self.beam_phi = self._double(0, 0, 360)
        grid.addWidget(QLabel("0x07/09/0A theta/phi"), 3, 0)
        grid.addWidget(self.beam_theta, 3, 1)
        grid.addWidget(self.beam_phi, 3, 2)
        buttons = QHBoxLayout()
        for text, command in (("TX(07)", 0x07), ("RX(09)", 0x09), ("共同(0A)", 0x0A)):
            button = QPushButton(text)
            button.clicked.connect(
                lambda _checked=False, selected_command=command: self._send_beam(selected_command)
            )
            buttons.addWidget(button)
        grid.addLayout(buttons, 3, 3, 1, 3)

        self.tle1 = QLineEdit()
        self.tle1.setPlaceholderText("TLE Line 1 (69 ASCII)")
        self.tle2 = QLineEdit()
        self.tle2.setPlaceholderText("TLE Line 2 (69 ASCII)")
        grid.addWidget(QLabel("0x08 TLE"), 4, 0)
        grid.addWidget(self.tle1, 4, 1, 1, 2)
        grid.addWidget(self.tle2, 4, 3, 1, 2)
        self._add_button(grid, "发送", 4, 5, self._send_08)
        layout.addWidget(command_group)

        middle = QHBoxLayout()
        telemetry_group = QGroupBox("0xA0 实时状态 (UI 10Hz)")
        telemetry_layout = QVBoxLayout(telemetry_group)
        self.telemetry_table = QTableWidget(0, 2)
        self.telemetry_table.setHorizontalHeaderLabels(["字段", "值"])
        self.telemetry_table.horizontalHeader().setStretchLastSection(True)
        telemetry_layout.addWidget(self.telemetry_table)
        middle.addWidget(telemetry_group, 1)

        array_group = QGroupBox("KA256 阵列规模 (0x0B/0xA1)")
        array_layout = QVBoxLayout(array_group)
        actions = QHBoxLayout()
        self.tx_size_cb = QComboBox()
        self.rx_size_cb = QComboBox()
        for size in (8, 7, 6, 5, 4):
            self.tx_size_cb.addItem(f"{size}×{size}", size)
            self.rx_size_cb.addItem(f"{size}×{size}", size)
        self.tx_size_cb.currentIndexChanged.connect(self._preview_array)
        self.rx_size_cb.currentIndexChanged.connect(self._preview_array)
        self.array_apply_btn = QPushButton("应用")
        self.array_read_btn = QPushButton("读取")
        self.array_apply_btn.clicked.connect(self._apply_array)
        self.array_read_btn.clicked.connect(self._query_array)
        actions.addWidget(QLabel("TX:"))
        actions.addWidget(self.tx_size_cb)
        actions.addWidget(QLabel("RX:"))
        actions.addWidget(self.rx_size_cb)
        actions.addWidget(self.array_apply_btn)
        actions.addWidget(self.array_read_btn)
        array_layout.addLayout(actions)

        grids = QHBoxLayout()
        self.tx_grid = ArrayGridWidget("TX")
        self.rx_grid = ArrayGridWidget("RX")
        grids.addWidget(self.tx_grid)
        grids.addWidget(self.rx_grid)
        array_layout.addLayout(grids)
        self.array_status_label = QLabel("未查询")
        self.array_status_label.setWordWrap(True)
        array_layout.addWidget(self.array_status_label)
        middle.addWidget(array_group, 2)
        layout.addLayout(middle)

    @staticmethod
    def _add_button(
        layout: QGridLayout,
        text: str,
        row: int,
        col: int,
        callback: Callable[[], None],
    ) -> None:
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button, row, col)

    @Slot(str, int)
    def _connect_device(self, port: str, baudrate: int) -> None:
        if self._shutdown:
            self.serial_connection.set_disconnected("页面已停止")
            return
        if self.worker is not None and not self.disconnect_device():
            return

        self._connection_generation += 1
        generation = self._connection_generation
        self.serial_connection.set_connecting()

        worker = Afd01QsDriver(port, baudrate, self)
        worker.frame_signal.connect(self.frame_signal.emit)
        worker.telemetry_signal.connect(
            lambda telemetry, current=worker, token=generation: self._on_driver_telemetry(
                current,
                token,
                telemetry,
            )
        )
        worker.report_rate_signal.connect(
            lambda rate, current=worker, token=generation: self._on_driver_report_rate(
                current,
                token,
                rate,
            )
        )
        worker.array_status_signal.connect(
            lambda status, current=worker, token=generation: self._on_driver_array_status(
                current,
                token,
                status,
            )
        )
        worker.opened_signal.connect(
            lambda opened, message, current=worker, token=generation: self._on_driver_opened(
                current,
                token,
                opened,
                message,
            )
        )
        worker.log_signal.connect(
            lambda message, current=worker, token=generation: self._on_driver_log(
                current,
                token,
                message,
            )
        )
        worker.finished.connect(lambda current=worker: self._on_driver_finished(current))
        self.worker = worker
        worker.start()

    @Slot()
    def _toggle_connection(self) -> None:
        """保留旧 QSPanel 的程序化连接入口。"""
        if self.worker is not None:
            self.disconnect_device()
            return
        port = self.port_cb.currentText()
        if not port:
            QMessageBox.warning(self, "警告", "请选择串口")
            return
        self.serial_connection.set_connecting()
        self._connect_device(port, int(self.baud_cb.currentText()))

    @Slot(bool, str)
    def _on_opened(self, opened: bool, message: str) -> None:
        if opened:
            self.serial_connection.set_connected(message)
            self._last_a0_time = 0.0
            self.report_rate_label.setText("A0 上报频率: 等待数据")
            self.report_rate_label.setStyleSheet("color:#666;")
            self._array_supported = True
            self._set_array_busy(False)
        else:
            self.serial_connection.set_disconnected(message)

    def _is_current_worker(self, worker: Afd01QsDriver, generation: int) -> bool:
        return worker is self.worker and generation == self._connection_generation

    def _on_driver_opened(
        self,
        worker: Afd01QsDriver,
        generation: int,
        opened: bool,
        message: str,
    ) -> None:
        if not self._is_current_worker(worker, generation):
            return
        self._on_opened(opened, message)
        if opened:
            QTimer.singleShot(
                100,
                lambda current=worker, token=generation: self._query_array_if_current(
                    current,
                    token,
                ),
            )

    def _on_driver_log(
        self,
        worker: Afd01QsDriver,
        generation: int,
        message: str,
    ) -> None:
        if self._is_current_worker(worker, generation):
            self.connection_label.setText(message)

    def _on_driver_telemetry(
        self,
        worker: Afd01QsDriver,
        generation: int,
        telemetry: Dict[str, object],
    ) -> None:
        if self._is_current_worker(worker, generation):
            self._on_telemetry(telemetry)

    def _on_driver_report_rate(
        self,
        worker: Afd01QsDriver,
        generation: int,
        rate: float,
    ) -> None:
        if self._is_current_worker(worker, generation):
            self._on_report_rate(rate)

    def _on_driver_array_status(
        self,
        worker: Afd01QsDriver,
        generation: int,
        status: Dict[str, int],
    ) -> None:
        if self._is_current_worker(worker, generation):
            self._on_array_status(status)

    def _query_array_if_current(self, worker: Afd01QsDriver, generation: int) -> None:
        if self._is_current_worker(worker, generation) and worker.running:
            self._begin_array_request(lambda driver: driver.query_array())

    def _on_driver_finished(self, worker: Afd01QsDriver) -> None:
        if worker is self.worker:
            self.worker = None
            self._reset_connection_display("串口已关闭")
        worker.deleteLater()

    @Slot()
    def disconnect_device(self) -> bool:
        self._connection_generation += 1
        self._array_timeout.stop()
        self._array_pending = False
        worker = self.worker
        if worker is not None:
            self.serial_connection.set_stopping()
            if worker.stop() is False:
                self.serial_connection.set_stop_failed("串口线程停止超时，请重试关闭")
                return False
            self.worker = None
            worker.deleteLater()
        self._reset_connection_display()
        return True

    def _reset_connection_display(self, message: str = "未连接") -> None:
        self.serial_connection.set_disconnected(message)
        self._last_a0_time = 0.0
        self.report_rate_label.setText("A0 上报频率: -- Hz")
        self.report_rate_label.setStyleSheet("")

    def _safe_send(self, action: Callable[[Afd01QsDriver], bool]) -> None:
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        try:
            action(self.worker)
        except (ValueError, UnicodeEncodeError) as exc:
            QMessageBox.warning(self, "参数错误", str(exc))

    @Slot()
    def _send_01(self) -> None:
        self._safe_send(
            lambda driver: driver.report_snr(
                self.snr.value(),
                self.indicator.value(),
                self.power.currentIndex(),
                self.reboot.currentIndex(),
            )
        )

    @Slot()
    def _send_02(self) -> None:
        self._safe_send(
            lambda driver: driver.configure_beam(
                self.sat_lon.value(),
                self.polar.currentIndex(),
                self.rx_freq.value(),
                self.tx_freq.value(),
            )
        )

    @Slot()
    def _send_03(self) -> None:
        self._safe_send(lambda driver: driver.set_transmit_enabled(self.tx_enable.currentIndex()))

    @Slot()
    def _send_04(self) -> None:
        self._safe_send(lambda driver: driver.set_heading_scan_angle(self.scan_angle.value()))

    @Slot()
    def _send_05(self) -> None:
        self._safe_send(lambda driver: driver.set_track_mode(self.track_mode.currentIndex()))

    @Slot()
    def _send_06(self) -> None:
        self._safe_send(lambda driver: driver.set_heading_align_angle(self.align_angle.value()))

    @Slot()
    def _send_08(self) -> None:
        self._safe_send(lambda driver: driver.configure_tle(self.tle1.text(), self.tle2.text()))

    @Slot(int)
    def _send_beam(self, command: int) -> None:
        self._safe_send(
            lambda driver: driver.set_beam_angle(
                command,
                self.beam_theta.value(),
                self.beam_phi.value(),
            )
        )

    @Slot(dict)
    def _on_telemetry(self, telemetry: Dict[str, object]) -> None:
        self._latest_telemetry = telemetry
        self._last_a0_time = time.monotonic()

    @Slot(float)
    def _on_report_rate(self, rate: float) -> None:
        self.report_rate_label.setText(f"A0 上报频率: {rate:.1f} Hz")
        color = "#198754" if 95.0 <= rate <= 105.0 else "#d97706"
        self.report_rate_label.setStyleSheet(f"color:{color}; font-weight:bold;")

    @Slot()
    def _refresh_telemetry(self) -> None:
        if self._last_a0_time and time.monotonic() - self._last_a0_time > 1.0:
            self.report_rate_label.setText("A0 上报频率: 0.0 Hz（超时）")
            self.report_rate_label.setStyleSheet("color:#c62828; font-weight:bold;")
        if not self._latest_telemetry:
            return

        items = list(self._latest_telemetry.items())
        self.telemetry_table.setRowCount(len(items))
        for row, (key, value) in enumerate(items):
            self.telemetry_table.setItem(row, 0, QTableWidgetItem(key))
            self.telemetry_table.setItem(row, 1, QTableWidgetItem(str(value)))

    @Slot()
    def _preview_array(self) -> None:
        tx_size = self.tx_size_cb.currentData()
        rx_size = self.rx_size_cb.currentData()
        confirmed = self._confirmed_array
        tx_changed = tx_size != confirmed["tx_size"]
        rx_changed = rx_size != confirmed["rx_size"]
        self.tx_grid.set_state(
            tx_size,
            bool(confirmed["power_flags"] & 1),
            "pending" if tx_changed else "active",
        )
        self.rx_grid.set_state(
            rx_size,
            bool(confirmed["power_flags"] & 2),
            "pending" if rx_changed else "active",
        )
        if tx_changed and not (confirmed["power_flags"] & 1):
            self.array_status_label.setText("TX 已预览；发射关闭时将缓存，待发射开启后生效")

    def _set_array_busy(self, busy: bool) -> None:
        enabled = not busy and self._array_supported
        self.array_apply_btn.setEnabled(enabled)
        self.array_read_btn.setEnabled(enabled)

    def _begin_array_request(
        self,
        action: Union[Callable[[Afd01QsDriver], bool], bytes],
    ) -> None:
        if self._array_pending:
            return
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        self._array_pending = True
        self._set_array_busy(True)
        # bytes 分支只用于兼容旧 QSPanel 私有方法测试；正式页面始终调用 Driver 语义接口。
        try:
            accepted = (
                self.worker.send_frame(action)
                if isinstance(action, bytes)
                else action(self.worker)
            )
        except (ValueError, UnicodeEncodeError) as exc:
            self._array_pending = False
            self._set_array_busy(False)
            QMessageBox.warning(self, "参数错误", str(exc))
            return
        if not accepted:
            self._array_pending = False
            self._set_array_busy(False)
            return
        self._array_timeout.start(3000)

    @Slot()
    def _query_array(self) -> None:
        self._begin_array_request(lambda driver: driver.query_array())

    @Slot()
    def _apply_array(self) -> None:
        self.tx_grid.set_state(
            self.tx_size_cb.currentData(),
            bool(self._confirmed_array["power_flags"] & 1),
            "pending",
        )
        self.rx_grid.set_state(
            self.rx_size_cb.currentData(),
            bool(self._confirmed_array["power_flags"] & 2),
            "pending",
        )
        self._begin_array_request(
            lambda driver: driver.set_array_size(
                self.tx_size_cb.currentData(),
                self.rx_size_cb.currentData(),
            )
        )

    @Slot(dict)
    def _on_array_status(self, status: Dict[str, int]) -> None:
        self._array_timeout.stop()
        self._array_pending = False
        self._array_supported = True
        self._set_array_busy(False)
        self._confirmed_array = dict(status)
        self.tx_size_cb.setCurrentIndex(max(0, self.tx_size_cb.findData(status["tx_size"])))
        self.rx_size_cb.setCurrentIndex(max(0, self.rx_size_cb.findData(status["rx_size"])))

        result = status["result"]
        tx_state = "failed" if result & 0x02 else "active"
        rx_state = "failed" if result & 0x04 else "active"
        self.tx_grid.set_state(status["tx_size"], bool(status["power_flags"] & 1), tx_state)
        self.rx_grid.set_state(status["rx_size"], bool(status["power_flags"] & 2), rx_state)

        notes = []
        if result & 0x01:
            notes.append("参数非法")
        if result & 0x02:
            notes.append("TX 回显失败")
        if result & 0x04:
            notes.append("RX 回显失败")
        if result & 0x08:
            notes.append("请求忙")
        if not notes:
            notes.append("成功")
        tx_power = "开" if status["power_flags"] & 1 else "关"
        rx_power = "开" if status["power_flags"] & 2 else "关"
        self.array_status_label.setText(
            f"{', '.join(notes)} | TX {status['tx_size']}×{status['tx_size']} 电源{tx_power} "
            f"确认={bool(status['apply_flags'] & 1)} | RX {status['rx_size']}×{status['rx_size']} "
            f"电源{rx_power} 确认={bool(status['apply_flags'] & 2)}"
        )

    @Slot()
    def _on_array_timeout(self) -> None:
        self._array_pending = False
        self._array_supported = False
        self._set_array_busy(False)
        self.array_status_label.setText(
            "固件不支持或通信超时；其他 QS 功能不受影响，重新连接后可再查询"
        )

    def activate(self) -> None:
        """工作区进入前台时恢复端口扫描和 10 Hz UI 刷新。"""

        if self._shutdown:
            return
        serial_timer = getattr(self.serial_connection, "_timer", None)
        if serial_timer is not None and not serial_timer.isActive():
            serial_timer.start(2000)
        if not self._telemetry_timer.isActive():
            self._telemetry_timer.start(100)

    def deactivate(self) -> bool:
        """断开串口并暂停隐藏页面的定时器。"""

        stopped = self.disconnect_device()
        if stopped:
            self._telemetry_timer.stop()
            serial_timer = getattr(self.serial_connection, "_timer", None)
            if serial_timer is not None:
                serial_timer.stop()
        return stopped

    @Slot()
    def shutdown(self) -> bool:
        """停止设备页面所有活动任务，允许重复调用。"""
        if self._shutdown:
            return True
        if not self.disconnect_device():
            return False
        self._telemetry_timer.stop()
        self._array_timeout.stop()
        serial_timer = getattr(self.serial_connection, "_timer", None)
        if serial_timer is not None:
            serial_timer.stop()
        self._shutdown = True
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self.shutdown():
            event.ignore()
            return
        super().closeEvent(event)


# 兼容原有主窗口与测试使用的名称。
QSPanel = Afd01QsPanel
