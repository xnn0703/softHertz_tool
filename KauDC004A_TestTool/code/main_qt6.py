#!/usr/bin/env python3
"""
KauDC004A_TestTool - PySide6 + pyserial 版本
设备控制测试工具 - 支持 KaUDC004A, AFDT1024_TX, AFDR1024_RX

架构: PySide6 UI + pyserial 串口 + Qt 信号通知 UI
"""

import sys

from PySide6.QtWidgets import (
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
    QScrollArea,
)
from PySide6.QtCore import QThread, Signal, Slot, QTimer, Qt
from PySide6.QtGui import QFont

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
    STATUS_RETURN_ADDRS,
    ADDR_STATUS_QUERY,
    ADDR_RX_STATUS_QUERY,
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

# KaUDC004A LO 频率选项 (单位: MHz)
TX_LO_OPTIONS = [
    ("26.55GHz (27.5-28.35)", 26550),
    ("27.40GHz (28.35-29.2)", 27400),
    ("28.05GHz (29.00-30.0)", 28050),
    ("29.05GHz (30.00-31.0)", 29050),
]

RX_LO_OPTIONS = [
    ("16.75GHz (17.7-18.2)", 16750),
    ("17.25GHz (18.2-19.2)", 17250),
    ("18.25GHz (19.2-20.2)", 18250),
    ("19.25GHz (20.2-21.2)", 19250),
]


# ============================================================
# SerialWorker - pyserial + Qt 信号架构
# ============================================================


class SerialWorker(QThread):
    """串口后台工作线程 - 使用 pyserial 读取 + Qt 信号通知
    原因: QSerialPort 在 QThread 中有线程亲和性问题，改用 pyserial
    """

    log_signal = Signal(str)
    status_signal = Signal(dict)
    config_success_signal = Signal(str)

    def __init__(self, port_name, baudrate, device_type="TX", parent=None):
        super().__init__(parent)
        self.port_name = port_name
        self.baudrate = baudrate
        self.device_type = device_type
        self.running = False
        self.serial = None
        self.buffer = bytearray()

    def run(self):
        import serial
        import serial.tools.list_ports

        try:
            self.serial = serial.Serial(self.port_name, self.baudrate, timeout=0.01)
            self.running = True
            self.log_signal.emit(f"串口已打开: {self.port_name} @ {self.baudrate}")

            while self.running:
                try:
                    if self.serial and self.serial.is_open:
                        n = self.serial.in_waiting
                        if n > 0:
                            data = self.serial.read(n)
                            if data:
                                self.buffer.extend(data)
                                self._process_buffer()
                        else:
                            QThread.msleep(5)
                    else:
                        break
                except Exception as e:
                    self.log_signal.emit(f"接收异常: {e}")
                    QThread.msleep(10)

        except Exception as e:
            self.log_signal.emit(f"错误: {e}")
        finally:
            if self.serial and self.serial.is_open:
                self.serial.close()
            self.log_signal.emit("串口已关闭")

    def _process_buffer(self):
        if len(self.buffer) < 7:
            return

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
            del self.buffer[:start_idx]

        if len(self.buffer) < 7:
            return

        length = self.buffer[4]
        total_len = 5 + length + 1

        if total_len <= 263 and len(self.buffer) >= total_len:
            frame = bytes(self.buffer[:total_len])
            del self.buffer[:total_len]
            self._process_frame(frame)

            if len(self.buffer) >= 7:
                self._process_buffer()
        else:
            del self.buffer[0]
            if len(self.buffer) >= 7:
                self._process_buffer()

    def _process_frame(self, frame):
        """解析并处理帧（V2.1：所有返回帧末尾为指令号 ADDR）"""
        try:
            parsed, msg = parse_afdt_response(frame)
            frame_hex = frame.hex().upper()

            if not parsed:
                self.log_signal.emit(f"<<< 收到: {frame_hex}")
                self.log_signal.emit(f"✗ 解析失败: {msg}")
                return

            addr = parsed.get("addr")

            if addr in STATUS_RETURN_ADDRS:
                # 查询返回：0x5C=TX, 0x9C=RX
                if addr == ADDR_STATUS_QUERY:
                    status_info, status_msg = parse_status_response(parsed["payload"])
                else:
                    status_info, status_msg = parse_rx_status_response(parsed["payload"])

                if status_msg == "OK" and status_info:
                    status_info["device_id"] = parsed.get("device_id")
                    sub_id = (parsed.get("device_id") or 0) & 0x7F
                    self.log_signal.emit(f"<<< 收到: {frame_hex}")
                    self.log_signal.emit(
                        f"[ID=0x{sub_id:02X}] 电压: {status_info.get('sys_vcc', 0):.1f}V, 温度: {status_info.get('sys_temp', 0)}°C"
                    )
                    self.status_signal.emit(status_info)
                else:
                    self.log_signal.emit(f"<<< 收到: {frame_hex}")
                    self.log_signal.emit(f"✗ 状态解析失败: {status_msg}")
            elif addr in ADDR_CMD_NAMES:
                cmd_name = ADDR_CMD_NAMES.get(addr, f"0x{addr:02X}")
                self.log_signal.emit(f"<<< 收到: {frame_hex}")
                self.log_signal.emit(f"✓ {cmd_name}配置成功")
            else:
                self.log_signal.emit(f"<<< 收到: {frame_hex}")
        except Exception as e:
            self.log_signal.emit(f"<<< 处理异常: {str(e)}")

    def send_frame(self, frame):
        if self.serial and self.serial.is_open:
            self.serial.write(frame)
            hex_str = frame.hex().upper()
            self.log_signal.emit(f">>> 发送: {hex_str}")

    def stop(self):
        self.running = False
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.quit()
        self.wait(2000)


