"""KaUDC004A 设备控制面板。"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from PySide6.QtCore import QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from soft_hertz_tool.shared.ui.serial_connection import SerialConnectionWidget

from .driver import KaUDCDriver


BAUD_RATES = (9600, 19200, 38400, 115200, 460800, 921600)

TX_LO_OPTIONS = (
    ("26.55GHz (27.5-28.35)", 26550),
    ("27.40GHz (28.35-29.2)", 27400),
    ("28.05GHz (29.00-30.0)", 28050),
    ("29.05GHz (30.00-31.0)", 29050),
)

RX_LO_OPTIONS = (
    ("16.75GHz (17.7-18.2)", 16750),
    ("17.25GHz (18.2-19.2)", 17250),
    ("18.25GHz (19.2-20.2)", 18250),
    ("19.25GHz (20.2-21.2)", 19250),
)


class KaUDCPanel(QFrame):
    """只处理交互和展示；协议帧构建与解析全部委托给 Driver。"""

    frame_signal = Signal(object)
    status_signal = Signal(dict)

    def __init__(
        self,
        parent=None,
        driver_factory: Callable[[str, int], KaUDCDriver] = KaUDCDriver,
    ) -> None:
        """创建 KaUDC004A 交互面板。

        Args:
            parent: 可选 Qt 父对象。
            driver_factory: 创建串口 Driver 的工厂，便于测试注入替身。
        """
        super().__init__(parent)
        self._driver_factory = driver_factory
        self._driver: Optional[KaUDCDriver] = None
        self._shutdown = False
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self._setup_ui()

    @property
    def driver(self) -> Optional[KaUDCDriver]:
        """返回当前连接的 Driver。

        Returns:
            已创建但尚未停止的 Driver；未连接时为 ``None``。
        """
        return self._driver

    @property
    def worker(self) -> Optional[KaUDCDriver]:
        """过渡期兼容旧页面通过 ``worker`` 读取连接状态的用法。"""
        return self._driver

    def _setup_ui(self) -> None:
        """创建固定的串口、状态、本振、命令和日志控件布局。"""
        layout = QVBoxLayout(self)

        title = QLabel("KaUDC004A")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        serial_group = QGroupBox("串口设置")
        serial_layout = QVBoxLayout(serial_group)
        self.connection = SerialConnectionWidget(BAUD_RATES, 115200)
        self.connection.connect_requested.connect(self._connect_device)
        self.connection.disconnect_requested.connect(self._disconnect_device)
        serial_layout.addWidget(self.connection)
        layout.addWidget(serial_group)

        layout.addWidget(self._create_status_group())
        layout.addWidget(self._create_lo_group())
        layout.addWidget(self._create_command_group())
        layout.addWidget(self._create_log_group())
        layout.addStretch()

    def _create_status_group(self) -> QGroupBox:
        """创建显示版本、温度、本振、衰减和锁定状态的表格。

        Returns:
            已初始化状态行映射的 Qt 分组控件。
        """
        group = QGroupBox("设备状态")
        group_layout = QVBoxLayout(group)
        labels = (
            "版本",
            "温度(原始值)",
            "TxLO",
            "RxLO",
            "Tx衰减(dB)",
            "Rx衰减(dB)",
            "锁定状态",
        )
        self.status_table = QTableWidget(len(labels), 2)
        self.status_table.setHorizontalHeaderLabels(["参数", "值"])
        self.status_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.status_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._status_rows: Dict[str, int] = {}
        for row, label in enumerate(labels):
            self._status_rows[label] = row
            self.status_table.setItem(row, 0, QTableWidgetItem(label))
            self.status_table.setItem(row, 1, QTableWidgetItem("N/A"))
        group_layout.addWidget(self.status_table)
        return group

    def _create_lo_group(self) -> QGroupBox:
        """创建收发本振预设选择与发送控件。

        Returns:
            使用 MHz 预设值的本振设置分组控件。
        """
        group = QGroupBox("本振设置")
        layout = QGridLayout(group)

        self.txlo_combo = QComboBox()
        self.txlo_combo.addItems([label for label, _ in TX_LO_OPTIONS])
        self.txlo_button = QPushButton("设置发射本振")
        self.txlo_button.clicked.connect(self._set_tx_lo)
        layout.addWidget(QLabel("发射本振:"), 0, 0)
        layout.addWidget(self.txlo_combo, 0, 1)
        layout.addWidget(self.txlo_button, 0, 2)

        self.rxlo_combo = QComboBox()
        self.rxlo_combo.addItems([label for label, _ in RX_LO_OPTIONS])
        self.rxlo_button = QPushButton("设置接收本振")
        self.rxlo_button.clicked.connect(self._set_rx_lo)
        layout.addWidget(QLabel("接收本振:"), 1, 0)
        layout.addWidget(self.rxlo_combo, 1, 1)
        layout.addWidget(self.rxlo_button, 1, 2)
        return group

    def _create_command_group(self) -> QGroupBox:
        """创建查询、复位和收发衰减命令分派控件。

        Returns:
            包含命令选择和衰减整数输入框的分组控件。
        """
        group = QGroupBox("命令")
        layout = QGridLayout(group)

        self.command_combo = QComboBox()
        self.command_combo.addItems(
            [
                "本振查询",
                "温度查询",
                "版本回读",
                "衰减查询",
                "发射衰减设置",
                "接收衰减设置",
                "复位",
            ]
        )
        self.parameter_edit = QLineEdit()
        self.parameter_edit.setPlaceholderText("衰减: 0-300 (值/10=dB)")
        self.send_button = QPushButton("发送指令")
        self.send_button.clicked.connect(self._send_selected_command)
        self.query_button = QPushButton("设备查询")
        self.query_button.clicked.connect(self._query_device)

        layout.addWidget(QLabel("命令:"), 0, 0)
        layout.addWidget(self.command_combo, 0, 1, 1, 2)
        layout.addWidget(QLabel("参数:"), 1, 0)
        layout.addWidget(self.parameter_edit, 1, 1, 1, 2)
        layout.addWidget(self.send_button, 2, 1)
        layout.addWidget(self.query_button, 2, 2)
        return group

    def _create_log_group(self) -> QGroupBox:
        """创建仅显示当前页面 Driver 日志的控件。

        Returns:
            含只读日志框和清除按钮的分组控件。
        """
        group = QGroupBox("日志")
        layout = QVBoxLayout(group)
        self.log_text = QPlainTextEdit()
        self.log_text.setMaximumHeight(100)
        self.log_text.setReadOnly(True)
        clear_button = QPushButton("清除")
        clear_button.clicked.connect(self.log_text.clear)
        layout.addWidget(self.log_text)
        layout.addWidget(clear_button)
        return group

    @Slot(str, int)
    def _connect_device(self, port_name: str, baudrate: int) -> None:
        """按用户选择创建并启动新的串口 Driver。

        Args:
            port_name: 要打开的串口名。
            baudrate: 目标串口波特率。

        状态:
            新连接前必须成功停止旧 Driver；各信号回调捕获该 Driver 实例，避免旧连接完成后
            覆盖当前页面状态。
        """
        if self._shutdown:
            self.connection.set_disconnected("页面已停止")
            return
        if not self._stop_driver():
            return
        self.connection.set_connecting()
        driver = self._driver_factory(port_name, baudrate)
        self._driver = driver
        driver.log_signal.connect(
            lambda message, current=driver: self._append_driver_log(current, message)
        )
        driver.status_signal.connect(
            lambda status, current=driver: self._on_driver_status(current, status)
        )
        driver.frame_signal.connect(self.frame_signal.emit)
        driver.opened_signal.connect(
            lambda success, message, current=driver: self._on_driver_opened(current, success, message)
        )
        driver.finished.connect(lambda current=driver: self._on_driver_finished(current))
        driver.start()

    def _on_driver_opened(self, driver: KaUDCDriver, success: bool, message: str) -> None:
        """仅接受当前 Driver 的打开结果并更新连接状态。

        Args:
            driver: 发出信号的 Driver 实例。
            success: 串口是否成功打开。
            message: 面向操作员的打开结果说明。
        """
        if driver is not self._driver:
            return
        if success:
            self.connection.set_connected(message)
        else:
            self.connection.set_disconnected(message)

    def _on_driver_finished(self, driver: KaUDCDriver) -> None:
        """处理 Driver 线程结束，且不清除新连接的状态。

        Args:
            driver: 已结束的 Driver 实例。
        """
        if driver is self._driver:
            self._driver = None
            self.connection.set_disconnected("串口已关闭")
        driver.deleteLater()

    def _append_driver_log(self, driver: KaUDCDriver, message: str) -> None:
        """将当前连接的 Driver 日志追加到面板。

        Args:
            driver: 日志来源 Driver。
            message: 要显示的诊断文本。
        """
        if driver is self._driver:
            self.log_text.appendPlainText(message)

    def _on_driver_status(self, driver: KaUDCDriver, status: dict) -> None:
        """仅将当前 Driver 的结构化响应更新到 UI。

        Args:
            driver: 状态来源 Driver。
            status: 已由协议层解码的命令响应字典。
        """
        if driver is self._driver:
            self._on_status(status)

    @Slot()
    def _disconnect_device(self) -> bool:
        """响应连接控件的断开请求。

        Returns:
            Driver 已安全停止并更新为未连接时为 ``True``。
        """
        stopped = self._stop_driver()
        if stopped:
            self.connection.set_disconnected()
        return stopped

    @Slot()
    def disconnect_device(self) -> bool:
        """断开串口；页面定时器由 workspace 的 activate/deactivate 管理。"""
        return self._disconnect_device()

    def _stop_driver(self) -> bool:
        """停止并释放当前 Driver，停止超时时保留对象供操作员重试。

        Returns:
            无 Driver 或 Driver 已确认停止时为 ``True``；停止超时时为 ``False``。
        """
        driver = self._driver
        if driver is not None:
            self.connection.set_stopping()
            if driver.stop() is False:
                self.connection.set_stop_failed("串口线程停止超时，请重试关闭")
                return False
            self._driver = None
            driver.deleteLater()
        return True

    def _active_driver(self) -> Optional[KaUDCDriver]:
        """取得可发送命令的当前 Driver。

        Returns:
            已运行的 Driver；未连接或已停止时显示提示并返回 ``None``。
        """
        if self._driver is None or not self._driver.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return None
        return self._driver

    @Slot()
    def _set_tx_lo(self) -> None:
        """发送当前选中的发射本振设置。

        状态:
            下拉预设以 MHz 传给 Driver；只有帧成功入队时才追加操作日志。
        """
        driver = self._active_driver()
        if driver is None:
            return
        label, freq_mhz = TX_LO_OPTIONS[self.txlo_combo.currentIndex()]
        if driver.set_tx_lo(freq_mhz):
            self.log_text.appendPlainText(f"设置发射本振: {label}")

    @Slot()
    def _set_rx_lo(self) -> None:
        """发送当前选中的接收本振设置。

        状态:
            下拉预设以 MHz 传给 Driver；只有帧成功入队时才追加操作日志。
        """
        driver = self._active_driver()
        if driver is None:
            return
        label, freq_mhz = RX_LO_OPTIONS[self.rxlo_combo.currentIndex()]
        if driver.set_rx_lo(freq_mhz):
            self.log_text.appendPlainText(f"设置接收本振: {label}")

    @Slot()
    def _send_selected_command(self) -> None:
        """按当前命令选择分派查询、复位或收发衰减设置。

        状态:
            查询与复位复用 Driver 语义方法；衰减输入必须是 ``0..300`` 的协议整数，
            对应 ``0.0..30.0 dB``，协议层拒绝时向操作员显示异常。
        """
        driver = self._active_driver()
        if driver is None:
            return

        command = self.command_combo.currentText()
        simple_commands = {
            "本振查询": driver.query_lo,
            "温度查询": driver.query_temperature,
            "版本回读": driver.query_version,
            "衰减查询": driver.query_attenuation,
            "复位": driver.send_reset,
        }
        action = simple_commands.get(command)
        if action is not None:
            if action():
                self.log_text.appendPlainText(f"发送命令: {command}")
            return

        try:
            attenuation = int(self.parameter_edit.text())
        except ValueError:
            QMessageBox.warning(self, "警告", "请输入有效的衰减整数")
            return
        try:
            if command == "发射衰减设置":
                sent = driver.set_tx_attenuation(attenuation)
            elif command == "接收衰减设置":
                sent = driver.set_rx_attenuation(attenuation)
            else:
                return
        except ValueError as exc:
            QMessageBox.warning(self, "警告", str(exc))
            return
        if sent:
            self.log_text.appendPlainText(f"发送命令: {command}")

    @Slot()
    def _query_device(self) -> None:
        """按短间隔依次发送版本、温度、本振和衰减查询。

        状态:
            使用 ``QTimer.singleShot`` 避免在 UI 线程阻塞；每次回调再次确认 Driver 仍是当前连接。
        """
        driver = self._active_driver()
        if driver is None:
            return
        method_names = ("query_version", "query_temperature", "query_lo", "query_attenuation")
        for index, method_name in enumerate(method_names):
            QTimer.singleShot(
                index * 50,
                lambda name=method_name, current=driver: self._invoke_driver(current, name),
            )
        self.log_text.appendPlainText("设备查询已发送")

    def _invoke_driver(self, driver: KaUDCDriver, method_name: str) -> None:
        """在延迟查询回调中安全调用仍有效的 Driver 方法。

        Args:
            driver: 定时器创建时捕获的 Driver。
            method_name: 无参数查询方法名。

        状态:
            若用户已断开或连接了新设备，旧回调不发送命令。
        """
        if driver is self._driver and driver.running:
            getattr(driver, method_name)()

    @Slot(dict)
    def _on_status(self, status: dict) -> None:
        """将协议层状态字典映射到状态表并转发给工作区。

        Args:
            status: 包含命令及其已解码字段的响应字典。本振单位为 MHz，衰减显示为 dB，
                温度当前显示原始字节。
        """
        if "version" in status:
            self._set_status("版本", f"0x{status['version']:02X}")
        if "temperature_raw" in status:
            self._set_status("温度(原始值)", status["temperature_raw"])
        if "tx_lo" in status:
            self._set_status("TxLO", status["tx_lo"])
        if "rx_lo" in status:
            self._set_status("RxLO", status["rx_lo"])
        if "tx_att_db" in status:
            self._set_status("Tx衰减(dB)", f"{status['tx_att_db']:.1f}")
        if "rx_att_db" in status:
            self._set_status("Rx衰减(dB)", f"{status['rx_att_db']:.1f}")
        if "lock_status" in status:
            rx_state = "Locked" if status["rx_locked"] else "Unlocked"
            tx_state = "Locked" if status["tx_locked"] else "Unlocked"
            ref_state = "Locked" if status["ref_locked"] else "Unlocked"
            self._set_status("锁定状态", f"RX:{rx_state} TX:{tx_state} REF:{ref_state}")
        if "status" in status:
            text = "复位完成" if status.get("status") == "reset_complete" else "复位失败"
            self.log_text.appendPlainText(text)
        self.status_signal.emit(status)

    def _set_status(self, label: str, value: object) -> None:
        """更新指定状态行的文本。

        Args:
            label: 初始化时建立的状态行名称。
            value: 要显示的值。
        """
        row = self._status_rows[label]
        self.status_table.item(row, 1).setText(str(value))

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
        """停止本页面后台活动；允许主窗口和 closeEvent 重复调用。"""

        if self._shutdown:
            return True
        if not self._stop_driver():
            return False
        self.connection.set_disconnected()
        timer = getattr(self.connection, "_timer", None)
        if timer is not None:
            timer.stop()
        self._shutdown = True
        return True

    def closeEvent(self, event) -> None:
        """关闭窗口前停止 Driver；停止失败时阻止 Qt 关闭。

        Args:
            event: Qt 关闭事件。
        """
        if not self.shutdown():
            event.ignore()
            return
        super().closeEvent(event)


DevicePanel = KaUDCPanel
