#!/usr/bin/env python3
"""
KauDC004A_TestTool - PyQt5 版本
设备控制测试工具 - 支持 KaUDC004A, AFDT1024_TX, AFDR1024_RX
"""

import sys
import serial
import serial.tools.list_ports
import queue
import threading
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QLineEdit,
    QPushButton,
    QGroupBox,
    QFormLayout,
    QRadioButton,
    QCheckBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QFrame,
    QTableWidget,
)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QFont
import time
import datetime
import struct

# 协议模块
from afdt1024_protocol import (
    build_tx_beam_frame,
    build_tx_enable_frame,
    build_tx_polarization_frame,
    build_pa_enable_frame,
    build_status_query_frame,
    build_rx_beam_frame,
    build_rx_enable_frame,
    build_rx_polarization_frame,
    build_rx_status_query_frame,
    parse_response as parse_afdt_response,
    parse_status_response,
    parse_rx_status_response,
    calculate_beam_values,
    POLARIZATION_LHCP,
    POLARIZATION_RHCP,
    ADDR_CMD_NAMES,
    FRAME_HEADER,
)

# KaUDC004A 协议
from protocol import (
    build_frame as kaudc_build_frame,
    parse_response as kaudc_parse_response,
)


# ============================================================
# 常量定义
# ============================================================

BAUD_RATES = ["9600", "19200", "38400", "115200", "460800", "921600"]

# TX 波束频率范围
TX_MIN_FREQ = 27500
TX_MAX_FREQ = 31000

# RX 波束频率范围
RX_MIN_FREQ = 17700
RX_MAX_FREQ = 21200

# KaUDC004A LO 频率选项
TX_LO_OPTIONS = [
    ("26.55GHz (27.5-28.35)", 0x00),
    ("27.40GHz (28.35-29.2)", 0x01),
    ("28.05GHz (29.00-30.0)", 0x02),
    ("29.05GHz (30.00-31.0)", 0x03),
]

RX_LO_OPTIONS = [
    ("16.75GHz (17.7-18.2)", 0x00),
    ("17.25GHz (18.2-19.2)", 0x01),
    ("18.25GHz (19.2-20.2)", 0x02),
    ("19.25GHz (20.2-21.2)", 0x03),
]


# ============================================================
# SerialWorker - 后台串口线程（双线程架构：接收 + 处理分离）
# ============================================================


