import tkinter as tk
import sys
import os
import tkinter as tk
from tkinter import ttk
from common.serial_controller import SerialController
from devices.kaudc004a_device import KauDC004ADevice
from devices.kaudc004a_protocol import KauDC004AProtocol
from ui.kaudc004a_ui import KauDC004AUI

class Application:
    def __init__(self, root):
        """初始化应用程序，整合串口控制器、设备协议、设备类和UI"""
        self.root = root
        self.root.title("softHertz串口调试工具")
        
        # 设置窗口图标
        self._set_window_icon()
        
        # 初始化组件
        self.serial_controller = SerialController()
        self.device = None
        self.ui = None
        
        # 保存引用，以便UI可以访问应用程序实例
        self.root.app = self
        
        # 初始化默认设备
        self.switch_device("KauDC004A")
        
        # 设置异常处理
        self._setup_exception_handling()
        
    def _set_window_icon(self):
        """设置窗口图标"""
        try:
            # 获取当前脚本所在目录
            script_dir = os.path.dirname(os.path.abspath(__file__))
            icon_path = os.path.join(script_dir, "soft_hertz_logo_deepspace_blue_512.png")
            logo_img = tk.PhotoImage(file=icon_path)
            self.root.iconphoto(True, logo_img)
        except Exception as e:
            print(f"设置图标失败: {e}")
    
    def _setup_exception_handling(self):
        """设置异常处理，确保程序优雅退出"""
        # 设置窗口关闭事件处理
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 重定向标准异常处理
        original_excepthook = sys.excepthook
        
        def exception_handler(exc_type, exc_value, exc_traceback):
            """自定义异常处理器"""
            # 记录异常信息
            print(f"程序异常: {exc_type.__name__}: {exc_value}")
            
            # 调用原始异常处理器
            original_excepthook(exc_type, exc_value, exc_traceback)
        
        sys.excepthook = exception_handler
    
    def on_closing(self):
        """处理窗口关闭事件"""
        # 关闭串口连接
        if self.serial_controller and self.serial_controller.is_connected():
            self.serial_controller.close()
            
        # 退出应用
        self.root.destroy()
        sys.exit(0)
        
    def switch_device(self, device_type):
        """切换设备类型"""
        # 断开当前设备连接
        if self.serial_controller and self.serial_controller.is_connected():
            self.serial_controller.close()
            
        # 清除当前UI组件
        if self.ui:
            for widget in self.root.winfo_children():
                widget.destroy()
        
        # 根据选择的设备类型创建设备和UI
        if device_type == "KauDC004A":
            from devices.kaudc004a_device import KauDC004ADevice
            from ui.kaudc004a_ui import KauDC004AUI
            
            self.device = KauDC004ADevice(self.serial_controller)
            self.ui = KauDC004AUI(self.root, self.device)
        elif device_type == "AFD01_QS":
            from devices.afd01_qs_device import AFD01_QS_Device
            from ui.afd01_qs_ui import AFD01_QS_UI
            
            self.device = AFD01_QS_Device(self.serial_controller)
            self.ui = AFD01_QS_UI(self.root, self.device)
        
        # 设置窗口标题
        self.root.title(f"softHertz串口调试工具 - {device_type}")

if __name__ == "__main__":
    # 创建主窗口
    root = tk.Tk()
    
    # 应用样式
    style = tk.ttk.Style()
    # 设置合适的字体以确保中文正常显示
    if sys.platform.startswith('win'):
        style.configure('.', font=('SimHei', 10))
    else:
        style.configure('.', font=('WenQuanYi Micro Hei', 10))
    
    # 初始化应用
    app = Application(root)
    
    # 启动主事件循环
    root.mainloop()