"""KA_RF_UNIT 设备页面。"""

from __future__ import annotations

import time
from typing import Callable, Dict, Optional, Tuple

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
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
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
        self._row_index: Dict[str, Tuple[int, int]] = {}

        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setMinimumWidth(1180)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """组装紧凑的串口、命令、状态、扫描和日志区域。

        设备型号已由工作区顶部下拉框呈现，因此不重复占用标题行。命令区左列为
        频点与常用控制，右列为波束与扫描；0x30 以三组字段/值并列显示。
        """
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)

        outer.addWidget(self._create_serial_group())

        # 命令区：左右两列；左侧两组固定紧凑，右侧波束和扫描保持同宽网格。
        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(6)
        left_col = QWidget()
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addWidget(self._create_freq_group())
        left_layout.addWidget(self._create_common_control_group())
        left_layout.addStretch()
        right_col = QWidget()
        right_layout = QVBoxLayout(right_col)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addWidget(self._create_beam_group())
        right_layout.addWidget(self._create_scan_group())
        right_layout.addStretch()
        columns.addWidget(left_col, 1)
        columns.addWidget(right_col, 1)
        outer.addLayout(columns)

        outer.addWidget(self._create_status_group())
        outer.addWidget(self._create_log_group())
        outer.addStretch()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_status_table)

        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.timeout.connect(self._scan_tick)
        self._scan_state = "IDLE"  # IDLE / RUNNING / PAUSED / FINISHED
        self._scan_total = 0
        self._scan_index = 0
        self._scan_current_theta = 0.0
        self._scan_current_phi = 0.0
        self._scan_skipped = 0

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
        """创建 0x10 频点与极化控件（2 行：RX 一行，TX 一行；右侧"设置"按钮独占列）。"""
        group = QGroupBox("0x10 频点与极化配置")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setContentsMargins(8, 8, 8, 8)
        # 公共：标签 / RF / 标签 / LO / 标签 / 极化 / 占位 / 设置
        for col in (0, 2, 4):
            grid.setColumnStretch(col, 0)
        for col in (1, 3, 5):
            grid.setColumnStretch(col, 1)
        # RX 行
        grid.addWidget(self._field_label("RX RF (MHz)"), 0, 0)
        self.rx_rf = self._int_spin(19966, 17700, 21200)
        self.rx_rf.setMaximumWidth(96)
        grid.addWidget(self.rx_rf, 0, 1)
        grid.addWidget(self._field_label("RX LO"), 0, 2)
        self.rx_lo = QLineEdit()
        self.rx_lo.setPlaceholderText("AUTO")
        self.rx_lo.setMaximumWidth(80)
        grid.addWidget(self.rx_lo, 0, 3)
        grid.addWidget(self._field_label("RX 极化"), 0, 4)
        self.rx_polar = QComboBox()
        for label, value in POLAR_OPTIONS:
            self.rx_polar.addItem(label, value)
        self.rx_polar.setMaximumWidth(96)
        grid.addWidget(self.rx_polar, 0, 5)
        # TX 行
        grid.addWidget(self._field_label("TX RF (MHz)"), 1, 0)
        self.tx_rf = self._int_spin(29500, 27500, 31000)
        self.tx_rf.setMaximumWidth(96)
        grid.addWidget(self.tx_rf, 1, 1)
        grid.addWidget(self._field_label("TX LO"), 1, 2)
        self.tx_lo = QLineEdit()
        self.tx_lo.setPlaceholderText("AUTO")
        self.tx_lo.setMaximumWidth(80)
        grid.addWidget(self.tx_lo, 1, 3)
        grid.addWidget(self._field_label("TX 极化"), 1, 4)
        self.tx_polar = QComboBox()
        for label, value in POLAR_OPTIONS:
            self.tx_polar.addItem(label, value)
        self.tx_polar.setMaximumWidth(96)
        grid.addWidget(self.tx_polar, 1, 5)
        # 右侧"设置"按钮独占 2 行
        apply = QPushButton("设置")
        apply.clicked.connect(self._apply_freq)
        apply.setMinimumWidth(72)
        grid.addWidget(apply, 0, 7, 2, 1)
        # 列 6 作为中间留白列
        grid.setColumnStretch(6, 1)
        return group

    def _create_common_control_group(self) -> QGroupBox:
        """创建衰减、阵列使能、外参与上报频率的三行紧凑控制区。"""
        group = QGroupBox("0x11 / 0x12 / 0x13 / 0x15 / 0x20 常用控制")
        grid = QGridLayout(group)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        # 第 0 行：0x11 变频衰减
        grid.addWidget(self._field_label("RX 衰减(dB)"), 0, 0)
        self.rx_att = QDoubleSpinBox()
        self.rx_att.setRange(0.0, 31.5)
        self.rx_att.setDecimals(1)
        self.rx_att.setSingleStep(0.5)
        self.rx_att.setValue(0.0)
        self.rx_att.setMaximumWidth(96)
        grid.addWidget(self.rx_att, 0, 1)
        grid.addWidget(self._field_label("TX 衰减(dB)"), 0, 2)
        self.tx_att = QDoubleSpinBox()
        self.tx_att.setRange(0.0, 31.5)
        self.tx_att.setDecimals(1)
        self.tx_att.setSingleStep(0.5)
        self.tx_att.setValue(0.0)
        self.tx_att.setMaximumWidth(96)
        grid.addWidget(self.tx_att, 0, 3)
        att_apply = QPushButton("设置衰减")
        att_apply.setMinimumWidth(80)
        att_apply.clicked.connect(self._apply_att)
        grid.addWidget(att_apply, 0, 4)

        # 第 1 行：0x12/0x13 阵列使能
        grid.addWidget(self._field_label("TX 阵列"), 1, 0)
        self.tx_en = QComboBox()
        for label, value in ENABLE_OPTIONS:
            self.tx_en.addItem(label, value)
        self.tx_en.setMaximumWidth(80)
        grid.addWidget(self.tx_en, 1, 1)
        tx_apply = QPushButton("设置 TX")
        tx_apply.setMinimumWidth(80)
        tx_apply.clicked.connect(lambda: self._apply_en("TX"))
        grid.addWidget(tx_apply, 1, 2)
        grid.addWidget(self._field_label("RX 阵列"), 1, 3)
        self.rx_en = QComboBox()
        for label, value in ENABLE_OPTIONS:
            self.rx_en.addItem(label, value)
        self.rx_en.setMaximumWidth(80)
        grid.addWidget(self.rx_en, 1, 4)
        rx_apply = QPushButton("设置 RX")
        rx_apply.setMinimumWidth(80)
        rx_apply.clicked.connect(lambda: self._apply_en("RX"))
        grid.addWidget(rx_apply, 1, 5)

        # 第 2 行：0x15 外参 / 0x20 主动上报频率
        grid.addWidget(self._field_label("外参"), 2, 0)
        self.ext_ref = QComboBox()
        for label, value in EXT_REF_OPTIONS:
            self.ext_ref.addItem(label, value)
        self.ext_ref.setMaximumWidth(96)
        grid.addWidget(self.ext_ref, 2, 1)
        ext_apply = QPushButton("设置外参")
        ext_apply.setMinimumWidth(80)
        ext_apply.clicked.connect(self._apply_ext_ref)
        grid.addWidget(ext_apply, 2, 2)
        grid.addWidget(self._field_label("上报(Hz, 0=关)"), 2, 3)
        self.report_hz = self._int_spin(50, 0, 200)
        self.report_hz.setMaximumWidth(80)
        grid.addWidget(self.report_hz, 2, 4)
        report_apply = QPushButton("设置上报")
        report_apply.setMinimumWidth(80)
        report_apply.clicked.connect(self._apply_report_hz)
        grid.addWidget(report_apply, 2, 5)

        for col in (1, 4):
            grid.setColumnStretch(col, 1)
        return group

    def _create_beam_group(self) -> QGroupBox:
        """创建 0x14 波束控件（目标一行 + BeamH 一行 + BeamV 一行 + 设置按钮独占列）。"""
        group = QGroupBox("0x14 波束配置 (Raw 码 0~4095)")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setContentsMargins(8, 8, 8, 8)
        # 列：标签 / TX / 标签 / RX / 占位 / 设置按钮
        for col in (0, 2):
            grid.setColumnStretch(col, 0)
        for col in (1, 3):
            grid.setColumnStretch(col, 1)
        # 第 0 行：目标 / TX(bit0) / RX(bit1)
        grid.addWidget(self._field_label("目标"), 0, 0)
        self.beam_tx_check = QCheckBox("TX (bit0)")
        self.beam_rx_check = QCheckBox("RX (bit1)")
        target_row = QHBoxLayout()
        target_row.setContentsMargins(0, 0, 0, 0)
        target_row.setSpacing(12)
        target_row.addWidget(self.beam_tx_check)
        target_row.addWidget(self.beam_rx_check)
        target_row.addStretch()
        target_widget = QWidget()
        target_widget.setLayout(target_row)
        grid.addWidget(target_widget, 0, 1, 1, 3)
        # 第 1 行：TX BeamH / RX BeamH
        self.tx_beam_h = self._int_spin(0, 0, protocol.BEAM_CODE_MAX)
        self.tx_beam_h.setMaximumWidth(80)
        self.rx_beam_h = self._int_spin(0, 0, protocol.BEAM_CODE_MAX)
        self.rx_beam_h.setMaximumWidth(80)
        grid.addWidget(self._field_label("TX BeamH"), 1, 0)
        grid.addWidget(self.tx_beam_h, 1, 1)
        grid.addWidget(self._field_label("RX BeamH"), 1, 2)
        grid.addWidget(self.rx_beam_h, 1, 3)
        # 第 2 行：TX BeamV / RX BeamV
        self.tx_beam_v = self._int_spin(0, 0, protocol.BEAM_CODE_MAX)
        self.tx_beam_v.setMaximumWidth(80)
        self.rx_beam_v = self._int_spin(0, 0, protocol.BEAM_CODE_MAX)
        self.rx_beam_v.setMaximumWidth(80)
        grid.addWidget(self._field_label("TX BeamV"), 2, 0)
        grid.addWidget(self.tx_beam_v, 2, 1)
        grid.addWidget(self._field_label("RX BeamV"), 2, 2)
        grid.addWidget(self.rx_beam_v, 2, 3)
        # 右侧"设置波束"按钮跨 3 行
        apply = QPushButton("设置波束")
        apply.setMinimumWidth(96)
        apply.clicked.connect(self._apply_beam)
        grid.addWidget(apply, 0, 5, 3, 1)
        grid.setColumnStretch(4, 1)
        return group

    def _create_status_group(self) -> QGroupBox:
        """创建 0x30 状态表：字段/值 × 3 块，23 项在 8 行内规整显示。"""
        group = QGroupBox("0x30 状态上报 (10 Hz 刷新)")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        self.status_meta = QLabel("上次上报: -- | 距离上次: --")
        layout.addWidget(self.status_meta)
        rows_total = len(STATUS_REPORT_ROWS)
        status_blocks = 3
        self._status_layout_columns = (rows_total + status_blocks - 1) // status_blocks  # 8
        self.status_table = QTableWidget(self._status_layout_columns, status_blocks * 2)
        self.status_table.setHorizontalHeaderLabels(["字段", "值"] * status_blocks)
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.status_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.status_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.status_table.horizontalHeader().setFixedHeight(22)
        self.status_table.verticalHeader().setDefaultSectionSize(22)
        for col in range(0, status_blocks * 2, 2):
            self.status_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        for col in range(1, status_blocks * 2, 2):
            self.status_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Stretch)
        for index, (key, label) in enumerate(STATUS_REPORT_ROWS):
            row = index % self._status_layout_columns
            label_col = (index // self._status_layout_columns) * 2
            self._row_index[key] = (row, label_col + 1)
            self.status_table.setItem(row, label_col, QTableWidgetItem(label))
            self.status_table.setItem(row, label_col + 1, QTableWidgetItem("--"))
        self.status_table.setFixedHeight(22 + self._status_layout_columns * 22 + 2)
        layout.addWidget(self.status_table)
        return group

    def _create_scan_group(self) -> QGroupBox:
        """创建波束扫描控件：6 列网格 + 单行按钮 + 状态。"""
        group = QGroupBox("波束扫描 (θ 离轴 0~90°，φ 方位 0~360°)")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        def _spin(min_val, max_val, value, step, decimals=1, max_width=80):
            """扫描组用紧凑浮点输入框。"""
            sb = QDoubleSpinBox()
            sb.setRange(min_val, max_val)
            sb.setDecimals(decimals)
            sb.setSingleStep(step)
            sb.setValue(value)
            sb.setMaximumWidth(max_width)
            return sb

        def _intspin(min_val, max_val, value, step=1, max_width=80):
            """扫描组用紧凑整数输入框。"""
            sb = QSpinBox()
            sb.setRange(min_val, max_val)
            sb.setValue(value)
            sb.setSingleStep(step)
            sb.setMaximumWidth(max_width)
            return sb

        # 第 0 行：θ 起始 / 终止 / 步进
        grid.addWidget(self._field_label("θ 起"), 0, 0)
        self.scan_theta_start = _spin(0.0, 90.0, 0.0, 0.5)
        grid.addWidget(self.scan_theta_start, 0, 1)
        grid.addWidget(self._field_label("θ 止"), 0, 2)
        self.scan_theta_end = _spin(0.0, 90.0, 30.0, 0.5)
        grid.addWidget(self.scan_theta_end, 0, 3)
        grid.addWidget(self._field_label("θ 步"), 0, 4)
        self.scan_theta_step = _spin(0.1, 90.0, 5.0, 0.1)
        grid.addWidget(self.scan_theta_step, 0, 5)
        # 第 1 行：φ 起始 / 终止 / 步进
        grid.addWidget(self._field_label("φ 起"), 1, 0)
        self.scan_phi_start = _spin(0.0, 360.0, 0.0, 1.0)
        grid.addWidget(self.scan_phi_start, 1, 1)
        grid.addWidget(self._field_label("φ 止"), 1, 2)
        self.scan_phi_end = _spin(0.0, 360.0, 90.0, 1.0)
        grid.addWidget(self.scan_phi_end, 1, 3)
        grid.addWidget(self._field_label("φ 步"), 1, 4)
        self.scan_phi_step = _spin(0.1, 360.0, 10.0, 0.1)
        grid.addWidget(self.scan_phi_step, 1, 5)
        # 第 2 行：间隔 / 频点来源
        grid.addWidget(self._field_label("间隔 (ms)"), 2, 0)
        self.scan_interval_ms = _intspin(1, 60000, 200, 50)
        grid.addWidget(self.scan_interval_ms, 2, 1)
        grid.addWidget(self._field_label("频点"), 2, 2)
        self.scan_freq_source = QComboBox()
        self.scan_freq_source.addItem("STATUS", "auto")
        self.scan_freq_source.addItem("手动", "manual")
        grid.addWidget(self.scan_freq_source, 2, 3)
        # 第 3 行：手动 TX / RX 频点
        grid.addWidget(self._field_label("TX (MHz)"), 3, 0)
        self.scan_tx_rf = QSpinBox()
        self.scan_tx_rf.setRange(protocol.TX_RF_MIN_MHZ, protocol.TX_RF_MAX_MHZ)
        self.scan_tx_rf.setValue(29500)
        self.scan_tx_rf.setMaximumWidth(96)
        grid.addWidget(self.scan_tx_rf, 3, 1)
        grid.addWidget(self._field_label("RX (MHz)"), 3, 2)
        self.scan_rx_rf = QSpinBox()
        self.scan_rx_rf.setRange(protocol.RX_RF_MIN_MHZ, protocol.RX_RF_MAX_MHZ)
        self.scan_rx_rf.setValue(19966)
        self.scan_rx_rf.setMaximumWidth(96)
        grid.addWidget(self.scan_rx_rf, 3, 3)
        # 频点来源切换控制 (auto/manual) 时启用/禁用手动频点
        self.scan_freq_source.currentIndexChanged.connect(self._on_scan_freq_source_changed)
        self._on_scan_freq_source_changed()

        layout.addLayout(grid)

        # 单行按钮 + 进度 + 状态
        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        self.scan_start_btn = QPushButton("开始")
        self.scan_start_btn.clicked.connect(self._on_scan_start)
        self.scan_pause_btn = QPushButton("暂停")
        self.scan_pause_btn.clicked.connect(self._on_scan_pause)
        self.scan_pause_btn.setEnabled(False)
        self.scan_stop_btn = QPushButton("结束")
        self.scan_stop_btn.clicked.connect(self._on_scan_stop)
        self.scan_stop_btn.setEnabled(False)
        button_row.addWidget(self.scan_start_btn)
        button_row.addWidget(self.scan_pause_btn)
        button_row.addWidget(self.scan_stop_btn)
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 1)
        self.scan_progress.setValue(0)
        self.scan_progress.setMaximumWidth(220)
        button_row.addWidget(self.scan_progress, 1)
        self.scan_status_label = QLabel("拍数 0/0 | 跳过 0 | θ=-- φ=--")
        self.scan_status_label.setMinimumWidth(180)
        button_row.addWidget(self.scan_status_label, 2)
        layout.addLayout(button_row)
        return group

    def _on_scan_freq_source_changed(self) -> None:
        """手动模式时启用 TX/RX 频点输入，自动模式时禁用并清空回退到 STATUS。"""
        manual = self.scan_freq_source.currentData() == "manual"
        self.scan_tx_rf.setEnabled(manual)
        self.scan_rx_rf.setEnabled(manual)

    def _create_log_group(self) -> QGroupBox:
        """创建紧凑的当前页面 Driver 日志控件。"""
        group = QGroupBox("日志")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        self.log_text = QPlainTextEdit()
        self.log_text.setFixedHeight(64)
        self.log_text.setReadOnly(True)
        clear = QPushButton("清除")
        clear.clicked.connect(self.log_text.clear)
        clear.setMinimumWidth(72)
        layout.addWidget(self.log_text, 1)
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

    @staticmethod
    def _field_label(text: str) -> QLabel:
        """生成字段标签，统一最小宽度，避免 GridLayout 拉伸到内容宽度。"""
        label = QLabel(text)
        label.setMinimumWidth(86)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return label

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
            rx_lo = self._parse_lo(self.rx_lo, label="RX LO")
            tx_lo = self._parse_lo(self.tx_lo, label="TX LO")
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
    def _scan_params(self) -> Optional[Dict[str, float]]:
        """读取并校验扫描参数；非法时返回 ``None`` 并提示。"""
        theta_start = self.scan_theta_start.value()
        theta_end = self.scan_theta_end.value()
        theta_step = self.scan_theta_step.value()
        phi_start = self.scan_phi_start.value()
        phi_end = self.scan_phi_end.value()
        phi_step = self.scan_phi_step.value()
        if theta_step <= 0 or phi_step <= 0:
            QMessageBox.warning(self, "参数错误", "θ 与 φ 步进必须 > 0")
            return None
        if not (theta_start <= theta_end):
            QMessageBox.warning(self, "参数错误", "θ 终止必须 ≥ θ 起始")
            return None
        if not (phi_start <= phi_end):
            QMessageBox.warning(self, "参数错误", "φ 终止必须 ≥ φ 起始")
            return None
        return {
            "theta_start": theta_start,
            "theta_end": theta_end,
            "theta_step": theta_step,
            "phi_start": phi_start,
            "phi_end": phi_end,
            "phi_step": phi_step,
            "interval_ms": max(1, int(self.scan_interval_ms.value())),
        }

    def _scan_count(self, params: Dict[str, float]) -> int:
        """按起止与步进计算总拍数（θ 外层、φ 内层）。"""
        theta_n = int(round((params["theta_end"] - params["theta_start"]) / params["theta_step"])) + 1
        phi_n = int(round((params["phi_end"] - params["phi_start"]) / params["phi_step"])) + 1
        return max(1, theta_n) * max(1, phi_n)

    def _scan_iter_pairs(self, params: Dict[str, float]):
        """生成 (θ, φ) 扫描序列；θ 外层、φ 内层。"""
        theta = params["theta_start"]
        step_t = params["theta_step"]
        step_p = params["phi_step"]
        while theta <= params["theta_end"] + 1e-9:
            phi = params["phi_start"]
            while phi <= params["phi_end"] + 1e-9:
                yield round(theta, 4), round(phi, 4)
                phi += step_p
            theta += step_t

    def _scan_resolve_freq(self, target_mask: int) -> Tuple[Optional[float], Optional[float], str]:
        """根据频点来源解析本次扫描使用的 TX/RX RF。

        Returns:
            (tx_rf, rx_rf, error_message)；未选阵面的频率为 ``None``，失败时 error_message 非空。
        """
        source = self.scan_freq_source.currentData()
        if source == "manual":
            tx_rf = float(self.scan_tx_rf.value()) if target_mask & protocol.BEAM_TARGET_TX else None
            rx_rf = float(self.scan_rx_rf.value()) if target_mask & protocol.BEAM_TARGET_RX else None
            if tx_rf is not None and not protocol.tx_rf_valid(int(tx_rf)):
                return None, None, "手动 TX 频率超出协议范围"
            if rx_rf is not None and not protocol.rx_rf_valid(int(rx_rf)):
                return None, None, "手动 RX 频率超出协议范围"
            return tx_rf, rx_rf, ""
        if self._last_status_time == 0.0 or time.monotonic() - self._last_status_time > REPORT_TIMEOUT_S:
            return None, None, "STATUS_REPORT 已超时，无法读取当前 RF"
        status = self._latest_status or {}
        tx_rf = float(status.get("tx_rf_mhz") or 0) if target_mask & protocol.BEAM_TARGET_TX else None
        rx_rf = float(status.get("rx_rf_mhz") or 0) if target_mask & protocol.BEAM_TARGET_RX else None
        if tx_rf is not None and not protocol.tx_rf_valid(int(tx_rf)):
            return None, None, "STATUS_REPORT 的 TX RF 超出协议范围"
        if rx_rf is not None and not protocol.rx_rf_valid(int(rx_rf)):
            return None, None, "STATUS_REPORT 的 RX RF 超出协议范围"
        return tx_rf, rx_rf, ""

    def _scan_target_mask(self) -> int:
        """根据现有勾选框计算 0x14 目标掩码。"""
        mask = 0
        if self.beam_tx_check.isChecked():
            mask |= protocol.BEAM_TARGET_TX
        if self.beam_rx_check.isChecked():
            mask |= protocol.BEAM_TARGET_RX
        return mask

    @Slot()
    def _on_scan_start(self) -> None:
        """开始波束扫描。"""
        if self._scan_state == "RUNNING":
            return
        if self._shutdown:
            return
        params = self._scan_params()
        if params is None:
            return
        mask = self._scan_target_mask()
        if mask == 0:
            QMessageBox.warning(self, "参数错误", "请至少勾选 TX 或 RX 目标")
            return
        tx_rf, rx_rf, err = self._scan_resolve_freq(mask)
        if err:
            QMessageBox.warning(self, "参数错误", err or "无法解析扫描频点")
            return

        self._scan_pairs = list(self._scan_iter_pairs(params))
        self._scan_total = len(self._scan_pairs)
        self._scan_index = 0
        self._scan_skipped = 0
        self._scan_tx_rf = tx_rf
        self._scan_rx_rf = rx_rf
        self._scan_mask = mask
        self._scan_params_snapshot = params
        self._scan_state = "RUNNING"
        self.scan_progress.setRange(0, self._scan_total)
        self.scan_progress.setValue(0)
        self._scan_update_status_label()
        self.scan_start_btn.setEnabled(False)
        self.scan_pause_btn.setEnabled(True)
        self.scan_pause_btn.setText("暂停")
        self.scan_stop_btn.setEnabled(True)
        self._scan_schedule_next()

    @Slot()
    def _on_scan_pause(self) -> None:
        """暂停或继续扫描。"""
        if self._scan_state == "RUNNING":
            self._scan_state = "PAUSED"
            self._scan_timer.stop()
            self.scan_pause_btn.setText("继续")
            self._scan_update_status_label()
        elif self._scan_state == "PAUSED":
            self._scan_state = "RUNNING"
            self.scan_pause_btn.setText("暂停")
            self._scan_update_status_label()
            self._scan_schedule_next()

    @Slot()
    def _on_scan_stop(self) -> None:
        """用户主动结束扫描：停止 timer、把指针拉满并复位按钮。"""
        self._scan_timer.stop()
        self._scan_index = self._scan_total
        self.scan_progress.setValue(self._scan_total)
        self._scan_reset_to_idle()

    def _scan_reset_to_idle(self) -> None:
        """把扫描状态重置为 IDLE 并复位按钮（自然完成也复用此状态）。"""
        self._scan_state = "IDLE"
        self.scan_start_btn.setEnabled(True)
        self.scan_pause_btn.setEnabled(False)
        self.scan_pause_btn.setText("暂停")
        self.scan_stop_btn.setEnabled(False)
        self._scan_update_status_label()

    def _reset_scan_controls(self) -> None:
        """兼容旧名；新代码请用 :meth:`_scan_reset_to_idle`。"""
        self._scan_reset_to_idle()

    def _scan_schedule_next(self) -> None:
        """调度下一拍扫描；达到末尾则切到 FINISHED（不重置为 IDLE）。"""
        if self._scan_state != "RUNNING":
            return
        if self._scan_index >= self._scan_total:
            self._scan_state = "FINISHED"
            self.scan_start_btn.setEnabled(True)
            self.scan_pause_btn.setEnabled(False)
            self.scan_pause_btn.setText("暂停")
            self.scan_stop_btn.setEnabled(False)
            self._scan_update_status_label()
            return
        self._scan_timer.start(max(10, int(self._scan_params_snapshot["interval_ms"])))

    def _scan_tick(self) -> None:
        """执行单拍：发送一次 0x14 并准备下一拍。"""
        if self._scan_state != "RUNNING":
            return
        if self._scan_index >= self._scan_total:
            # 拍数已耗尽，自然完成（与用户主动结束区分）
            self._scan_state = "FINISHED"
            self.scan_start_btn.setEnabled(True)
            self.scan_pause_btn.setEnabled(False)
            self.scan_pause_btn.setText("暂停")
            self.scan_stop_btn.setEnabled(False)
            self._scan_update_status_label()
            return
        theta, phi = self._scan_pairs[self._scan_index]
        self._scan_current_theta = theta
        self._scan_current_phi = phi
        self._scan_index += 1
        self.scan_progress.setValue(self._scan_index)
        ok = self._emit_scan_frame(theta, phi)
        if not ok:
            self._scan_skipped += 1
        self._scan_update_status_label()
        self._scan_schedule_next()

    def _emit_scan_frame(self, theta: float, phi: float) -> bool:
        """通过当前 Driver 发送一次扫描帧；返回是否成功入队。"""
        driver = self._driver
        if driver is None or not driver.running:
            self.log_text.appendPlainText("扫描跳过：串口未连接")
            return False
        try:
            tx_bh = tx_bv = rx_bh = rx_bv = 0
            if self._scan_mask & protocol.BEAM_TARGET_TX:
                tx_bh, tx_bv = protocol.compute_beam_pair(
                    theta, phi, freq_mhz=self._scan_tx_rf, f0=protocol.TX_BEAM_F0
                )
            if self._scan_mask & protocol.BEAM_TARGET_RX:
                rx_bh, rx_bv = protocol.compute_beam_pair(
                    theta, phi, freq_mhz=self._scan_rx_rf, f0=protocol.RX_BEAM_F0
                )
            sent = driver.set_beam(self._scan_mask, tx_bh, tx_bv, rx_bh, rx_bv)
            if not sent:
                self.log_text.appendPlainText("扫描跳过：发送队列拒绝或串口异常")
                return False
            return True
        except ValueError as exc:
            self.log_text.appendPlainText(f"扫描跳过：{exc}")
            return False

    def _scan_update_status_label(self) -> None:
        """把扫描进度与状态写入标签。"""
        theta_text = "--" if self._scan_index == 0 else f"{self._scan_current_theta:.2f}"
        phi_text = "--" if self._scan_index == 0 else f"{self._scan_current_phi:.2f}"
        self.scan_status_label.setText(
            f"拍数 {self._scan_index}/{self._scan_total} | 跳过 {self._scan_skipped} | "
            f"当前 θ={theta_text}° φ={phi_text}° | 状态 {self._scan_state}"
        )

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
        for key, (row, col_value) in self._row_index.items():
            if key not in status:
                continue
            self.status_table.item(row, col_value).setText(
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
        # 隐藏前强制停止波束扫描，避免页面被禁用时仍持续发送。
        self._scan_timer.stop()
        if self._scan_state in ("RUNNING", "PAUSED"):
            self._scan_state = "PAUSED"
            self.scan_pause_btn.setText("继续")
            self._scan_update_status_label()
        stopped = self.disconnect_device()
        if stopped:
            self._refresh_timer.stop()
            timer = getattr(self.connection, "_timer", None)
            if timer is not None:
                timer.stop()
        return stopped

    def shutdown(self) -> bool:
        """停止本页面后台活动；允许主窗口和 closeEvent 重复调用。"""
        self._scan_timer.stop()
        if self._scan_state != "IDLE":
            self._scan_state = "IDLE"
            self._scan_update_status_label()
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
