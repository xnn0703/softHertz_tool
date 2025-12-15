import sys
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                           QComboBox, QPushButton, QGroupBox, QScrollArea,
                           QTableWidget, QTableWidgetItem, QTextEdit, QSplitter,
                           QMainWindow, QFrame, QApplication)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont

class QBaseUI(QWidget):
    """基于PyQt5的UI基础类"""
    
    # 信号定义
    device_type_changed = pyqtSignal(str)  # 设备类型变更信号
    port_changed = pyqtSignal(str)        # 串口变更信号
    baud_rate_changed = pyqtSignal(str)   # 波特率变更信号
    connect_toggled = pyqtSignal(bool)     # 连接状态变更信号
    
    def __init__(self, parent=None, device=None):
        super().__init__(parent)
        self.parent = parent
        self.device = device
        
        # 初始化设备类型，默认为KauDC004A
        self.current_device_type = "KauDC004A"
        
        # 保存定时器ID
        self.update_ports_timer = None
        self.ui_update_timer = None
        
        # 创建主布局
        self.main_layout = QVBoxLayout(self)
        
        # 创建滚动区域
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.main_layout.addWidget(self.scroll_area)
        
        # 创建滚动内容窗口
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_area.setWidget(self.scroll_content)
        
        # 创建基本UI组件
        self.create_widgets()
        
        # 设置样式
        self.set_style()
        
        # 设置回调函数
        self.setup_callbacks()
        
    def create_widgets(self):
        """创建基本UI组件"""
        # 设备类型选择区域
        device_group = QGroupBox("设备设置")
        device_layout = QHBoxLayout()
        
        self.device_type_label = QLabel("设备类型:")
        self.device_type_cb = QComboBox()
        self.device_type_cb.addItems(["KauDC004A", "AFD01_QS", "DEBUG"])
        self.device_type_cb.setCurrentText(self.current_device_type)
        self.device_type_cb.currentTextChanged.connect(self.on_device_type_changed)
        
        device_layout.addWidget(self.device_type_label)
        device_layout.addWidget(self.device_type_cb)
        device_layout.addStretch()
        
        device_group.setLayout(device_layout)
        self.scroll_layout.addWidget(device_group)
        
        # 通信设置区域
        serial_group = QGroupBox("通信设置")
        serial_layout = QHBoxLayout()
        
        self.port_label = QLabel("串口:")
        self.port_cb = QComboBox()
        self.port_cb.currentTextChanged.connect(self.on_port_changed)
        
        self.baud_label = QLabel("波特率:")
        self.baud_cb = QComboBox()
        self.baud_cb.addItems(["9600", "19200", "38400", "115200", "921600"])
        self.baud_cb.setCurrentText("115200")
        self.baud_cb.currentTextChanged.connect(self.on_baud_rate_changed)
        
        self.connect_btn = QPushButton("打开串口")
        self.connect_btn.clicked.connect(self.on_connect_toggled)
        
        serial_layout.addWidget(self.port_label)
        serial_layout.addWidget(self.port_cb)
        serial_layout.addWidget(self.baud_label)
        serial_layout.addWidget(self.baud_cb)
        serial_layout.addWidget(self.connect_btn)
        serial_layout.addStretch()
        
        serial_group.setLayout(serial_layout)
        self.scroll_layout.addWidget(serial_group)
        
    def set_style(self):
        """设置UI样式"""
        # 设置全局字体
        font = QFont("SimHei", 10)
        QApplication.setFont(font)
        
    def setup_callbacks(self):
        """设置回调函数"""
        # 定时器每1秒刷新一次串口列表
        self._schedule_update_ports()
        # 定时器每100毫秒刷新一次UI
        self._schedule_update_ui()
        
    def _schedule_update_ports(self):
        """安排下一次串口更新"""
        if self.update_ports_timer is not None:
            self.update_ports_timer.stop()
        self.update_ports_timer = QTimer(self)
        self.update_ports_timer.timeout.connect(self.update_ports)
        self.update_ports_timer.start(1000)
        
    def _schedule_update_ui(self):
        """安排下一次UI更新"""
        if self.ui_update_timer is not None:
            self.ui_update_timer.stop()
        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.timeout.connect(self.update_ui)
        self.ui_update_timer.start(100)  # 将UI更新间隔从50ms改为100ms，减少UI卡顿
        
    @pyqtSlot(str)
    def on_device_type_changed(self, device_type):
        """处理设备类型变更"""
        if device_type != self.current_device_type:
            self.current_device_type = device_type
            self.device_type_changed.emit(device_type)
            self.update_ports()
    
    @pyqtSlot(str)
    def on_port_changed(self, port):
        """处理串口变更"""
        self.port_changed.emit(port)
    
    @pyqtSlot(str)
    def on_baud_rate_changed(self, baud_rate):
        """处理波特率变更"""
        self.baud_rate_changed.emit(baud_rate)
    
    @pyqtSlot()
    def on_connect_toggled(self):
        """处理连接按钮点击"""
        # 检查设备是否有communication_controller属性
        if not hasattr(self.device, 'communication_controller'):
            return
        
        port = self.port_cb.currentText()
        baud_rate = self.baud_cb.currentText()
        
        if not port:
            return
        
        # 使用toggle_connection方法，兼容各种通信方式
        if hasattr(self.device.communication_controller, 'toggle_connection'):
            success, msg = self.device.communication_controller.toggle_connection(port, baud_rate)
        elif hasattr(self.device.communication_controller, 'toggle_serial'):
            # 兼容旧的toggle_serial方法
            success, msg = self.device.communication_controller.toggle_serial(port, baud_rate)
        else:
            return
        
        # 无论操作是打开还是关闭，都直接检查当前的连接状态来更新UI
        current_state = self.device.is_connected()
        
        if success:
            self.connect_btn.setText("关闭连接" if current_state else "打开连接")
            self.log_message(msg)
        else:
            # 发生错误时也更新UI状态
            self.connect_btn.setText("打开连接")
        
        # 发送连接状态变更信号
        self.connect_toggled.emit(current_state)
    
    def update_ports(self):
        """更新可用串口列表"""
        if hasattr(self.device.communication_controller, 'update_ports'):
            ports = self.device.communication_controller.update_ports()
            current_port = self.port_cb.currentText()
            
            # 更新下拉框选项
            self.port_cb.clear()
            self.port_cb.addItems(ports)
            
            # 如果当前选择的串口仍然可用，保持当前选择
            if current_port in ports:
                self.port_cb.setCurrentText(current_port)
            # 否则，如果有可用串口，选择第一个
            elif ports:
                self.port_cb.setCurrentText(ports[0])
        
        # 安排下一次更新
        self._schedule_update_ports()
    
    def update_ui(self):
        """更新UI显示（子类需要重写此方法）
        
        基类方法负责安排下一次UI更新，子类应该先调用super().update_ui()，
        然后再添加自己的UI更新逻辑。
        """
        # 继续安排下一次UI更新
        self._schedule_update_ui()
        pass
    
    def log_message(self, msg):
        """记录日志（仅写入文件，不在UI中显示）"""
        # 日志信息仍会由设备控制器写入到文件中
        pass
    
    def set_device_type(self, device_type):
        """设置设备类型"""
        print(f"[DEBUG] QBaseUI: 设置设备类型为: {device_type}")
        self.current_device_type = device_type
        self.device_type_cb.setCurrentText(device_type)
        # 设备切换后立即更新串口列表
        self.update_ports()
    
    def destroy(self):
        """清理资源，停止定时器"""
        print("[DEBUG] QBaseUI: 清理资源，停止定时器")
        # 停止串口更新定时器
        if self.update_ports_timer:
            self.update_ports_timer.stop()
            self.update_ports_timer.deleteLater()
            self.update_ports_timer = None
        
        # 停止UI更新定时器
        if self.ui_update_timer:
            self.ui_update_timer.stop()
            self.ui_update_timer.deleteLater()
            self.ui_update_timer = None
        
        # 关闭通信连接
        if hasattr(self.device, 'is_connected') and self.device.is_connected():
            self.device.communication_controller.close()
        
        # 调用父类的destroy方法
        super().destroy()
    
    def clear_log(self):
        """清除日志方法"""
        pass