class SerialWorker(QThread):
    """串口后台工作线程 - 双线程架构
    - 接收线程：只负责从串口读取数据，放入队列
    - 处理线程：负责从队列取出数据并解析
    """

    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(dict)
    config_success_signal = pyqtSignal(str)

    def __init__(self, port, baudrate, device_type="TX", parent=None):
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self.device_type = device_type
        self.running = False
        self.ser = None

        # 线程间通信队列
        self.data_queue = queue.Queue(maxsize=100)
        self.buffer = bytearray()
        self.buffer_lock = threading.Lock()

        # 接收线程
        self.receive_thread = None
        self.receive_running = False

    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.01)
            self.running = True
            self.log_signal.emit(f"串口已打开: {self.port} @ {self.baudrate}")

            # 启动接收线程
            self.receive_running = True
            self.receive_thread = threading.Thread(
                target=self._receive_loop, daemon=True
            )
            self.receive_thread.start()

            # 主循环：处理队列中的数据
            while self.running:
                try:
                    # 从队列获取数据（阻塞等待，最多50ms）
                    try:
                        chunk = self.data_queue.get(timeout=0.05)
                        with self.buffer_lock:
                            self.buffer.extend(chunk)
                    except queue.Empty:
                        continue

                    # 处理缓冲区中的数据
                    self._process_buffer()

                except Exception:
                    time.sleep(0.01)

        except Exception as e:
            self.log_signal.emit(f"错误: {e}")
        finally:
            self.receive_running = False
            if self.receive_thread:
                self.receive_thread.join(timeout=0.5)
            if self.ser and self.ser.is_open:
                self.ser.close()
            self.log_signal.emit("串口已关闭")

    def _receive_loop(self):
        """接收线程：只负责从串口读取数据，放入队列"""
        while self.receive_running:
            try:
                if self.ser and self.ser.is_open:
                    n = self.ser.in_waiting
                    if n > 0:
                        chunk = self.ser.read(min(n, 1024))
                        if chunk:
                            try:
                                self.data_queue.put_nowait(chunk)
                            except queue.Full:
                                # 队列满了，丢弃旧数据
                                try:
                                    self.data_queue.get_nowait()
                                    self.data_queue.put_nowait(chunk)
                                except queue.Empty:
                                    pass
                    else:
                        time.sleep(0.005)
                else:
                    time.sleep(0.01)
            except Exception:
                time.sleep(0.01)

    def _process_buffer(self):
        """处理缓冲区中的数据帧"""
        with self.buffer_lock:
            if len(self.buffer) < 6:
                return

            # 查找帧头
            start_idx = -1
            for i in range(len(self.buffer) - 2):
                if (
                    self.buffer[i] == 0x50
                    and self.buffer[i + 1] == 0x53
                    and self.buffer[i + 2] == 0x41
                ):
                    start_idx = i
                    break

            if start_idx > 0:
                # 丢弃无效的头部数据
                del self.buffer[:start_idx]

            if len(self.buffer) < 6:
                return

            length = self.buffer[4]
            total_len = 5 + length + 1

            # 验证帧长度合法性
            if (
                6 <= length <= 255
                and total_len <= 263
                and len(self.buffer) >= total_len
            ):
                frame = bytes(self.buffer[:total_len])
                del self.buffer[:total_len]

                # 在主线程中处理帧（通过信号）
                self._process_frame(frame)
            elif total_len > 263 or length < 6:
                # 无效长度，丢弃第一字节
                del self.buffer[0]

    def _process_frame(self, frame):
        """解析并处理帧"""
        try:
            parsed, msg = parse_afdt_response(frame, has_rx_status_bug=False)

            if not parsed and self.device_type == "RX":
                parsed, msg = parse_afdt_response(frame, has_rx_status_bug=True)

            if parsed:
                addr = parsed.get("addr")

                if addr in ADDR_CMD_NAMES:
                    self.log_signal.emit(f"<<< 收到: {frame.hex().upper()[:48]}")
                elif addr is None and parsed.get("payload"):
                    if self.device_type == "TX":
                        status_info, status_msg = parse_status_response(
                            parsed["payload"]
                        )
                    else:
                        status_info, status_msg = parse_rx_status_response(
                            parsed["payload"]
                        )

                    if status_msg == "OK" and status_info:
                        self.status_signal.emit(status_info)
                        self.log_signal.emit(f"<<< 状态已更新")
                else:
                    self.log_signal.emit(f"<<< 收到: {frame.hex().upper()[:48]}")
            else:
                self.log_signal.emit(f"<<< 解析失败: {frame.hex().upper()[:48]}")
        except Exception as e:
            self.log_signal.emit(f"<<< 处理异常: {str(e)}")

    def send_frame(self, frame):
        if self.ser and self.ser.is_open:
            self.ser.write(frame)

    def stop(self):
        self.running = False


# ============================================================
# KaUDC Worker - KaUDC004A 专用线程（双线程架构）
# ============================================================


