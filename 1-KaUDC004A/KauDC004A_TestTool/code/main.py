import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import serial
import serial.tools.list_ports
from protocol import build_frame, parse_response
import threading
import datetime
import time
import queue

# 定义布局配置字典
layout_config = {
    'port_cb': {'row': 0, 'column': 0, 'padx': 10, 'pady': 10},
    'baud_cb': {'row': 0, 'column': 1, 'padx': 10, 'pady': 10},
    'connect_btn': {'row': 0, 'column': 2, 'padx': 10, 'pady': 10},
    'status_table': {'row': 1, 'column': 0, 'column_span': 4, 'padx': 10, 'pady': 10},
    'txlo_btn': {'row': 2, 'column': 0, 'padx': 10, 'pady': 10},
    'txlo_cb': {'row': 2, 'column': 1, 'padx': 10, 'pady': 10},
    'rxlo_btn': {'row': 3, 'column': 0, 'padx': 10, 'pady': 10},
    'rxlo_cb': {'row': 3, 'column': 1, 'padx': 10, 'pady': 10},
    'cmd_cb': {'row': 4, 'column': 0, 'column_span': 1, 'padx': 10, 'pady': 10},
    'param_entry': {'row': 4, 'column': 1, 'padx': 10, 'pady': 10},
    'send_btn': {'row': 4, 'column': 2, 'padx': 10, 'pady': 10},
    'text': {'row': 5, 'column': 0, 'column_span': 3, 'padx': 10, 'pady': 10},
    'device_query_btn': {'row': 6, 'column': 1, 'padx': 10, 'pady': 10},
    'clear_btn': {'row': 6, 'column': 2, 'padx': 10, 'pady': 10}
}

