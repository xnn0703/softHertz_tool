import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import serial
import serial.tools.list_ports
from protocol import build_frame, parse_response
from afdt1024_protocol import (
    build_tx_beam_frame,
    build_tx_enable_frame,
    build_tx_polarization_frame,
    build_pa_enable_frame,
    build_phase_cal_frame,
    build_id_update_frame,
    build_status_query_frame,
    parse_response as parse_afdt_response,
    parse_status_response,
    POLARIZATION_LHCP,
    POLARIZATION_RHCP,
    PA_ENABLE,
    PA_DISABLE,
    ARRAY_ENABLE,
    ARRAY_DISABLE,
    calculate_beam_values,
    ADDR_CMD_NAMES,
    # RX设备相关函数
    build_rx_beam_frame,
    build_rx_enable_frame,
    build_rx_polarization_frame,
    build_rx_phase_cal_frame,
    build_rx_status_query_frame,
    parse_rx_status_response,
)
import threading
import datetime
import time
import queue

# 定义布局配置字典
layout_config = {
    "port_cb": {"row": 0, "column": 0, "padx": 5, "pady": 5},
    "baud_cb": {"row": 0, "column": 1, "padx": 5, "pady": 5},
    "connect_btn": {"row": 0, "column": 2, "padx": 5, "pady": 5},
    "status_table": {"row": 1, "column": 0, "column_span": 4, "padx": 5, "pady": 5},
    "txlo_btn": {"row": 2, "column": 0, "padx": 5, "pady": 5},
    "txlo_cb": {"row": 2, "column": 1, "padx": 5, "pady": 5},
    "rxlo_btn": {"row": 3, "column": 0, "padx": 5, "pady": 5},
    "rxlo_cb": {"row": 3, "column": 1, "padx": 5, "pady": 5},
    "cmd_cb": {"row": 4, "column": 0, "column_span": 1, "padx": 5, "pady": 5},
    "param_entry": {"row": 4, "column": 1, "padx": 5, "pady": 5},
    "send_btn": {"row": 4, "column": 2, "padx": 5, "pady": 5},
    "text": {"row": 5, "column": 0, "column_span": 3, "padx": 5, "pady": 5},
    "device_query_btn": {"row": 6, "column": 1, "padx": 5, "pady": 5},
    "clear_btn": {"row": 6, "column": 2, "padx": 5, "pady": 5},
}


class ThreadSafeUIMixin:
    """线程安全的UI更新Mixin - 解决跨线程访问Tkinter问题"""

    def _safe_insert(self, text):
        """在主线程中插入文本到text widget"""

        def callback():
            if hasattr(self, "text") and self.text.winfo_exists():
                self.text.insert(tk.END, text + "\n")

        if hasattr(self, "master"):
            self.master.after(1, callback)

    def _safe_update_status_display(self, status_info):
        """在主线程中更新状态表格"""

        def callback():
            if hasattr(self, "status_table") and self.status_table.winfo_exists():
                items = self.status_table.get_children()
                if items:
                    self.status_table.item(
                        items[0],
                        values=("输入电压(V)", f"{status_info.get('sys_vcc', 0):.1f}"),
                    )
                    self.status_table.item(
                        items[1],
                        values=("温度(°C)", f"{status_info.get('sys_temp', 0)}"),
                    )

        if hasattr(self, "master"):
            self.master.after(0, callback)


class AsyncLogger:
    DEBUG = False

    def __init__(self, filename):
        self.filename = filename
        self.queue = queue.Queue()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        if self.DEBUG:
            return
        with open(self.filename, "a", encoding="utf-8") as f:
            while True:
                msg = self.queue.get()
                if msg is None:
                    break
                ts = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")
                f.write(ts + msg + "\n")
                f.flush()

    def log(self, msg):
        if self.DEBUG:
            return
        self.queue.put(msg)

    def close(self):
        self.queue.put(None)
        self.thread.join(timeout=1)


# DEBUG模式：True=禁用文件日志，False=启用文件日志
# 设为True可测试是否是日志导致的UI卡顿
AsyncLogger.DEBUG = True


