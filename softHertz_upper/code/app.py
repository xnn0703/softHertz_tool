import sys
import os
import webbrowser
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QMessageBox, QMenuBar, QMenu, QAction)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QFont, QPixmap
from common.serial_controller import SerialController
from devices.kaudc004a_device import KauDC004ADevice
from devices.kaudc004a_protocol import KauDC004AProtocol

# 软件版本号
APP_VERSION = "V2.0"
# 软件发布日期
APP_RELEASE_DATE = "2025-10-01"
# 公司官网
COMPANY_WEBSITE = "http://www.soft-hertz.com/"

class Application(QMainWindow):
    def __init__(self):
        """初始化应用程序，整合串口控制器、设备协议、设备类和UI"""
        super().__init__()
        
        self.setWindowTitle(f"softHertz串口调试工具")
        self.setGeometry(100, 100, 1200, 800)  # 设置初始窗口大小
        
        # 设置窗口图标
        self._set_window_icon()
        
        # 创建菜单栏
        self._create_menu()
        
        # 创建中央组件和布局
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        
        # 初始化组件
        self.serial_controller = SerialController()
        self.device = None
        self.ui = None
        
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
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception as e:
            print(f"设置图标失败: {e}")
    
    def _setup_exception_handling(self):
        """设置异常处理，确保程序优雅退出"""
        # 重定向标准异常处理
        original_excepthook = sys.excepthook
        
        def exception_handler(exc_type, exc_value, exc_traceback):
            """自定义异常处理器"""
            # 记录异常信息
            print(f"程序异常: {exc_type.__name__}: {exc_value}")
            
            # 调用原始异常处理器
            original_excepthook(exc_type, exc_value, exc_traceback)
        
        sys.excepthook = exception_handler
    
    def closeEvent(self, event):
        """处理窗口关闭事件"""
        # 清理UI资源，停止所有定时器
        if self.ui:
            try:
                self.ui.destroy()
            except Exception as e:
                print(f"清理UI资源时出错: {e}")
        
        # 关闭串口连接
        if self.serial_controller and self.serial_controller.is_connected():
            self.serial_controller.close()
            
        # 接受关闭事件
        event.accept()
        sys.exit(0)
        
    def switch_device(self, device_type):
        """切换设备类型"""
        print(f"[DEBUG] 开始切换设备类型: {device_type}")
        
        # 断开当前设备连接 - 加强版：无论是否连接都尝试关闭
        if self.serial_controller:
            print(f"[DEBUG] 强制断开当前串口连接")
            self.serial_controller.close()  # 强制调用close方法，确保串口资源释放
            # 强制调用close方法，确保串口资源释放
            import time
            time.sleep(0.2)
            print(f"[DEBUG] 串口已关闭，等待资源释放完成")
        else:
            print(f"[DEBUG] 串口控制器不存在")
        
        # 更新串口控制器的设备类型
        if self.serial_controller:
            self.serial_controller.current_device_type = device_type
            print(f"[DEBUG] 串口控制器设备类型已更新为: {device_type}")
            
        # 清除当前UI组件
        if self.ui:
            print(f"[DEBUG] 清除UI组件")
            # 调用destroy方法停止定时器
            try:
                self.ui.destroy()
            except Exception as e:
                print(f"[DEBUG] 调用UI destroy方法时出错: {e}")
            
            # 移除UI组件
            self.ui.setParent(None)
        
        # 根据选择的设备类型创建设备和UI
        if device_type == "KauDC004A":
            print(f"[DEBUG] 创建KauDC004A设备和UI")
            from devices.kaudc004a_device import KauDC004ADevice
            from ui.qt_kaudc004a_ui import QKauDC004AUI
            
            self.device = KauDC004ADevice(self.serial_controller)
            self.ui = QKauDC004AUI(self.central_widget, self.device)
            # 连接设备类型变更信号
            self.ui.device_type_changed.connect(self.switch_device)
        elif device_type == "AFD01_QS":
            print(f"[DEBUG] 创建AFD01_QS设备和UI")
            from devices.afd01_qs_device import AFD01_QS_Device
            from ui.qt_afd01_qs_ui import QAFD01_QS_UI
            
            self.device = AFD01_QS_Device(self.serial_controller)
            self.ui = QAFD01_QS_UI(self.central_widget, self.device)
            # 连接设备类型变更信号
            self.ui.device_type_changed.connect(self.switch_device)
        elif device_type == "DEBUG":
            print(f"[DEBUG] 创建DEBUG设备和UI")
            from devices.debug_device import DebugDevice
            from ui.q_debug_ui import QDebugUI
            
            self.device = DebugDevice(self.serial_controller)
            self.ui = QDebugUI(self.central_widget, self.device)
            # 连接设备类型变更信号
            self.ui.device_type_changed.connect(self.switch_device)
        else:
            print(f"[DEBUG] 未知设备类型: {device_type}")
            return
        
        # 添加UI组件到布局
        if self.ui:
            self.main_layout.addWidget(self.ui)
            # 设置设备类型，确保UI显示正确
            self.ui.set_device_type(device_type)
        
        # 设置窗口标题
        self.setWindowTitle(f"softHertz串口调试工具 - {device_type}")
        print(f"[DEBUG] 设置窗口标题为: softHertz串口调试工具 - {device_type}")
        
        print(f"[DEBUG] 设备切换完成: {device_type}")

    def _create_menu(self):
        """创建菜单栏，包含软件信息按钮"""
        # 创建菜单栏
        menubar = self.menuBar()
        
        # 创建帮助菜单
        help_menu = QMenu("帮助", self)
        about_action = QAction("软件信息", self)
        about_action.triggered.connect(self.show_software_info)
        help_menu.addAction(about_action)
        
        # 将帮助菜单添加到菜单栏
        menubar.addMenu(help_menu)
    
    def show_software_info(self):
        """显示软件信息弹窗"""
        # 创建弹窗
        info_dialog = QMessageBox(self)
        info_dialog.setWindowTitle("软件信息")
        
        # 设置弹窗大小
        info_dialog.setFixedSize(400, 300)
        
        # 创建内容
        content = "softHertz串口调试工具\n\n"
        content += f"版本: {APP_VERSION}\n"
        content += f"发布日期: {APP_RELEASE_DATE}\n\n"
        content += "软赫电子出品设备的调试工具。\n\n"
        content += f"公司官网: <a href='{COMPANY_WEBSITE}'>{COMPANY_WEBSITE}</a>"
        
        info_dialog.setText(content)
        info_dialog.setTextFormat(Qt.RichText)
        info_dialog.setTextInteractionFlags(Qt.TextBrowserInteraction)
        info_dialog.setStandardButtons(QMessageBox.Close)
        
        # 显示弹窗
        info_dialog.exec_()

if __name__ == "__main__":
    # 创建PyQt5应用
    app = QApplication(sys.argv)
    
    # 设置全局字体
    font = QFont("SimHei", 10)
    app.setFont(font)
    
    # 初始化应用
    application = Application()
    
    # 显示主窗口
    application.show()
    
    # 启动主事件循环
    sys.exit(app.exec_())