class KaUDCWorker(QThread):
    """KaUDC004A 串口后台工作线程 - 双线程架构"""

    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(dict)
    response_signal = pyqtSignal(str, str)  # cmd_name, value

    def __init__(self, port, baudrate, parent=None):
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self.running = False
        self.ser = None

        # 线程间通信队列
        self.data_queue = queue.Queue(maxsize=100)
        self.buffer = bytearray()
        self.buffer_lock = threading.Lock()

        # 接收线程
        self.receive_thread = None
        self.receive_running = False

    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.01)
            self.running = True
            self.log_signal.emit(f"串口已打开: {self.port} @ {self.baudrate}")

            # 启动接收线程
            self.receive_running = True
            self.receive_thread = threading.Thread(
                target=self._receive_loop, daemon=True
            )
            self.receive_thread.start()

            # 主循环：处理队列中的数据
            while self.running:
                try:
                    try:
                        chunk = self.data_queue.get(timeout=0.05)
                        with self.buffer_lock:
                            self.buffer.extend(chunk)
                    except queue.Empty:
                        continue

                    # 处理缓冲区
                    self._process_buffer()

                except Exception:
                    time.sleep(0.01)

        except Exception as e:
            self.log_signal.emit(f"错误: {e}")
        finally:
            self.receive_running = False
            if self.receive_thread:
                self.receive_thread.join(timeout=0.5)
            if self.ser and self.ser.is_open:
                self.ser.close()
            self.log_signal.emit("串口已关闭")

    def _receive_loop(self):
        """接收线程：只负责从串口读取数据，放入队列"""
        while self.receive_running:
            try:
                if self.ser and self.ser.is_open:
                    n = self.ser.in_waiting
                    if n > 0:
                        chunk = self.ser.read(min(n, 1024))
                        if chunk:
                            try:
                                self.data_queue.put_nowait(chunk)
                            except queue.Full:
                                pass
                    else:
                        time.sleep(0.005)
                else:
                    time.sleep(0.01)
            except Exception:
                time.sleep(0.01)

    def _process_buffer(self):
        """处理缓冲区中的数据帧"""
        with self.buffer_lock:
            while len(self.buffer) >= 12:
                if self.buffer[0] != 0xAA or self.buffer[1] != 0x55:
                    del self.buffer[0]
                    continue

                frame = bytes(self.buffer[:12])
                del self.buffer[:12]
                self._process_frame(frame)

    def _process_frame(self, frame):
        try:
            data, msg = kaudc_parse_response(frame)
            if data:
                self.log_signal.emit(f"<<< 收到响应")
                # 解析响应数据
                # data[0:2] 是命令码, data[2:6] 是数据
                cmd = data[0]
                if cmd == 0x0B:  # 版本回读
                    self.response_signal.emit("版本回读", data[2:6].hex())
                elif cmd == 0x0C:  # 温度查询
                    temp = int.from_bytes(data[2:4], "big")
                    self.status_signal.emit({"temperature": temp})
                elif cmd == 0x13:  # 本振查询
                    lo_data = data[2]
                    self.response_signal.emit(
                        "本振查询", f"TxLO={lo_data >> 4}, RxLO={lo_data & 0x0F}"
                    )
                elif cmd == 0x16:  # 衰减查询
                    att_data = int.from_bytes(data[2:4], "big")
                    self.response_signal.emit(
                        "衰减查询", f"TxAtt={att_data >> 8}, RxAtt={att_data & 0xFF}"
                    )
        except Exception as e:
            pass

    def send_frame(self, frame):
        if self.ser and self.ser.is_open:
            self.ser.write(frame)

    def stop(self):
        self.running = False


# ============================================================
# DevicePanel 基类
# ============================================================


