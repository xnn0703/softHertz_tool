"""KuR512B 设备页面：串口、子阵、波束/极化、相位校准、状态、主动读取、实时曲线与日志。"""

from __future__ import annotations

import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
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
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from soft_hertz_tool.devices.kur512 import protocol
from soft_hertz_tool.devices.kur512.driver import (
    DEFAULT_QUERY_HZ,
    KUR512Driver,
    MAX_QUERY_HZ,
)
from soft_hertz_tool.devices.kur512.models import BeamSetting, ChartWindow, Polarity
from soft_hertz_tool.devices.kur512.widgets import KUR512ChartView
from soft_hertz_tool.identity import default_log_directory
from soft_hertz_tool.shared.ui.serial_connection import SerialConnectionWidget


BAUD_RATES = (9600, 19200, 38400, 115200, 460800, 921600)

STATUS_COLUMNS = (
    "ID",
    "电压(V)",
    "温度(℃)",
    "MCU_VER",
    "最近原始报文",
)


def _format_id(device_id: int) -> str:
    """格式化子阵 ID 显示文本。"""
    return f"0x{int(device_id) & 0xFF:02X}"


class KUR512Panel(QFrame):
    """KuR512B 设备页面；UI 仅采集输入与显示状态，构帧全部走 ``protocol``。"""

    frame_signal = Signal(object)

    REFRESH_INTERVAL_MS = 100

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        driver_factory: Callable[..., KUR512Driver] = KUR512Driver,
    ) -> None:
        """创建 KuR512B Panel；Driver 在连接时延迟创建。"""
        super().__init__(parent)
        self._driver_factory = driver_factory
        self.driver: Optional[KUR512Driver] = None
        self._connection_generation = 0
        self._shutdown = False
        self._polling_active = False

        self._status_rows: dict[int, int] = {}
        self._status_columns = list(STATUS_COLUMNS)
        self._column_index = {name: index for index, name in enumerate(self._status_columns)}

        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self._log_root_path: Optional[Path] = None
        self._setup_ui()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_status_table)
        self._refresh_timer.setInterval(self.REFRESH_INTERVAL_MS)

    def _setup_ui(self) -> None:
        """组装所有 UI 分组。"""
        layout = QVBoxLayout(self)

        self.title_label = QLabel("KuR512")
        self.title_label.setObjectName("panelTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        serial_group = QGroupBox("串口设置")
        serial_layout = QVBoxLayout(serial_group)
        self.connection = SerialConnectionWidget(BAUD_RATES, 460800)
        self.connection.connect_requested.connect(self._connect_driver)
        self.connection.disconnect_requested.connect(self._disconnect_driver)
        serial_layout.addWidget(self.connection)
        layout.addWidget(serial_group)

        layout.addWidget(self._create_subarray_group())
        layout.addWidget(self._create_beam_group())
        layout.addWidget(self._create_array_group())
        layout.addWidget(self._create_phase_group())
        layout.addWidget(self._create_status_group())
        layout.addWidget(self._create_polling_group())
        layout.addWidget(self._create_chart_group())
        layout.addWidget(self._create_log_group())
        layout.addStretch()

    # -------------------- 子阵 ID --------------------
    def _create_subarray_group(self) -> QGroupBox:
        """创建子阵 ID 生成、目标选择与单阵寻址控件。"""
        group = QGroupBox("子阵设置")
        layout = QVBoxLayout(group)

        generator_row = QHBoxLayout()
        generator_row.addWidget(QLabel("阵列拼接:"))
        self.column_combo = QComboBox()
        self.column_combo.addItems(["1列", "2列"])
        generator_row.addWidget(self.column_combo)
        generator_row.addWidget(QLabel("每列子阵数:"))
        self.row_count_spin = QSpinBox()
        self.row_count_spin.setRange(1, 15)
        self.row_count_spin.setValue(1)
        generator_row.addWidget(self.row_count_spin)
        generate_button = QPushButton("生成ID")
        generate_button.clicked.connect(self._generate_ids)
        generator_row.addWidget(generate_button)
        generator_row.addStretch()
        layout.addLayout(generator_row)

        id_row = QHBoxLayout()
        id_row.addWidget(QLabel("子阵ID列表:"))
        self.id_list_edit = QLineEdit("0x01")
        self.id_list_edit.setPlaceholderText("逗号分隔，如 0x01,0x02,0x11")
        self.id_list_edit.editingFinished.connect(self._on_id_list_changed)
        id_row.addWidget(self.id_list_edit)
        layout.addLayout(id_row)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("目标:"))
        self.target_combo = QComboBox()
        target_row.addWidget(self.target_combo)
        self.plus_0x80_check = QCheckBox("仅本子阵(+0x80)")
        target_row.addWidget(self.plus_0x80_check)
        target_row.addStretch()
        layout.addLayout(target_row)
        self._refresh_target_combo()
        return group

    def _create_beam_group(self) -> QGroupBox:
        """创建波束设置控件；包含 POL 三选一与线极化角度输入。"""
        group = QGroupBox("RX 波束设置")
        layout = QGridLayout(group)
        layout.addWidget(QLabel("频率(MHz):"), 0, 0)
        self.frequency_edit = QLineEdit(str(protocol.MIN_FREQUENCY_MHZ))
        layout.addWidget(self.frequency_edit, 0, 1)

        layout.addWidget(QLabel("θ角度:"), 1, 0)
        self.theta_edit = QLineEdit("0")
        layout.addWidget(self.theta_edit, 1, 1)
        layout.addWidget(QLabel("φ角度:"), 2, 0)
        self.phi_edit = QLineEdit("0")
        layout.addWidget(self.phi_edit, 2, 1)

        layout.addWidget(QLabel("极化方式:"), 3, 0)
        polarity_row = QHBoxLayout()
        self.polarity_linear_radio = QRadioButton("线极化")
        self.polarity_lhcp_radio = QRadioButton("LHCP")
        self.polarity_rhcp_radio = QRadioButton("RHCP")
        self.polarity_linear_radio.setChecked(True)
        self.polarity_linear_radio.toggled.connect(self._on_polarity_changed)
        self.polarity_lhcp_radio.toggled.connect(self._on_polarity_changed)
        self.polarity_rhcp_radio.toggled.connect(self._on_polarity_changed)
        polarity_row.addWidget(self.polarity_linear_radio)
        polarity_row.addWidget(self.polarity_lhcp_radio)
        polarity_row.addWidget(self.polarity_rhcp_radio)
        polarity_row.addStretch()
        polarity_widget = QWidget()
        polarity_widget.setLayout(polarity_row)
        layout.addWidget(polarity_widget, 3, 1)

        layout.addWidget(QLabel("线极化角度(0..180):"), 4, 0)
        self.pol_value_edit = QLineEdit("0")
        layout.addWidget(self.pol_value_edit, 4, 1)

        apply_button = QPushButton("设置波束")
        apply_button.clicked.connect(self._apply_beam)
        layout.addWidget(apply_button, 0, 2, 5, 1)
        return group

    def _create_array_group(self) -> QGroupBox:
        """创建阵列使能控件。"""
        group = QGroupBox("RX 阵列")
        layout = QHBoxLayout(group)
        self.array_enabled_check = QCheckBox("使能")
        button = QPushButton("应用")
        button.clicked.connect(self._apply_array_enabled)
        layout.addWidget(self.array_enabled_check)
        layout.addWidget(button)
        return group

    def _create_phase_group(self) -> QGroupBox:
        """创建整板相位校准控件。"""
        group = QGroupBox("RX 整板相位校准 (0..63, 步进 5.625°)")
        layout = QHBoxLayout(group)
        self.phase_spin = QSpinBox()
        self.phase_spin.setRange(protocol.PHASE_CAL_MIN, protocol.PHASE_CAL_MAX)
        self.phase_spin.setValue(0)
        button = QPushButton("应用")
        button.clicked.connect(self._apply_phase_cal)
        layout.addWidget(QLabel("PS_Align:"))
        layout.addWidget(self.phase_spin)
        layout.addWidget(button)
        return group

    def _create_status_group(self) -> QGroupBox:
        """创建按子阵展示最新状态字段的表格。"""
        group = QGroupBox("状态")
        layout = QVBoxLayout(group)
        self.status_table = QTableWidget(0, len(self._status_columns))
        self.status_table.setHorizontalHeaderLabels(self._status_columns)
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.status_table.setMinimumHeight(140)
        for column in range(len(self._status_columns)):
            self.status_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        layout.addWidget(self.status_table)
        query_button = QPushButton("查询全部状态")
        query_button.clicked.connect(self._query_all_status)
        layout.addWidget(query_button)
        self._rebuild_status_table()
        return group

    def _create_polling_group(self) -> QGroupBox:
        """创建主动读取与 CSV 落盘相关控件。"""
        group = QGroupBox("主动读取（按用户配置频率向列表中每个子阵发送 0x9C）")
        layout = QGridLayout(group)

        layout.addWidget(QLabel("查询频率(0..100Hz):"), 0, 0)
        self.query_hz_spin = QSpinBox()
        self.query_hz_spin.setRange(0, MAX_QUERY_HZ)
        self.query_hz_spin.setValue(DEFAULT_QUERY_HZ)
        self.query_hz_spin.setSingleStep(1)
        layout.addWidget(self.query_hz_spin, 0, 1)

        self.start_button = QPushButton("启动主动读取")
        self.start_button.clicked.connect(self._start_polling)
        self.stop_button = QPushButton("停止")
        self.stop_button.clicked.connect(self._stop_polling)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.start_button, 0, 2)
        layout.addWidget(self.stop_button, 1, 2)

        self.actual_rate_label = QLabel("实际查询频率: -- Hz")
        layout.addWidget(self.actual_rate_label, 2, 0)

        self.open_log_button = QPushButton("打开日志目录")
        self.open_log_button.clicked.connect(self._open_log_directory)
        layout.addWidget(self.open_log_button, 2, 1, 1, 2)

        layout.addWidget(QLabel("最近一行:"), 3, 0)
        self.last_line_edit = QLineEdit()
        self.last_line_edit.setReadOnly(True)
        self.last_line_edit.setPlaceholderText("启动后此处显示最近写入 CSV 的原始报文与字段。")
        layout.addWidget(self.last_line_edit, 3, 1, 1, 2)
        return group

    def _create_chart_group(self) -> QGroupBox:
        """创建实时温度/电压曲线视图。"""
        group = QGroupBox("实时曲线（最近 5 分钟温度/电压）")
        layout = QVBoxLayout(group)
        control_row = QHBoxLayout()
        control_row.addWidget(QLabel("窗口:"))
        self.window_combo = QComboBox()
        for window in ChartWindow:
            self.window_combo.addItem(window.label, int(window.value))
        self.window_combo.setCurrentIndex(1)  # 默认 5 min
        self.window_combo.currentIndexChanged.connect(self._on_window_changed)
        control_row.addWidget(self.window_combo)
        clear_button = QPushButton("清空曲线")
        clear_button.clicked.connect(self._clear_chart)
        control_row.addWidget(clear_button)
        control_row.addStretch()
        layout.addLayout(control_row)

        self.chart_view = KUR512ChartView()
        self.chart_view.setMinimumHeight(220)
        layout.addWidget(self.chart_view)
        return group

    def _create_log_group(self) -> QGroupBox:
        """创建页面日志只读文本区域。"""
        group = QGroupBox("日志")
        layout = QVBoxLayout(group)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(100)
        layout.addWidget(self.log_text)
        clear_button = QPushButton("清除")
        clear_button.clicked.connect(self.log_text.clear)
        layout.addWidget(clear_button)
        return group

    # -------------------- 业务方法 --------------------
    @staticmethod
    def parse_subarray_ids(text: str) -> list[int]:
        """解析逗号分隔的子阵 ID，支持十进制与 0x 前缀。"""
        ids: list[int] = []
        for token in text.replace("，", ",").split(","):
            token = token.strip()
            if not token:
                continue
            try:
                value = int(token, 0)
            except ValueError:
                continue
            if 1 <= value <= 0x7F and value not in ids:
                ids.append(value)
        return sorted(ids)

    @staticmethod
    def generate_subarray_ids(columns: int, rows_per_column: int) -> list[int]:
        """按 1 或 2 列阵列生成 0x01..0x1F 范围内的子阵 ID。"""
        if columns not in (1, 2):
            raise ValueError("阵列列数只支持 1 或 2")
        if not 1 <= rows_per_column <= 15:
            raise ValueError("每列子阵数必须在 1~15 范围内")
        return [
            (column << 4) | row
            for column in range(columns)
            for row in range(1, rows_per_column + 1)
        ]

    def subarray_ids(self) -> list[int]:
        """返回当前合法子阵 ID。"""
        return self.parse_subarray_ids(self.id_list_edit.text())

    @Slot()
    def _generate_ids(self) -> None:
        """根据控件生成 ID 并刷新目标与状态表。"""
        ids = self.generate_subarray_ids(
            self.column_combo.currentIndex() + 1,
            self.row_count_spin.value(),
        )
        self.id_list_edit.setText(",".join(_format_id(value) for value in ids))
        self._on_id_list_changed()

    @Slot()
    def _on_id_list_changed(self) -> None:
        """ID 变更后刷新目标下拉框与状态表。"""
        self._refresh_target_combo()
        self._rebuild_status_table()

    def _refresh_target_combo(self) -> None:
        """用当前合法 ID 更新目标下拉框，并尽量保留既有选择。"""
        if not hasattr(self, "target_combo"):
            return
        current = self.target_combo.currentText()
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        self.target_combo.addItem("全部(广播 ID=0)")
        for device_id in self.subarray_ids():
            self.target_combo.addItem(_format_id(device_id))
        index = self.target_combo.findText(current)
        if index >= 0:
            self.target_combo.setCurrentIndex(index)
        self.target_combo.blockSignals(False)

    def target_device_id(self) -> int:
        """返回当前寻址字节；广播为 0，勾选时为子阵 ID + 0x80。"""
        text = self.target_combo.currentText()
        if text.startswith("全部"):
            return 0
        try:
            device_id = int(text, 0)
        except ValueError:
            return 0
        if self.plus_0x80_check.isChecked():
            return (device_id + 0x80) & 0xFF
        return device_id

    def _rebuild_status_table(self) -> None:
        """按当前子阵 ID 重建状态表，未知字段显示为 ``N/A``。"""
        if not hasattr(self, "status_table"):
            return
        ids = self.subarray_ids()
        self._status_rows.clear()
        self.status_table.setRowCount(len(ids))
        for row, device_id in enumerate(ids):
            self._status_rows[device_id] = row
            for column in range(len(self._status_columns)):
                text = _format_id(device_id) if column == 0 else "N/A"
                self.status_table.setItem(row, column, QTableWidgetItem(text))

    @Slot(int)
    def _on_window_changed(self, _index: int) -> None:
        """切换曲线显示窗口。"""
        seconds = int(self.window_combo.currentData())
        try:
            window = ChartWindow(seconds)
        except ValueError:
            return
        self.chart_view.set_window(window)

    @Slot()
    def _clear_chart(self) -> None:
        """清空曲线缓冲。"""
        self.chart_view.clear()

    def _on_polarity_changed(self, _checked: bool) -> None:
        """切换极化方式时启用/禁用线极化角度输入框。"""
        linear_active = self.polarity_linear_radio.isChecked()
        self.pol_value_edit.setEnabled(linear_active)

    def _current_polarity(self) -> tuple[Polarity, int]:
        """读取当前极化控件；LHCP/RHCP 时 pol_value=0。"""
        if self.polarity_lhcp_radio.isChecked():
            return Polarity.LHCP, 0
        if self.polarity_rhcp_radio.isChecked():
            return Polarity.RHCP, 0
        try:
            value = int(self.pol_value_edit.text())
        except ValueError as exc:
            raise ValueError(f"线极化角度必须为整数: {exc}") from exc
        return Polarity.LINEAR, value

    def _log_root(self) -> Path:
        """解析并缓存默认日志目录根。"""
        if self._log_root_path is not None:
            return self._log_root_path
        docs = Path.home() / "Documents"
        self._log_root_path = default_log_directory(docs) / "kur512"
        self._log_root_path.mkdir(parents=True, exist_ok=True)
        return self._log_root_path

    def _open_log_directory(self) -> None:
        """打开日志根目录；按平台选择对应命令。"""
        directory = self._log_root()
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.Popen(["open", str(directory)])
                return
            if system == "Windows":
                QDesktopServices.openUrl(directory.as_uri())
                return
            subprocess.Popen(["xdg-open", str(directory)])
        except Exception as exc:
            QMessageBox.warning(self, "打开日志目录失败", str(exc))

    @Slot()
    def _start_polling(self) -> None:
        """启动主动轮询：校验输入、调用 Driver.start_polling。"""
        driver = self._active_driver()
        if driver is None:
            return
        ids = self.subarray_ids()
        if not ids:
            QMessageBox.warning(self, "主动读取", "子阵 ID 列表不能为空")
            return
        try:
            freq_hz = int(self.query_hz_spin.value())
        except ValueError as exc:
            QMessageBox.warning(self, "主动读取", str(exc))
            return

        driver.set_log_root(self._log_root())
        driver.start_polling(ids, freq_hz)
        # 当前 KUR512 曲线为单 subarray 视图；若多 subarray 共用一张图，按目标 ID
        # 设图例；其它 ID 仍落 CSV，不进曲线（panel 一次只看一个 ID 的曲线）
        target_id = self.target_device_id()
        if target_id:
            self.chart_view.set_legend_label(f"ID=0x{target_id:02X}")
        elif ids:
            self.chart_view.set_legend_label(f"ID=0x{ids[0]:02X}")

        self._polling_active = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.query_hz_spin.setEnabled(False)
        self._refresh_timer.start()
        self.log_text.appendPlainText(
            f">>> 主动读取已启动: {len(ids)} 个子阵, 频率={freq_hz}Hz"
        )

    @Slot()
    def _stop_polling(self) -> None:
        """停止主动轮询；关闭 recorder 并清空曲线。"""
        if self.driver is not None:
            self.driver.stop_polling()
        self._polling_active = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.query_hz_spin.setEnabled(True)
        self._refresh_timer.stop()
        self.chart_view.reset()
        self.actual_rate_label.setText("实际查询频率: -- Hz")
        self.last_line_edit.clear()
        self.log_text.appendPlainText(">>> 主动读取已停止")

    @Slot()
    def _refresh_status_table(self) -> None:
        """10 Hz 节流刷新状态表、实际频率与曲线。"""
        driver = self.driver
        if driver is None:
            return
        snapshot = driver.status_snapshot()
        for sub_id, info in snapshot.items():
            row = self._status_rows.get(sub_id)
            if row is None:
                continue
            self._update_status_row(row, info)
        achieved = driver.achieved_hz
        self.actual_rate_label.setText(f"实际查询频率: {achieved:.1f} Hz")
        # 曲线按 10 Hz 节流重绘：拉 buffer → ndarray → setData
        self.chart_view.refresh()

    def _update_status_row(self, row: int, info: dict) -> None:
        """更新单行状态；按列写入文本。"""
        if "sys_vcc" in info:
            self.status_table.setItem(row, self._column_index["电压(V)"], QTableWidgetItem(f"{info['sys_vcc']:.1f}"))
        if "sys_temp" in info:
            self.status_table.setItem(row, self._column_index["温度(℃)"], QTableWidgetItem(str(info["sys_temp"])))
        if "mcu_ver" in info:
            self.status_table.setItem(row, self._column_index["MCU_VER"], QTableWidgetItem(str(info["mcu_ver"])))
        if "last_raw_hex" in info and info["last_raw_hex"]:
            raw_text = str(info["last_raw_hex"])
            display = raw_text if len(raw_text) <= 24 else raw_text[:21] + "..."
            self.status_table.setItem(row, self._column_index["最近原始报文"], QTableWidgetItem(display))
            self.last_line_edit.setText(
                f"0x{info.get('device_id', 0) & 0xFF:02X} "
                f"vcc={info.get('sys_vcc'):.1f}V temp={info.get('sys_temp')}°C raw={raw_text}"
            )

    @Slot(str, int)
    def _connect_driver(self, port: str, baudrate: int) -> None:
        """创建 Driver、绑定信号、连接代际递增。"""
        if self._shutdown:
            self.connection.set_disconnected("页面已停止")
            return
        if not self.disconnect_device():
            return
        self._connection_generation += 1
        generation = self._connection_generation
        self.connection.set_connecting()
        try:
            driver = self._driver_factory(port, baudrate)
            driver.log_signal.connect(
                lambda message, current=driver, token=generation: self._append_driver_log(current, token, message)
            )
            driver.opened_signal.connect(
                lambda opened, message, current=driver, token=generation: self._on_driver_opened(current, token, opened, message)
            )
            driver.status_signal.connect(
                lambda info, current=driver, token=generation: self._on_driver_status(current, token, info)
            )
            driver.frame_signal.connect(self.frame_signal.emit)
            driver.finished.connect(lambda current=driver: self._on_driver_finished(current))
            self.driver = driver
            driver.start()
        except Exception as exc:
            self.connection.set_disconnected(str(exc))
            QMessageBox.warning(self, "串口错误", str(exc))

    def _is_current_driver(self, driver: KUR512Driver, generation: int) -> bool:
        """判断异步信号是否仍属于当前 Driver 与当前连接代际。"""
        return driver is self.driver and generation == self._connection_generation

    def _append_driver_log(self, driver: KUR512Driver, generation: int, message: str) -> None:
        """仅追加当前连接代际 Driver 的日志。"""
        if self._is_current_driver(driver, generation):
            self.log_text.appendPlainText(message)

    def _on_driver_opened(
        self,
        driver: KUR512Driver,
        generation: int,
        opened: bool,
        message: str,
    ) -> None:
        """将打开结果同步到串口连接状态控件。"""
        if not self._is_current_driver(driver, generation):
            return
        if opened:
            self.connection.set_connected(message)
        else:
            self.connection.set_disconnected(message)

    def _on_driver_status(self, driver: KUR512Driver, generation: int, info: dict) -> None:
        """Driver 推送的 status_signal 直接驱动状态表与曲线。"""
        if not self._is_current_driver(driver, generation):
            return
        row = self._status_rows.get(int(info.get("device_id", -1)) & 0x7F)
        if row is not None:
            self._update_status_row(row, info)
        if "sys_vcc" in info and "sys_temp" in info and "last_ts_ns" in info:
            self.chart_view.append(
                int(info["last_ts_ns"]),
                float(info["sys_vcc"]),
                int(info["sys_temp"]),
            )
            # 曲线实际 setData 由 _refresh_status_table 的 10 Hz 节流触发

    def _on_driver_finished(self, driver: KUR512Driver) -> None:
        """Driver 线程结束后回收引用，更新 UI。"""
        if driver is self.driver:
            self.driver = None
            self.connection.set_disconnected("串口已关闭")
            if self._polling_active:
                self._polling_active = False
                self.start_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                self.query_hz_spin.setEnabled(True)
                self._refresh_timer.stop()
                self.chart_view.reset()
        driver.deleteLater()

    @Slot()
    def _disconnect_driver(self) -> None:
        """处理串口断开请求。"""
        self.disconnect_device()

    def disconnect_device(self) -> bool:
        """断开设备串口；允许重复调用。"""
        self._connection_generation += 1
        driver = self.driver
        if driver is not None:
            self.connection.set_stopping()
            if driver.stop() is False:
                self.connection.set_stop_failed("串口线程停止超时，请重试关闭")
                return False
            self.driver = None
            driver.deleteLater()
        if hasattr(self, "connection"):
            self.connection.set_disconnected()
        if self._polling_active:
            self._polling_active = False
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.query_hz_spin.setEnabled(True)
            self._refresh_timer.stop()
            self.chart_view.reset()
        return True

    def _active_driver(self) -> Optional[KUR512Driver]:
        """返回运行中的 Driver；未连接时提示用户并返回 ``None``。"""
        if self.driver is None or not self.driver.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return None
        return self.driver

    @Slot()
    def _apply_beam(self) -> None:
        """读取输入并发送波束配置。"""
        driver = self._active_driver()
        if driver is None:
            return
        try:
            polarity, pol_value = self._current_polarity()
            setting = protocol.make_beam_setting(
                float(self.frequency_edit.text()),
                float(self.theta_edit.text()),
                float(self.phi_edit.text()),
                polarity=polarity,
                pol_value=pol_value,
            )
            driver.set_beam(self.target_device_id(), setting)
            self.log_text.appendPlainText(
                f">>> 波束设置: 实际频率={setting.actual_frequency_mhz}MHz "
                f"BeamH={setting.beam_h}, BeamV={setting.beam_v}, POL={polarity.value}"
                + (f"({setting.pol_value}°)" if polarity is Polarity.LINEAR else "")
            )
        except (ValueError, ConnectionError) as exc:
            QMessageBox.warning(self, "警告", str(exc))

    @Slot()
    def _apply_array_enabled(self) -> None:
        """向当前目标发送阵列使能命令。"""
        driver = self._active_driver()
        if driver is None:
            return
        try:
            driver.set_array_enabled(self.target_device_id(), self.array_enabled_check.isChecked())
        except (ValueError, ConnectionError) as exc:
            QMessageBox.warning(self, "警告", str(exc))

    @Slot()
    def _apply_phase_cal(self) -> None:
        """向当前目标发送整板相位校准命令。"""
        driver = self._active_driver()
        if driver is None:
            return
        try:
            driver.set_phase_calibration(self.target_device_id(), self.phase_spin.value())
        except (ValueError, ConnectionError) as exc:
            QMessageBox.warning(self, "警告", str(exc))

    @Slot()
    def _query_all_status(self) -> None:
        """按当前 ID 列表发送一次 0x9C 查询（不依赖主动轮询）。"""
        driver = self._active_driver()
        if driver is None:
            return
        try:
            count = driver.query_status(self.subarray_ids())
            self.log_text.appendPlainText(f">>> 已发送 {count} 个子阵的状态查询")
        except (ValueError, ConnectionError) as exc:
            QMessageBox.warning(self, "警告", str(exc))

    def activate(self) -> None:
        """进入前台时恢复端口扫描。"""
        if self._shutdown:
            return
        timer = getattr(self.connection, "_timer", None)
        if timer is not None and not timer.isActive():
            timer.start(2000)

    def deactivate(self) -> bool:
        """断开串口并暂停隐藏页面的端口扫描。"""
        stopped = self.disconnect_device()
        if stopped:
            timer = getattr(self.connection, "_timer", None)
            if timer is not None:
                timer.stop()
        return stopped

    def shutdown(self) -> bool:
        """最终关闭：停止串口、停止主动读取、停止定时器。"""
        if self._shutdown:
            return True
        if not self.disconnect_device():
            return False
        timer = getattr(self.connection, "_timer", None)
        if timer is not None:
            timer.stop()
        self._shutdown = True
        return True

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Qt 显示事件：恢复工作区所需的端口扫描。"""
        self.activate()
        super().showEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Qt 关闭事件：仅在串口停止成功后允许窗口销毁。"""
        if not self.shutdown():
            event.ignore()
            return
        super().closeEvent(event)


Panel = KUR512Panel


__all__ = ["KUR512Panel", "Panel"]
