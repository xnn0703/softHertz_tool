"""KA_RF_UNIT 设备页面。"""

from __future__ import annotations

import time
from typing import Callable, Dict, Optional

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from soft_hertz_tool.devices.ka_rf_unit import protocol
from soft_hertz_tool.devices.ka_rf_unit.driver import KaRfUnitDriver
from soft_hertz_tool.shared.ui.serial_connection import SerialConnectionWidget


BAUD_RATES = (460800, 921600)

POLAR_OPTIONS = (("LHCP(0)", protocol.POLAR_LEFT_CIRCLE), ("RHCP(1)", protocol.POLAR_RIGHT_CIRCLE))
EXT_REF_OPTIONS = (("10 MHz", 10), ("100 MHz", 100))

ENABLE_OPTIONS = (("关闭", False), ("开启", True))

STATUS_REPORT_ROWS = (
    ("uptime_ms", "uptime(ms)"),
    ("conv_lock_mask", "conv_lock_mask"),
    ("pa_enable", "PA 使能"),
    ("tx_enable", "TX 阵列"),
    ("rx_enable", "RX 阵列"),
    ("status_report_rate_hz", "上报频率(Hz)"),
    ("unit_sw", "整机软件版本"),
    ("rx_rf_mhz", "RX RF (MHz)"),
    ("rx_lo_mhz", "RX LO (MHz)"),
    ("tx_rf_mhz", "TX RF (MHz)"),
    ("tx_lo_mhz", "TX LO (MHz)"),
    ("rx_conv_att_x10", "RX 衰减 (0.1 dB)"),
    ("tx_conv_att_x10", "TX 衰减 (0.1 dB)"),
    ("ext_ref_mhz", "外参 (MHz)"),
    ("conv_temp_x10", "变频温度 (0.1°C)"),
    ("tx_array_temp_x10", "TX 阵列温度 (0.1°C)"),
    ("rx_array_temp_x10", "RX 阵列温度 (0.1°C)"),
    ("tx_beam_h", "TX BeamH"),
    ("tx_beam_v", "TX BeamV"),
    ("rx_beam_h", "RX BeamH"),
    ("rx_beam_v", "RX BeamV"),
    ("rx_polar", "RX 极化"),
    ("tx_polar", "TX 极化"),
)

REPORT_TIMEOUT_S = 1.0
REFRESH_INTERVAL_MS = 100  # 10 Hz 业务 UI 刷新


def _polar_text(value: int) -> str:
    """将极化字段值转换为客户可见文本。

    Args:
        value: 协议载荷中的极化字节。

    Returns:
        ``"RHCP"`` 或 ``"LHCP"``；其它值统一按左旋显示。
    """
    return "RHCP" if value == protocol.POLAR_RIGHT_CIRCLE else "LHCP"


