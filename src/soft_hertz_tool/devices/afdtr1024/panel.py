"""AFDT1024/AFDR1024 共用设备页面。"""

from __future__ import annotations

from typing import Callable, Optional, Union

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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
)

from soft_hertz_tool.devices.afdtr1024.driver import AFDTR1024Driver
from soft_hertz_tool.devices.afdtr1024.models import DeviceVariant
from soft_hertz_tool.shared.ui.serial_connection import SerialConnectionWidget


BAUD_RATES = (9600, 19200, 38400, 115200, 460800, 921600)


class AFDTR1024Panel(QFrame):
    """以 Driver 语义接口操作设备，不在 UI 层拼帧或解析帧。"""

    frame_signal = Signal(object)

    def __init__(
        self,
        variant: Union[DeviceVariant, str],
        parent=None,
        driver_factory: Callable[..., AFDTR1024Driver] = AFDTR1024Driver,
    ):
        """创建指定 AFDT1024/AFDR1024 变体的页面及其延迟创建的 Driver。"""
        super().__init__(parent)
        self.variant = DeviceVariant.coerce(variant)
        self._driver_factory = driver_factory
        self.driver: Optional[AFDTR1024Driver] = None
        self._status_rows: dict[int, int] = {}
        self._status_columns: list[str] = []
        self._column_index: dict[str, int] = {}
        self._connection_generation = 0
        self._shutdown = False
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """组装串口、子阵、配置、状态和日志区域。"""
        layout = QVBoxLayout(self)

        self.title_label = QLabel(self.variant.model_name)
        self.title_label.setObjectName("panelTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        serial_group = QGroupBox("串口设置")
        serial_layout = QVBoxLayout(serial_group)
        self.connection = SerialConnectionWidget(BAUD_RATES, 115200)
        self.connection.connect_requested.connect(self._connect_driver)
        self.connection.disconnect_requested.connect(self._disconnect_driver)
        serial_layout.addWidget(self.connection)
        layout.addWidget(serial_group)

        layout.addWidget(self._create_subarray_group())
        layout.addWidget(self._create_beam_group())
        layout.addWidget(self._create_array_group())
        if self.variant.is_tx:
            layout.addWidget(self._create_pa_group())
        layout.addWidget(self._create_polarization_group())
        layout.addWidget(self._create_status_group())
        layout.addWidget(self._create_log_group())
        layout.addStretch()

    def _create_subarray_group(self) -> QGroupBox:
        """创建子阵 ID 生成、目标选择和单阵寻址控件。"""
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
        """创建以 MHz 和度为单位的波束设置控件。"""
        group = QGroupBox(f"{self.variant.value}波束设置")
        layout = QGridLayout(group)
        layout.addWidget(QLabel("频率(MHz):"), 0, 0)
        default_frequency = "27500" if self.variant.is_tx else "20270"
        self.frequency_edit = QLineEdit(default_frequency)
        layout.addWidget(self.frequency_edit, 0, 1)
        layout.addWidget(QLabel("θ角度:"), 1, 0)
        self.theta_edit = QLineEdit("0")
        layout.addWidget(self.theta_edit, 1, 1)
        layout.addWidget(QLabel("φ角度:"), 2, 0)
        self.phi_edit = QLineEdit("0")
        layout.addWidget(self.phi_edit, 2, 1)
        apply_button = QPushButton("设置波束")
        apply_button.clicked.connect(self._apply_beam)
        layout.addWidget(apply_button, 0, 2, 3, 1)
        return group

    def _create_array_group(self) -> QGroupBox:
        """创建当前变体的阵列使能控件。"""
        group = QGroupBox(f"{self.variant.value}阵列")
        layout = QHBoxLayout(group)
        self.array_enabled_check = QCheckBox("使能")
        button = QPushButton("应用")
        button.clicked.connect(self._apply_array_enabled)
        layout.addWidget(self.array_enabled_check)
        layout.addWidget(button)
        return group

    def _create_pa_group(self) -> QGroupBox:
        """创建仅 AFDT1024 可用的推动 PA 控件。"""
        group = QGroupBox("推动PA")
        layout = QHBoxLayout(group)
        self.pa_enabled_check = QCheckBox("使能")
        button = QPushButton("应用")
        button.clicked.connect(self._apply_pa_enabled)
        layout.addWidget(self.pa_enabled_check)
        layout.addWidget(button)
        return group

    def _create_polarization_group(self) -> QGroupBox:
        """创建 LHCP/RHCP 极化选择控件。"""
        group = QGroupBox("极化设置")
        layout = QHBoxLayout(group)
        self.lhcp_radio = QRadioButton("LHCP")
        self.rhcp_radio = QRadioButton("RHCP")
        self.lhcp_radio.setChecked(True)
        button = QPushButton("设置")
        button.clicked.connect(self._apply_polarization)
        layout.addWidget(self.lhcp_radio)
        layout.addWidget(self.rhcp_radio)
        layout.addWidget(button)
        return group

    def _create_status_group(self) -> QGroupBox:
        """创建按子阵展示查询 1 和查询 2 合并状态的表格。"""
        beam_columns = ["极化", "使能", "频率(MHz)", "BeamV", "BeamH"]
        prefix = ["ID", "电压(V)", "温度(°C)"]
        if self.variant.is_tx:
            prefix.append("PA")
        self._status_columns = prefix + beam_columns
        self._column_index = {name: index for index, name in enumerate(self._status_columns)}

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

    def _create_log_group(self) -> QGroupBox:
        """创建显示当前页面 Driver 日志的只读文本区域。"""
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

    @staticmethod
    def parse_subarray_ids(text: str) -> list[int]:
        """解析逗号分隔的十进制或十六进制子阵 ID，并去重排序。"""
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
        """按 1 或 2 列阵列规则生成 0x01~0x1F 范围内的子阵 ID。

        Raises:
            ValueError: 列数或每列数量超出页面支持范围。
        """
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
        """返回当前输入框中合法且排序后的子阵 ID。"""
        return self.parse_subarray_ids(self.id_list_edit.text())

    @staticmethod
    def _format_id(device_id: int) -> str:
        """将设备 ID 格式化为两位十六进制显示文本。"""
        return f"0x{device_id:02X}"

    @Slot()
    def _generate_ids(self) -> None:
        """根据阵列拼接控件生成 ID，并刷新目标和状态表。"""
        ids = self.generate_subarray_ids(
            self.column_combo.currentIndex() + 1,
            self.row_count_spin.value(),
        )
        self.id_list_edit.setText(",".join(self._format_id(value) for value in ids))
        self._on_id_list_changed()

    @Slot()
    def _on_id_list_changed(self) -> None:
        """在 ID 文本变更后重建目标列表和状态表行。"""
        self._refresh_target_combo()
        self._rebuild_status_table()

    def _refresh_target_combo(self) -> None:
        """用当前合法 ID 更新目标下拉框，并尽量保持既有选择。"""
        current = self.target_combo.currentText() if hasattr(self, "target_combo") else ""
        if not hasattr(self, "target_combo"):
            return
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        self.target_combo.addItem("全部(广播 ID=0)")
        for device_id in self.subarray_ids():
            self.target_combo.addItem(self._format_id(device_id))
        index = self.target_combo.findText(current)
        if index >= 0:
            self.target_combo.setCurrentIndex(index)
        self.target_combo.blockSignals(False)

    def target_device_id(self) -> int:
        """返回当前寻址字节；广播为 0，勾选时为子阵 ID 加 ``0x80``。"""
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
            self.status_table.setItem(row, 0, QTableWidgetItem(self._format_id(device_id)))
            for column in range(1, len(self._status_columns)):
                self.status_table.setItem(row, column, QTableWidgetItem("N/A"))

    @Slot(dict)
    def update_status(self, info: dict) -> None:
        """将 Driver 发出的单个子阵合并状态渲染到对应表格行。"""
        device_id = info.get("device_id")
        if device_id is None:
            return
        row = self._status_rows.get(int(device_id) & 0x7F)
        if row is None:
            return

        def set_column(name: str, value: object) -> None:
            """仅在该变体拥有目标列时写入当前状态表单元格。"""
            column = self._column_index.get(name)
            if column is not None:
                self.status_table.setItem(row, column, QTableWidgetItem(str(value)))

        if "sys_vcc" in info:
            set_column("电压(V)", f"{info['sys_vcc']:.1f}")
        if "sys_temp" in info:
            set_column("温度(°C)", info["sys_temp"])
        if "pa_en" in info:
            set_column("PA", "ON" if info["pa_en"] else "OFF")
        if "pol" in info:
            set_column("极化", "RHCP" if info["pol"] else "LHCP")
        if "en_row" in info:
            set_column("使能", "ON" if info["en_row"] else "OFF")
        if "freq_mhz" in info:
            set_column("频率(MHz)", info["freq_mhz"])
        if "beam_v" in info:
            set_column("BeamV", info["beam_v"])
        if "beam_h" in info:
            set_column("BeamH", info["beam_h"])

    @Slot(str, int)
    def _connect_driver(self, port: str, baudrate: int) -> None:
        """停止旧连接后创建并启动新 Driver，给所有异步槽绑定连接代际。"""
        if self._shutdown:
            self.connection.set_disconnected("页面已停止")
            return
        if not self.disconnect_device():
            return
        # 每次重连都更换代际，旧线程排队的 Qt 信号不得覆盖新连接的 UI。
        self._connection_generation += 1
        generation = self._connection_generation
        self.connection.set_connecting()
        try:
            driver = self._driver_factory(port, baudrate, self.variant)
            driver.log_signal.connect(
                lambda message, current=driver, token=generation: self._append_driver_log(
                    current,
                    token,
                    message,
                )
            )
            driver.opened_signal.connect(
                lambda opened, message, current=driver, token=generation: self._on_driver_opened(
                    current,
                    token,
                    opened,
                    message,
                )
            )
            driver.status_signal.connect(
                lambda info, current=driver, token=generation: self._on_driver_status(
                    current,
                    token,
                    info,
                )
            )
            driver.config_success_signal.connect(
                lambda command, current=driver, token=generation: self._on_driver_config_success(
                    current,
                    token,
                    command,
                )
            )
            driver.frame_signal.connect(self.frame_signal.emit)
            driver.finished.connect(lambda current=driver: self._on_driver_finished(current))
            self.driver = driver
            driver.start()
        except Exception as exc:
            self.connection.set_disconnected(str(exc))
            QMessageBox.warning(self, "串口错误", str(exc))

    def _is_current_driver(self, driver: AFDTR1024Driver, generation: int) -> bool:
        """判断异步信号是否仍属于当前 Driver 与当前连接代际。"""
        return driver is self.driver and generation == self._connection_generation

    def _append_driver_log(
        self,
        driver: AFDTR1024Driver,
        generation: int,
        message: str,
    ) -> None:
        """仅追加当前连接代际 Driver 的日志，忽略陈旧线程信号。"""
        if self._is_current_driver(driver, generation):
            self.log_text.appendPlainText(message)

    def _on_driver_opened(
        self,
        driver: AFDTR1024Driver,
        generation: int,
        opened: bool,
        message: str,
    ) -> None:
        """将当前 Driver 的打开结果同步到串口连接状态控件。"""
        if not self._is_current_driver(driver, generation):
            return
        if opened:
            self.connection.set_connected(message)
        else:
            self.connection.set_disconnected(message)

    def _on_driver_status(
        self,
        driver: AFDTR1024Driver,
        generation: int,
        info: dict,
    ) -> None:
        """仅接受当前连接代际的状态信号并更新状态表。"""
        if self._is_current_driver(driver, generation):
            self.update_status(info)

    def _on_driver_config_success(
        self,
        driver: AFDTR1024Driver,
        generation: int,
        command: str,
    ) -> None:
        """仅显示当前连接代际的配置回显成功消息。"""
        if self._is_current_driver(driver, generation):
            self._on_config_success(command)

    def _on_driver_finished(self, driver: AFDTR1024Driver) -> None:
        """回收已结束 Driver；若仍为当前连接则更新 UI 状态。"""
        if driver is self.driver:
            self.driver = None
            self.connection.set_disconnected("串口已关闭")
        driver.deleteLater()

    @Slot()
    def _disconnect_driver(self) -> None:
        """处理串口控件的断开请求。"""
        self.disconnect_device()

    def disconnect_device(self) -> bool:
        """只断开设备串口，保留端口扫描；允许重复调用。"""

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
        return True

    @Slot(str)
    def _on_config_success(self, command: str) -> None:
        """在页面日志中记录已收到配置回显的指令名称。"""
        self.log_text.appendPlainText(f"✓ {command}配置成功")

    def _active_driver(self) -> Optional[AFDTR1024Driver]:
        """返回运行中的 Driver；未连接时提示用户并返回 ``None``。"""
        if self.driver is None or not self.driver.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return None
        return self.driver

    @Slot()
    def _apply_beam(self) -> None:
        """读取 MHz/度输入并向当前目标发送波束设置。"""
        driver = self._active_driver()
        if driver is None:
            return
        try:
            setting = driver.set_beam(
                self.target_device_id(),
                float(self.frequency_edit.text()),
                float(self.theta_edit.text()),
                float(self.phi_edit.text()),
            )
            self.log_text.appendPlainText(
                f">>> 波束设置: 实际频率={setting.actual_frequency_mhz}MHz "
                f"BeamH={setting.beam_h}, BeamV={setting.beam_v}"
            )
        except (ValueError, ConnectionError) as exc:
            QMessageBox.warning(self, "警告", str(exc))

    @Slot()
    def _apply_array_enabled(self) -> None:
        """向当前目标发送阵列使能或关闭命令。"""
        driver = self._active_driver()
        if driver is None:
            return
        try:
            driver.set_array_enabled(self.target_device_id(), self.array_enabled_check.isChecked())
        except (ValueError, ConnectionError) as exc:
            QMessageBox.warning(self, "警告", str(exc))

    @Slot()
    def _apply_pa_enabled(self) -> None:
        """向当前 AFDT1024 目标发送推动 PA 使能命令。"""
        driver = self._active_driver()
        if driver is None:
            return
        try:
            driver.set_pa_enabled(self.target_device_id(), self.pa_enabled_check.isChecked())
        except (ValueError, ConnectionError) as exc:
            QMessageBox.warning(self, "警告", str(exc))

    @Slot()
    def _apply_polarization(self) -> None:
        """将页面极化单选状态发送给当前目标。"""
        driver = self._active_driver()
        if driver is None:
            return
        try:
            polarization = 1 if self.rhcp_radio.isChecked() else 0
            driver.set_polarization(self.target_device_id(), polarization)
        except (ValueError, ConnectionError) as exc:
            QMessageBox.warning(self, "警告", str(exc))

    @Slot()
    def _query_all_status(self) -> None:
        """按当前 ID 列表调度查询 1/查询 2，避免在 UI 线程集中发送。"""
        driver = self._active_driver()
        if driver is None:
            return
        try:
            count = driver.query_status(
                self.subarray_ids(),
                plus_0x80=self.plus_0x80_check.isChecked(),
            )
            self.log_text.appendPlainText(f">>> 已安排查询 {count} 个子阵状态")
        except (ValueError, ConnectionError) as exc:
            QMessageBox.warning(self, "警告", str(exc))

    def activate(self) -> None:
        """工作区进入前台时恢复端口扫描。"""

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
        """最终关闭时停止串口和端口扫描，允许重复调用。"""

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


class TXPanel(AFDTR1024Panel):
    """将共用页面固定为 AFDT1024 发射端变体的便捷子类。"""

    def __init__(self, parent=None, driver_factory: Callable[..., AFDTR1024Driver] = AFDTR1024Driver):
        """创建 AFDT1024 页面，可注入 Driver 工厂用于测试。"""
        super().__init__(DeviceVariant.TX, parent=parent, driver_factory=driver_factory)


class RXPanel(AFDTR1024Panel):
    """将共用页面固定为 AFDR1024 接收端变体的便捷子类。"""

    def __init__(self, parent=None, driver_factory: Callable[..., AFDTR1024Driver] = AFDTR1024Driver):
        """创建 AFDR1024 页面，可注入 Driver 工厂用于测试。"""
        super().__init__(DeviceVariant.RX, parent=parent, driver_factory=driver_factory)


Panel = AFDTR1024Panel