class DevicePanel(QFrame):
    """设备控制面板基类"""

    def __init__(self, title, device_type, parent=None):
        super().__init__(parent)
        self.device_type = device_type
        self.worker = None
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self._setup_ui(title)

    def _setup_ui(self, title):
        raise NotImplementedError

    def _create_serial_settings(self, layout):
        serial_group = QGroupBox("串口设置")
        serial_layout = QHBoxLayout()

        self.port_cb = QComboBox()
        self.baud_cb = QComboBox()
        self.baud_cb.addItems(BAUD_RATES)
        self.baud_cb.setCurrentText("115200")
        self.connect_btn = QPushButton("打开串口")
        self.connect_btn.clicked.connect(self._on_connect_clicked)

        serial_layout.addWidget(QLabel("端口:"))
        serial_layout.addWidget(self.port_cb)
        serial_layout.addWidget(QLabel("波特率:"))
        serial_layout.addWidget(self.baud_cb)
        serial_layout.addWidget(self.connect_btn)

        serial_group.setLayout(serial_layout)
        layout.addWidget(serial_group)

        self._refresh_ports()
        self.port_timer = QTimer(self)
        self.port_timer.timeout.connect(self._refresh_ports)
        self.port_timer.start(2000)

    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        current = self.port_cb.currentText()
        self.port_cb.clear()
        self.port_cb.addItems(ports)
        if current in ports:
            self.port_cb.setCurrentText(current)

    def _on_connect_clicked(self):
        if self.worker and self.worker.running:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        port = self.port_cb.currentText()
        if not port:
            QMessageBox.warning(self, "警告", "请选择串口")
            return

        baudrate = int(self.baud_cb.currentText())
        self._do_connect(port, baudrate)
        self.connect_btn.setText("关闭串口")

    def _do_connect(self, port, baudrate):
        raise NotImplementedError

    def _disconnect(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait(1000)
            self.worker = None
        self.connect_btn.setText("打开串口")

    def _on_log(self, msg):
        self.log_text.appendPlainText(msg)

    def _on_status(self, status_info):
        raise NotImplementedError

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
            self.worker.wait(1000)
        super().closeEvent(event)


# ============================================================
# KaUDC004A Panel
# ============================================================


class KaUDCPanel(DevicePanel):
    """KaUDC004A 设备控制面板"""

    def __init__(self, parent=None):
        super().__init__("KaUDC004A", "KaUDC", parent)

    def _setup_ui(self, title):
        layout = QVBoxLayout(self)

        # 串口设置
        self._create_serial_settings(layout)

        # 状态表格
        status_group = QGroupBox("设备状态")
        status_layout = QFormLayout()
        self.status_table = QTableWidget(7, 2)
        self.status_table.setHorizontalHeaderLabels(["参数", "值"])
        self.status_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.status_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.setItem(0, 0, QTableWidgetItem("版本"))
        self.status_table.setItem(0, 1, QTableWidgetItem("N/A"))
        self.status_table.setItem(1, 0, QTableWidgetItem("温度(°C)"))
        self.status_table.setItem(1, 1, QTableWidgetItem("N/A"))
        self.status_table.setItem(2, 0, QTableWidgetItem("TxLO"))
        self.status_table.setItem(2, 1, QTableWidgetItem("N/A"))
        self.status_table.setItem(3, 0, QTableWidgetItem("RxLO"))
        self.status_table.setItem(3, 1, QTableWidgetItem("N/A"))
        self.status_table.setItem(4, 0, QTableWidgetItem("Tx衰减(dB)"))
        self.status_table.setItem(4, 1, QTableWidgetItem("N/A"))
        self.status_table.setItem(5, 0, QTableWidgetItem("Rx衰减(dB)"))
        self.status_table.setItem(5, 1, QTableWidgetItem("N/A"))
        self.status_table.setItem(6, 0, QTableWidgetItem("锁定状态"))
        self.status_table.setItem(6, 1, QTableWidgetItem("N/A"))
        status_layout.addWidget(self.status_table)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # LO设置
        lo_group = QGroupBox("本振设置")
        lo_layout = QGridLayout()

        lo_layout.addWidget(QLabel("发射本振:"), 0, 0)
        self.txlo_cb = QComboBox()
        self.txlo_cb.addItems([opt[0] for opt in TX_LO_OPTIONS])
        self.txlo_cb.setCurrentIndex(0)
        lo_layout.addWidget(self.txlo_cb, 0, 1)
        self.txlo_set_btn = QPushButton("设置发射本振")
        self.txlo_set_btn.clicked.connect(self._on_set_txlo)
        lo_layout.addWidget(self.txlo_set_btn, 0, 2)

        lo_layout.addWidget(QLabel("接收本振:"), 1, 0)
        self.rxlo_cb = QComboBox()
        self.rxlo_cb.addItems([opt[0] for opt in RX_LO_OPTIONS])
        self.rxlo_cb.setCurrentIndex(0)
        lo_layout.addWidget(self.rxlo_cb, 1, 1)
        self.rxlo_set_btn = QPushButton("设置接收本振")
        self.rxlo_set_btn.clicked.connect(self._on_set_rxlo)
        lo_layout.addWidget(self.rxlo_set_btn, 1, 2)

        lo_group.setLayout(lo_layout)
        layout.addWidget(lo_group)

        # 命令选择
        cmd_group = QGroupBox("命令")
        cmd_layout = QGridLayout()

        self.cmd_cb = QComboBox()
        self.cmd_cb.addItems(
            [
                "本振查询",
                "温度查询",
                "版本回读",
                "衰减查询",
                "发射衰减设置",
                "接收衰减设置",
            ]
        )
        cmd_layout.addWidget(QLabel("命令:"), 0, 0)
        cmd_layout.addWidget(self.cmd_cb, 0, 1, 1, 2)

        cmd_layout.addWidget(QLabel("参数:"), 1, 0)
        self.param_entry = QLineEdit()
        self.param_entry.setPlaceholderText("衰减: 0-30")
        cmd_layout.addWidget(self.param_entry, 1, 1, 1, 2)

        self.send_cmd_btn = QPushButton("发送指令")
        self.send_cmd_btn.clicked.connect(self._on_send_command)
        cmd_layout.addWidget(self.send_cmd_btn, 2, 1)

        self.query_device_btn = QPushButton("设备查询")
        self.query_device_btn.clicked.connect(self._on_query_device)
        cmd_layout.addWidget(self.query_device_btn, 2, 2)

        cmd_group.setLayout(cmd_layout)
        layout.addWidget(cmd_group)

        # 日志窗口
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        self.log_text = QPlainTextEdit()
        self.log_text.setMaximumHeight(100)
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_btn)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        layout.addStretch()

    def _do_connect(self, port, baudrate):
        self.worker = KaUDCWorker(port, baudrate)
        self.worker.log_signal.connect(self._on_log)
        self.worker.status_signal.connect(self._on_status)
        self.worker.response_signal.connect(self._on_response)
        self.worker.start()

    def _on_set_txlo(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        idx = self.txlo_cb.currentIndex()
        lo_cmd = TX_LO_OPTIONS[idx][1] << 4 | 0x01
        frame = kaudc_build_frame(bytes([0x11, 0x00, 0x00, lo_cmd, 0x00, 0x00]))
        self.worker.send_frame(frame)
        self.log_text.appendPlainText(f"设置发射本振: {TX_LO_OPTIONS[idx][0]}")

    def _on_set_rxlo(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        idx = self.rxlo_cb.currentIndex()
        lo_cmd = 0x10 | RX_LO_OPTIONS[idx][1]
        frame = kaudc_build_frame(bytes([lo_cmd, 0x00, 0x00, 0x01, 0x00, 0x00]))
        self.worker.send_frame(frame)
        self.log_text.appendPlainText(f"设置接收本振: {RX_LO_OPTIONS[idx][0]}")

    def _on_send_command(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return

        cmd = self.cmd_cb.currentText()
        param = self.param_entry.text()

        if cmd == "本振查询":
            frame = kaudc_build_frame(bytes([0x13, 0x00, 0x00, 0x00, 0x00, 0x00]))
        elif cmd == "温度查询":
            frame = kaudc_build_frame(bytes([0x0C, 0x00, 0x00, 0x00, 0x00, 0x00]))
        elif cmd == "版本回读":
            frame = kaudc_build_frame(bytes([0x0B, 0x00, 0x00, 0x00, 0x00, 0x00]))
        elif cmd == "衰减查询":
            frame = kaudc_build_frame(bytes([0x16, 0x00, 0x00, 0x00, 0x00, 0x00]))
        elif cmd == "发射衰减设置":
            try:
                att = int(param)
                if 0 <= att <= 30:
                    att_bytes = att.to_bytes(2, "big")
                    frame = kaudc_build_frame(
                        bytes([0x14, 0x00, 0x00]) + att_bytes + bytes([0x00])
                    )
                else:
                    QMessageBox.warning(self, "警告", "衰减必须在0-30之间")
                    return
            except ValueError:
                QMessageBox.warning(self, "警告", "请输入有效的数字")
                return
        elif cmd == "接收衰减设置":
            try:
                att = int(param)
                if 0 <= att <= 30:
                    att_bytes = att.to_bytes(2, "big")
                    frame = kaudc_build_frame(
                        bytes([0x15, 0x00, 0x00]) + att_bytes + bytes([0x00])
                    )
                else:
                    QMessageBox.warning(self, "警告", "衰减必须在0-30之间")
                    return
            except ValueError:
                QMessageBox.warning(self, "警告", "请输入有效的数字")
                return
        else:
            return

        self.worker.send_frame(frame)
        self.log_text.appendPlainText(f"发送命令: {cmd}")

    def _on_query_device(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return

        # 查询版本、温度、本振、衰减
        for cmd in [0x0B, 0x0C, 0x13, 0x16]:
            frame = kaudc_build_frame(bytes([cmd, 0x00, 0x00, 0x00, 0x00, 0x00]))
            self.worker.send_frame(frame)
            time.sleep(0.05)

        self.log_text.appendPlainText("设备查询已发送")

    def _on_status(self, status_info):
        if "temperature" in status_info:
            self.status_table.item(1, 1).setText(str(status_info["temperature"]))

    def _on_response(self, cmd_name, value):
        if cmd_name == "版本回读":
            self.status_table.item(0, 1).setText(value)
        elif cmd_name == "本振查询":
            parts = value.split(", ")
            if len(parts) == 2:
                self.status_table.item(2, 1).setText(parts[0].split("=")[1])
                self.status_table.item(3, 1).setText(parts[1].split("=")[1])
        elif cmd_name == "衰减查询":
            parts = value.split(", ")
            if len(parts) == 2:
                self.status_table.item(4, 1).setText(parts[0].split("=")[1])
                self.status_table.item(5, 1).setText(parts[1].split("=")[1])


# ============================================================
# TX Panel (AFDT1024)
# ============================================================


class TXPanel(DevicePanel):
    """TX设备控制面板"""

    def __init__(self, parent=None):
        super().__init__("Ka1024_TX", "TX", parent)

    def _setup_ui(self, title):
        layout = QVBoxLayout(self)

        # 串口设置
        self._create_serial_settings(layout)

        # 子阵ID
        id_group = QGroupBox("子阵设置")
        id_layout = QHBoxLayout()
        id_layout.addWidget(QLabel("子阵ID:"))
        self.id_spin = QSpinBox()
        self.id_spin.setRange(1, 255)
        self.id_spin.setValue(1)
        id_layout.addWidget(self.id_spin)
        id_group.setLayout(id_layout)
        layout.addWidget(id_group)

        # 波束设置
        beam_group = QGroupBox("TX波束设置")
        beam_layout = QGridLayout()

        beam_layout.addWidget(QLabel("频率(MHz):"), 0, 0)
        self.freq_entry = QLineEdit("27500")
        beam_layout.addWidget(self.freq_entry, 0, 1)

        beam_layout.addWidget(QLabel("θ角度:"), 1, 0)
        self.theta_entry = QLineEdit("0")
        beam_layout.addWidget(self.theta_entry, 1, 1)

        beam_layout.addWidget(QLabel("φ角度:"), 2, 0)
        self.phi_entry = QLineEdit("0")
        beam_layout.addWidget(self.phi_entry, 2, 1)

        self.set_beam_btn = QPushButton("设置波束")
        self.set_beam_btn.clicked.connect(self._on_set_beam)
        beam_layout.addWidget(self.set_beam_btn, 0, 2, 3, 1)

        beam_group.setLayout(beam_layout)
        layout.addWidget(beam_group)

        # 阵列使能
        array_group = QGroupBox("TX阵列")
        array_layout = QHBoxLayout()
        self.array_enable_cb = QCheckBox("使能")
        self.array_apply_btn = QPushButton("应用")
        self.array_apply_btn.clicked.connect(self._on_set_array)
        array_layout.addWidget(self.array_enable_cb)
        array_layout.addWidget(self.array_apply_btn)
        array_group.setLayout(array_layout)
        layout.addWidget(array_group)

        # PA使能
        pa_group = QGroupBox("推动PA")
        pa_layout = QHBoxLayout()
        self.pa_enable_cb = QCheckBox("使能")
        self.pa_apply_btn = QPushButton("应用")
        self.pa_apply_btn.clicked.connect(self._on_set_pa)
        pa_layout.addWidget(self.pa_enable_cb)
        pa_layout.addWidget(self.pa_apply_btn)
        pa_group.setLayout(pa_layout)
        layout.addWidget(pa_group)

        # 极化设置
        pol_group = QGroupBox("极化设置")
        pol_layout = QHBoxLayout()
        self.pol_lhcp = QRadioButton("LHCP")
        self.pol_rhcp = QRadioButton("RHCP")
        self.pol_lhcp.setChecked(True)
        self.pol_set_btn = QPushButton("设置")
        self.pol_set_btn.clicked.connect(self._on_set_polarization)
        pol_layout.addWidget(self.pol_lhcp)
        pol_layout.addWidget(self.pol_rhcp)
        pol_layout.addWidget(self.pol_set_btn)
        pol_group.setLayout(pol_layout)
        layout.addWidget(pol_group)

        # 状态查询
        self.query_btn = QPushButton("查询状态")
        self.query_btn.clicked.connect(self._on_query_status)
        layout.addWidget(self.query_btn)

        # 状态显示
        status_group = QGroupBox("状态")
        status_layout = QFormLayout()
        self.voltage_label = QLabel("N/A")
        self.temp_label = QLabel("N/A")
        status_layout.addRow("输入电压(V):", self.voltage_label)
        status_layout.addRow("温度(°C):", self.temp_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # 日志窗口
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        self.log_text = QPlainTextEdit()
        self.log_text.setMaximumHeight(100)
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_btn)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        layout.addStretch()

    def _do_connect(self, port, baudrate):
        self.worker = SerialWorker(port, baudrate, "TX")
        self.worker.log_signal.connect(self._on_log)
        self.worker.status_signal.connect(self._on_status)
        self.worker.config_success_signal.connect(self._on_config_success)
        self.worker.start()

    def _on_set_beam(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        try:
            device_id = self.id_spin.value()
            freq = float(self.freq_entry.text())
            theta = float(self.theta_entry.text())
            phi = float(self.phi_entry.text())

            if not (TX_MIN_FREQ <= freq <= TX_MAX_FREQ):
                QMessageBox.warning(
                    self, "警告", f"频率必须在{TX_MIN_FREQ}-{TX_MAX_FREQ} MHz之间"
                )
                return

            freq_num = int((freq - 27500) / 50)
            if not (0 <= freq_num <= 70):
                QMessageBox.warning(self, "警告", "频段号超出范围")
                return

            beam_h, beam_v = calculate_beam_values(theta, phi, freq, is_tx=True)
            frame = build_tx_beam_frame(device_id, freq_num, beam_h, beam_v)
            self.worker.send_frame(frame)
            self.log_text.appendPlainText(f">>> 发送波束设置")
        except ValueError:
            QMessageBox.warning(self, "警告", "请输入有效的数字")

    def _on_set_array(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        try:
            device_id = self.id_spin.value()
            enable = self.array_enable_cb.isChecked()
            frame = build_tx_enable_frame(device_id, enable)
            self.worker.send_frame(frame)
            self.log_text.appendPlainText(f">>> 发送阵列使能设置")
        except Exception as e:
            QMessageBox.warning(self, "警告", str(e))

    def _on_set_pa(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        try:
            device_id = self.id_spin.value()
            enable = self.pa_enable_cb.isChecked()
            frame = build_pa_enable_frame(device_id, enable)
            self.worker.send_frame(frame)
            self.log_text.appendPlainText(f">>> 发送PA使能设置")
        except Exception as e:
            QMessageBox.warning(self, "警告", str(e))

    def _on_set_polarization(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        try:
            device_id = self.id_spin.value()
            pol = POLARIZATION_RHCP if self.pol_rhcp.isChecked() else POLARIZATION_LHCP
            frame = build_tx_polarization_frame(device_id, pol)
            self.worker.send_frame(frame)
            self.log_text.appendPlainText(f">>> 发送极化设置")
        except Exception as e:
            QMessageBox.warning(self, "警告", str(e))

    def _on_query_status(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        try:
            device_id = self.id_spin.value()
            frame = build_status_query_frame(device_id)
            self.worker.send_frame(frame)
            self.log_text.appendPlainText(f">>> 发送状态查询")
        except Exception as e:
            QMessageBox.warning(self, "警告", str(e))

    def _on_status(self, status_info):
        vcc = status_info.get("sys_vcc", 0)
        temp = status_info.get("sys_temp", 0)
        self.voltage_label.setText(f"{vcc:.1f}")
        self.temp_label.setText(f"{temp}")

    def _on_config_success(self, cmd_name):
        pass


# ============================================================
# RX Panel (AFDR1024)
# ============================================================


class RXPanel(DevicePanel):
    """RX设备控制面板"""

    def __init__(self, parent=None):
        super().__init__("Ka1024_RX", "RX", parent)

    def _setup_ui(self, title):
        layout = QVBoxLayout(self)

        # 串口设置
        self._create_serial_settings(layout)

        # 子阵ID
        id_group = QGroupBox("子阵设置")
        id_layout = QHBoxLayout()
        id_layout.addWidget(QLabel("子阵ID:"))
        self.id_spin = QSpinBox()
        self.id_spin.setRange(1, 255)
        self.id_spin.setValue(1)
        id_layout.addWidget(self.id_spin)
        id_group.setLayout(id_layout)
        layout.addWidget(id_group)

        # 波束设置
        beam_group = QGroupBox("RX波束设置")
        beam_layout = QGridLayout()

        beam_layout.addWidget(QLabel("频率(MHz):"), 0, 0)
        self.freq_entry = QLineEdit("20270")
        beam_layout.addWidget(self.freq_entry, 0, 1)

        beam_layout.addWidget(QLabel("θ角度:"), 1, 0)
        self.theta_entry = QLineEdit("0")
        beam_layout.addWidget(self.theta_entry, 1, 1)

        beam_layout.addWidget(QLabel("φ角度:"), 2, 0)
        self.phi_entry = QLineEdit("0")
        beam_layout.addWidget(self.phi_entry, 2, 1)

        self.set_beam_btn = QPushButton("设置波束")
        self.set_beam_btn.clicked.connect(self._on_set_beam)
        beam_layout.addWidget(self.set_beam_btn, 0, 2, 3, 1)

        beam_group.setLayout(beam_layout)
        layout.addWidget(beam_group)

        # 阵列使能
        array_group = QGroupBox("RX阵列")
        array_layout = QHBoxLayout()
        self.array_enable_cb = QCheckBox("使能")
        self.array_apply_btn = QPushButton("应用")
        self.array_apply_btn.clicked.connect(self._on_set_array)
        array_layout.addWidget(self.array_enable_cb)
        array_layout.addWidget(self.array_apply_btn)
        array_group.setLayout(array_layout)
        layout.addWidget(array_group)

        # 极化设置
        pol_group = QGroupBox("极化设置")
        pol_layout = QHBoxLayout()
        self.pol_lhcp = QRadioButton("LHCP")
        self.pol_rhcp = QRadioButton("RHCP")
        self.pol_lhcp.setChecked(True)
        self.pol_set_btn = QPushButton("设置")
        self.pol_set_btn.clicked.connect(self._on_set_polarization)
        pol_layout.addWidget(self.pol_lhcp)
        pol_layout.addWidget(self.pol_rhcp)
        pol_layout.addWidget(self.pol_set_btn)
        pol_group.setLayout(pol_layout)
        layout.addWidget(pol_group)

        # 状态查询
        self.query_btn = QPushButton("查询状态")
        self.query_btn.clicked.connect(self._on_query_status)
        layout.addWidget(self.query_btn)

        # 状态显示
        status_group = QGroupBox("状态")
        status_layout = QFormLayout()
        self.voltage_label = QLabel("N/A")
        self.temp_label = QLabel("N/A")
        status_layout.addRow("输入电压(V):", self.voltage_label)
        status_layout.addRow("温度(°C):", self.temp_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # 日志窗口
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        self.log_text = QPlainTextEdit()
        self.log_text.setMaximumHeight(100)
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_btn)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        layout.addStretch()

    def _do_connect(self, port, baudrate):
        self.worker = SerialWorker(port, baudrate, "RX")
        self.worker.log_signal.connect(self._on_log)
        self.worker.status_signal.connect(self._on_status)
        self.worker.config_success_signal.connect(self._on_config_success)
        self.worker.start()

    def _on_set_beam(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        try:
            device_id = self.id_spin.value()
            freq = float(self.freq_entry.text())
            theta = float(self.theta_entry.text())
            phi = float(self.phi_entry.text())

            if not (RX_MIN_FREQ <= freq <= RX_MAX_FREQ):
                QMessageBox.warning(
                    self, "警告", f"频率必须在{RX_MIN_FREQ}-{RX_MAX_FREQ} MHz之间"
                )
                return

            freq_num = int((freq - 17700) / 50)
            if not (0 <= freq_num <= 70):
                QMessageBox.warning(self, "警告", "频段号超出范围")
                return

            beam_h, beam_v = calculate_beam_values(theta, phi, freq, is_tx=False)
            frame = build_rx_beam_frame(device_id, freq_num, beam_v, beam_h)
            self.worker.send_frame(frame)
            self.log_text.appendPlainText(f">>> 发送波束设置")
        except ValueError:
            QMessageBox.warning(self, "警告", "请输入有效的数字")

    def _on_set_array(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        try:
            device_id = self.id_spin.value()
            enable = self.array_enable_cb.isChecked()
            frame = build_rx_enable_frame(device_id, enable)
            self.worker.send_frame(frame)
            self.log_text.appendPlainText(f">>> 发送阵列使能设置")
        except Exception as e:
            QMessageBox.warning(self, "警告", str(e))

    def _on_set_pa(self):
        self.log_text.appendPlainText("RX设备不支持PA使能")

    def _on_set_polarization(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        try:
            device_id = self.id_spin.value()
            pol = POLARIZATION_RHCP if self.pol_rhcp.isChecked() else POLARIZATION_LHCP
            frame = build_rx_polarization_frame(device_id, pol)
            self.worker.send_frame(frame)
            self.log_text.appendPlainText(f">>> 发送极化设置")
        except Exception as e:
            QMessageBox.warning(self, "警告", str(e))

    def _on_query_status(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        try:
            device_id = self.id_spin.value()
            frame = build_rx_status_query_frame(device_id)
            self.worker.send_frame(frame)
            self.log_text.appendPlainText(f">>> 发送状态查询")
        except Exception as e:
            QMessageBox.warning(self, "警告", str(e))

    def _on_status(self, status_info):
        vcc = status_info.get("sys_vcc", 0)
        temp = status_info.get("sys_temp", 0)
        self.voltage_label.setText(f"{vcc:.1f}")
        self.temp_label.setText(f"{temp}")

    def _on_config_success(self, cmd_name):
        pass


# ============================================================
# 主窗口
# ============================================================


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KauDC004A TestTool - PyQt5")
        self.setGeometry(100, 100, 1200, 700)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)

        # KaUDC004A 面板
        self.kaudc_panel = KaUDCPanel()
        main_layout.addWidget(self.kaudc_panel, 1)

        # TX面板
        self.tx_panel = TXPanel()
        main_layout.addWidget(self.tx_panel, 1)

        # RX面板
        self.rx_panel = RXPanel()
        main_layout.addWidget(self.rx_panel, 1)

    def closeEvent(self, event):
        self.kaudc_panel._disconnect()
        self.tx_panel._disconnect()
        self.rx_panel._disconnect()
        super().closeEvent(event)


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