class KaRfUnitPanel(QFrame):
    """KA_RF_UNIT V1 控制与 0x30 状态页面。"""

    frame_signal = Signal(object)

    def __init__(
        self,
        parent=None,
        driver_factory: Callable[[str, int], KaRfUnitDriver] = KaRfUnitDriver,
    ) -> None:
        """创建 KA_RF_UNIT 交互面板。

        Args:
            parent: 可选 Qt 父对象。
            driver_factory: 创建串口 Driver 的工厂，便于测试注入替身。
        """
        super().__init__(parent)
        self._driver_factory = driver_factory
        self._driver: Optional[KaRfUnitDriver] = None
        self._shutdown = False
        self._connection_generation = 0
        self._latest_status: Optional[Dict[str, object]] = None
        self._last_status_time = 0.0
        self._row_index: Dict[str, int] = {}

        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setMinimumWidth(560)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """组装串口、命令、状态和日志区域。"""
        layout = QVBoxLayout(self)

        self.title_label = QLabel("KA_RF_UNIT")
        self.title_label.setObjectName("panelTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        layout.addWidget(self._create_serial_group())
        layout.addWidget(self._create_freq_group())
        layout.addWidget(self._create_att_group())
        layout.addWidget(self._create_en_group())
        layout.addWidget(self._create_beam_group())
        layout.addWidget(self._create_extref_report_group())
        layout.addWidget(self._create_status_group())
        layout.addWidget(self._create_log_group())
        layout.addStretch()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_status_table)

    def _create_serial_group(self) -> QGroupBox:
        """创建串口连接栏与上报频率指示。"""
        group = QGroupBox("串口设置")
        row = QHBoxLayout(group)
        self.connection = SerialConnectionWidget(BAUD_RATES, 460800)
        self.connection.connect_requested.connect(self._connect_device)
        self.connection.disconnect_requested.connect(self._disconnect_device)
        row.addWidget(self.connection, 1)
        self.report_rate_label = QLabel("0x30 上报频率: -- Hz")
        self.report_rate_label.setMinimumWidth(160)
        row.addWidget(self.report_rate_label)
        return group

    def _create_freq_group(self) -> QGroupBox:
        """创建 0x10 频点与极化控件。"""
        group = QGroupBox("0x10 频点与极化配置")
        grid = QGridLayout(group)
        grid.addWidget(QLabel("RX RF (MHz)"), 0, 0)
        self.rx_rf = self._int_spin(19966, 17700, 21200)
        grid.addWidget(self.rx_rf, 0, 1)
        grid.addWidget(QLabel("RX LO (MHz，留空=AUTO)"), 0, 2)
        self.rx_lo = QLineEdit()
        self.rx_lo.setPlaceholderText("AUTO")
        grid.addWidget(self.rx_lo, 0, 3)
        grid.addWidget(QLabel("RX 极化"), 0, 4)
        self.rx_polar = QComboBox()
        for label, value in POLAR_OPTIONS:
            self.rx_polar.addItem(label, value)
        grid.addWidget(self.rx_polar, 0, 5)

        grid.addWidget(QLabel("TX RF (MHz)"), 1, 0)
        self.tx_rf = self._int_spin(29500, 27500, 31000)
        grid.addWidget(self.tx_rf, 1, 1)
        grid.addWidget(QLabel("TX LO (MHz，留空=AUTO)"), 1, 2)
        self.tx_lo = QLineEdit()
        self.tx_lo.setPlaceholderText("AUTO")
        grid.addWidget(self.tx_lo, 1, 3)
        grid.addWidget(QLabel("TX 极化"), 1, 4)
        self.tx_polar = QComboBox()
        for label, value in POLAR_OPTIONS:
            self.tx_polar.addItem(label, value)
        grid.addWidget(self.tx_polar, 1, 5)

        apply = QPushButton("设置")
        apply.clicked.connect(self._apply_freq)
        grid.addWidget(apply, 0, 6, 2, 1)
        return group

    def _create_att_group(self) -> QGroupBox:
        """创建 0x11 衰减控件。"""
        group = QGroupBox("0x11 变频衰减 (0.0~31.5 dB，步进 0.5)")
        row = QHBoxLayout(group)
        row.addWidget(QLabel("RX 衰减 (dB)"))
        self.rx_att = QDoubleSpinBox()
        self.rx_att.setRange(0.0, 31.5)
        self.rx_att.setDecimals(1)
        self.rx_att.setSingleStep(0.5)
        self.rx_att.setValue(0.0)
        row.addWidget(self.rx_att)
        row.addWidget(QLabel("TX 衰减 (dB)"))
        self.tx_att = QDoubleSpinBox()
        self.tx_att.setRange(0.0, 31.5)
        self.tx_att.setDecimals(1)
        self.tx_att.setSingleStep(0.5)
        self.tx_att.setValue(0.0)
        row.addWidget(self.tx_att)
        apply = QPushButton("设置")
        apply.clicked.connect(self._apply_att)
        row.addWidget(apply)
        row.addStretch()
        return group

    def _create_en_group(self) -> QGroupBox:
        """创建 0x12/0x13 阵列使能控件。"""
        group = QGroupBox("0x12/0x13 阵列使能")
        row = QHBoxLayout(group)
        self.tx_en = QComboBox()
        for label, value in ENABLE_OPTIONS:
            self.tx_en.addItem(label, value)
        tx_apply = QPushButton("设置 TX")
        tx_apply.clicked.connect(lambda: self._apply_en("TX"))
        self.rx_en = QComboBox()
        for label, value in ENABLE_OPTIONS:
            self.rx_en.addItem(label, value)
        rx_apply = QPushButton("设置 RX")
        rx_apply.clicked.connect(lambda: self._apply_en("RX"))
        row.addWidget(QLabel("TX 阵列"))
        row.addWidget(self.tx_en)
        row.addWidget(tx_apply)
        row.addSpacing(16)
        row.addWidget(QLabel("RX 阵列"))
        row.addWidget(self.rx_en)
        row.addWidget(rx_apply)
        row.addStretch()
        return group

    def _create_beam_group(self) -> QGroupBox:
        """创建 0x14 波束控件。"""
        group = QGroupBox("0x14 波束配置 (Raw 码 0~4095)")
        grid = QGridLayout(group)
        grid.addWidget(QLabel("目标"), 0, 0)
        self.beam_tx_check = QCheckBox("TX (bit0)")
        self.beam_rx_check = QCheckBox("RX (bit1)")
        grid.addWidget(self.beam_tx_check, 0, 1)
        grid.addWidget(self.beam_rx_check, 0, 2)

        grid.addWidget(QLabel("TX BeamH"), 1, 0)
        self.tx_beam_h = self._int_spin(0, 0, protocol.BEAM_CODE_MAX)
        grid.addWidget(self.tx_beam_h, 1, 1)
        grid.addWidget(QLabel("TX BeamV"), 1, 2)
        self.tx_beam_v = self._int_spin(0, 0, protocol.BEAM_CODE_MAX)
        grid.addWidget(self.tx_beam_v, 1, 3)

        grid.addWidget(QLabel("RX BeamH"), 2, 0)
        self.rx_beam_h = self._int_spin(0, 0, protocol.BEAM_CODE_MAX)
        grid.addWidget(self.rx_beam_h, 2, 1)
        grid.addWidget(QLabel("RX BeamV"), 2, 2)
        self.rx_beam_v = self._int_spin(0, 0, protocol.BEAM_CODE_MAX)
        grid.addWidget(self.rx_beam_v, 2, 3)

        apply = QPushButton("设置波束")
        apply.clicked.connect(self._apply_beam)
        grid.addWidget(apply, 0, 4, 3, 1)
        return group

    def _create_extref_report_group(self) -> QGroupBox:
        """创建 0x15/0x20 外参与上报频率控件。"""
        group = QGroupBox("0x15 外参 / 0x20 主动上报频率")
        row = QHBoxLayout(group)
        row.addWidget(QLabel("外参时钟"))
        self.ext_ref = QComboBox()
        for label, value in EXT_REF_OPTIONS:
            self.ext_ref.addItem(label, value)
        row.addWidget(self.ext_ref)
        ext_apply = QPushButton("设置")
        ext_apply.clicked.connect(self._apply_ext_ref)
        row.addWidget(ext_apply)
        row.addSpacing(16)
        row.addWidget(QLabel("上报频率 (Hz，0=关闭)"))
        self.report_hz = self._int_spin(50, 0, 200)
        row.addWidget(self.report_hz)
        report_apply = QPushButton("设置")
        report_apply.clicked.connect(self._apply_report_hz)
        row.addWidget(report_apply)
        row.addStretch()
        return group

    def _create_status_group(self) -> QGroupBox:
        """创建 0x30 状态上报显示表格。"""
        group = QGroupBox("0x30 状态上报 (10 Hz 刷新)")
        layout = QVBoxLayout(group)
        self.status_meta = QLabel("上次上报: -- | 距离上次: --")
        layout.addWidget(self.status_meta)
        self.status_table = QTableWidget(len(STATUS_REPORT_ROWS), 2)
        self.status_table.setHorizontalHeaderLabels(["字段", "值"])
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.status_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.status_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for row, (key, label) in enumerate(STATUS_REPORT_ROWS):
            self._row_index[key] = row
            self.status_table.setItem(row, 0, QTableWidgetItem(label))
            self.status_table.setItem(row, 1, QTableWidgetItem("--"))
        layout.addWidget(self.status_table)
        return group

    def _create_log_group(self) -> QGroupBox:
        """创建仅显示当前页面 Driver 日志的控件。"""
        group = QGroupBox("日志")
        layout = QVBoxLayout(group)
        self.log_text = QPlainTextEdit()
        self.log_text.setMaximumHeight(120)
        self.log_text.setReadOnly(True)
        clear = QPushButton("清除")
        clear.clicked.connect(self.log_text.clear)
        layout.addWidget(self.log_text)
        layout.addWidget(clear)
        return group

    @staticmethod
    def _int_spin(value: int, minimum: int, maximum: int) -> QSpinBox:
        """创建统一范围和初始值的整数输入框。

        Args:
            value: 初始值。
            minimum: 最小允许值。
            maximum: 最大允许值。

        Returns:
            已配置完成的 Qt 整数输入框。
        """
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        return widget

    def _parse_lo(self, edit: QLineEdit, *, label: str) -> int:
        """解析 LO 输入：空串=0/AUTO；否则必须是协议偶数 MHz。

        Args:
            edit: QLineEdit 输入框。
            label: 错误信息前缀，例如 ``"RX LO"``。

        Returns:
            解析后的 LO 频率（0 表示 AUTO）。

        Raises:
            ValueError: 非数字或非偶数 MHz。
        """
        text = edit.text().strip()
        if not text:
            return 0
        try:
            value = int(text)
        except ValueError as exc:
            raise ValueError(f"{label} 必须是整数 MHz 或留空") from exc
        if value < 0 or value > 0xFFFF:
            raise ValueError(f"{label} 越界")
        if value != 0 and value % 2 != 0:
            raise ValueError(f"{label} 手动值必须为偶数 MHz")
        return value

    @Slot(str, int)
    def _connect_device(self, port_name: str, baudrate: int) -> None:
        """按用户选择创建并启动新的串口 Driver。"""
        if self._shutdown:
            self.connection.set_disconnected("页面已停止")
            return
        if not self._stop_driver():
            return
        self.connection.set_connecting()
        self._connection_generation += 1
        generation = self._connection_generation
        driver = self._driver_factory(port_name, baudrate)
        self._driver = driver
        driver.log_signal.connect(
            lambda message, current=driver, token=generation: self._on_driver_log(
                current, token, message
            )
        )
        driver.status_signal.connect(
            lambda status, current=driver, token=generation: self._on_driver_status(
                current, token, status
            )
        )
        driver.report_rate_signal.connect(
            lambda rate, current=driver, token=generation: self._on_driver_report_rate(
                current, token, rate
            )
        )
        driver.result_signal.connect(
            lambda command, name, current=driver, token=generation: self._on_driver_result(
                current, token, command, name
            )
        )
        driver.opened_signal.connect(
            lambda success, message, current=driver, token=generation: self._on_driver_opened(
                current, token, success, message
            )
        )
        driver.frame_signal.connect(self.frame_signal.emit)
        driver.finished.connect(lambda current=driver: self._on_driver_finished(current))
        driver.start()

    def _is_current(self, driver: KaRfUnitDriver, generation: int) -> bool:
        """判断异步信号是否仍属于当前串口连接代际。"""
        return driver is self._driver and generation == self._connection_generation

    def _on_driver_opened(
        self, driver: KaRfUnitDriver, generation: int, success: bool, message: str
    ) -> None:
        """处理当前 Driver 的串口打开结果。"""
        if not self._is_current(driver, generation):
            return
        if success:
            self.connection.set_connected(message)
            self._latest_status = None
            self._last_status_time = 0.0
            self.report_rate_label.setText("0x30 上报频率: 等待数据")
            self.report_rate_label.setStyleSheet("color:#666;")
        else:
            self.connection.set_disconnected(message)

    def _on_driver_log(
        self, driver: KaRfUnitDriver, generation: int, message: str
    ) -> None:
        """将当前连接的 Driver 日志追加到日志栏。"""
        if self._is_current(driver, generation):
            self.log_text.appendPlainText(message)

    def _on_driver_status(
        self, driver: KaRfUnitDriver, generation: int, status: Dict[str, object]
    ) -> None:
        """缓存当前连接返回的 STATUS_REPORT 字段，等待 UI 定时器刷新。"""
        if self._is_current(driver, generation):
            self._latest_status = status
            self._last_status_time = time.monotonic()

    def _on_driver_report_rate(
        self, driver: KaRfUnitDriver, generation: int, rate: float
    ) -> None:
        """显示当前连接的 0x30 上报频率并按正常范围设色。"""
        if self._is_current(driver, generation):
            self.report_rate_label.setText(f"0x30 上报频率: {rate:.1f} Hz")
            color = "#198754" if 95.0 <= rate <= 105.0 else "#d97706"
            self.report_rate_label.setStyleSheet(f"color:{color}; font-weight:bold;")

    def _on_driver_result(
        self,
        driver: KaRfUnitDriver,
        generation: int,
        command: int,
        name: str,
    ) -> None:
        """在日志栏打印当前连接的命令响应结果。"""
        if self._is_current(driver, generation):
            self.log_text.appendPlainText(f"<< 响应 0x{command:02X} {name}")

    def _on_driver_finished(self, driver: KaRfUnitDriver) -> None:
        """Driver 线程结束后清理当前引用和 Qt 对象。"""
        if driver is self._driver:
            self._driver = None
            self.connection.set_disconnected("串口已关闭")
            self._latest_status = None
            self._last_status_time = 0.0
        driver.deleteLater()

    @Slot()
    def _disconnect_device(self) -> bool:
        """响应连接控件的断开请求并更新连接栏状态。"""
        stopped = self._stop_driver()
        if stopped:
            self.connection.set_disconnected()
        return stopped

    @Slot()
    def disconnect_device(self) -> bool:
        """断开串口；页面定时器由 workspace 的 activate/deactivate 管理。"""
        return self._disconnect_device()

    def _stop_driver(self) -> bool:
        """停止并释放当前 Driver，停止超时时保留对象供操作员重试。"""
        driver = self._driver
        self._connection_generation += 1
        if driver is not None:
            self.connection.set_stopping()
            if driver.stop() is False:
                self.connection.set_stop_failed("串口线程停止超时，请重试关闭")
                return False
            self._driver = None
            driver.deleteLater()
        return True

    def _active_driver(self) -> Optional[KaRfUnitDriver]:
        """取得可发送命令的当前 Driver；未连接时显示提示。"""
        if self._driver is None or not self._driver.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return None
        return self._driver

    def _safe_send(self, action: Callable[[KaRfUnitDriver], bool]) -> None:
        """在 Driver 已运行时执行语义发送，并向操作员显示参数错误。"""
        driver = self._active_driver()
        if driver is None:
            return
        try:
            action(driver)
        except (ValueError, UnicodeEncodeError) as exc:
            QMessageBox.warning(self, "参数错误", str(exc))

    @Slot()
    def _apply_freq(self) -> None:
        """读取页面输入并发送 0x10 频点与极化配置。"""

        def action(driver: KaRfUnitDriver) -> bool:
            """在 Driver 上发送 0x10 频点与极化配置。"""
            rx_lo = self._parse_lo(self.rx_lo, "RX LO")
            tx_lo = self._parse_lo(self.tx_lo, "TX LO")
            return driver.set_conv_freq(
                self.rx_rf.value(),
                rx_lo,
                self.tx_rf.value(),
                tx_lo,
                int(self.rx_polar.currentData()),
                int(self.tx_polar.currentData()),
            )

        self._safe_send(action)

    @Slot()
    def _apply_att(self) -> None:
        """读取页面输入并发送 0x11 变频衰减。"""

        def action(driver: KaRfUnitDriver) -> bool:
            """在 Driver 上发送 0x11 衰减。"""
            return driver.set_conv_att(self.rx_att.value(), self.tx_att.value())

        self._safe_send(action)

    @Slot()
    def _apply_en(self, target: str) -> None:
        """发送 0x12 或 0x13 阵列使能命令。

        Args:
            target: ``"TX"`` 或 ``"RX"``。
        """
        combo = self.tx_en if target == "TX" else self.rx_en
        value = bool(combo.currentData())

        def action(driver: KaRfUnitDriver) -> bool:
            """在 Driver 上发送对应阵列的使能命令。"""
            if target == "TX":
                return driver.set_tx_enabled(value)
            return driver.set_rx_enabled(value)

        self._safe_send(action)

    @Slot()
    def _apply_beam(self) -> None:
        """按勾选的目标位和当前 BeamH/V 发送 0x14 波束命令。"""

        def action(driver: KaRfUnitDriver) -> bool:
            """在 Driver 上发送 0x14 波束配置。"""
            mask = (
                (protocol.BEAM_TARGET_TX if self.beam_tx_check.isChecked() else 0)
                | (protocol.BEAM_TARGET_RX if self.beam_rx_check.isChecked() else 0)
            )
            return driver.set_beam(
                mask,
                self.tx_beam_h.value(),
                self.tx_beam_v.value(),
                self.rx_beam_h.value(),
                self.rx_beam_v.value(),
            )

        self._safe_send(action)

    @Slot()
    def _apply_ext_ref(self) -> None:
        """发送 0x15 外参时钟配置。"""

        def action(driver: KaRfUnitDriver) -> bool:
            """在 Driver 上发送 0x15 外参。"""
            return driver.set_ext_ref(int(self.ext_ref.currentData()))

        self._safe_send(action)

    @Slot()
    def _apply_report_hz(self) -> None:
        """发送 0x20 主动上报频率配置。"""

        def action(driver: KaRfUnitDriver) -> bool:
            """在 Driver 上发送 0x20 上报频率。"""
            return driver.set_report_hz(self.report_hz.value())

        self._safe_send(action)

    def _format_status_value(self, key: str, value: object) -> str:
        """将 STATUS_REPORT 字段值格式化为客户可读文本。

        Args:
            key: 字段名。
            value: 原始字段值。

        Returns:
            适合直接显示到状态表第二列的文本。
        """
        if key in ("conv_temp_x10", "tx_array_temp_x10", "rx_array_temp_x10"):
            return f"{int(value) / 10.0:.1f} °C"
        if key == "conv_lock_mask":
            mask = int(value)
            lock = protocol.decode_lock_mask(mask)
            ref = "V" if lock.ref_valid else "I"
            rx = "L" if lock.rx_lo_lock else "U"
            tx = "L" if lock.tx_lo_lock else "U"
            return f"0x{mask:04X} REF={ref} RX_LO={rx} TX_LO={tx}"
        if key == "unit_sw":
            major = (int(value) >> 8) & 0xFF
            minor = int(value) & 0xFF
            return f"V{major}.{minor} (0x{int(value) & 0xFFFF:04X})"
        if key in ("rx_polar", "tx_polar"):
            return _polar_text(int(value))
        if key in ("pa_enable", "tx_enable", "rx_enable"):
            return "开启" if int(value) else "关闭"
        if key in ("rx_conv_att_x10", "tx_conv_att_x10"):
            return f"{int(value) / 10.0:.1f} dB"
        return str(value)

    def _refresh_status_table(self) -> None:
        """在 10 Hz 定时器中刷新状态表格，并在 1 s 内无 STATUS_REPORT 时显示超时。"""
        if self._last_status_time:
            elapsed = time.monotonic() - self._last_status_time
            if elapsed > REPORT_TIMEOUT_S:
                self.report_rate_label.setText("0x30 上报频率: 0.0 Hz（超时）")
                self.report_rate_label.setStyleSheet(
                    "color:#c62828; font-weight:bold;"
                )
            self.status_meta.setText(
                f"上次上报: {self._last_status_time:.3f} | 距离上次: {elapsed:.3f}s"
            )
        else:
            self.status_meta.setText("上次上报: -- | 距离上次: --")

        status = self._latest_status
        if not status:
            return
        for key, row in self._row_index.items():
            if key not in status:
                continue
            self.status_table.item(row, 1).setText(
                self._format_status_value(key, status[key])
            )

    def activate(self) -> None:
        """工作区进入前台时恢复端口扫描与状态刷新定时器。"""
        if self._shutdown:
            return
        timer = getattr(self.connection, "_timer", None)
        if timer is not None and not timer.isActive():
            timer.start(2000)
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(REFRESH_INTERVAL_MS)

    def deactivate(self) -> bool:
        """断开串口并暂停隐藏页面的定时器。"""
        stopped = self.disconnect_device()
        if stopped:
            self._refresh_timer.stop()
            timer = getattr(self.connection, "_timer", None)
            if timer is not None:
                timer.stop()
        return stopped

    def shutdown(self) -> bool:
        """停止本页面后台活动；允许主窗口和 closeEvent 重复调用。"""
        if self._shutdown:
            return True
        if not self._stop_driver():
            return False
        self.connection.set_disconnected()
        self._refresh_timer.stop()
        timer = getattr(self.connection, "_timer", None)
        if timer is not None:
            timer.stop()
        self._shutdown = True
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """关闭窗口前确认后台串口线程已停止；停止失败时阻止 Qt 关闭。

        Args:
            event: Qt 关闭事件；停止失败时会被忽略以允许用户重试。
        """
        if not self.shutdown():
            event.ignore()
            return
        super().closeEvent(event)


DevicePanel = KaRfUnitPanel