# ============================================================
# KaUDC Worker - KaUDC004A 专用线程
# ============================================================


class KaUDCWorker(QThread):
    """KaUDC004A 串口后台工作线程 - pyserial"""

    log_signal = Signal(str)
    status_signal = Signal(dict)
    response_signal = Signal(str, str)

    def __init__(self, port_name, baudrate, parent=None):
        super().__init__(parent)
        self.port_name = port_name
        self.baudrate = baudrate
        self.running = False
        self.serial = None
        self.buffer = bytearray()

    def run(self):
        import serial

        try:
            self.serial = serial.Serial(self.port_name, self.baudrate, timeout=0.01)
            self.running = True
            self.log_signal.emit(f"串口已打开: {self.port_name} @ {self.baudrate}")

            while self.running:
                try:
                    if self.serial and self.serial.is_open:
                        n = self.serial.in_waiting
                        if n > 0:
                            data = self.serial.read(n)
                            if data:
                                self.buffer.extend(data)
                                self._process_buffer()
                        else:
                            QThread.msleep(5)
                    else:
                        break
                except Exception as e:
                    self.log_signal.emit(f"接收异常: {e}")
                    QThread.msleep(10)

        except Exception as e:
            self.log_signal.emit(f"错误: {e}")
        finally:
            if self.serial and self.serial.is_open:
                self.serial.close()
            self.log_signal.emit("串口已关闭")

    def _process_buffer(self):
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
            frame_hex = frame.hex().upper()
            if data:
                self.log_signal.emit(f"<<< 收到: {frame_hex}")
                cmd = data[0]
                if cmd == 0x0B:
                    version = data[1]
                    self.response_signal.emit("版本回读", f"0x{version:02X}")
                elif cmd == 0x0C:
                    temp_byte = data[1]
                    temperature = temp_byte
                    # if temp_byte >= 0x80:
                    #     temperature = temp_byte - 0x80
                    # else:
                    #     temperature = -(0x80 - temp_byte)
                    self.status_signal.emit({"temperature": temperature})
                elif cmd == 0x13:
                    tx_lo = int.from_bytes(data[1:3], "big")
                    rx_lo = int.from_bytes(data[3:5], "big")
                    lock_st = data[5]
                    self.response_signal.emit(
                        "本振查询", f"TxLO={tx_lo}, RxLO={rx_lo}, LOCK={lock_st:08b}"
                    )
                elif cmd == 0x16:
                    tx_att = int.from_bytes(data[1:3], "big")
                    rx_att = int.from_bytes(data[3:5], "big")
                    self.response_signal.emit(
                        "衰减查询",
                        f"TxAtt={tx_att}({tx_att / 10:.1f}dB), RxAtt={rx_att}({rx_att / 10:.1f}dB)",
                    )
        except Exception:
            pass

    def send_frame(self, frame):
        if self.serial and self.serial.is_open:
            self.serial.write(frame)
            hex_str = frame.hex().upper()
            self.log_signal.emit(f">>> 发送: {hex_str}")

    def stop(self):
        self.running = False
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.quit()
        self.wait(2000)


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
        import serial.tools.list_ports

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

    # ---- 子阵管理（多子阵：ID列表 + 目标 + ID模式）----

    def _create_subarray_group(self):
        """子阵设置组：ID列表输入 + 目标下拉 + 仅本子阵(+128)"""
        group = QGroupBox("子阵设置")
        v = QVBoxLayout()

        # 阵列拼接：按协议编号规则自动生成 ID（左列 0x01~0x0N，右列 0x11~0x1N）
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("阵列拼接:"))
        self.cols_cb = QComboBox()
        self.cols_cb.addItems(["1列", "2列"])
        row0.addWidget(self.cols_cb)
        row0.addWidget(QLabel("每列子阵数:"))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 15)
        self.rows_spin.setValue(1)
        row0.addWidget(self.rows_spin)
        gen_btn = QPushButton("生成ID")
        gen_btn.clicked.connect(self._on_gen_ids)
        row0.addWidget(gen_btn)
        row0.addStretch()
        v.addLayout(row0)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("子阵ID列表:"))
        self.id_list_edit = QLineEdit("0x01")
        self.id_list_edit.setPlaceholderText("逗号分隔(十六进制), 如 0x01,0x02,0x11")
        self.id_list_edit.editingFinished.connect(self._on_id_list_changed)
        row1.addWidget(self.id_list_edit)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("目标:"))
        self.target_cb = QComboBox()
        row2.addWidget(self.target_cb)
        self.plus128_cb = QCheckBox("仅本子阵(+128)")
        row2.addWidget(self.plus128_cb)
        row2.addStretch()
        v.addLayout(row2)

        group.setLayout(v)
        self._refresh_target_combo()
        return group

    def _parse_id_list(self):
        """解析 ID 列表输入 -> 去重排序的 [int]（1~127）"""
        ids = []
        for tok in self.id_list_edit.text().replace("，", ",").split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                val = int(tok, 0)
            except ValueError:
                continue
            if 1 <= val <= 127 and val not in ids:
                ids.append(val)
        return sorted(ids)

    @staticmethod
    def _fmt_id(i):
        """子阵 ID 以两位十六进制显示，便于与协议编号核验"""
        return f"0x{i:02X}"

    @staticmethod
    def _gen_subarray_ids(cols, n):
        """按协议拼接编号规则生成子阵 ID。

        左列(col=0): 0x01~0x0N；右列(col=1): 0x11~0x1N。
        ID = (列号<<4) | 行号，列号 0=左/1=右，行号 1~N（从下到上）。
        """
        ids = []
        for col in range(cols):
            for row in range(1, n + 1):
                ids.append((col << 4) | row)
        return ids

    def _on_gen_ids(self):
        cols = self.cols_cb.currentIndex() + 1  # "1列"->1, "2列"->2
        n = self.rows_spin.value()
        ids = self._gen_subarray_ids(cols, n)
        self.id_list_edit.setText(",".join(self._fmt_id(i) for i in ids))
        self._on_id_list_changed()

    def _on_id_list_changed(self):
        self._refresh_target_combo()
        self._rebuild_status_table()

    def _refresh_target_combo(self):
        if not hasattr(self, "target_cb"):
            return
        cur = self.target_cb.currentText()
        self.target_cb.blockSignals(True)
        self.target_cb.clear()
        self.target_cb.addItem("全部(广播 ID=0)")
        for i in self._parse_id_list():
            self.target_cb.addItem(self._fmt_id(i))
        idx = self.target_cb.findText(cur)
        if idx >= 0:
            self.target_cb.setCurrentIndex(idx)
        self.target_cb.blockSignals(False)

    def _get_target_device_id(self):
        """配置指令目标 device_id：全部→0(广播)；指定ID→ID(勾+128则 ID+128)"""
        txt = self.target_cb.currentText()
        if txt.startswith("全部"):
            return 0
        try:
            base = int(txt, 0)
        except ValueError:
            return 0
        if self.plus128_cb.isChecked():
            return (base + 128) & 0xFF
        return base

    # ---- 状态表格（每个子阵 ID 一行）----

    def _create_status_group(self, columns):
        """状态表格组。columns 首列为 ID。含"查询全部状态"按钮。"""
        self._status_columns = columns
        group = QGroupBox("状态")
        v = QVBoxLayout()

        self.status_table = QTableWidget(0, len(columns))
        self.status_table.setHorizontalHeaderLabels(columns)
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.status_table.setMinimumHeight(140)  # 默认可见约 4~5 行，更多则滚动
        for c in range(len(columns)):
            self.status_table.horizontalHeader().setSectionResizeMode(c, QHeaderView.Stretch)
        v.addWidget(self.status_table)

        self.query_btn = QPushButton("查询全部状态")
        self.query_btn.clicked.connect(self._on_query_status)
        v.addWidget(self.query_btn)

        group.setLayout(v)
        self._rebuild_status_table()
        return group

    def _rebuild_status_table(self):
        if not hasattr(self, "status_table"):
            return
        ids = self._parse_id_list()
        self._status_rows = {}
        self.status_table.setRowCount(len(ids))
        for row, i in enumerate(ids):
            self._status_rows[i] = row
            self.status_table.setItem(row, 0, QTableWidgetItem(self._fmt_id(i)))
            for c in range(1, len(self._status_columns)):
                self.status_table.setItem(row, c, QTableWidgetItem("N/A"))

    def _update_status_row(self, status_info):
        """按 device_id 路由到对应行更新电压/温度(/PA)"""
        dev = status_info.get("device_id")
        if dev is None:
            return
        sub_id = dev & 0x7F  # 去掉可能的 +128
        row = getattr(self, "_status_rows", {}).get(sub_id)
        if row is None:
            return
        self.status_table.setItem(
            row, 1, QTableWidgetItem(f"{status_info.get('sys_vcc', 0):.1f}")
        )
        self.status_table.setItem(
            row, 2, QTableWidgetItem(str(status_info.get("sys_temp", 0)))
        )
        if len(self._status_columns) >= 4 and "pa_en" in status_info:
            self.status_table.setItem(
                row, 3, QTableWidgetItem("ON" if status_info["pa_en"] else "OFF")
            )

    def _on_query_status(self):
        """逐个 ID 发状态查询"""
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        ids = self._parse_id_list()
        if not ids:
            QMessageBox.warning(self, "警告", "请先填写子阵ID列表")
            return
        plus = self.plus128_cb.isChecked()
        for i in ids:
            dev = (i + 128) & 0xFF if plus else i
            try:
                self.worker.send_frame(self._build_status_query_frame(dev))
                QThread.msleep(50)
            except Exception as e:
                self.log_text.appendPlainText(f"查询ID=0x{i:02X}失败: {e}")
        self.log_text.appendPlainText(f">>> 已查询 {len(ids)} 个子阵状态")

    def _build_status_query_frame(self, device_id):
        raise NotImplementedError

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
            self.worker = None
        self.connect_btn.setText("打开串口")

    def _on_log(self, msg):
        self.log_text.appendPlainText(msg)

    def _on_status(self, status_info):
        self._update_status_row(status_info)

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
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
        self.param_entry.setPlaceholderText("衰减: 0-300 (值/10=dB)")
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
        freq_mhz = TX_LO_OPTIONS[idx][1]
        freq_bytes = freq_mhz.to_bytes(2, "big")
        frame = kaudc_build_frame(bytes([0x12, 0x00, 0x00, 0x00]) + freq_bytes)
        self.worker.send_frame(frame)
        self.log_text.appendPlainText(f"设置发射本振: {TX_LO_OPTIONS[idx][0]}")

    def _on_set_rxlo(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        idx = self.rxlo_cb.currentIndex()
        freq_mhz = RX_LO_OPTIONS[idx][1]
        freq_bytes = freq_mhz.to_bytes(2, "big")
        frame = kaudc_build_frame(bytes([0x0E, 0x00, 0x00, 0x00]) + freq_bytes)
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
                if 0 <= att <= 300:
                    att_bytes = att.to_bytes(2, "big")
                    frame = kaudc_build_frame(bytes([0x14, 0x00, 0x00, 0x00]) + att_bytes)
                else:
                    QMessageBox.warning(
                        self, "警告", "衰减必须在0-300之间(0=0dB, 300=30dB)"
                    )
                    return
            except ValueError:
                QMessageBox.warning(self, "警告", "请输入有效的数字")
                return
        elif cmd == "接收衰减设置":
            try:
                att = int(param)
                if 0 <= att <= 300:
                    att_bytes = att.to_bytes(2, "big")
                    frame = kaudc_build_frame(bytes([0x15, 0x00, 0x00, 0x00]) + att_bytes)
                else:
                    QMessageBox.warning(
                        self, "警告", "衰减必须在0-300之间(0=0dB, 300=30dB)"
                    )
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

        for cmd in [0x0B, 0x0C, 0x13, 0x16]:
            frame = kaudc_build_frame(bytes([cmd, 0x00, 0x00, 0x00, 0x00, 0x00]))
            self.worker.send_frame(frame)
            QThread.msleep(50)

        self.log_text.appendPlainText("设备查询已发送")

    def _on_status(self, status_info):
        if "temperature" in status_info:
            self.status_table.item(1, 1).setText(str(status_info["temperature"]))

    def _on_response(self, cmd_name, value):
        if cmd_name == "版本回读":
            self.status_table.item(0, 1).setText(value)
        elif cmd_name == "本振查询":
            parts = value.split(", ")
            if len(parts) >= 2:
                self.status_table.item(2, 1).setText(parts[0].split("=")[1])
                self.status_table.item(3, 1).setText(parts[1].split("=")[1])
            if len(parts) >= 3:
                lock_str = parts[2].split("=")[1]
                lock_bits = int(lock_str, 2)
                rx_lock = "Locked" if (lock_bits & 0x01) else "Unlocked"
                tx_lock = "Locked" if (lock_bits & 0x02) else "Unlocked"
                ref_lock = "Locked" if (lock_bits & 0x04) else "Unlocked"
                self.status_table.item(6, 1).setText(f"RX:{rx_lock} TX:{tx_lock} REF:{ref_lock}")
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

        # 子阵设置（ID列表 + 目标 + ID模式）
        layout.addWidget(self._create_subarray_group())

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

        # 状态表格（每个子阵 ID 一行）+ 查询全部
        _cols = (
            ["ID", "电压(V)", "温度(°C)", "PA"]
            if self.device_type == "TX"
            else ["ID", "电压(V)", "温度(°C)"]
        )
        layout.addWidget(self._create_status_group(_cols))

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
            device_id = self._get_target_device_id()
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
            self.log_text.appendPlainText(
                f">>> 发送波束设置: BeamH={beam_h}, BeamV={beam_v}"
            )
        except ValueError:
            QMessageBox.warning(self, "警告", "请输入有效的数字")

    def _on_set_array(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        try:
            device_id = self._get_target_device_id()
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
            device_id = self._get_target_device_id()
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
            device_id = self._get_target_device_id()
            pol = POLARIZATION_RHCP if self.pol_rhcp.isChecked() else POLARIZATION_LHCP
            frame = build_tx_polarization_frame(device_id, pol)
            self.worker.send_frame(frame)
            self.log_text.appendPlainText(f">>> 发送极化设置")
        except Exception as e:
            QMessageBox.warning(self, "警告", str(e))

    def _build_status_query_frame(self, device_id):
        return build_status_query_frame(device_id)

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

        # 子阵设置（ID列表 + 目标 + ID模式）
        layout.addWidget(self._create_subarray_group())

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

        # 状态表格（每个子阵 ID 一行）+ 查询全部
        _cols = (
            ["ID", "电压(V)", "温度(°C)", "PA"]
            if self.device_type == "TX"
            else ["ID", "电压(V)", "温度(°C)"]
        )
        layout.addWidget(self._create_status_group(_cols))

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
            device_id = self._get_target_device_id()
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
            frame = build_rx_beam_frame(device_id, freq_num, beam_h, beam_v)
            self.log_text.appendPlainText(
                f">>> 发送波束设置: BeamH={beam_h}, BeamV={beam_v}"
            )
            self.worker.send_frame(frame)
        except ValueError:
            QMessageBox.warning(self, "警告", "请输入有效的数字")

    def _on_set_array(self):
        if not self.worker or not self.worker.running:
            QMessageBox.warning(self, "警告", "请先打开串口")
            return
        try:
            device_id = self._get_target_device_id()
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
            device_id = self._get_target_device_id()
            pol = POLARIZATION_RHCP if self.pol_rhcp.isChecked() else POLARIZATION_LHCP
            frame = build_rx_polarization_frame(device_id, pol)
            self.worker.send_frame(frame)
            self.log_text.appendPlainText(f">>> 发送极化设置")
        except Exception as e:
            QMessageBox.warning(self, "警告", str(e))

    def _build_status_query_frame(self, device_id):
        return build_rx_status_query_frame(device_id)

    def _on_config_success(self, cmd_name):
        pass


# ============================================================
# 主窗口
# ============================================================


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SoftHertz AFDTR Tool")
        self.setGeometry(100, 100, 1200, 700)

        # 横向滚动区包裹三面板：窗口变窄/变矮时出现滚动条，而非压缩内容
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.setCentralWidget(scroll)

        container = QWidget()
        main_layout = QHBoxLayout()
        container.setLayout(main_layout)
        scroll.setWidget(container)

        # KaUDC004A / TX / RX 面板（各设最小宽度，避免被压缩）
        self.kaudc_panel = KaUDCPanel()
        self.tx_panel = TXPanel()
        self.rx_panel = RXPanel()
        for p in (self.kaudc_panel, self.tx_panel, self.rx_panel):
            p.setMinimumWidth(400)
            main_layout.addWidget(p)

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
    sys.exit(app.exec())
