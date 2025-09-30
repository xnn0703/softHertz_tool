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
        # 初始化设备类型，默认为KauDC004A
        self.current_device_type = "KauDC004A"
        # 保存定时器ID
        self.update_ports_timer = None
        self.ui_update_timer = None
        self.create_widgets()
        self.setup_callbacks()
        
    def set_device_type(self, device_type):
        """设置设备类型"""
        print(f"[DEBUG] UIBase: 设置设备类型为: {device_type}")
        self.current_device_type = device_type
        if hasattr(self, 'device_type_cb'):
            self.device_type_cb.set(device_type)
        
    def destroy(self):
        """清理资源，停止定时器"""
        print("[DEBUG] UIBase: 清理资源，停止定时器")
        # 停止串口更新定时器
        if self.update_ports_timer:
            self.master.after_cancel(self.update_ports_timer)
            self.update_ports_timer = None
        # 停止UI更新定时器
        if self.ui_update_timer:
            self.master.after_cancel(self.ui_update_timer)
            self.ui_update_timer = None
    
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
        self._schedule_update_ports()
        # 定时器每100毫秒刷新一次UI
        self._schedule_update_ui()
    
    def _schedule_update_ports(self):
        """安排下一次串口更新"""
        if self.update_ports_timer is not None:
            self.master.after_cancel(self.update_ports_timer)
        self.update_ports_timer = self.master.after(1000, self.update_ports)
    
    def _schedule_update_ui(self):
        """安排下一次UI更新"""
        if self.ui_update_timer is not None:
            self.master.after_cancel(self.ui_update_timer)
        self.ui_update_timer = self.master.after(100, self.update_ui)
    
    def update_ports(self):
        """更新可用串口列表"""
        if hasattr(self.device.serial_controller, 'update_ports'):
            ports = self.device.serial_controller.update_ports()
            # 安全检查：确保port_cb仍然存在
            if hasattr(self, 'port_cb') and self.port_cb.winfo_exists():
                current_port = self.port_cb.get()
                
                # 更新下拉框选项
                self.port_cb['values'] = ports
                
                # 如果当前选择的串口不可用，选择第一个可用串口
                if current_port not in ports and ports:
                    self.port_cb.set(ports[0])
        
        # 安排下一次更新，使用_schedule_update_ports方法
        if hasattr(self, '_schedule_update_ports'):
            self._schedule_update_ports()
    
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
        
        # 无论操作是打开还是关闭，都直接检查当前的连接状态来更新UI
        current_state = self.device.is_connected()
        
        if success:
            self.connect_btn.config(text="关闭串口" if current_state else "打开串口")
            self.log_message(msg)
        else:
            # 发生错误时也更新UI状态
            self.connect_btn.config(text="打开串口")
            messagebox.showerror("串口错误", msg)
            
        # 强制更新UI以确保状态一致
        self.master.update_idletasks()
    
    def log_message(self, msg):
        """记录日志（仅写入文件，不在UI中显示）"""
        # 日志信息仍会由设备控制器写入到文件中
        pass
    
    def clear_log(self):
        """清除日志方法（由于已移除UI组件，此方法为空实现）"""
        pass
    
    def update_ui(self):
        """更新UI显示（子类需要重写此方法）
        
        基类方法负责安排下一次UI更新，子类应该先调用super().update_ui()，
        然后再添加自己的UI更新逻辑。
        """
        # 继续安排下一次UI更新
        self._schedule_update_ui()
        pass
    
    def run(self):
        """运行UI主循环"""
        self.master.mainloop()