class SerialTool:
    def __init__(self, master):
        self.master = master
        self.master.title("KaUDC004A串口调试助手")
        self.ser = None
        self.running = False
        self.logfile = open("serial_log.txt", "a", encoding="utf-8")

        # 响应队列，用于 query_device_worker
        self.response_queue = queue.Queue()

        # 串口设置
        self.port_cb = ttk.Combobox(master, width=10)
        self.port_cb.grid(row=layout_config['port_cb']['row'], column=layout_config['port_cb']['column'],
                          padx=layout_config['port_cb']['padx'], pady=layout_config['port_cb']['pady'])
        self.update_ports()  # 初始更新串口列表

        self.baud_cb = ttk.Combobox(master, values=["9600", "19200", "38400", "115200", "921600"], width=10)
        self.baud_cb.grid(row=layout_config['baud_cb']['row'], column=layout_config['baud_cb']['column'],
                          padx=layout_config['baud_cb']['padx'], pady=layout_config['baud_cb']['pady'])
        self.baud_cb.set("115200")

        self.connect_btn = ttk.Button(master, text="打开串口", command=self.toggle_serial)
        self.connect_btn.grid(row=layout_config['connect_btn']['row'], column=layout_config['connect_btn']['column'],
                              padx=layout_config['connect_btn']['padx'], pady=layout_config['connect_btn']['pady'])

        # 状态表格
        self.status_table = ttk.Treeview(master, columns=("Parameter", "Value"), show="headings", height=8)
        self.status_table.grid(row=layout_config['status_table']['row'], column=layout_config['status_table']['column'],
                               columnspan=layout_config['status_table']['column_span'], padx=layout_config['status_table']['padx'],
                               pady=layout_config['status_table']['pady'])
        self.status_table.heading("Parameter", text="参数")
        self.status_table.heading("Value", text="值")
        for param in ["版本", "温度", "TxLO", "RxLO", "Tx衰减", "Rx衰减", "锁定状态"]:
            self.status_table.insert("", "end", values=(param, "N/A"))

        # 接收本振下拉框（RxLO）
        self.rxlo_cb = ttk.Combobox(master, values=[ "16.75GHz (17.7-18.2)", "17.25GHz (18.2-19.2)", "18.25GHz (19.2-20.2)", "19.25GHz (20.2-21.2)"], width=25)
        self.rxlo_cb.grid(row=layout_config['rxlo_cb']['row'], column=layout_config['rxlo_cb']['column'],
                          padx=layout_config['rxlo_cb']['padx'], pady=layout_config['rxlo_cb']['pady'])
        self.rxlo_cb.set("16.75GHz (17.7-18.2)")

        # 发射本振下拉框（TxLO）
        self.txlo_cb = ttk.Combobox(master, values=["26.55GHz (27.5-28.35)", "27.40GHz (28.35-29.2)", "28.05GHz (29.00-30.0)", "29.05GHz (30.00-31.0)"], width=25)
        self.txlo_cb.grid(row=layout_config['txlo_cb']['row'], column=layout_config['txlo_cb']['column'],
                          padx=layout_config['txlo_cb']['padx'], pady=layout_config['txlo_cb']['pady'])
        self.txlo_cb.set("26.55GHz (27.5-28.35)")

        # 分开设置发射和接收本振按钮
        self.txlo_btn = ttk.Button(master, text="设置发射本振", command=self.set_txlo)
        self.txlo_btn.grid(row=layout_config['txlo_btn']['row'], column=layout_config['txlo_btn']['column'],
                           padx=layout_config['txlo_btn']['padx'], pady=layout_config['txlo_btn']['pady'])

        self.rxlo_btn = ttk.Button(master, text="设置接收本振", command=self.set_rxlo)
        self.rxlo_btn.grid(row=layout_config['rxlo_btn']['row'], column=layout_config['rxlo_btn']['column'],
                           padx=layout_config['rxlo_btn']['padx'], pady=layout_config['rxlo_btn']['pady'])

        # 命令选择
        self.cmd_cb = ttk.Combobox(master, values=["发射衰减设置", "接收衰减设置", "本振查询", "衰减查询", "复位设备", "版本回读", "温度查询"], width=25)
        self.cmd_cb.grid(row=layout_config['cmd_cb']['row'], column=layout_config['cmd_cb']['column'],
                         columnspan=layout_config['cmd_cb']['column_span'], padx=layout_config['cmd_cb']['padx'],
                         pady=layout_config['cmd_cb']['pady'])
        self.cmd_cb.set("本振查询")
        self.cmd_cb.bind("<<ComboboxSelected>>", self.update_input_type)

        self.param_entry = ttk.Entry(master, width=10)
        self.param_entry.grid(row=layout_config['param_entry']['row'], column=layout_config['param_entry']['column'],
                              padx=layout_config['param_entry']['padx'], pady=layout_config['param_entry']['pady'])
        self.param_entry.grid_forget()

        self.send_btn = ttk.Button(master, text="发送指令", command=self.send_command)
        self.send_btn.grid(row=layout_config['send_btn']['row'], column=layout_config['send_btn']['column'],
                           padx=layout_config['send_btn']['padx'], pady=layout_config['send_btn']['pady'])

        self.text = scrolledtext.ScrolledText(master, width=80, height=10)
        self.text.grid(row=layout_config['text']['row'], column=layout_config['text']['column'],
                       columnspan=layout_config['text']['column_span'], padx=layout_config['text']['padx'],
                       pady=layout_config['text']['pady'])

        # 设备查询按钮
        self.device_query_btn = ttk.Button(master, text="设备查询", command=self.query_device_thread)
        self.device_query_btn.grid(row=layout_config['device_query_btn']['row'], column=layout_config['device_query_btn']['column'],
                                   padx=layout_config['device_query_btn']['padx'], pady=layout_config['device_query_btn']['pady'])

        # 清除数据按钮
        self.clear_btn = ttk.Button(master, text="清除数据", command=self.clear_data)
        self.clear_btn.grid(row=layout_config['clear_btn']['row'], column=layout_config['clear_btn']['column'],
                            padx=layout_config['clear_btn']['padx'], pady=layout_config['clear_btn']['pady'])
        self._cmd_name_map = {
            0x0B: "版本回读", 0x0C: "温度查询", 0x13: "本振查询", 0x16: "衰减查询"
        }

        # 定时器每5秒刷新一次串口列表
        self.master.after(1000, self.update_ports)

    def update_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_cb['values'] = ports

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
        ts = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")
        self.logfile.write(ts + msg + "\n")
        self.logfile.flush()

    def toggle_serial(self):
        if self.ser and self.ser.is_open:
            self.running = False
            self.ser.close()
            self.connect_btn.config(text="打开串口")
        else:
            try:
                self.ser = serial.Serial(self.port_cb.get(), int(self.baud_cb.get()), timeout=0.1)
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
        payload = b'\x12\x00\x00\x00' + int(float(freq)).to_bytes(2, 'big')
        self.send_payload(payload)

    def set_rxlo(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return        
        # 获取接收本振频率并发送指令
        freq = self.extract_frequency(self.rxlo_cb.get())
        payload = b'\x0E\x00\x00\x00' + int(float(freq)).to_bytes(2, 'big')
        self.send_payload(payload)

    def send_payload(self, payload):
        # 发送构建好的数据包
        frame = build_frame(payload)
        self.ser.write(frame)
        line = f">>> 发送: {frame.hex().upper()}"
        self.text.insert(tk.END, line + "\n")
        self.log(line)

    def send_command(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return

        cmd = self.cmd_cb.get()
        payload = b''
        param = self.param_entry.get().strip()

        try:
            if cmd == "复位设备":
                payload = b'\x0A\x00\x00\x00\x00\x00'
            elif cmd == "版本回读":
                payload = b'\x0B\x00\x00\x00\x00\x00'
            elif cmd == "温度查询":
                payload = b'\x0C\x00\x00\x00\x00\x00'
            elif cmd == "接收本振设置":
                freq = self.extract_frequency(self.rxlo_cb.get())  # 获取频率并提取数字部分
                payload = b'\x0E\x00\x00\x00' + int(float(freq)).to_bytes(2, 'big')
            elif cmd == "发射本振设置":
                freq = self.extract_frequency(self.txlo_cb.get())  # 获取频率并提取数字部分
                payload = b'\x12\x00\x00\x00' + int(float(freq)).to_bytes(2, 'big')
            elif cmd == "本振查询":
                payload = b'\x13\x00\x00\x00\x00\x00'
            elif cmd == "发射衰减设置":
                try:
                    att = float(param)
                    if 0 <= att <= 30:
                        # 将衰减值转换为 2 字节，并且乘以 10 来实现 dB 单位
                        tmp = int(att * 10).to_bytes(2, 'big')
                        payload = b'\x14\x00\x00\x00' + tmp
                    else:
                        messagebox.showerror("数值必须在0-30内", "发射衰减值必须在0到30之间")
                except ValueError:
                    messagebox.showerror("无效输入", "请输入有效的数字")

            elif cmd == "接收衰减设置":
                try:
                    att = float(param)
                    if 0 <= att <= 30:
                        # 将衰减值转换为 2 字节，并且乘以 10 来实现 dB 单位
                        tmp = int(att * 10).to_bytes(2, 'big')
                        payload = b'\x15\x00\x00\x00' + tmp
                    else:
                        messagebox.showerror("数值必须在0-30内", "接收衰减值必须在0到30之间")
                except ValueError:
                    messagebox.showerror("无效输入", "请输入有效的数字")
            elif cmd == "衰减查询":
                payload = b'\x16\x00\x00\x00\x00\x00'
            else:
                messagebox.showerror("命令错误", "未知命令")
                return

            frame = build_frame(payload)
            self.ser.write(frame)
            line = f">>> 发送: {frame.hex().upper()}"
            self.text.insert(tk.END, line + "\n")
            self.log(line)
        except Exception as e:
            messagebox.showerror("发送错误", str(e))

    def parse_fields(self, cmd_byte, data):
        if cmd_byte == 0x0B:
            # 提取版本号：Byte5 到 Byte7，合并成一个 24 位的整数
            version_bytes = data[1:5]  # 取 Byte5, Byte6, Byte7 Byte8
            version = int.from_bytes(version_bytes, byteorder='big')  # 转换为十进制
            return f"版本号: {version}"
        elif cmd_byte == 0x0C:
            temp_c = data[1]
            return f"温度: {temp_c}°C"
        elif cmd_byte == 0x13:
            tx = int.from_bytes(data[1:3], 'big')
            rx = int.from_bytes(data[3:5], 'big')
            bits = f"{data[5]:08b}"
            return f"TxLO: {tx} MHz, RxLO: {rx} MHz, LOCK: {bits}"
        elif cmd_byte in (0x14, 0x15):
            att = int.from_bytes(data[4:6], 'big') / 10
            return f"衰减: {att:.1f} dB"
        elif cmd_byte == 0x16:
            tx = int.from_bytes(data[1:3], 'big') / 10
            rx = int.from_bytes(data[3:5], 'big') / 10
            return f"Tx衰减: {tx:.1f} dB, Rx衰减: {rx:.1f} dB"
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
            self.param_entry.grid(row=layout_config['param_entry']['row'], column=layout_config['param_entry']['column'],
                                  padx=layout_config['param_entry']['padx'], pady=layout_config['param_entry']['pady'])

    def read_thread(self):
        buffer = bytearray()
        while self.running:
            try:
                chunk = self.ser.read(1)
                if not chunk:
                    continue
                buffer.extend(chunk)
                while len(buffer) >= 2:
                    if buffer[0] != 0xAA or buffer[1] != 0x55:
                        buffer.pop(0)
                        continue
                    if len(buffer) < 12:
                        break
                    frame = bytes(buffer[:12])
                    del buffer[:12]

                    parsed, msg = parse_response(frame)
                    line = f"<<< 收到: {frame.hex().upper()} [{msg}]"
                    self.text.insert(tk.END, line + "\n")
                    self.log(line)

                    if msg == "OK":
                        cmd = parsed[0]
                        # 1) 原来的队列逻辑
                        self.response_queue.put((cmd, parsed))
                        # 2) 打印字段
                        extra = self.parse_fields(cmd, parsed)
                        if extra:
                            self.text.insert(tk.END, "    " + extra + "\n")
                            self.log("    " + extra)
                        # 3) **立刻更新表格**（新增这段）
                        name = self._cmd_name_map.get(cmd)
                        if name:
                            self.update_display(name, parsed)

                    self.text.see(tk.END)
            except Exception as e:
                err = f"[接收错误] {e}"
                self.text.insert(tk.END, err + "\n")
                self.log(err)

    def update_display(self, name, data):
        if name == "版本回读":
            version_bytes = data[1:5]
            version = int.from_bytes(version_bytes, byteorder='big')  # 转换为十进制
            self.status_table.item(self.status_table.get_children()[0], values=("版本", f"{version}"))
        elif name == "温度查询":
            temp_c = data[1]
            self.status_table.item(self.status_table.get_children()[1], values=("温度", f"{temp_c}°C"))
        elif name == "本振查询":
            tx = int.from_bytes(data[1:3], 'big')
            rx = int.from_bytes(data[3:5], 'big')
            bits = f"{data[5]:08b}"
            self.status_table.item(self.status_table.get_children()[2], values=("TxLO", f"{tx} MHz"))
            self.status_table.item(self.status_table.get_children()[3], values=("RxLO", f"{rx} MHz"))
            self.status_table.item(self.status_table.get_children()[6], values=("锁定状态", bits))
        elif name == "衰减查询":
            tx = int.from_bytes(data[1:3], 'big') / 10
            rx = int.from_bytes(data[3:5], 'big') / 10
            self.status_table.item(self.status_table.get_children()[4], values=("Tx衰减", f"{tx:.1f} dB"))
            self.status_table.item(self.status_table.get_children()[5], values=("Rx衰减", f"{rx:.1f} dB"))

    def query_device_worker(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先打开串口")
            return
        queries = [
            (0x0B, b'\x0B\x00\x00\x00\x00\x00', "版本回读"),
            (0x0C, b'\x0C\x00\x00\x00\x00\x00', "温度查询"),
            (0x13, b'\x13\x00\x00\x00\x00\x00', "本振查询"),
            (0x16, b'\x16\x00\x00\x00\x00\x00', "衰减查询")
        ]
        for attempt in range(3):
            self.text.insert(tk.END, f"\n尝试查询设备，第 {attempt+1} 次...\n")
            self.log(f"尝试查询设备，第 {attempt+1} 次...")
            all_ok = True
            for cmd_byte, payload, name in queries:
                self.text.insert(tk.END, f"\n查询: {name}\n")
                self.log(f"查询: {name}")
                self.ser.write(build_frame(payload))
                self.log(f">>> 发送查询指令: {payload.hex().upper()}")

                # 清空旧回复
                while not self.response_queue.empty():
                    self.response_queue.get_nowait()

                try:
                    got_cmd, parsed = self.response_queue.get(timeout=2)
                    if got_cmd == cmd_byte:
                        self.text.insert(tk.END, f"{name} 查询成功，回复正常\n")
                        self.log(f"{name} 查询成功，回复正常")
                        self.update_display(name, parsed)
                    else:
                        all_ok = False
                        self.text.insert(tk.END, f"{name} 收到错帧: 0x{got_cmd:02X}\n")
                        self.log(f"{name} 收到错帧: 0x{got_cmd:02X}")
                except queue.Empty:
                    all_ok = False
                    self.text.insert(tk.END, f"{name} 查询超时无响应\n")
                    self.log(f"{name} 查询超时无响应")

            if all_ok:
                self.text.insert(tk.END, "✅ 设备查询完成，全部成功！\n")
                self.log("设备查询完成，全部成功")
                break
            else:
                self.text.insert(tk.END, "❌ 本轮查询有失败，重试...\n")
                self.log("本轮查询有失败，重试...")
        else:
            self.text.insert(tk.END, "❌ 所有查询尝试失败！请检查设备连接或协议配置。\n")
            self.log("所有查询尝试失败")

    def query_device_thread(self):
        threading.Thread(target=self.query_device_worker, daemon=True).start()

    def clear_data(self):
        # 清除文本显示
        self.text.delete('1.0', tk.END)
        # 重置状态表格
        for iid in self.status_table.get_children():
            param = self.status_table.item(iid, 'values')[0]
            self.status_table.item(iid, values=(param, "N/A"))
        # 清空响应队列
        while not self.response_queue.empty():
            try: self.response_queue.get_nowait()
            except queue.Empty: break
        self.log("已清除所有数据和缓存")

    def __del__(self):
        if self.logfile:
            self.logfile.close()

if __name__ == "__main__":
    root = tk.Tk()
    try:
        logo_img = tk.PhotoImage(file="soft_hertz_logo_deepspace_blue_512.png")
        root.iconphoto(True, logo_img)
    except Exception:
        pass    
    app = SerialTool(root)
    root.mainloop()
