import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
import tkinter as tk

class UIBase:
    """UI基础类"""
    
    def __init__(self, master, device):
        self.master = master
        self.device = device
        self.master.title("设备调试助手")
        self.current_device_type = "KauDC004A"
        self.create_widgets()
        self.setup_callbacks()
        
    def create_widgets(self):
        """创建UI组件"""
        # 设备类型选择区域
        self.device_type_label = ttk.Label(self.master, text="设备类型:")
        self.device_type_label.grid(row=0, column=0, padx=5, pady=5)
        self.device_type_cb = ttk.Combobox(self.master, values=["KauDC004A", "AFD01_QS"], width=12)
        self.device_type_cb.grid(row=0, column=1, padx=5, pady=5)
        self.device_type_cb.set("KauDC004A")
        self.device_type_cb.bind("<<ComboboxSelected>>", self.on_device_type_changed)
        
        # 串口设置区域
        self.port_label = ttk.Label(self.master, text="串口:")
        self.port_label.grid(row=0, column=2, padx=5, pady=5)
        self.port_cb = ttk.Combobox(self.master, width=10)
        self.port_cb.grid(row=0, column=3, padx=5, pady=5)
        
        self.baud_label = ttk.Label(self.master, text="波特率:")
        self.baud_label.grid(row=0, column=4, padx=5, pady=5)
        self.baud_cb = ttk.Combobox(self.master, values=["9600", "19200", "38400", "115200", "921600"], width=10)
        self.baud_cb.grid(row=0, column=5, padx=5, pady=5)
        self.baud_cb.set("115200")
        
        self.connect_btn = ttk.Button(self.master, text="打开串口", command=self.toggle_serial)
        self.connect_btn.grid(row=0, column=6, padx=5, pady=5)
    
    def setup_callbacks(self):
        """设置回调函数"""
        # 定时器每1秒刷新一次串口列表
        self.master.after(1000, self.update_ports)
    
    def update_ports(self):
        """更新可用串口列表"""
        if hasattr(self.device.serial_controller, 'update_ports'):
            ports = self.device.serial_controller.update_ports()
            current_port = self.port_cb.get()
            
            # 更新下拉框选项
            self.port_cb['values'] = ports
            
            # 如果当前选择的串口不可用，选择第一个可用串口
            if current_port not in ports and ports:
                self.port_cb.set(ports[0])
        
        # 继续定时更新
        self.master.after(1000, self.update_ports)
    
    def toggle_serial(self):
        """打开或关闭串口"""
        if not hasattr(self.device.serial_controller, 'toggle_serial'):
            messagebox.showerror("错误", "设备控制器不支持串口操作")
            return
        
        port = self.port_cb.get()
        baud_rate = self.baud_cb.get()
        
        if not port:
            messagebox.showwarning("警告", "请选择串口")
            return
        
        success, msg = self.device.serial_controller.toggle_serial(port, baud_rate)
        if success:
            self.connect_btn.config(text="关闭串口" if self.device.is_connected() else "打开串口")
            self.log_message(msg)
        else:
            messagebox.showerror("串口错误", msg)
    
    def log_message(self, msg):
        """记录日志（仅写入文件，不在UI中显示）"""
        # 日志信息仍会由设备控制器写入到文件中
        pass
        
    def on_device_type_changed(self, event):
        """设备类型变更事件处理"""
        new_device_type = self.device_type_cb.get()
        if new_device_type != self.current_device_type:
            self.current_device_type = new_device_type
            self.log_message(f"设备类型已切换为: {new_device_type}")
            # 通知应用程序切换设备
            if hasattr(self.master, 'app') and hasattr(self.master.app, 'switch_device'):
                self.master.app.switch_device(new_device_type)
    
    def clear_log(self):
        """清除日志方法（由于已移除UI组件，此方法为空实现）"""
        pass
    
    def run(self):
        """运行UI主循环"""
        self.master.mainloop()