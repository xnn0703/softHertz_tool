import sys
import time
import numpy as np
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                           QComboBox, QPushButton, QGroupBox, QScrollArea,
                           QTableWidget, QTableWidgetItem, QTextEdit, QSplitter,
                           QFrame, QCheckBox, QGridLayout, QSizePolicy, QLineEdit)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont
import pyqtgraph as pg
from ui.qt_base_ui import QBaseUI
from common.serial_controller import SerialController
from common.tcp_controller import TCPController
from common.udp_controller import UDPController

class QDebugUI(QBaseUI):
    """基于PyQt5和PyQtGraph的DEBUG设备UI"""
    
    # 添加信号定义，用于在主线程中更新UI
    data_received_signal = pyqtSignal(dict, bool)  # 参数：数据，是否来自缓冲区
    
    def __init__(self, parent=None, device=None):
        super().__init__(parent, device)
        
        # 通信模式
        self.current_communication_mode = "serial"  # 默认串口通信
        self.serial_controller = device.communication_controller
        
        # 连接信号和槽
        self.data_received_signal.connect(self.on_data_received)
        
        # 初始化TCP和UDP控制器
        self.tcp_controller = TCPController()
        self.udp_controller = UDPController()
        
        # 初始化网络模式变量
        self.net_mode_var = "client"  # 默认客户端模式
        
        # 通道显示控制
        self.channel_visibility = {}
        self.channel_colors = {
            0: 'b', 1: 'r', 2: 'g', 3: 'y',
            4: 'm', 5: 'c', 6: 'w', 7: 'k',
            8: '#FFA500', 9: '#800080', 10: '#00FF00', 11: '#FF00FF',
            12: '#00FFFF', 13: '#808000', 14: '#800000', 15: '#008000'
        }
        
        # 数据缓存，用于曲线绘制
        self.data_cache = {}
        self.max_data_points = 1000
        
        # 初始时间，用于计算相对时间
        self.start_time = time.time()
        
        # 自动流动状态管理
        self.auto_scroll = True  # 是否自动流动
        self.is_dragging = False  # 是否正在拖动
        
        # 帧率控制
        self.last_plot_time = 0  # 上次绘制时间
        self.min_plot_interval = 10  # 最小绘制间隔（毫秒）
        
        # 键盘状态管理
        self.ctrl_pressed = False  # ctrl键是否按下
        
        # 批量更新相关变量
        self.batch_data = []  # 用于批量更新的数据源
        self.batch_update_interval = 20  # 批量更新间隔（毫秒），提高到20ms，增加刷新频率
        
        # PyQtGraph相关变量
        self.plot_widget = None  # 绘图组件
        self.lines = {}  # 存储曲线对象
        self.plot_data = {}  # 存储曲线数据
        self.legend = None  # 图例
        
        # 创建DEBUG设备特定的UI组件
        self.create_debug_widgets()
        
        # 设置数据回调，使用包装函数通过信号机制调用UI方法
        self.device.set_data_callback(self._on_data_received_wrapper)
        
        # 启动批量更新定时器
        self._start_batch_update_timer()
        
        # 设置设备类型
        self.current_device_type = "DEBUG"
        self.serial_controller.current_device_type = "DEBUG"
    
    def _on_data_received_wrapper(self, data):
        """数据回调包装函数，用于在主线程中更新UI"""
        # 发射信号，将数据传递给主线程中的槽函数
        self.data_received_signal.emit(data, False)
        
    def create_debug_widgets(self):
        """创建DEBUG设备特定的UI组件"""
        # 保留设备类型选择组件可见，允许用户切换设备
        self.device_type_label.show()
        self.device_type_cb.show()
        
        # 通信方式选择区域
        comm_group = QGroupBox("通信方式")
        comm_layout = QHBoxLayout()
        
        self.comm_mode_var = QComboBox()
        self.comm_mode_var.addItems(["serial", "tcp", "udp"])
        self.comm_mode_var.setCurrentText(self.current_communication_mode)
        self.comm_mode_var.currentTextChanged.connect(self.on_comm_mode_changed)
        
        comm_layout.addWidget(QLabel("通信方式:"))
        comm_layout.addWidget(self.comm_mode_var)
        comm_layout.addStretch()
        
        comm_group.setLayout(comm_layout)
        self.scroll_layout.insertWidget(1, comm_group)
        
        # TCP/UDP配置区域
        self.network_group = QGroupBox("网络配置")
        self.network_layout = QGridLayout()
        
        # 主机和端口配置
        self.host_label = QLabel("主机:")
        self.host_entry = QLineEdit()
        self.host_entry.setText("192.168.1.12")
        self.network_layout.addWidget(self.host_label, 0, 0)
        self.network_layout.addWidget(self.host_entry, 0, 1)
        
        self.remote_port_label = QLabel("远程端口:")
        self.remote_port_entry = QLineEdit()
        self.remote_port_entry.setText("4004")
        self.network_layout.addWidget(self.remote_port_label, 0, 2)
        self.network_layout.addWidget(self.remote_port_entry, 0, 3)
        
        self.local_port_label = QLabel("本地端口:")
        self.local_port_entry = QLineEdit()
        self.local_port_entry.setText("8080")
        self.network_layout.addWidget(self.local_port_label, 1, 0)
        self.network_layout.addWidget(self.local_port_entry, 1, 1)
        
        # 网络模式选择
        self.mode_group = QGroupBox("模式")
        self.mode_layout = QHBoxLayout()
        
        # TCP模式选项
        self.tcp_client_rb = QPushButton("客户端")
        self.tcp_server_rb = QPushButton("服务器")
        self.udp_unicast_rb = QPushButton("单播")
        self.udp_broadcast_rb = QPushButton("广播")
        
        self.tcp_client_rb.clicked.connect(lambda: self.on_net_mode_changed("client"))
        self.tcp_server_rb.clicked.connect(lambda: self.on_net_mode_changed("server"))
        self.udp_unicast_rb.clicked.connect(lambda: self.on_net_mode_changed("unicast"))
        self.udp_broadcast_rb.clicked.connect(lambda: self.on_net_mode_changed("broadcast"))
        
        self.mode_layout.addWidget(self.tcp_client_rb)
        self.mode_layout.addWidget(self.tcp_server_rb)
        self.mode_layout.addWidget(self.udp_unicast_rb)
        self.mode_layout.addWidget(self.udp_broadcast_rb)
        self.mode_group.setLayout(self.mode_layout)
        
        self.network_layout.addWidget(self.mode_group, 1, 2, 1, 2)
        self.network_group.setLayout(self.network_layout)
        self.scroll_layout.insertWidget(2, self.network_group)
        
        # 初始隐藏网络配置
        self.network_group.hide()
        
        # 实时曲线和通道数据并排显示区域
        plot_values_group = QGroupBox()
        plot_values_layout = QHBoxLayout()
        
        # 曲线绘制区域
        plot_subgroup = QGroupBox("实时曲线")
        plot_layout = QVBoxLayout()
        
        # 创建PyQtGraph PlotWidget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setAntialiasing(True)  # 启用抗锯齿
        self.plot_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.plot_widget.setMinimumHeight(400)  # 设置最小高度
        
        # 设置网格
        self.plot_widget.showGrid(x=True, y=True, alpha=0.7)
        
        # 设置坐标轴标签和标题
        self.plot_widget.setLabel('left', '数值')
        self.plot_widget.setLabel('bottom', '时间 (ms)')
        self.plot_widget.setTitle('实时数据曲线')
        
        # 初始化图例
        self.legend = self.plot_widget.addLegend()
        
        # 获取视图框，用于控制缩放和平移
        self.view_box = self.plot_widget.getViewBox()
        
        # 设置自动缩放策略
        self.view_box.setAutoVisible(y=True)
        
        # 添加鼠标事件监听器
        self.plot_widget.scene().sigMouseClicked.connect(self.on_mouse_press)
        
        plot_layout.addWidget(self.plot_widget)
        plot_subgroup.setLayout(plot_layout)
        
        # 通道数值实时显示区域
        values_subgroup = QGroupBox("通道数值实时显示")
        values_layout = QVBoxLayout()
        
        self.channel_values_table = QTableWidget()
        self.channel_values_table.setColumnCount(3)  # 添加复选框列
        self.channel_values_table.setHorizontalHeaderLabels(["显示", "通道名称", "数值"])
        self.channel_values_table.horizontalHeader().setStretchLastSection(True)
        self.channel_values_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 设置第一列（复选框列）的宽度
        self.channel_values_table.setColumnWidth(0, 50)
        values_layout.addWidget(self.channel_values_table)
        values_subgroup.setLayout(values_layout)
        
        # 使用QSplitter实现可调整大小的并排布局
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(plot_subgroup)
        splitter.addWidget(values_subgroup)
        splitter.setSizes([800, 400])  # 设置初始大小比例
        
        plot_values_layout.addWidget(splitter)
        plot_values_group.setLayout(plot_values_layout)
        self.scroll_layout.addWidget(plot_values_group)
        
        # 通道控制区域
        channel_group = QGroupBox("通道控制")
        channel_layout = QVBoxLayout()
        
        # 控制按钮
        control_layout = QHBoxLayout()
        
        self.clear_data_btn = QPushButton("清除数据")
        self.clear_data_btn.clicked.connect(self.clear_data)
        
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self.select_all_channels)
        
        self.select_none_btn = QPushButton("全不选")
        self.select_none_btn.clicked.connect(self.select_none_channels)
        
        # 添加debug开关按钮
        self.debug_toggle_btn = QPushButton("开启Debug")
        self.debug_toggle_btn.clicked.connect(self.toggle_debug)
        self.debug_enabled = False
        
        control_layout.addWidget(self.clear_data_btn)
        control_layout.addWidget(self.select_all_btn)
        control_layout.addWidget(self.select_none_btn)
        control_layout.addWidget(self.debug_toggle_btn)
        control_layout.addStretch()
        
        channel_layout.addLayout(control_layout)
        channel_group.setLayout(channel_layout)
        self.scroll_layout.addWidget(channel_group)
        
        # 日志区域
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.NoWrap)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        self.scroll_layout.addWidget(log_group)
        
        # 初始化通信模式
        self.on_comm_mode_changed()
        
    def on_comm_mode_changed(self):
        """处理通信方式变更"""
        old_mode = self.current_communication_mode
        self.current_communication_mode = self.comm_mode_var.currentText()
        
        self.log_message(f"通信模式切换：{old_mode} → {self.current_communication_mode}")
        
        # 清空数据缓冲区和缓存
        self.data_buffer = []
        self.data_cache.clear()
        
        # 关闭当前所有控制器的连接
        if self.serial_controller.is_connected():
            self.serial_controller.close()
        if self.tcp_controller.is_connected():
            self.tcp_controller.close()
        if self.udp_controller.is_connected():
            self.udp_controller.close()
        
        if self.current_communication_mode == "serial":
            # 显示串口配置，隐藏网络配置
            self.port_label.show()
            self.port_cb.show()
            self.baud_label.show()
            self.baud_cb.show()
            self.network_group.hide()
            # 更新连接按钮文本
            self.connect_btn.setText("打开串口")
        else:
            # 隐藏串口配置，显示网络配置
            self.port_label.hide()
            self.port_cb.hide()
            self.baud_label.hide()
            self.baud_cb.hide()
            self.network_group.show()
            
            # 根据通信方式更新网络配置选项
            self.update_network_config()
            
            # 更新连接按钮文本
            if self.current_communication_mode == "tcp":
                # TCP模式：客户端/服务器
                if self.net_mode_var == "server":
                    self.connect_btn.setText("开始监听")
                else:
                    self.connect_btn.setText("连接")
            elif self.current_communication_mode == "udp":
                # UDP模式
                self.connect_btn.setText("连接")
        
        # 更新设备的通信控制器
        if self.current_communication_mode == "serial":
            self.device.communication_controller = self.serial_controller
        elif self.current_communication_mode == "tcp":
            self.device.communication_controller = self.tcp_controller
        elif self.current_communication_mode == "udp":
            self.device.communication_controller = self.udp_controller
        
        # 设置设备类型
        self.device.communication_controller.current_device_type = "DEBUG"
        
        # 更新数据回调
        self.device.communication_controller.received_data_callback = self.device.on_received_data
    
    @pyqtSlot()
    def on_connect_toggled(self):
        """处理连接按钮点击，支持串口、TCP和UDP连接"""
        # 检查设备是否有communication_controller属性
        if not hasattr(self.device, 'communication_controller'):
            return
        
        if self.current_communication_mode == "serial":
            # 串口连接逻辑，使用父类的实现
            super().on_connect_toggled()
        else:
            # TCP/UDP连接逻辑
            host = self.host_entry.text()
            remote_port = self.remote_port_entry.text()
            local_port = self.local_port_entry.text()
            
            if not host or not remote_port or not local_port:
                self.log_message("[错误] 请填写完整的网络配置")
                return
            
            try:
                remote_port = int(remote_port)
                local_port = int(local_port)
            except ValueError:
                self.log_message("[错误] 端口号必须是整数")
                return
            
            # 根据当前通信模式和网络模式调用相应的连接方法
            controller = self.device.communication_controller
            success = False
            msg = ""
            
            if self.current_communication_mode == "tcp":
                # TCP模式
                is_server_mode = (self.net_mode_var == "server")
                success, msg = controller.toggle_connection(host, remote_port, is_server_mode=is_server_mode)
            elif self.current_communication_mode == "udp":
                # UDP模式
                is_broadcast_mode = (self.net_mode_var == "broadcast")
                success, msg = controller.toggle_connection(host, remote_port, local_port, is_broadcast_mode=is_broadcast_mode)
            
            # 更新UI状态
            current_state = controller.is_connected()
            
            if success:
                if self.current_communication_mode == "tcp":
                    if self.net_mode_var == "server":
                        self.connect_btn.setText("停止监听" if current_state else "开始监听")
                    else:
                        self.connect_btn.setText("断开连接" if current_state else "连接")
                elif self.current_communication_mode == "udp":
                    self.connect_btn.setText("断开连接" if current_state else "连接")
                self.log_message(msg)
            else:
                # 发生错误时也更新UI状态
                if self.current_communication_mode == "tcp":
                    if self.net_mode_var == "server":
                        self.connect_btn.setText("开始监听")
                    else:
                        self.connect_btn.setText("连接")
                elif self.current_communication_mode == "udp":
                    self.connect_btn.setText("连接")
                self.log_message(f"[错误] {msg}")
            
            # 发送连接状态变更信号
            self.connect_toggled.emit(current_state)
    
    def update_network_config(self):
        """根据通信方式更新网络配置选项"""
        # 隐藏所有模式按钮
        self.tcp_client_rb.hide()
        self.tcp_server_rb.hide()
        self.udp_unicast_rb.hide()
        self.udp_broadcast_rb.hide()
        
        if self.current_communication_mode == "tcp":
            # TCP模式：客户端/服务器
            self.tcp_client_rb.show()
            self.tcp_server_rb.show()
            self.net_mode_var = "client"
            self.log_message(f"TCP网络模式：客户端")
        elif self.current_communication_mode == "udp":
            # UDP模式：单播/广播
            self.udp_unicast_rb.show()
            self.udp_broadcast_rb.show()
            self.net_mode_var = "unicast"
            self.log_message(f"UDP网络模式：单播")
    
    def on_net_mode_changed(self, mode):
        """处理网络模式变更"""
        self.net_mode_var = mode
        self.log_message(f"网络模式变更：{mode}")
        
        # 更新连接按钮文本
        if self.current_communication_mode == "tcp":
            if mode == "server":
                self.connect_btn.setText("开始监听")
            else:
                self.connect_btn.setText("连接")
    
    def on_data_received(self, data, from_buffer=False):
        """处理接收到的数据，将数据添加到批量更新列表"""
        if 'channel_data' not in data:
            return
        
        # 严格检查条件：必须设备连接
        if not self.device.is_connected():
            return
        
        # 将数据添加到批量更新列表
        self.batch_data.append(data)
        
        # 如果距离上次批量更新超过了设定的间隔，立即进行一次更新
        current_time = time.time() * 1000
        if current_time - self.last_plot_time >= 200:  # 200ms强制更新一次
            self._process_batch_data()
    
    def _start_batch_update_timer(self):
        """启动批量更新定时器"""
        self.batch_update_timer = QTimer(self)
        self.batch_update_timer.timeout.connect(self._process_batch_data)
        self.batch_update_timer.start(self.batch_update_interval)
    
    def _process_batch_data(self):
        """处理批量数据更新"""
        if not self.batch_data:
            return
        
        # 使用相对时间（毫秒）
        current_time = (time.time() - self.start_time) * 1000
        
        # 批量处理所有数据
        for data in self.batch_data:
            if 'channel_data' not in data:
                continue
            
            for channel in data['channel_data']:
                channel_name = channel['name']
                value = channel['value']
                
                # 更新数据缓存
                if channel_name not in self.data_cache:
                    self.data_cache[channel_name] = []
                
                self.data_cache[channel_name].append((current_time, value))
                
                # 限制数据点数量
                if len(self.data_cache[channel_name]) > self.max_data_points:
                    self.data_cache[channel_name].pop(0)
                
                # 添加新通道到曲线
                if channel_name not in self.lines:
                    self.add_channel_to_plot(channel_name)
                
                # 更新通道数值表格
                self.update_channel_values(channel_name, value)
        
        # 清空批量数据列表
        self.batch_data.clear()
        
        # 更新曲线绘制
        self.update_plot()
        self.last_plot_time = current_time
    
    def add_channel_to_plot(self, channel_name):
        """添加新通道到曲线"""
        if channel_name in self.lines:
            return  # 通道已存在，不需要重复添加
        
        color = self.channel_colors[len(self.lines) % len(self.channel_colors)]
        
        # 使用PyQtGraph创建曲线，优化曲线平滑度
        line = self.plot_widget.plot(
            name=channel_name, 
            pen=pg.mkPen(color=color, width=2.0, style=Qt.SolidLine),
            antialias=True
        )
        self.lines[channel_name] = line
        
        # 初始化曲线数据
        self.plot_data[channel_name] = {'x': [], 'y': []}
        
        # 在表格中添加新行
        row = self.channel_values_table.rowCount()
        self.channel_values_table.insertRow(row)
        
        # 添加复选框
        checkbox = QCheckBox()
        checkbox.setChecked(True)
        checkbox.stateChanged.connect(lambda state, ch=channel_name: self.toggle_channel_visibility(ch, state))
        self.channel_values_table.setCellWidget(row, 0, checkbox)
        
        # 添加通道名称
        self.channel_values_table.setItem(row, 1, QTableWidgetItem(channel_name))
        
        # 初始化数值
        self.channel_values_table.setItem(row, 2, QTableWidgetItem("0.00"))
        
        # 记录日志
        self.log_message(f"通道 {channel_name} 已添加到曲线")
    
    def toggle_channel_visibility(self, channel_name, state):
        """切换通道可见性"""
        if channel_name in self.lines:
            visible = (state == Qt.Checked)
            line = self.lines[channel_name]
            line.setVisible(visible)
            # 记录日志
            status = "显示" if visible else "隐藏"
            self.log_message(f"通道 {channel_name} 已{status}")
    
    def select_all_channels(self):
        """全选所有通道"""
        for row in range(self.channel_values_table.rowCount()):
            checkbox = self.channel_values_table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(True)
        
        # 更新曲线显示
        for line in self.lines.values():
            line.setVisible(True)
        
        self.log_message(f"已全选 {self.channel_values_table.rowCount()} 个通道")
    
    def select_none_channels(self):
        """全不选所有通道"""
        for row in range(self.channel_values_table.rowCount()):
            checkbox = self.channel_values_table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(False)
        
        # 更新曲线显示
        for line in self.lines.values():
            line.setVisible(False)
        
        self.log_message(f"已全不选 {self.channel_values_table.rowCount()} 个通道")
    
    def update_channel_values(self, channel_name, value):
        """更新通道数值表格"""
        # 查找通道在表格中的位置
        row = -1
        for i in range(self.channel_values_table.rowCount()):
            if self.channel_values_table.item(i, 1) and self.channel_values_table.item(i, 1).text() == channel_name:
                row = i
                break
        
        if row != -1:
            # 更新数值
            self.channel_values_table.setItem(row, 2, QTableWidgetItem(f"{value:.2f}"))
    
    def update_plot(self):
        """更新曲线绘制，优化绘制效率"""
        if not self.data_cache:
            return
        
        # 初始化变量
        has_visible_data = False
        visible_lines = {}
        latest_time = 0
        
        # 只处理可见的曲线，减少计算量
        for channel_name, line in self.lines.items():
            if line.isVisible() and channel_name in self.data_cache:
                channel_data = self.data_cache[channel_name]
                if channel_data:
                    visible_lines[channel_name] = line
                    has_visible_data = True
                    # 只获取最新时间点，用于X轴范围计算
                    latest_channel_time = channel_data[-1][0]
                    if latest_channel_time > latest_time:
                        latest_time = latest_channel_time
        
        if has_visible_data:
            # 更新X轴范围，只使用最新的时间点
            if self.auto_scroll:
                min_time = max(0, latest_time - 10000)  # 显示最近10秒的数据
                self.plot_widget.setXRange(min_time, latest_time, padding=0)
            
            # 批量更新所有可见曲线的数据
            update_needed = False
            for channel_name, line in visible_lines.items():
                channel_data = self.data_cache[channel_name]
                if channel_data:
                    # 直接解包最新数据，避免重复计算
                    timestamps = [t for t, v in channel_data]
                    values = [v for t, v in channel_data]
                    line.setData(timestamps, values)
                    update_needed = True
            
            # 只在需要更新时才重新计算Y轴范围
            if update_needed:
                # 计算Y轴范围，只使用最新数据点
                recent_values = []
                for channel_name in visible_lines:
                    channel_data = self.data_cache[channel_name]
                    # 只使用最近的数据点来计算范围，减少计算量
                    recent_points = channel_data[-50:]
                    recent_values.extend([v for t, v in recent_points])
                
                if recent_values:
                    min_val = min(recent_values)
                    max_val = max(recent_values)
                    val_range = max_val - min_val
                    if val_range == 0:
                        val_range = 1  # 防止除以0
                    
                    new_min = min_val - val_range * 0.1
                    new_max = max_val + val_range * 0.1
                    self.plot_widget.setYRange(new_min, new_max, padding=0.05)
    
    def on_mouse_press(self, event):
        """鼠标按下事件处理，暂停自动流动"""
        if event.button() == 1:  # 左键按下
            self.is_dragging = True
            self.auto_scroll = False
            self.log_message("曲线操作：暂停自动滚动")
    
    def on_mouse_release(self, event):
        """鼠标释放事件处理，检查是否恢复自动流动"""
        if event.button() == 1:  # 左键释放
            self.is_dragging = False
            # 检查当前X轴范围是否在最新数据位置
            current_xlim = self.plot_widget.viewRange()[0]
            max_time = max([max([t for t, v in self.data_cache[ch]]) for ch in self.data_cache if self.data_cache[ch]]) if self.data_cache else 0
            # 如果当前X轴右边界接近最新数据，恢复自动流动
            if max_time > 0 and current_xlim[1] >= max_time - 100:  # 100ms的容差
                self.auto_scroll = True
                self.log_message("曲线操作：恢复自动滚动")
            else:
                self.log_message("曲线操作：保持手动滚动")
    
    def on_mouse_scroll(self, event):
        """鼠标滚轮事件处理，支持按住ctrl加滚轮缩放曲线"""
        # 计算缩放比例，每次缩放10%
        scale_factor = 1.1 if event.delta() > 0 else 0.9
        
        # 获取当前X轴和Y轴范围
        current_xlim, current_ylim = self.plot_widget.viewRange()
        
        # 计算鼠标位置在当前坐标系统中的比例
        pos = event.pos()
        scene_pos = self.view_box.mapSceneToView(pos)
        x_data = scene_pos.x()
        y_data = scene_pos.y()
        
        # 计算新的X轴范围，以鼠标位置为中心进行缩放
        x_range = current_xlim[1] - current_xlim[0]
        x_span_left = x_data - current_xlim[0]
        x_span_right = current_xlim[1] - x_data
        new_x_range = x_range * scale_factor
        new_xlim = (x_data - x_span_left * scale_factor, x_data + x_span_right * scale_factor)
        
        # 计算新的Y轴范围，以鼠标位置为中心进行缩放
        y_range = current_ylim[1] - current_ylim[0]
        y_span_left = y_data - current_ylim[0]
        y_span_right = current_ylim[1] - y_data
        new_y_range = y_range * scale_factor
        new_ylim = (y_data - y_span_left * scale_factor, y_data + y_span_right * scale_factor)
        
        # 设置新的X轴和Y轴范围
        self.plot_widget.setXRange(new_xlim[0], new_xlim[1], padding=0)
        self.plot_widget.setYRange(new_ylim[0], new_ylim[1], padding=0)
    
    def clear_data(self):
        """清除数据和曲线"""
        # 清除数据缓存
        self.data_cache.clear()
        self.plot_data.clear()
        
        # 清除曲线
        for line in self.lines.values():
            line.clear()
        
        self.channel_visibility.clear()
        self.lines.clear()
        
        # 清空通道数值表格
        self.channel_values_table.setRowCount(0)
        
        # 重置初始时间
        self.start_time = time.time()
        
        # 重置PlotWidget
        self.plot_widget.clear()
        # 重新设置网格
        self.plot_widget.showGrid(x=True, y=True, alpha=0.7)
        # 重新设置坐标轴标签和标题
        self.plot_widget.setLabel('left', '数值')
        self.plot_widget.setLabel('bottom', '时间 (ms)')
        self.plot_widget.setTitle('实时数据曲线')
        # 重新添加图例
        self.legend = self.plot_widget.addLegend()
        
        self.log_message("数据已清除")
    
    def log_message(self, msg):
        """记录日志"""
        timestamp = time.strftime("[%Y-%m-%d %H:%M:%S] ")
        log_entry = timestamp + "[UI] " + msg + "\n"
        
        # 显示到UI
        self.log_text.append(log_entry)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
        
        # 写入到统一日志文件
        try:
            with open("log.txt", "a", encoding="utf-8") as f:
                f.write(log_entry)
                f.flush()
        except Exception as e:
            # 捕获异常，确保程序不会崩溃
            pass
    
    def toggle_debug(self):
        """处理debug开关按钮点击，向设备发送开关指令"""
        # 检查设备是否连接
        if not self.device.is_connected():
            self.log_message("[错误] 请先连接设备")
            return
        
        # 切换debug状态
        self.debug_enabled = not self.debug_enabled
        
        # 更新按钮文本
        self.debug_toggle_btn.setText("关闭Debug" if self.debug_enabled else "开启Debug")
        
        # 向设备发送debug开关指令
        cmd_name = "Debug开关"
        success, msg = self.device.send_command(cmd_name, self.debug_enabled)
        
        # 记录详细日志，便于调试
        self.log_message(f"[DEBUG] 发送Debug开关命令: {'开启' if self.debug_enabled else '关闭'}")
        self.log_message(f"[DEBUG] 命令发送结果: 成功={success}, 消息={msg}")
        
        if success:
            status = "开启" if self.debug_enabled else "关闭"
            self.log_message(f"[成功] Debug {status}成功: {msg}")
        else:
            # 恢复原状态
            self.debug_enabled = not self.debug_enabled
            self.debug_toggle_btn.setText("关闭Debug" if self.debug_enabled else "开启Debug")
            self.log_message(f"[错误] Debug开关设置失败: {msg}")
    
    def destroy(self):
        """清理资源"""
        # 停止批量更新定时器
        if hasattr(self, 'batch_update_timer') and self.batch_update_timer:
            self.batch_update_timer.stop()
            self.batch_update_timer.deleteLater()
        
        # 关闭通信连接
        if self.device.is_connected():
            self.device.communication_controller.close()
        
        # 调用父类的destroy方法
        super().destroy()
