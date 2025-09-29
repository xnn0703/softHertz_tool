import tkinter as tk
import sys
import os
import tkinter as tk
import webbrowser
from tkinter import ttk
from common.serial_controller import SerialController
from devices.kaudc004a_device import KauDC004ADevice
from devices.kaudc004a_protocol import KauDC004AProtocol
from ui.kaudc004a_ui import KauDC004AUI

# 软件版本号
APP_VERSION = "V2.0"
# 软件发布日期
APP_RELEASE_DATE = "2025-10-01"
# 公司官网
COMPANY_WEBSITE = "http://www.soft-hertz.com/"

class Application:
    def __init__(self, root):
        """初始化应用程序，整合串口控制器、设备协议、设备类和UI"""
        self.root = root
        self.root.title(f"softHertz串口调试工具")
        
        # 设置窗口图标
        self._set_window_icon()
        
        # 创建菜单栏
        self._create_menu()
        
        # 创建UI容器，用于后续只销毁UI组件而不影响菜单栏
        self.ui_container = ttk.Frame(self.root)
        self.ui_container.pack(fill=tk.BOTH, expand=True)
        
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
        print(f"[DEBUG] 开始切换设备类型: {device_type}")
        
        # 断开当前设备连接 - 加强版：无论是否连接都尝试关闭
        if self.serial_controller:
            print(f"[DEBUG] 强制断开当前串口连接")
            self.serial_controller.close()  # 强制调用close方法，确保串口资源释放
            # 额外添加短暂延迟，确保串口端口完全释放
            import time
            time.sleep(0.2)
            print(f"[DEBUG] 串口已关闭，等待资源释放完成")
        else:
            print(f"[DEBUG] 串口控制器不存在")
            
        # 清除当前UI容器内的组件
        if self.ui:
            print(f"[DEBUG] 清除UI容器中的组件")
            # 调用destroy方法停止定时器
            try:
                self.ui.destroy()
            except Exception as e:
                print(f"[DEBUG] 调用UI destroy方法时出错: {e}")
            
            # 销毁所有组件
            for widget in self.ui_container.winfo_children():
                widget.destroy()
        
        # 根据选择的设备类型创建设备和UI
        if device_type == "KauDC004A":
            print(f"[DEBUG] 创建KauDC004A设备和UI")
            from devices.kaudc004a_device import KauDC004ADevice
            from ui.kaudc004a_ui import KauDC004AUI
            
            self.device = KauDC004ADevice(self.serial_controller)
            self.ui = KauDC004AUI(self.ui_container, self.device)
            # 设置设备类型变更回调函数
            print(f"[DEBUG] 为KauDC004AUI设置回调函数")
            self.ui.device_type_change_callback = self.switch_device
        elif device_type == "AFD01_QS":
            print(f"[DEBUG] 创建AFD01_QS设备和UI")
            from devices.afd01_qs_device import AFD01_QS_Device
            from ui.afd01_qs_ui import AFD01_QS_UI
            
            self.device = AFD01_QS_Device(self.serial_controller)
            self.ui = AFD01_QS_UI(self.ui_container, self.device)
            # 设置设备类型变更回调函数
            print(f"[DEBUG] 为AFD01_QS_UI设置回调函数")
            self.ui.device_type_change_callback = self.switch_device
        else:
            print(f"[DEBUG] 未知设备类型: {device_type}")
        
        # 设置窗口标题
        self.root.title(f"softHertz串口调试工具 - {device_type}")
        print(f"[DEBUG] 设置窗口标题为: softHertz串口调试工具 - {device_type}")
        
        # 使用set_device_type方法设置设备类型，确保UI和内部状态同步
        if hasattr(self.ui, 'set_device_type'):
            print(f"[DEBUG] 调用set_device_type设置设备类型: {device_type}")
            self.ui.set_device_type(device_type)
        
        print(f"[DEBUG] 设备切换完成: {device_type}")

    def _create_menu(self):
        """创建菜单栏，包含软件信息按钮"""
        # 创建菜单栏
        menubar = tk.Menu(self.root)
        
        # 创建帮助菜单
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="软件信息", command=self.show_software_info)
        
        # 将帮助菜单添加到菜单栏
        menubar.add_cascade(label="帮助", menu=help_menu)
        
        # 设置窗口菜单栏
        self.root.config(menu=menubar)
    
    def show_software_info(self):
        """显示软件信息弹窗"""
        # 创建弹窗
        info_window = tk.Toplevel(self.root)
        info_window.title("软件信息")
        info_window.geometry("400x300")
        info_window.resizable(False, False)
        
        # 创建内容框架
        frame = ttk.Frame(info_window, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 添加软件信息
        ttk.Label(frame, text="softHertz串口调试工具", font=("SimHei", 16, "bold")).pack(pady=(0, 10))
        ttk.Label(frame, text=f"版本: {APP_VERSION}").pack(anchor="w", pady=(5, 0))
        ttk.Label(frame, text=f"发布日期: {APP_RELEASE_DATE}").pack(anchor="w", pady=(5, 0))
        
        # 添加软件描述
        description = "\n软赫电子出品设备的调试工具。"
        ttk.Label(frame, text=description, justify="left").pack(anchor="w", pady=(10, 0))
        
        # 添加官网链接按钮
        link_frame = ttk.Frame(frame)
        link_frame.pack(fill=tk.X, pady=(15, 0))
        
        def open_website():
            webbrowser.open(COMPANY_WEBSITE)
        
        ttk.Label(link_frame, text="公司官网: ").pack(side="left")
        website_label = ttk.Label(link_frame, text=COMPANY_WEBSITE, foreground="blue", cursor="hand2")
        website_label.pack(side="left")
        website_label.bind("<Button-1>", lambda e: open_website())
        
        # 添加关闭按钮
        ttk.Button(frame, text="关闭", command=info_window.destroy).pack(pady=(20, 0))
        
        # 居中弹窗
        info_window.transient(self.root)
        info_window.grab_set()
        self.root.wait_window(info_window)

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