class DeviceController:
    def __init__(self, master, device_name):
        self.master = master
        self.device_name = device_name
        self.ser = None
        self.running = False
        self.logfile = AsyncLogger(f"{device_name}_serial_log.txt")

        # 响应队列，用于 query_device_worker
        self.response_queue = queue.Queue()

        # 串口设置
        self.port_cb = ttk.Combobox(master, width=10)
        self.port_cb.grid(
            row=layout_config["port_cb"]["row"],
            column=layout_config["port_cb"]["column"],
            padx=layout_config["port_cb"]["padx"],
            pady=layout_config["port_cb"]["pady"],
        )
        self.update_ports()  # 初始更新串口列表

        self.baud_cb = ttk.Combobox(
            master, values=["9600", "19200", "38400", "115200", "921600"], width=10
        )
        self.baud_cb.grid(
            row=layout_config["baud_cb"]["row"],
            column=layout_config["baud_cb"]["column"],
            padx=layout_config["baud_cb"]["padx"],
            pady=layout_config["baud_cb"]["pady"],
        )
        self.baud_cb.set("115200")

        self.connect_btn = ttk.Button(
            master, text="打开串口", command=self.toggle_serial
        )
        self.connect_btn.grid(
            row=layout_config["connect_btn"]["row"],
            column=layout_config["connect_btn"]["column"],
            padx=layout_config["connect_btn"]["padx"],
            pady=layout_config["connect_btn"]["pady"],
        )

        # 状态表格
        self.status_table = ttk.Treeview(
            master, columns=("Parameter", "Value"), show="headings", height=8
        )
        self.status_table.grid(
            row=layout_config["status_table"]["row"],
            column=layout_config["status_table"]["column"],
            columnspan=layout_config["status_table"]["column_span"],
            padx=layout_config["status_table"]["padx"],
            pady=layout_config["status_table"]["pady"],
        )
        self.status_table.heading("Parameter", text="参数")
        self.status_table.heading("Value", text="值")
        for param in ["版本", "温度", "TxLO", "RxLO", "Tx衰减", "Rx衰减", "锁定状态"]:
            self.status_table.insert("", "end", values=(param, "N/A"))

        # 接收本振下拉框（RxLO）
        self.rxlo_cb = ttk.Combobox(
            master,
            values=[
                "16.75GHz (17.7-18.2)",
                "17.25GHz (18.2-19.2)",
                "18.25GHz (19.2-20.2)",
                "19.25GHz (20.2-21.2)",
            ],
            width=25,
        )
        self.rxlo_cb.grid(
            row=layout_config["rxlo_cb"]["row"],
            column=layout_config["rxlo_cb"]["column"],
            padx=layout_config["rxlo_cb"]["padx"],
            pady=layout_config["rxlo_cb"]["pady"],
        )
        self.rxlo_cb.set("16.75GHz (17.7-18.2)")

        # 发射本振下拉框（TxLO）
        self.txlo_cb = ttk.Combobox(
            master,
            values=[
                "26.55GHz (27.5-28.35)",
                "27.40GHz (28.35-29.2)",
                "28.05GHz (29.00-30.0)",
                "29.05GHz (30.00-31.0)",
            ],
            width=25,
        )
        self.txlo_cb.grid(
            row=layout_config["txlo_cb"]["row"],
            column=layout_config["txlo_cb"]["column"],
            padx=layout_config["txlo_cb"]["padx"],
            pady=layout_config["txlo_cb"]["pady"],
        )
        self.txlo_cb.set("26.55GHz (27.5-28.35)")

        # 分开设置发射和接收本振按钮
        self.txlo_btn = ttk.Button(master, text="设置发射本振", command=self.set_txlo)
        self.txlo_btn.grid(
            row=layout_config["txlo_btn"]["row"],
            column=layout_config["txlo_btn"]["column"],
            padx=layout_config["txlo_btn"]["padx"],
            pady=layout_config["txlo_btn"]["pady"],
        )

        self.rxlo_btn = ttk.Button(master, text="设置接收本振", command=self.set_rxlo)
        self.rxlo_btn.grid(
            row=layout_config["rxlo_btn"]["row"],
            column=layout_config["rxlo_btn"]["column"],
            padx=layout_config["rxlo_btn"]["padx"],
            pady=layout_config["rxlo_btn"]["pady"],
        )

        # 命令选择
        self.cmd_cb = ttk.Combobox(
            master,
            values=[
                "发射衰减设置",
                "接收衰减设置",
                "本振查询",
                "衰减查询",
                "复位设备",
                "版本回读",
                "温度查询",
            ],
            width=25,
        )
        self.cmd_cb.grid(
            row=layout_config["cmd_cb"]["row"],
            column=layout_config["cmd_cb"]["column"],
            columnspan=layout_config["cmd_cb"]["column_span"],
            padx=layout_config["cmd_cb"]["padx"],
            pady=layout_config["cmd_cb"]["pady"],
        )
        self.cmd_cb.set("本振查询")
        self.cmd_cb.bind("<<ComboboxSelected>>", self.update_input_type)

        self.param_entry = ttk.Entry(master, width=10)
        self.param_entry.grid(
            row=layout_config["param_entry"]["row"],
            column=layout_config["param_entry"]["column"],
            padx=layout_config["param_entry"]["padx"],
            pady=layout_config["param_entry"]["pady"],
        )
        self.param_entry.grid_forget()

        self.send_btn = ttk.Button(master, text="发送指令", command=self.send_command)
        self.send_btn.grid(
            row=layout_config["send_btn"]["row"],
            column=layout_config["send_btn"]["column"],
            padx=layout_config["send_btn"]["padx"],
            pady=layout_config["send_btn"]["pady"],
        )

        self.text = scrolledtext.ScrolledText(master, width=40, height=8)
        self.text.grid(
            row=layout_config["text"]["row"],
            column=layout_config["text"]["column"],
            columnspan=layout_config["text"]["column_span"],
            padx=layout_config["text"]["padx"],
            pady=layout_config["text"]["pady"],
        )

        # 设备查询按钮
        self.device_query_btn = ttk.Button(
            master, text="设备查询", command=self.query_device_thread
        )
        self.device_query_btn.grid(
            row=layout_config["device_query_btn"]["row"],
            column=layout_config["device_query_btn"]["column"],
            padx=layout_config["device_query_btn"]["padx"],
            pady=layout_config["device_query_btn"]["pady"],
        )

        # 清除数据按钮
        self.clear_btn = ttk.Button(master, text="清除数据", command=self.clear_data)
        self.clear_btn.grid(
            row=layout_config["clear_btn"]["row"],
            column=layout_config["clear_btn"]["column"],
            padx=layout_config["clear_btn"]["padx"],
            pady=layout_config["clear_btn"]["pady"],
        )
        self._cmd_name_map = {
            0x0B: "版本回读",
            0x0C: "温度查询",
            0x13: "本振查询",
            0x16: "衰减查询",
        }

        # 定时器每1秒刷新一次串口列表
        self.master.after(1000, self.update_ports)

    def update_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_cb["values"] = ports

        current_port = self.port_cb.get()
        # 如果当前串口不在列表中，关闭串口并更新按钮
        if current_port not in ports and self.ser and self.ser.is_open:
            self.ser.close()  # 关闭串口
            self.connect_btn.config(text="打开串口")  # 更新按钮文本
            self.running = False  # 停止接收线程

        # 如果当前串口不在列表中，清空串口选择
        if current_port not in ports:
            self.port_cb.set(ports[0] if ports else "")

        # 每隔1秒更新串口列表
        self.master.after(1000, self.update_ports)

    def log(self, msg):
        self.logfile.log(msg)

    def toggle_serial(self):
        if self.ser and self.ser.is_open:
            self.running = False
            self.ser.close()
            self.connect_btn.config(text="打开串口")
        else:
            try:
                self.ser = serial.Serial(
                    self.port_cb.get(), int(self.baud_cb.get()), timeout=0.01
                )
                self.running = True
                threading.Thread(target=self.read_thread, daemon=True).start()
                self.connect_btn.config(text="关闭串口")
            except Exception as e:
                messagebox.showerror("串口错误", str(e))

    def set_txlo(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return
        # 获取发射本振频率并发送指令
        freq = self.extract_frequency(self.txlo_cb.get())
        payload = b"\x12\x00\x00\x00" + int(float(freq)).to_bytes(2, "big")
        self.send_payload(payload)

    def set_rxlo(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return
        # 获取接收本振频率并发送指令
        freq = self.extract_frequency(self.rxlo_cb.get())
        payload = b"\x0e\x00\x00\x00" + int(float(freq)).to_bytes(2, "big")
        self.send_payload(payload)

    def send_payload(self, payload):
        # 发送构建好的数据包
        frame = build_frame(payload)
        self.ser.write(frame)
        line = f">>> 发送: {frame.hex().upper()}"
        self._safe_insert(line + "\n")
        self.log(line)

    def send_command(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        cmd = self.cmd_cb.get()
        payload = b""
        param = self.param_entry.get().strip()

        try:
            if cmd == "复位设备":
                payload = b"\x0a\x00\x00\x00\x00\x00"
            elif cmd == "版本回读":
                payload = b"\x0b\x00\x00\x00\x00\x00"
            elif cmd == "温度查询":
                payload = b"\x0c\x00\x00\x00\x00\x00"
            elif cmd == "接收本振设置":
                freq = self.extract_frequency(
                    self.rxlo_cb.get()
                )  # 获取频率并提取数字部分
                payload = b"\x0e\x00\x00\x00" + int(float(freq)).to_bytes(2, "big")
            elif cmd == "发射本振设置":
                freq = self.extract_frequency(
                    self.txlo_cb.get()
                )  # 获取频率并提取数字部分
                payload = b"\x12\x00\x00\x00" + int(float(freq)).to_bytes(2, "big")
            elif cmd == "本振查询":
                payload = b"\x13\x00\x00\x00\x00\x00"
            elif cmd == "发射衰减设置":
                try:
                    att = float(param)
                    if 0 <= att <= 30:
                        # 将衰减值转换为 2 字节，并且乘以 10 来实现 dB 单位
                        tmp = int(att * 10).to_bytes(2, "big")
                        payload = b"\x14\x00\x00\x00" + tmp
                    else:
                        messagebox.showerror(
                            "数值必须在0-30内", "发射衰减值必须在0到30之间"
                        )
                except ValueError:
                    messagebox.showerror("无效输入", "请输入有效的数字")

            elif cmd == "接收衰减设置":
                try:
                    att = float(param)
                    if 0 <= att <= 30:
                        # 将衰减值转换为 2 字节，并且乘以 10 来实现 dB 单位
                        tmp = int(att * 10).to_bytes(2, "big")
                        payload = b"\x15\x00\x00\x00" + tmp
                    else:
                        messagebox.showerror(
                            "数值必须在0-30内", "接收衰减值必须在0到30之间"
                        )
                except ValueError:
                    messagebox.showerror("无效输入", "请输入有效的数字")
            elif cmd == "衰减查询":
                payload = b"\x16\x00\x00\x00\x00\x00"
            else:
                messagebox.showerror("命令错误", "未知命令")
                return

            frame = build_frame(payload)
            self.ser.write(frame)
            line = f">>> 发送: {frame.hex().upper()}"
            self._safe_insert(line + "\n")
            self.log(line)
        except Exception as e:
            messagebox.showerror("发送错误", str(e))

    def parse_fields(self, cmd_byte, data):
        try:
            if len(data) < 6:
                return ""

            if cmd_byte == 0x0B:
                version_bytes = data[1:5]
                if len(version_bytes) < 4:
                    return ""
                version = int.from_bytes(version_bytes, byteorder="big")
                return f"版本号: {version}"
            elif cmd_byte == 0x0C:
                temp_c = data[1]
                return f"温度: {temp_c}°C"
            elif cmd_byte == 0x13:
                tx = int.from_bytes(data[1:3], "big")
                rx = int.from_bytes(data[3:5], "big")
                bits = f"{data[5]:08b}"
                return f"TxLO: {tx} MHz, RxLO: {rx} MHz, LOCK: {bits}"
            elif cmd_byte in (0x14, 0x15):
                att = int.from_bytes(data[4:6], "big") / 10
                return f"衰减: {att:.1f} dB"
            elif cmd_byte == 0x16:
                tx = int.from_bytes(data[1:3], "big") / 10
                rx = int.from_bytes(data[3:5], "big") / 10
                return f"Tx衰减: {tx:.1f} dB, Rx衰减: {rx:.1f} dB"
        except (ValueError, TypeError, IndexError) as e:
            return f"[解析错误: {e}]"
        return ""

    def extract_frequency(self, freq_str):
        try:
            ghz_part = freq_str.split()[0].replace("GHz", "")
            mhz = int(float(ghz_part) * 1000)
            return mhz
        except Exception:
            return 0

    def update_input_type(self, event):
        cmd = self.cmd_cb.get()
        self.param_entry.grid_forget()
        if cmd in ("发射衰减设置", "接收衰减设置"):
            self.param_entry.grid(
                row=layout_config["param_entry"]["row"],
                column=layout_config["param_entry"]["column"],
                padx=layout_config["param_entry"]["padx"],
                pady=layout_config["param_entry"]["pady"],
            )

    def read_thread(self):
        buffer = bytearray()
        last_receive_time = time.time()
        BUFFER_TIMEOUT = 0.1

        while self.running:
            try:
                # 批量读取优化：使用in_waiting获取可读字节数
                if self.ser.in_waiting > 0:
                    chunk = self.ser.read(min(self.ser.in_waiting, 1024))
                else:
                    # 检查buffer超时
                    if buffer and (time.time() - last_receive_time) > BUFFER_TIMEOUT:
                        line = f"[超时] 丢弃{len(buffer)}字节不完整数据: {buffer.hex().upper()}"
                        self._safe_insert(line + "\n")
                        self.log(line)
                        buffer.clear()
                    time.sleep(0.001)
                    continue

                if not chunk:
                    continue

                buffer.extend(chunk)
                last_receive_time = time.time()

                # 处理AFDT1024设备回复（以0x50 0x53 0x41开头）
                while len(buffer) >= 3:
                    if buffer[0] == 0x50 and buffer[1] == 0x53 and buffer[2] == 0x41:
                        # 解析AFDT1024格式的帧
                        if len(buffer) < 7:
                            break

                        # 帧长度校验：防止溢出
                        length = buffer[4]
                        if length > 255:
                            buffer.clear()
                            line = "[错误] 长度字段异常，清空buffer"
                            self._safe_insert(line + "\n")
                            self.log(line)
                            break

                        # 完整帧长度
                        total_length = 3 + 1 + 1 + length + 1
                        if total_length > 263:  # 最大帧长限制
                            buffer.clear()
                            line = "[错误] 帧长超限，清空buffer"
                            self._safe_insert(line + "\n")
                            self.log(line)
                            break

                        if len(buffer) < total_length:
                            break

                        frame = bytes(buffer[:total_length])
                        del buffer[:total_length]

                        line = f"<<< 收到AFDT1024帧: {frame.hex().upper()}"
                        self._safe_insert(line + "\n")
                        self.log(line)

                        try:
                            parsed, msg = parse_afdt_response(frame)
                            line = f"<<< 解析结果: {msg}"
                            self._safe_insert(line + "\n")
                            self.log(line)

                            if msg == "OK" and parsed:
                                if parsed.get("payload"):
                                    status, status_msg = parse_status_response(
                                        parsed["payload"]
                                    )
                                    if status_msg == "OK" and status:
                                        extra = f"状态: Rev={status.get('rev', 0)}, 电压={status.get('sys_vcc', 0)}V, 温度={status.get('sys_temp', 0)}°C, ATT_TC={status.get('att_tc', 0)}, MCU_VER={status.get('mcu_ver', 0)}"
                                        self._safe_insert("    " + extra + "\n")
                                        self.log("    " + extra)
                                        self.update_afdt_status(status)
                        except Exception as e:
                            line = f"<<< 解析失败: {str(e)}"
                            self._safe_insert(line + "\n")
                            self.log(line)

                        self.text.see(tk.END)
                    else:
                        # 处理其他格式的帧（如0xAA 0x55开头的）
                        if len(buffer) >= 2:
                            if buffer[0] == 0xAA and buffer[1] == 0x55:
                                if len(buffer) < 12:
                                    break
                                frame = bytes(buffer[:12])
                                del buffer[:12]

                                line = f"<<< 收到其他帧: {frame.hex().upper()}"
                                self._safe_insert(line + "\n")
                                self.log(line)

                                try:
                                    parsed, msg = parse_response(frame)
                                    line = f"<<< 解析结果: {msg}"
                                    self._safe_insert(line + "\n")
                                    self.log(line)

                                    if msg == "OK" and parsed:
                                        cmd = parsed[0]
                                        self.response_queue.put((cmd, parsed))
                                        extra = self.parse_fields(cmd, parsed)
                                        if extra:
                                            self._safe_insert("    " + extra + "\n")
                                            self.log("    " + extra)
                                        name = self._cmd_name_map.get(cmd)
                                        if name:
                                            self.update_display(name, parsed)
                                except Exception as e:
                                    line = f"<<< 解析失败: {str(e)}"
                                    self._safe_insert(line + "\n")
                                    self.log(line)

                                self.text.see(tk.END)
                            else:
                                byte = buffer.pop(0)
                                line = f"<<< 丢弃字节: {byte:02X}"
                                self._safe_insert(line + "\n")
                                self.log(line)
                        else:
                            break
            except Exception as e:
                err = f"[接收错误] {e}"
                self._safe_insert(err + "\n")
                self.log(err)

    def update_display(self, name, data):
        if name == "版本回读":
            version_bytes = data[1:5]
            version = int.from_bytes(version_bytes, byteorder="big")  # 转换为十进制
            self.status_table.item(
                self.status_table.get_children()[0], values=("版本", f"{version}")
            )
        elif name == "温度查询":
            temp_c = data[1]
            self.status_table.item(
                self.status_table.get_children()[1], values=("温度", f"{temp_c}°C")
            )
        elif name == "本振查询":
            tx = int.from_bytes(data[1:3], "big")
            rx = int.from_bytes(data[3:5], "big")
            bits = f"{data[5]:08b}"
            self.status_table.item(
                self.status_table.get_children()[2], values=("TxLO", f"{tx} MHz")
            )
            self.status_table.item(
                self.status_table.get_children()[3], values=("RxLO", f"{rx} MHz")
            )
            self.status_table.item(
                self.status_table.get_children()[6], values=("锁定状态", bits)
            )
        elif name == "衰减查询":
            tx = int.from_bytes(data[1:3], "big") / 10
            rx = int.from_bytes(data[3:5], "big") / 10
            self.status_table.item(
                self.status_table.get_children()[4], values=("Tx衰减", f"{tx:.1f} dB")
            )
            self.status_table.item(
                self.status_table.get_children()[5], values=("Rx衰减", f"{rx:.1f} dB")
            )

    def update_afdt_status(self, status):
        """更新AFDT1024设备状态显示"""
        try:
            items = self.status_table.get_children()
            if items:
                self.status_table.item(
                    items[0], values=("版本", f"Rev:{status.get('rev', 0)}")
                )
                self.status_table.item(
                    items[1], values=("温度", f"{status.get('sys_temp', 0)}°C")
                )
                self.status_table.item(
                    items[2], values=("TxLO", f"state:{status.get('state', 0)}")
                )
                self.status_table.item(
                    items[3], values=("RxLO", f"ATT_TC:{status.get('att_tc', 0)}")
                )
                self.status_table.item(
                    items[4], values=("Tx衰减", f"{status.get('sys_vcc', 0)}V")
                )
                self.status_table.item(
                    items[5], values=("Rx衰减", f"MCU:{status.get('mcu_ver', 0)}")
                )
        except Exception as e:
            self._safe_insert(f"[更新状态失败] {e}\n")

    def query_device_worker(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return
        queries = [
            (0x0B, b"\x0b\x00\x00\x00\x00\x00", "版本回读"),
            (0x0C, b"\x0c\x00\x00\x00\x00\x00", "温度查询"),
            (0x13, b"\x13\x00\x00\x00\x00\x00", "本振查询"),
            (0x16, b"\x16\x00\x00\x00\x00\x00", "衰减查询"),
        ]
        for attempt in range(3):
            self._safe_insert(f"\n尝试查询设备，第 {attempt + 1} 次...\n")
            self.log(f"尝试查询设备，第 {attempt + 1} 次...")
            all_ok = True
            for cmd_byte, payload, name in queries:
                self._safe_insert(f"\n查询: {name}\n")
                self.log(f"查询: {name}")
                self.ser.write(build_frame(payload))
                self.log(f">>> 发送查询指令: {payload.hex().upper()}")

                # 清空旧回复
                while not self.response_queue.empty():
                    self.response_queue.get_nowait()

                try:
                    got_cmd, parsed = self.response_queue.get(timeout=2)
                    if got_cmd == cmd_byte:
                        self._safe_insert(f"{name} 查询成功，回复正常\n")
                        self.log(f"{name} 查询成功，回复正常")
                        self.update_display(name, parsed)
                    else:
                        all_ok = False
                        self._safe_insert(f"{name} 收到错帧: 0x{got_cmd:02X}\n")
                        self.log(f"{name} 收到错帧: 0x{got_cmd:02X}")
                except queue.Empty:
                    all_ok = False
                    self._safe_insert(f"{name} 查询超时无响应\n")
                    self.log(f"{name} 查询超时无响应")

            if all_ok:
                self._safe_insert("✅ 设备查询完成，全部成功！\n")
                self.log("设备查询完成，全部成功")
                break
            else:
                self._safe_insert("❌ 本轮查询有失败，重试...\n")
                self.log("本轮查询有失败，重试...")
        else:
            self._safe_insert("❌ 所有查询尝试失败！请检查设备连接或协议配置。\n")
            self.log("所有查询尝试失败")

    def query_device_thread(self):
        threading.Thread(target=self.query_device_worker, daemon=True).start()

    def clear_data(self):
        # 清除文本显示
        self.text.delete("1.0", tk.END)
        # 重置状态表格
        for iid in self.status_table.get_children():
            param = self.status_table.item(iid, "values")[0]
            self.status_table.item(iid, values=(param, "N/A"))
        # 清空响应队列
        while not self.response_queue.empty():
            try:
                self.response_queue.get_nowait()
            except queue.Empty:
                break
        self.log("已清除所有数据和缓存")

    def __del__(self):
        if self.logfile:
            self.logfile.close()


class AFDT1024Controller(ThreadSafeUIMixin):
    def __init__(self, master, device_name):
        self.master = master
        self.device_name = device_name
        self.ser = None
        self.running = False
        self.logfile = AsyncLogger(f"{device_name}_serial_log.txt")

        # 响应队列
        self.response_queue = queue.Queue()

        # 串口设置
        self.port_cb = ttk.Combobox(master, width=10)
        self.port_cb.grid(row=0, column=0, padx=5, pady=5)
        self.update_ports()

        self.baud_cb = ttk.Combobox(
            master,
            values=["9600", "19200", "38400", "115200", "460800", "921600"],
            width=10,
        )
        self.baud_cb.grid(row=0, column=1, padx=5, pady=5)
        self.baud_cb.set("460800")  # AFDT1024默认波特率

        self.connect_btn = ttk.Button(
            master, text="打开串口", command=self.toggle_serial
        )
        self.connect_btn.grid(row=0, column=2, padx=5, pady=5)

        # 子阵ID设置
        ttk.Label(master, text="子阵ID:").grid(
            row=1, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.id_entry = ttk.Entry(master, width=5)
        self.id_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        self.id_entry.insert(0, "1")

        # TX波束设置
        ttk.Label(master, text="TX波束设置").grid(
            row=2, column=0, columnspan=3, padx=5, pady=5, sticky=tk.W
        )

        ttk.Label(master, text="实际频率(MHz):").grid(
            row=3, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.freq_entry = ttk.Entry(master, width=10)
        self.freq_entry.grid(row=3, column=1, padx=5, pady=3, sticky=tk.W)
        self.freq_entry.insert(0, "27500")  # 默认频率

        ttk.Label(master, text="俯仰角θ:").grid(
            row=4, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.theta_entry = ttk.Entry(master, width=8)
        self.theta_entry.grid(row=4, column=1, padx=5, pady=3, sticky=tk.W)
        self.theta_entry.insert(0, "0")

        ttk.Label(master, text="方位角φ:").grid(
            row=5, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.phi_entry = ttk.Entry(master, width=8)
        self.phi_entry.grid(row=5, column=1, padx=5, pady=3, sticky=tk.W)
        self.phi_entry.insert(0, "0")

        self.set_beam_btn = ttk.Button(master, text="设置波束", command=self.set_beam)
        self.set_beam_btn.grid(row=3, column=2, rowspan=3, padx=5, pady=3, sticky=tk.NS)

        # TX阵列使能
        ttk.Label(master, text="TX阵列:").grid(
            row=6, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.array_enable_var = tk.BooleanVar()
        self.array_enable_check = ttk.Checkbutton(
            master, text="使能", variable=self.array_enable_var
        )
        self.array_enable_check.grid(row=6, column=1, padx=5, pady=5, sticky=tk.W)
        self.set_array_btn = ttk.Button(
            master, text="应用", command=self.set_array_enable
        )
        self.set_array_btn.grid(row=6, column=2, padx=5, pady=5, sticky=tk.W)

        # TX极化设置
        ttk.Label(master, text="极化设置:").grid(
            row=7, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.polarization_var = tk.IntVar(value=POLARIZATION_LHCP)
        ttk.Radiobutton(
            master, text="LHCP", variable=self.polarization_var, value=POLARIZATION_LHCP
        ).grid(row=7, column=1, padx=5, pady=5, sticky=tk.W)
        ttk.Radiobutton(
            master, text="RHCP", variable=self.polarization_var, value=POLARIZATION_RHCP
        ).grid(row=7, column=2, padx=5, pady=5, sticky=tk.W)
        self.set_polarization_btn = ttk.Button(
            master, text="设置极化", command=self.set_polarization
        )
        self.set_polarization_btn.grid(
            row=8, column=1, columnspan=2, padx=5, pady=5, sticky=tk.W
        )

        # PA使能
        ttk.Label(master, text="推动PA:").grid(
            row=9, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.pa_enable_var = tk.BooleanVar()
        self.pa_enable_check = ttk.Checkbutton(
            master, text="使能", variable=self.pa_enable_var
        )
        self.pa_enable_check.grid(row=9, column=1, padx=5, pady=5, sticky=tk.W)
        self.set_pa_btn = ttk.Button(master, text="应用", command=self.set_pa_enable)
        self.set_pa_btn.grid(row=9, column=2, padx=5, pady=5, sticky=tk.W)

        # 相位校准 (已隐藏)
        # ttk.Label(master, text="相位偏移(0-63):").grid(row=10, column=0, padx=5, pady=5, sticky=tk.W)
        # self.phase_entry = ttk.Entry(master, width=5)
        # self.phase_entry.grid(row=10, column=1, padx=5, pady=5, sticky=tk.W)
        # self.phase_entry.insert(0, "0")
        # self.set_phase_btn = ttk.Button(master, text="校准", command=self.set_phase_cal)
        # self.set_phase_btn.grid(row=10, column=2, padx=5, pady=5, sticky=tk.W)

        # 状态查询
        self.query_status_btn = ttk.Button(
            master, text="查询状态", command=self.query_status
        )
        self.query_status_btn.grid(row=11, column=0, columnspan=3, padx=5, pady=5)

        # 状态表格
        self.status_table = ttk.Treeview(
            master, columns=("参数", "值"), show="headings", height=6
        )
        self.status_table.grid(
            row=12, column=0, columnspan=3, padx=5, pady=5, sticky=tk.NSEW
        )
        self.status_table.heading("参数", text="参数")
        self.status_table.heading("值", text="值")

        # 状态项
        status_params = ["输入电压(V)", "温度(°C)"]
        for param in status_params:
            self.status_table.insert("", "end", values=(param, "N/A"))

        # 日志显示
        self.text = scrolledtext.ScrolledText(master, width=40, height=8)
        self.text.grid(row=13, column=0, columnspan=3, padx=5, pady=5, sticky=tk.NSEW)

        # 清除按钮
        self.clear_btn = ttk.Button(master, text="清除数据", command=self.clear_data)
        self.clear_btn.grid(row=14, column=2, padx=5, pady=5, sticky=tk.E)

        # 定时器更新串口列表
        self.master.after(1000, self.update_ports)

    def update_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_cb["values"] = ports

        current_port = self.port_cb.get()
        if current_port not in ports and self.ser and self.ser.is_open:
            self.ser.close()
            self.connect_btn.config(text="打开串口")
            self.running = False

        if current_port not in ports:
            self.port_cb.set(ports[0] if ports else "")

        self.master.after(1000, self.update_ports)

    def log(self, msg):
        self.logfile.log(msg)

    def toggle_serial(self):
        if self.ser and self.ser.is_open:
            self.running = False
            self.ser.close()
            self.connect_btn.config(text="打开串口")
        else:
            try:
                self.ser = serial.Serial(
                    self.port_cb.get(), int(self.baud_cb.get()), timeout=0.01
                )
                self.running = True
                threading.Thread(target=self.read_thread, daemon=True).start()
                self.connect_btn.config(text="关闭串口")
            except Exception as e:
                messagebox.showerror("串口错误", str(e))

    def send_frame(self, frame):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        try:
            self.ser.write(frame)
            line = f">>> 发送: {frame.hex().upper()}"
            self._safe_insert(line + "\n")
            self.log(line)
        except Exception as e:
            messagebox.showerror("发送错误", str(e))

    def set_beam(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        try:
            device_id = int(self.id_entry.get())
            actual_freq = float(self.freq_entry.get())
            theta = float(self.theta_entry.get())
            phi = float(self.phi_entry.get())

            # 验证频率范围
            min_freq = 27500
            max_freq = 27500 + 50 * 70  # 27500 + 3500 = 31000
            if not (min_freq <= actual_freq <= max_freq):
                messagebox.showerror(
                    "参数错误", f"频率必须在{min_freq}-{max_freq} MHz之间"
                )
                return

            # 转换为频段号
            freq = int((actual_freq - 27500) / 50)

            # 验证频段号范围
            if not (0 <= freq <= 70):
                messagebox.showerror("参数错误", "计算得到的频段号超出范围")
                return

            # 计算beam值
            beam_h, beam_v = calculate_beam_values(theta, phi, actual_freq, is_tx=True)

            frame = build_tx_beam_frame(device_id, freq, beam_h, beam_v)
            self.send_frame(frame)
            self._safe_insert(f"实际频率: {actual_freq} MHz, 转换为频段号: {freq}")
            self._safe_insert(f"输入角度: θ={theta}°, φ={phi}°")
            self._safe_insert(f"计算得到: beam_h={beam_h}, beam_v={beam_v}")
        except ValueError:
            messagebox.showerror("参数错误", "请输入有效的数字")

    def set_array_enable(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        try:
            device_id = int(self.id_entry.get())
            enable = self.array_enable_var.get()
            frame = build_tx_enable_frame(device_id, enable)
            self.send_frame(frame)
        except ValueError:
            messagebox.showerror("参数错误", "请输入有效的设备ID")

    def set_polarization(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        try:
            device_id = int(self.id_entry.get())
            polarization = self.polarization_var.get()
            frame = build_tx_polarization_frame(device_id, polarization)
            self.send_frame(frame)
        except ValueError:
            messagebox.showerror("参数错误", "请输入有效的设备ID")

    def set_pa_enable(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        try:
            device_id = int(self.id_entry.get())
            enable = self.pa_enable_var.get()
            frame = build_pa_enable_frame(device_id, enable)
            self.send_frame(frame)
        except ValueError:
            messagebox.showerror("参数错误", "请输入有效的设备ID")

    # def set_phase_cal(self):  # 已隐藏
    #     if not self.ser or not self.ser.is_open:
    #         messagebox.showwarning("未连接", "请先打开串口")
    #         return
    #     try:
    #         device_id = int(self.id_entry.get())
    #         phase_offset = int(self.phase_entry.get())
    #         if not (0 <= phase_offset <= 63):
    #             messagebox.showerror("参数错误", "相位偏移必须在0-63之间")
    #             return
    #         frame = build_phase_cal_frame(device_id, phase_offset)
    #         self.send_frame(frame)
    #     except ValueError:
    #         messagebox.showerror("参数错误", "请输入有效的数字")

    def query_status(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        try:
            device_id = int(self.id_entry.get())
            frame = build_status_query_frame(device_id)
            self.send_frame(frame)
        except ValueError:
            messagebox.showerror("参数错误", "请输入有效的设备ID")

    def read_thread(self):
        buffer = bytearray()
        error_count = 0
        max_errors = 10
        last_receive_time = time.time()
        BUFFER_TIMEOUT = 0.1

        while self.running:
            try:
                if not self.ser or not self.ser.is_open:
                    time.sleep(0.1)
                    continue

                if self.ser.in_waiting > 0:
                    chunk = self.ser.read(min(self.ser.in_waiting, 1024))
                else:
                    if buffer and (time.time() - last_receive_time) > BUFFER_TIMEOUT:
                        line = f"[超时] 丢弃{len(buffer)}字节不完整数据: {buffer.hex().upper()}"
                        self._safe_insert(line)
                        self.log(line)
                        buffer.clear()
                    time.sleep(0.001)
                    continue

                if not chunk:
                    continue

                buffer.extend(chunk)
                last_receive_time = time.time()

                while len(buffer) >= 3:
                    if buffer[:3] != b"\x50\x53\x41":
                        byte = buffer.pop(0)
                        line = f"<<< 丢弃字节: {byte:02X}"
                        self._safe_insert(line)
                        self.log(line)
                        continue

                    if len(buffer) >= 6:
                        length = buffer[4]
                        if length > 255:
                            buffer.clear()
                            line = "[错误] 长度字段异常，清空buffer"
                            self._safe_insert(line)
                            self.log(line)
                            break

                        total_length = 5 + length + 1
                        if total_length > 263:
                            buffer.clear()
                            line = "[错误] 帧长超限，清空buffer"
                            self._safe_insert(line)
                            self.log(line)
                            break

                        if len(buffer) >= total_length:
                            frame = bytes(buffer[:total_length])
                            del buffer[:total_length]

                            try:
                                parsed, msg = parse_afdt_response(frame)
                                if parsed:
                                    addr = parsed.get("addr")
                                    if addr in ADDR_CMD_NAMES:
                                        name = ADDR_CMD_NAMES[addr]
                                        self._safe_insert(f"✓ {name}配置成功")
                                        self.log(f"收到回复: {name}配置成功")
                                    elif addr is None and parsed.get("payload"):
                                        status_info, status_msg = parse_status_response(
                                            parsed["payload"]
                                        )
                                        if status_msg == "OK" and status_info:
                                            self._safe_update_status_display(
                                                status_info
                                            )
                                            self._safe_insert(f"状态已更新")
                                            self.log(
                                                f"状态已更新: V={status_info.get('sys_vcc', 0)}V, T={status_info.get('sys_temp', 0)}°C"
                                            )
                            except Exception as e:
                                pass

                    error_count = 0
            except Exception as e:
                error_count += 1
                if error_count <= max_errors:
                    err = f"[接收错误] {e}"
                    self._safe_insert(err)
                    self.log(err)
                elif error_count == max_errors + 1:
                    err = "[接收错误] 连续错误过多，暂停错误打印"
                    self._safe_insert(err)
                    self.log(err)

                if not self.ser or not self.ser.is_open:
                    self.running = False
                    err = "[接收错误] 串口已关闭，停止接收线程"
                    self._safe_insert(err)
                    self.log(err)
                    break

                time.sleep(0.1)

    def update_status_display(self, status_info):
        items = self.status_table.get_children()
        if items:
            self.status_table.item(
                items[0], values=("输入电压(V)", f"{status_info.get('sys_vcc', 0):.1f}")
            )
            self.status_table.item(
                items[1], values=("温度(°C)", f"{status_info.get('sys_temp', 0)}")
            )

    def clear_data(self):
        self.text.delete("1.0", tk.END)
        for iid in self.status_table.get_children():
            param = self.status_table.item(iid, "values")[0]
            self.status_table.item(iid, values=(param, "N/A"))
        while not self.response_queue.empty():
            try:
                self.response_queue.get_nowait()
            except queue.Empty:
                break
        self.log("已清除所有数据和缓存")

    def __del__(self):
        if self.logfile:
            self.logfile.close()


class AFDR1024Controller(ThreadSafeUIMixin):
    def __init__(self, master, device_name):
        self.master = master
        self.device_name = device_name
        self.ser = None
        self.running = False
        self.logfile = AsyncLogger(f"{device_name}_serial_log.txt")

        # 响应队列
        self.response_queue = queue.Queue()

        # 串口设置
        self.port_cb = ttk.Combobox(master, width=10)
        self.port_cb.grid(row=0, column=0, padx=5, pady=5)
        self.update_ports()

        self.baud_cb = ttk.Combobox(
            master,
            values=["9600", "19200", "38400", "115200", "460800", "921600"],
            width=10,
        )
        self.baud_cb.grid(row=0, column=1, padx=5, pady=5)
        self.baud_cb.set("460800")  # AFDR1024默认波特率

        self.connect_btn = ttk.Button(
            master, text="打开串口", command=self.toggle_serial
        )
        self.connect_btn.grid(row=0, column=2, padx=5, pady=5)

        # 子阵ID设置
        ttk.Label(master, text="子阵ID:").grid(
            row=1, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.id_entry = ttk.Entry(master, width=5)
        self.id_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        self.id_entry.insert(0, "1")

        # RX波束设置
        ttk.Label(master, text="RX波束设置").grid(
            row=2, column=0, columnspan=3, padx=5, pady=5, sticky=tk.W
        )

        ttk.Label(master, text="实际频率(MHz):").grid(
            row=3, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.freq_entry = ttk.Entry(master, width=10)
        self.freq_entry.grid(row=3, column=1, padx=5, pady=3, sticky=tk.W)
        self.freq_entry.insert(0, "17700")  # 默认频率

        ttk.Label(master, text="俯仰角θ:").grid(
            row=4, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.theta_entry = ttk.Entry(master, width=8)
        self.theta_entry.grid(row=4, column=1, padx=5, pady=3, sticky=tk.W)
        self.theta_entry.insert(0, "0")

        ttk.Label(master, text="方位角φ:").grid(
            row=5, column=0, padx=5, pady=3, sticky=tk.W
        )
        self.phi_entry = ttk.Entry(master, width=8)
        self.phi_entry.grid(row=5, column=1, padx=5, pady=3, sticky=tk.W)
        self.phi_entry.insert(0, "0")

        self.set_beam_btn = ttk.Button(master, text="设置波束", command=self.set_beam)
        self.set_beam_btn.grid(row=3, column=2, rowspan=3, padx=5, pady=3, sticky=tk.NS)

        # RX阵列使能
        ttk.Label(master, text="RX阵列:").grid(
            row=6, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.array_enable_var = tk.BooleanVar()
        self.array_enable_check = ttk.Checkbutton(
            master, text="使能", variable=self.array_enable_var
        )
        self.array_enable_check.grid(row=6, column=1, padx=5, pady=5, sticky=tk.W)
        self.set_array_btn = ttk.Button(
            master, text="应用", command=self.set_array_enable
        )
        self.set_array_btn.grid(row=6, column=2, padx=5, pady=5, sticky=tk.W)

        # RX极化设置
        ttk.Label(master, text="极化设置:").grid(
            row=7, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.polarization_var = tk.IntVar(value=POLARIZATION_LHCP)
        ttk.Radiobutton(
            master, text="LHCP", variable=self.polarization_var, value=POLARIZATION_LHCP
        ).grid(row=7, column=1, padx=5, pady=5, sticky=tk.W)
        ttk.Radiobutton(
            master, text="RHCP", variable=self.polarization_var, value=POLARIZATION_RHCP
        ).grid(row=7, column=2, padx=5, pady=5, sticky=tk.W)
        self.set_polarization_btn = ttk.Button(
            master, text="设置极化", command=self.set_polarization
        )
        self.set_polarization_btn.grid(
            row=8, column=1, columnspan=2, padx=5, pady=5, sticky=tk.W
        )

        # 相位校准 (已隐藏)
        # ttk.Label(master, text="相位偏移(0-63):").grid(row=9, column=0, padx=5, pady=5, sticky=tk.W)
        # self.phase_entry = ttk.Entry(master, width=5)
        # self.phase_entry.grid(row=9, column=1, padx=5, pady=5, sticky=tk.W)
        # self.phase_entry.insert(0, "0")
        # self.set_phase_btn = ttk.Button(master, text="校准", command=self.set_phase_cal)
        # self.set_phase_btn.grid(row=9, column=2, padx=5, pady=5, sticky=tk.W)

        # 状态查询
        self.query_status_btn = ttk.Button(
            master, text="查询状态", command=self.query_status
        )
        self.query_status_btn.grid(row=10, column=0, columnspan=3, padx=5, pady=5)

        # 状态表格
        self.status_table = ttk.Treeview(
            master, columns=("参数", "值"), show="headings", height=6
        )
        self.status_table.grid(
            row=11, column=0, columnspan=3, padx=5, pady=5, sticky=tk.NSEW
        )
        self.status_table.heading("参数", text="参数")
        self.status_table.heading("值", text="值")

        # 状态项
        status_params = ["输入电压(V)", "温度(°C)"]
        for param in status_params:
            self.status_table.insert("", "end", values=(param, "N/A"))

        # 日志显示
        self.text = scrolledtext.ScrolledText(master, width=40, height=8)
        self.text.grid(row=12, column=0, columnspan=3, padx=5, pady=5, sticky=tk.NSEW)

        # 清除按钮
        self.clear_btn = ttk.Button(master, text="清除数据", command=self.clear_data)
        self.clear_btn.grid(row=13, column=2, padx=5, pady=5, sticky=tk.E)

        # 定时器更新串口列表
        self.master.after(1000, self.update_ports)

    def update_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_cb["values"] = ports

        current_port = self.port_cb.get()
        if current_port not in ports and self.ser and self.ser.is_open:
            self.ser.close()
            self.connect_btn.config(text="打开串口")
            self.running = False

        if current_port not in ports:
            self.port_cb.set(ports[0] if ports else "")

        self.master.after(1000, self.update_ports)

    def log(self, msg):
        self.logfile.log(msg)

    def toggle_serial(self):
        if self.ser and self.ser.is_open:
            self.running = False
            self.ser.close()
            self.connect_btn.config(text="打开串口")
        else:
            try:
                self.ser = serial.Serial(
                    self.port_cb.get(), int(self.baud_cb.get()), timeout=0.01
                )
                self.running = True
                threading.Thread(target=self.read_thread, daemon=True).start()
                self.connect_btn.config(text="关闭串口")
            except Exception as e:
                messagebox.showerror("串口错误", str(e))

    def send_frame(self, frame):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        try:
            self.ser.write(frame)
            line = f">>> 发送: {frame.hex().upper()}"
            self._safe_insert(line + "\n")
            self.log(line)
        except Exception as e:
            messagebox.showerror("发送错误", str(e))

    def set_beam(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        try:
            device_id = int(self.id_entry.get())
            actual_freq = float(self.freq_entry.get())
            theta = float(self.theta_entry.get())
            phi = float(self.phi_entry.get())

            # 验证频率范围
            min_freq = 17700
            max_freq = 17700 + 50 * 70  # 17700 + 3500 = 21200
            if not (min_freq <= actual_freq <= max_freq):
                messagebox.showerror(
                    "参数错误", f"频率必须在{min_freq}-{max_freq} MHz之间"
                )
                return

            # 转换为频段号
            freq = int((actual_freq - 17700) / 50)

            # 验证频段号范围
            if not (0 <= freq <= 70):
                messagebox.showerror("参数错误", "计算得到的频段号超出范围")
                return

            # 计算beam值
            beam_h, beam_v = calculate_beam_values(theta, phi, actual_freq, is_tx=False)

            frame = build_rx_beam_frame(device_id, freq, beam_v, beam_h)
            self.send_frame(frame)
            self._safe_insert(f"实际频率: {actual_freq} MHz, 转换为频段号: {freq}")
            self._safe_insert(f"输入角度: θ={theta}°, φ={phi}°")
            self._safe_insert(f"计算得到: beam_h={beam_h}, beam_v={beam_v}")
        except ValueError:
            messagebox.showerror("参数错误", "请输入有效的数字")

    def set_array_enable(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        try:
            device_id = int(self.id_entry.get())
            enable = self.array_enable_var.get()
            frame = build_rx_enable_frame(device_id, enable)
            self.send_frame(frame)
        except ValueError:
            messagebox.showerror("参数错误", "请输入有效的设备ID")

    def set_polarization(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        try:
            device_id = int(self.id_entry.get())
            polarization = self.polarization_var.get()
            frame = build_rx_polarization_frame(device_id, polarization)
            self.send_frame(frame)
        except ValueError:
            messagebox.showerror("参数错误", "请输入有效的设备ID")

        # def set_phase_cal(self):  # 已隐藏
        #     if not self.ser or not self.ser.is_open:
        #         messagebox.showwarning("未连接", "请先打开串口")
        #         return
        #     try:
        #         device_id = int(self.id_entry.get())
        #         phase_offset = int(self.phase_entry.get())
        #         if not (0 <= phase_offset <= 63):
        #             messagebox.showerror("参数错误", "相位偏移必须在0-63之间")
        #             return
        #         frame = build_rx_phase_cal_frame(device_id, phase_offset)
        #         self.send_frame(frame)
        except ValueError:
            messagebox.showerror("参数错误", "请输入有效的数字")

    def query_status(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        try:
            device_id = int(self.id_entry.get())
            frame = build_rx_status_query_frame(device_id)
            self.send_frame(frame)
        except ValueError:
            messagebox.showerror("参数错误", "请输入有效的设备ID")

    def read_thread(self):
        buffer = bytearray()
        error_count = 0
        max_errors = 10
        last_receive_time = time.time()
        BUFFER_TIMEOUT = 0.1

        while self.running:
            try:
                if not self.ser or not self.ser.is_open:
                    time.sleep(0.1)
                    continue

                if self.ser.in_waiting > 0:
                    chunk = self.ser.read(min(self.ser.in_waiting, 1024))
                else:
                    if buffer and (time.time() - last_receive_time) > BUFFER_TIMEOUT:
                        line = f"[超时] 丢弃{len(buffer)}字节不完整数据: {buffer.hex().upper()}"
                        self._safe_insert(line)
                        self.log(line)
                        buffer.clear()
                    time.sleep(0.001)
                    continue

                if not chunk:
                    continue

                buffer.extend(chunk)
                last_receive_time = time.time()

                while len(buffer) >= 3:
                    if buffer[:3] != b"\x50\x53\x41":
                        byte = buffer.pop(0)
                        line = f"<<< 丢弃字节: {byte:02X}"
                        self._safe_insert(line)
                        self.log(line)
                        continue

                    if len(buffer) >= 6:
                        length = buffer[4]
                        if length > 255:
                            buffer.clear()
                            line = "[错误] 长度字段异常，清空buffer"
                            self._safe_insert(line)
                            self.log(line)
                            break

                        total_length = 5 + length + 1
                        if total_length > 263:
                            buffer.clear()
                            line = "[错误] 帧长超限，清空buffer"
                            self._safe_insert(line)
                            self.log(line)
                            break

                        if len(buffer) >= total_length:
                            frame = bytes(buffer[:total_length])
                            del buffer[:total_length]

                            try:
                                parsed, msg = parse_afdt_response(
                                    frame, has_rx_status_bug=True
                                )
                                if parsed:
                                    addr = parsed.get("addr")
                                    if addr in ADDR_CMD_NAMES:
                                        name = ADDR_CMD_NAMES[addr]
                                        self._safe_insert(f"✓ {name}配置成功")
                                        self.log(f"收到回复: {name}配置成功")
                                    elif addr is None and parsed.get("payload"):
                                        status_info, status_msg = (
                                            parse_rx_status_response(parsed["payload"])
                                        )
                                        if status_msg == "OK" and status_info:
                                            self._safe_update_status_display(
                                                status_info
                                            )
                                            self._safe_insert(f"状态已更新")
                                            self.log(
                                                f"状态已更新: V={status_info.get('sys_vcc', 0)}V, T={status_info.get('sys_temp', 0)}°C"
                                            )
                            except Exception as e:
                                pass
                                line = f"<<< 解析失败: {str(e)}"
                                self._safe_insert(line)
                                self.log(line)

                    error_count = 0
            except Exception as e:
                error_count += 1
                if error_count <= max_errors:
                    err = f"[接收错误] {e}"
                    self._safe_insert(err)
                    self.log(err)
                elif error_count == max_errors + 1:
                    err = "[接收错误] 连续错误过多，暂停错误打印"
                    self._safe_insert(err)
                    self.log(err)

                if not self.ser or not self.ser.is_open:
                    self.running = False
                    err = "[接收错误] 串口已关闭，停止接收线程"
                    self._safe_insert(err)
                    self.log(err)
                    break

                time.sleep(0.1)

    def update_status_display(self, status_info):
        items = self.status_table.get_children()
        if items:
            self.status_table.item(
                items[0], values=("输入电压(V)", f"{status_info.get('sys_vcc', 0):.1f}")
            )
            self.status_table.item(
                items[1], values=("温度(°C)", f"{status_info.get('sys_temp', 0)}")
            )

    def clear_data(self):
        self.text.delete("1.0", tk.END)
        for iid in self.status_table.get_children():
            param = self.status_table.item(iid, "values")[0]
            self.status_table.item(iid, values=(param, "N/A"))
        while not self.response_queue.empty():
            try:
                self.response_queue.get_nowait()
            except queue.Empty:
                break
        self.log("已清除所有数据和缓存")

    def __del__(self):
        if self.logfile:
            self.logfile.close()


class SerialTool:
    def __init__(self, master):
        self.master = master
        self.master.title("多设备串口调试助手")
        self.master.geometry("1400x600")

        # 创建主框架
        self.main_frame = ttk.Frame(master)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 创建设备框架
        self.devices = {}

        # KaUDC004A 设备框架
        kaudc_frame = ttk.LabelFrame(self.main_frame, text="KaUDC004A")
        kaudc_frame.grid(row=0, column=0, padx=5, pady=5, sticky=tk.NSEW)
        self.devices["KaUDC004A"] = DeviceController(kaudc_frame, "KaUDC004A")

        # Ka1024_TX 设备框架（使用AFDT1024协议）
        ka1024_tx_frame = ttk.LabelFrame(self.main_frame, text="Ka1024_TX")
        ka1024_tx_frame.grid(row=0, column=1, padx=5, pady=5, sticky=tk.NSEW)
        self.devices["Ka1024_TX"] = AFDT1024Controller(ka1024_tx_frame, "Ka1024_TX")

        # Ka1024_RX 设备框架（使用AFDR1024协议）
        ka1024_rx_frame = ttk.LabelFrame(self.main_frame, text="Ka1024_RX")
        ka1024_rx_frame.grid(row=0, column=2, padx=5, pady=5, sticky=tk.NSEW)
        self.devices["Ka1024_RX"] = AFDR1024Controller(ka1024_rx_frame, "Ka1024_RX")

        # 设置列权重，使三个设备框架均匀分布
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.columnconfigure(2, weight=1)
        self.main_frame.rowconfigure(0, weight=1)


if __name__ == "__main__":
    root = tk.Tk()
    try:
        logo_img = tk.PhotoImage(file="soft_hertz_logo_deepspace_blue_512.png")
        root.iconphoto(True, logo_img)
    except Exception:
        pass
    app = SerialTool(root)
    root.mainloop()
