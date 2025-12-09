import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from ui.ui_base import UIBase
from common.serial_controller import SerialController
from common.tcp_controller import TCPController
from common.udp_controller import UDPController

class DebugUI(UIBase):
    """DEBUG设备UI，支持曲线绘制和交互"""
    
    def __init__(self, master, device):
        self.current_communication_mode = "serial"  # 默认串口通信
        self.serial_controller = device.communication_controller
        
        # 初始化TCP和UDP控制器
        self.tcp_controller = TCPController()
        self.udp_controller = UDPController()
        
        # 初始化网络模式变量
        self.net_mode_var = tk.StringVar(value="client")
        
        # 通道显示控制
        self.channel_visibility = {}
        self.channel_colors = {
            0: 'blue', 1: 'red', 2: 'green', 3: 'orange',
            4: 'purple', 5: 'brown', 6: 'pink', 7: 'gray',
            8: 'cyan', 9: 'magenta', 10: 'lime', 11: 'yellow',
            12: 'teal', 13: 'navy', 14: 'olive', 15: 'maroon'
        }
        
        # 数据缓存，用于曲线绘制
        self.data_cache = {}
        self.max_data_points = 1000
        
        # 初始化matplotlib图形，设置中文字体
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']  # 支持中文显示
        plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.lines = {}
        
        # 初始时间，用于计算相对时间
        self.start_time = time.time()
        
        # 自动流动状态管理
        self.auto_scroll = True  # 是否自动流动
        self.is_dragging = False  # 是否正在拖动
        
        # 帧率控制
        self.last_plot_time = 0  # 上次绘制时间
        self.min_plot_interval = 10  # 最小绘制间隔（毫秒），平衡实时性和性能，限制最高100fps
        
        # 键盘状态管理
        self.ctrl_pressed = False  # ctrl键是否按下
        
        # 窗口大小变化节流相关变量
        self.resize_timer = None
        self.resize_delay = 100  # 窗口大小变化延迟处理时间（毫秒）
        self.is_resizing = False  # 是否正在调整窗口大小
        
        # 数据缓冲区，用于保存窗口调整期间的数据
        self.data_buffer = []
        
        # blit技术相关变量（已不再使用）
        self.blit_background = None
        self.artist_list = []
        
        super().__init__(master, device)
        
        # 设置设备类型
        self.current_device_type = "DEBUG"
        self.serial_controller.current_device_type = "DEBUG"
        
        # 设置数据回调
        self.device.set_data_callback(self.on_data_received)
        
        # 添加鼠标事件监听器
        self.canvas_widget.mpl_connect('button_press_event', self.on_mouse_press)
        self.canvas_widget.mpl_connect('button_release_event', self.on_mouse_release)
        # 添加鼠标滚轮事件监听器，支持缩放
        self.canvas_widget.mpl_connect('scroll_event', self.on_mouse_scroll)
        
        # 添加键盘事件监听器，跟踪ctrl键状态
        self.canvas_widget.mpl_connect('key_press_event', self.on_key_press)
        self.canvas_widget.mpl_connect('key_release_event', self.on_key_release)
    
    def create_widgets(self):
        """创建UI组件"""
        # 先调用父类的create_widgets方法，创建基础组件
        super().create_widgets()
        
        # 移除父类创建的设备类型选择
        try:
            self.device_type_label.grid_remove()
            self.device_type_cb.grid_remove()
        except Exception as e:
            pass
        
        # 设置主窗口的grid权重，确保内容能够随窗口大小变化而调整
        self.master.grid_columnconfigure(0, weight=1)
        self.master.grid_rowconfigure(0, weight=1)
        
        # 设置滚动框架的grid权重
        self.scrollable_frame.grid_columnconfigure(0, weight=1)
        self.scrollable_frame.grid_rowconfigure(3, weight=1)  # 曲线绘制区域占据最大权重
        
        # 通信方式选择区域
        self.create_communication_selection()
        
        # 调整串口配置区域的位置，横向排列，节省垂直空间
        try:
            self.port_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")
            self.port_cb.grid(row=1, column=1, padx=5, pady=5, sticky="w")
            self.baud_label.grid(row=1, column=2, padx=5, pady=5, sticky="w")
            self.baud_cb.grid(row=1, column=3, padx=5, pady=5, sticky="w")
            self.connect_btn.grid(row=1, column=4, padx=5, pady=5, sticky="w")
        except Exception as e:
            pass
        
        # TCP/UDP配置区域
        self.create_network_config()
        
        # 曲线绘制区域，让它占据左侧主要空间
        self.create_plot_area()
        
        # 通道数值实时显示区域，放置在曲线右侧的红框区域
        self.create_channel_values_display()
        
        # 通道控制区域，放置在曲线和数值显示区域下方
        self.create_channel_controls()
        
        # 添加debug模式开关
        self.create_debug_switch()
        
        # 日志区域
        self.create_log_area()
        
        # 初始化通信模式
        self.on_comm_mode_changed()
        
        # 添加窗口大小变化事件处理，动态调整图形大小
        self.master.bind("<Configure>", self.on_window_resize)
    
    def create_communication_selection(self):
        """创建通信方式选择组件"""
        comm_frame = ttk.LabelFrame(self.scrollable_frame, text="通信方式", padding=(10, 5))
        comm_frame.grid(row=0, column=0, columnspan=7, sticky="ew", padx=5, pady=5)
        
        self.comm_mode_var = tk.StringVar(value="serial")
        
        ttk.Radiobutton(comm_frame, text="串口", variable=self.comm_mode_var, value="serial", command=self.on_comm_mode_changed).grid(row=0, column=0, sticky="w", padx=5, pady=5)
        ttk.Radiobutton(comm_frame, text="TCP", variable=self.comm_mode_var, value="tcp", command=self.on_comm_mode_changed).grid(row=0, column=1, sticky="w", padx=5, pady=5)
        ttk.Radiobutton(comm_frame, text="UDP", variable=self.comm_mode_var, value="udp", command=self.on_comm_mode_changed).grid(row=0, column=2, sticky="w", padx=5, pady=5)
    
    def create_network_config(self):
        """创建TCP/UDP配置区域"""
        self.network_frame = ttk.LabelFrame(self.scrollable_frame, text="网络配置", padding=(10, 5))
        self.network_frame.grid(row=2, column=0, columnspan=7, sticky="ew", padx=5, pady=5)
        
        # TCP/UDP配置
        ttk.Label(self.network_frame, text="主机:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.host_entry = ttk.Entry(self.network_frame, width=15)
        self.host_entry.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        self.host_entry.insert(0, "127.0.0.1")
        
        ttk.Label(self.network_frame, text="远程端口:").grid(row=0, column=2, sticky="w", padx=5, pady=5)
        self.port_entry = ttk.Entry(self.network_frame, width=10)
        self.port_entry.grid(row=0, column=3, sticky="w", padx=5, pady=5)
        self.port_entry.insert(0, "8080")
        
        ttk.Label(self.network_frame, text="本地端口:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.local_port_entry = ttk.Entry(self.network_frame, width=10)
        self.local_port_entry.grid(row=1, column=1, sticky="w", padx=5, pady=5)
        self.local_port_entry.insert(0, "8080")
        
        # 网络模式选择区域
        self.mode_frame = ttk.Frame(self.network_frame)
        self.mode_frame.grid(row=0, column=4, columnspan=2, sticky="w", padx=5, pady=5)
        
        # TCP模式选项
        self.tcp_client_rb = ttk.Radiobutton(self.mode_frame, text="客户端", variable=self.net_mode_var, value="client", command=self.on_comm_mode_changed)
        self.tcp_server_rb = ttk.Radiobutton(self.mode_frame, text="服务器", variable=self.net_mode_var, value="server", command=self.on_comm_mode_changed)
        
        # UDP模式选项
        self.udp_unicast_rb = ttk.Radiobutton(self.mode_frame, text="单播", variable=self.net_mode_var, value="unicast", command=self.on_comm_mode_changed)
        self.udp_broadcast_rb = ttk.Radiobutton(self.mode_frame, text="广播", variable=self.net_mode_var, value="broadcast", command=self.on_comm_mode_changed)
        
        # 初始隐藏网络配置
        self.network_frame.grid_remove()
    
    def update_network_config(self):
        """根据通信方式更新网络配置选项"""
        # 清除模式框架中的所有组件
        for widget in self.mode_frame.winfo_children():
            widget.grid_remove()
        
        if self.current_communication_mode == "tcp":
            # TCP模式：客户端/服务器
            self.tcp_client_rb.grid(row=0, column=0, sticky="w", padx=5, pady=5)
            self.tcp_server_rb.grid(row=0, column=1, sticky="w", padx=5, pady=5)
            self.net_mode_var.set("client")
            self.log_message(f"TCP网络模式：客户端")
        elif self.current_communication_mode == "udp":
            # UDP模式：单播/广播
            self.udp_unicast_rb.grid(row=0, column=0, sticky="w", padx=5, pady=5)
            self.udp_broadcast_rb.grid(row=0, column=1, sticky="w", padx=5, pady=5)
            self.net_mode_var.set("unicast")
            self.log_message(f"UDP网络模式：单播")
    
    def create_plot_area(self):
        """创建曲线绘制区域，只占据左侧空间"""
        # 让曲线绘制区域只占据左侧空间
        plot_frame = ttk.LabelFrame(self.scrollable_frame, text="实时曲线", padding=(10, 5))
        # 只占据左侧5列，留出右侧空间给通道数值显示
        plot_frame.grid(row=3, column=0, columnspan=5, sticky="nsew", padx=5, pady=5)
        
        # 设置plot_frame内部的网格权重
        plot_frame.grid_columnconfigure(0, weight=1)
        plot_frame.grid_rowconfigure(0, weight=1)  # 曲线区域占据主要权重
        
        # 创建Canvas，设置figsize为None，让它自适应窗口大小
        self.canvas_widget = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas_widget.draw()
        # 设置Canvas占据plot_frame的整个空间
        self.canvas_widget.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        
        # 创建工具栏，使用Frame包装以兼容grid布局
        toolbar_frame = ttk.Frame(plot_frame)
        toolbar_frame.grid(row=1, column=0, sticky="ew")
        toolbar = NavigationToolbar2Tk(self.canvas_widget, toolbar_frame)
        toolbar.update()
        
        # 设置网格
        self.ax.grid(True, linestyle='--', alpha=0.7)
        self.ax.set_xlabel('时间 (ms)')
        self.ax.set_ylabel('数值')
        self.ax.set_title('实时数据曲线')
        # 初始化时不创建图例，在添加第一个通道时再创建
        
        # 初始化blit背景
        self.blit_background = self.canvas_widget.copy_from_bbox(self.fig.bbox)
    
    def create_channel_controls(self):
        """创建通道控制区域，调整位置到曲线和数值显示下方"""
        channel_frame = ttk.LabelFrame(self.scrollable_frame, text="通道控制", padding=(10, 5))
        # 调整位置到row=4，位于曲线和数值显示下方，减少与曲线区域的间距
        channel_frame.grid(row=4, column=0, columnspan=10, sticky="ew", padx=5, pady=2)
        
        # 设置channel_frame内部的网格权重
        channel_frame.grid_columnconfigure(4, weight=1)
        
        # 清除数据按钮
        self.clear_data_btn = ttk.Button(channel_frame, text="清除数据", command=self.clear_data)
        self.clear_data_btn.grid(row=0, column=0, sticky="w", padx=5, pady=2)
        
        # 通道选择控制
        self.select_all_btn = ttk.Button(channel_frame, text="全选", command=self.select_all_channels)
        self.select_all_btn.grid(row=0, column=2, sticky="w", padx=5, pady=2)
        
        self.select_none_btn = ttk.Button(channel_frame, text="全不选", command=self.select_none_channels)
        self.select_none_btn.grid(row=0, column=3, sticky="w", padx=5, pady=2)
        
        # 添加通道选择说明
        ttk.Label(channel_frame, text="通道开关:").grid(row=0, column=4, sticky="w", padx=5, pady=2)
        
        # 创建通道按钮的滚动区域，减少垂直间距
        scrollable_channel_frame = ttk.Frame(channel_frame)
        # 减少与上方组件的间距，设置高度为60px以限制垂直空间
        scrollable_channel_frame.grid(row=1, column=0, columnspan=10, sticky="ew", padx=5, pady=2, ipady=0)
        
        # 创建水平滚动条
        channel_scrollbar = ttk.Scrollbar(scrollable_channel_frame, orient="horizontal")
        channel_scrollbar.grid(row=1, column=0, sticky="ew")
        
        # 创建通道按钮容器，使用Canvas和Frame组合实现水平滚动
        self.channel_canvas = tk.Canvas(scrollable_channel_frame, xscrollcommand=channel_scrollbar.set, height=40)
        self.channel_canvas.grid(row=0, column=0, sticky="ew")
        
        # 配置滚动条
        channel_scrollbar.config(command=self.channel_canvas.xview)
        
        # 创建通道按钮Frame
        self.channel_frame = ttk.Frame(self.channel_canvas)
        self.channel_canvas.create_window((0, 0), window=self.channel_frame, anchor="nw")
        
        # 通道按钮容器
        self.channel_buttons = {}
        
        # 更新滚动区域大小
        def update_scroll_region(event):
            self.channel_canvas.configure(scrollregion=self.channel_canvas.bbox("all"))
        
        self.channel_frame.bind("<Configure>", update_scroll_region)
        
        # 设置滚动框架的权重
        scrollable_channel_frame.grid_columnconfigure(0, weight=1)
    
    def select_all_channels(self):
        """全选所有通道"""
        channel_count = len(self.channel_visibility)
        for var in self.channel_visibility.values():
            var.set(True)
        
        # 更新曲线显示
        for channel_name, line in self.lines.items():
            line.set_visible(True)
        
        self.canvas_widget.draw()
        self.log_message(f"已全选 {channel_count} 个通道")
    
    def select_none_channels(self):
        """全不选所有通道"""
        channel_count = len(self.channel_visibility)
        for var in self.channel_visibility.values():
            var.set(False)
        
        # 更新曲线显示
        for channel_name, line in self.lines.items():
            line.set_visible(False)
        
        self.canvas_widget.draw()
        self.log_message(f"已全不选 {channel_count} 个通道")
    
    def create_debug_switch(self):
        """创建debug模式开关，减少与其他组件的间距"""
        debug_frame = ttk.LabelFrame(self.scrollable_frame, text="调试控制", padding=(10, 5))
        # 调整位置，减少与通道控制区域的间距，占据整个宽度
        debug_frame.grid(row=5, column=0, columnspan=10, sticky="ew", padx=5, pady=2)
        
        # debug模式开关按钮
        self.debug_mode_var = tk.BooleanVar(value=False)
        self.debug_switch_btn = ttk.Checkbutton(debug_frame, text="开启Debug模式", variable=self.debug_mode_var, command=self.on_debug_switch)
        self.debug_switch_btn.grid(row=0, column=0, sticky="w", padx=5, pady=5)
        
        # 添加debug指令说明，调整columnspan使其能显示完整
        ttk.Label(debug_frame, text="点击开启后向设备发送开启debug指令，设备开始输出通道数据").grid(row=0, column=1, columnspan=8, sticky="w", padx=5, pady=5)
    
    def on_comm_mode_changed(self):
        """处理通信方式变更"""
        old_mode = self.current_communication_mode
        self.current_communication_mode = self.comm_mode_var.get()
        
        # 记录通信模式切换
        self.log_message(f"通信模式切换：{old_mode} → {self.current_communication_mode}")
        
        # 清空数据缓冲区和缓存，确保不处理旧数据
        self.data_buffer.clear()
        self.data_cache.clear()
        # 清除曲线
        for line in self.lines.values():
            line.set_data([], [])
        self.canvas_widget.draw()
        
        # 关闭当前所有控制器的连接
        if self.serial_controller.is_connected():
            self.serial_controller.close()
        if self.tcp_controller.is_connected():
            self.tcp_controller.close()
        if self.udp_controller.is_connected():
            self.udp_controller.close()
        
        if self.current_communication_mode == "serial":
            # 显示串口配置，隐藏网络配置
            try:
                self.port_label.grid()
                self.port_cb.grid()
                self.baud_label.grid()
                self.baud_cb.grid()
            except Exception as e:
                pass
            self.network_frame.grid_remove()
            # 更新连接按钮文本
            self.connect_btn.config(text="打开串口")
        else:
            # 隐藏串口配置，显示网络配置
            try:
                self.port_label.grid_remove()
                self.port_cb.grid_remove()
                self.baud_label.grid_remove()
                self.baud_cb.grid_remove()
            except Exception as e:
                pass
            self.network_frame.grid()
            
            # 根据通信方式更新网络配置选项
            self.update_network_config()
            
            # 更新连接按钮文本
            if self.current_communication_mode == "tcp":
                # TCP模式：客户端/服务器
                if self.net_mode_var.get() == "server":
                    self.connect_btn.config(text="开始监听")
                else:
                    self.connect_btn.config(text="连接")
            elif self.current_communication_mode == "udp":
                # UDP模式
                self.connect_btn.config(text="连接")
        
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
    
    def on_debug_switch(self):
        """处理debug模式开关事件"""
        is_debug = self.debug_mode_var.get()
        
        if is_debug:
            # 发送开启debug指令
            self.send_debug_command(1)
            self.log_message("发送开启debug指令")
        else:
            # 发送关闭debug指令
            self.send_debug_command(0)
            self.log_message("发送关闭debug指令")
    
    def send_debug_command(self, enable):
        """向设备发送debug指令"""
        # 检查连接状态
        if not self.device.is_connected():
            messagebox.showwarning("警告", "请先建立连接")
            return
        
        # 构建debug指令
        # 根据协议定义，构建debug指令帧
        # 这里使用简化的实现，实际需要根据协议规范实现
        try:
            # 从debug_protocol中获取协议实现
            if hasattr(self.device.protocol, 'build_debug_command'):
                debug_cmd = self.device.protocol.build_debug_command(enable)
                success, msg = self.device.communication_controller.send_data(debug_cmd)
                if success:
                    self.log_message(f"debug指令发送成功: {'开启' if enable else '关闭'}")
                else:
                    self.log_message(f"debug指令发送失败: {msg}")
            else:
                self.log_message("设备协议不支持debug指令")
        except Exception as e:
            self.log_message(f"发送debug指令时发生错误: {str(e)}")
    
    def toggle_serial(self):
        """打开或关闭通信连接"""
        success = False
        msg = ""
        is_broadcast = False  # 初始化变量，避免未定义错误
        port = ""  # 初始化port变量，避免未定义错误
        
        # 根据通信方式选择控制器
        if self.current_communication_mode == "serial":
            # 串口模式
            port = self.port_cb.get()
            baud_rate = self.baud_cb.get()
            
            if not port:
                messagebox.showwarning("警告", "请选择串口")
                return
            
            self.log_message(f"尝试{self.connect_btn.cget('text')}：串口{port}，波特率{baud_rate}")
            success, msg = self.serial_controller.toggle_connection(port, baud_rate)
            
            # 更新设备的通信控制器
            self.device.communication_controller = self.serial_controller
            
            # 更新按钮文本
            if self.device.is_connected():
                self.connect_btn.config(text="关闭串口")
                self.log_message(f"串口连接成功：{port}，波特率{baud_rate}")
            else:
                self.connect_btn.config(text="打开串口")
                self.log_message(f"串口连接关闭：{port}")
        elif self.current_communication_mode == "tcp":
            # TCP模式
            host = self.host_entry.get()
            port = self.port_entry.get()
            
            if not host or not port:
                messagebox.showwarning("警告", "请填写完整的网络配置")
                return
            
            is_server = self.net_mode_var.get() == "server"
            mode_text = "服务器监听" if is_server else "客户端连接"
            self.log_message(f"尝试{self.connect_btn.cget('text')}：TCP{mode_text}，{host}:{port}")
            
            success, msg = self.tcp_controller.toggle_connection(host, int(port), is_server)
            
            # 更新设备的通信控制器
            self.device.communication_controller = self.tcp_controller
            
            # 更新按钮文本
            if self.device.is_connected():
                if is_server:
                    self.connect_btn.config(text="停止监听")
                    self.log_message(f"TCP服务器监听成功：{host}:{port}")
                else:
                    self.connect_btn.config(text="断开连接")
                    self.log_message(f"TCP客户端连接成功：{host}:{port}")
            else:
                if is_server:
                    self.connect_btn.config(text="开始监听")
                    self.log_message(f"TCP服务器监听关闭：{host}:{port}")
                else:
                    self.connect_btn.config(text="连接")
                    self.log_message(f"TCP客户端连接关闭：{host}:{port}")
        elif self.current_communication_mode == "udp":
            # UDP模式
            host = self.host_entry.get()
            remote_port = self.port_entry.get()
            local_port = self.local_port_entry.get()
            
            if not host or not remote_port:
                messagebox.showwarning("警告", "请填写完整的网络配置")
                return
            
            is_broadcast = self.net_mode_var.get() == "广播"
            mode_text = "广播" if is_broadcast else "单播"
            local_port_text = local_port if local_port else remote_port
            self.log_message(f"尝试{self.connect_btn.cget('text')}：UDP{mode_text}，远程{host}:{remote_port}，本地端口{local_port_text}")
            
            # 如果本地端口为空，则使用远程端口
            if not local_port:
                success, msg = self.udp_controller.toggle_connection(host, int(remote_port), None, is_broadcast)
            else:
                success, msg = self.udp_controller.toggle_connection(host, int(remote_port), int(local_port), is_broadcast)
            
            # 更新设备的通信控制器
            self.device.communication_controller = self.udp_controller
            
            # 更新按钮文本
            if self.device.is_connected():
                self.connect_btn.config(text="断开连接")
                self.log_message(f"UDP{mode_text}连接成功：远程{host}:{remote_port}，本地端口{local_port_text}")
            else:
                self.connect_btn.config(text="连接")
                self.log_message(f"UDP{mode_text}连接关闭：远程{host}:{remote_port}，本地端口{local_port_text}")
        
        # 设置设备类型
        self.device.communication_controller.current_device_type = "DEBUG"
        
        # 检查连接状态，如果连接已关闭，清空数据缓冲区和缓存
        if not self.device.is_connected():
            # 调用设备的close方法，清空设备内部缓冲区和资源
            self.device.close()
            self.data_buffer.clear()
            self.data_cache.clear()
            # 清除曲线
            for line in self.lines.values():
                line.set_data([], [])
            self.canvas_widget.draw()
            self.log_message("连接已关闭，已清空所有数据缓冲区和缓存")
        
        if success:
            self.log_message(msg)
        else:
            messagebox.showerror("连接错误", msg)
        
        self.master.update_idletasks()
    
    def on_data_received(self, data, from_buffer=False):
        """处理接收到的数据，窗口调整期间将数据存入缓冲区"""
        if 'channel_data' not in data:
            return
        
        # 严格检查条件：必须开启DEBUG模式且设备连接
        # 确保只处理当前连接的数据，避免处理断开连接后的旧数据
        if not (self.debug_mode_var.get() and self.device.is_connected()):
            # 如果是从缓冲区处理数据且连接已关闭，清空缓冲区
            if from_buffer:
                self.data_buffer.clear()
            return
        
        # 如果正在调整窗口大小且数据不是来自缓冲区，则将数据存入缓冲区
        if self.is_resizing and not from_buffer:
            # 限制缓冲区大小，只保留最新的10条数据
            if len(self.data_buffer) > 10:
                self.data_buffer.pop(0)
            self.data_buffer.append(data.copy())
            return
        
        # 使用相对时间（毫秒）
        current_time = (time.time() - self.start_time) * 1000
        
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
        
        # 只有在有数据到达时才绘制，同时限制最小绘制间隔为5ms
        current_time = time.time() * 1000
        if current_time - self.last_plot_time >= self.min_plot_interval:
            self.update_plot()
            self.last_plot_time = current_time
    
    def update_channel_values(self, channel_name, value):
        """更新通道数值表格"""
        # 检查通道是否已在表格中
        channel_exists = False
        for item in self.channel_values_tree.get_children():
            if self.channel_values_tree.item(item, 'values')[0] == channel_name:
                # 更新现有通道数值
                self.channel_values_tree.item(item, values=(channel_name, f"{value:.2f}"))
                channel_exists = True
                break
        
        # 如果通道不在表格中，添加新通道
        if not channel_exists:
            self.channel_values_tree.insert('', 'end', values=(channel_name, f"{value:.2f}"))
    
    def add_channel_to_plot(self, channel_name):
        """添加新通道到曲线"""
        if channel_name in self.lines:
            return  # 通道已存在，不需要重复添加
        
        color = self.channel_colors[len(self.lines) % len(self.channel_colors)]
        line, = self.ax.plot([], [], color=color, label=channel_name, linewidth=1.5)
        self.lines[channel_name] = line
        
        # 将曲线添加到artist列表，用于blit更新
        self.artist_list.append(line)
        
        # 添加通道控制按钮
        self.add_channel_button(channel_name)
        
        # 更新图例，使用固定位置
        self.ax.legend(loc='upper right')
        
        # 立即更新画布，确保新通道显示
        self.canvas_widget.draw()
        # 更新blit背景
        self.blit_background = self.canvas_widget.copy_from_bbox(self.fig.bbox)
        # 记录日志
        self.log_message(f"通道 {channel_name} 已添加到曲线")
    
    def add_channel_button(self, channel_name):
        """添加通道控制按钮"""
        if channel_name in self.channel_buttons:
            return  # 按钮已存在，不需要重复添加
        
        # 创建变量
        var = tk.BooleanVar(value=True)
        self.channel_visibility[channel_name] = var
        
        # 创建复选框
        checkbox = ttk.Checkbutton(self.channel_frame, text=channel_name, variable=var, command=lambda: self.toggle_channel_visibility(channel_name))
        # 使用网格布局，每行8个按钮
        row = len(self.channel_buttons) // 8
        column = len(self.channel_buttons) % 8
        checkbox.grid(row=row, column=column, sticky="w", padx=5, pady=2)
        
        self.channel_buttons[channel_name] = checkbox
    
    def toggle_channel_visibility(self, channel_name):
        """切换通道可见性"""
        if channel_name in self.lines:
            visible = self.channel_visibility[channel_name].get()
            self.lines[channel_name].set_visible(visible)
            # 重绘整个画布，因为通道可见性变化会影响图例和坐标轴
            self.canvas_widget.draw()
            # 更新blit背景
            self.blit_background = self.canvas_widget.copy_from_bbox(self.fig.bbox)
            # 记录日志
            status = "显示" if visible else "隐藏"
            self.log_message(f"通道 {channel_name} 已{status}")
    
    def on_mouse_press(self, event):
        """鼠标按下事件处理，暂停自动流动"""
        if event.button == 1:  # 左键按下
            self.is_dragging = True
            self.auto_scroll = False
            self.log_message("曲线操作：暂停自动滚动")
    
    def on_mouse_release(self, event):
        """鼠标释放事件处理，检查是否恢复自动流动"""
        if event.button == 1:  # 左键释放
            self.is_dragging = False
            # 检查当前X轴范围是否在最新数据位置
            current_xlim = self.ax.get_xlim()
            max_time = max([max([t for t, v in self.data_cache[ch]]) for ch in self.data_cache if self.data_cache[ch]]) if self.data_cache else 0
            # 如果当前X轴右边界接近最新数据，恢复自动流动
            if max_time > 0 and current_xlim[1] >= max_time - 100:  # 100ms的容差
                self.auto_scroll = True
                self.log_message("曲线操作：恢复自动滚动")
            else:
                self.log_message("曲线操作：保持手动滚动")
    
    def on_key_press(self, event):
        """键盘按键按下事件处理，跟踪ctrl键状态"""
        if event.key == 'control' or event.key == 'ctrl':
            self.ctrl_pressed = True
    
    def on_key_release(self, event):
        """键盘按键释放事件处理，跟踪ctrl键状态"""
        if event.key == 'control' or event.key == 'ctrl':
            self.ctrl_pressed = False
    
    def on_window_resize(self, event):
        """窗口大小变化事件处理，动态调整图形大小，使用节流技术避免频繁重绘"""
        # 跳过初始事件和非主窗口事件
        if event.widget != self.master:
            return
        
        # 标记为正在调整窗口大小
        if not self.is_resizing:
            self.is_resizing = True
            
        # 取消之前的定时器
        if self.resize_timer is not None:
            self.master.after_cancel(self.resize_timer)
            self.resize_timer = None
        
        # 设置新的定时器，延迟处理窗口大小变化
        self.resize_timer = self.master.after(self.resize_delay, self._handle_window_resize)
    
    def _handle_window_resize(self):
        """实际处理窗口大小变化的方法，只在窗口大小变化停止后调用"""
        try:
            # 调整图形大小，使用自动布局
            self.fig.tight_layout()
            
            # 重新绘制整个画布
            self.canvas_widget.draw()
            
            # 处理缓冲区中的数据，只处理最新的数据，避免数据积压
            if self.data_buffer:
                # 只处理最新的数据，忽略中间数据
                latest_data = self.data_buffer[-1]
                self.on_data_received(latest_data, from_buffer=True)
                # 清空缓冲区
                self.data_buffer.clear()
        except Exception as e:
            pass
        finally:
            # 清除定时器
            self.resize_timer = None
            # 标记为窗口大小调整完成
            self.is_resizing = False
    
    def on_mouse_scroll(self, event):
        """鼠标滚轮事件处理，支持按住ctrl加滚轮缩放曲线"""
        # 检查是否按住了ctrl键
        if self.ctrl_pressed:
            # 确保鼠标在曲线区域
            if event.inaxes == self.ax:
                # 计算缩放比例，每次缩放10%
                scale_factor = 1.1 if event.button == 'up' else 0.9
                
                # 获取当前X轴和Y轴范围
                current_xlim = self.ax.get_xlim()
                current_ylim = self.ax.get_ylim()
                
                # 计算鼠标位置在当前坐标系统中的比例
                x_data = event.xdata
                y_data = event.ydata
                
                # 计算新的X轴范围，以鼠标位置为中心进行缩放
                if x_data is not None:
                    x_range = current_xlim[1] - current_xlim[0]
                    x_span_left = x_data - current_xlim[0]
                    x_span_right = current_xlim[1] - x_data
                    new_x_range = x_range * scale_factor
                    new_xlim = (x_data - x_span_left * scale_factor, x_data + x_span_right * scale_factor)
                else:
                    # 如果鼠标位置不在坐标系内，使用中心缩放
                    x_center = (current_xlim[0] + current_xlim[1]) / 2
                    x_range = current_xlim[1] - current_xlim[0]
                    new_x_range = x_range * scale_factor
                    new_xlim = (x_center - new_x_range / 2, x_center + new_x_range / 2)
                
                # 计算新的Y轴范围，以鼠标位置为中心进行缩放
                if y_data is not None:
                    y_range = current_ylim[1] - current_ylim[0]
                    y_span_left = y_data - current_ylim[0]
                    y_span_right = current_ylim[1] - y_data
                    new_y_range = y_range * scale_factor
                    new_ylim = (y_data - y_span_left * scale_factor, y_data + y_span_right * scale_factor)
                else:
                    # 如果鼠标位置不在坐标系内，使用中心缩放
                    y_center = (current_ylim[0] + current_ylim[1]) / 2
                    y_range = current_ylim[1] - current_ylim[0]
                    new_y_range = y_range * scale_factor
                    new_ylim = (y_center - new_y_range / 2, y_center + new_y_range / 2)
                
                # 设置新的X轴和Y轴范围
                self.ax.set_xlim(new_xlim)
                self.ax.set_ylim(new_ylim)
                
                # 重绘整个画布，确保背景正确更新
                self.canvas_widget.draw()
                # 重新初始化blit背景，防止重影
                self.blit_background = self.canvas_widget.copy_from_bbox(self.fig.bbox)
    
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
            if line.get_visible() and channel_name in self.data_cache:
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
                self.ax.set_xlim(min_time, latest_time)
            
            # 批量更新所有可见曲线的数据
            update_needed = False
            for channel_name, line in visible_lines.items():
                channel_data = self.data_cache[channel_name]
                if channel_data:
                    # 直接解包最新数据，避免重复计算
                    timestamps = [t for t, v in channel_data]
                    values = [v for t, v in channel_data]
                    line.set_data(timestamps, values)
                    update_needed = True
            
            # 只在需要更新时才重新计算Y轴范围和绘制
            if update_needed:
                # 计算Y轴范围，只使用最新数据点
                recent_values = []
                for channel_name in visible_lines:
                    channel_data = self.data_cache[channel_name]
                    # 只使用最近的数据点来计算范围，减少计算量
                    recent_points = channel_data[-50:]  # 减少到最近50个点
                    recent_values.extend([v for t, v in recent_points])
                
                if recent_values:
                    min_val = min(recent_values)
                    max_val = max(recent_values)
                    val_range = max_val - min_val
                    if val_range == 0:
                        val_range = 1  # 防止除以0
                    
                    new_min = min_val - val_range * 0.1
                    new_max = max_val + val_range * 0.1
                    self.ax.set_ylim(new_min, new_max)
        
        # 使用普通绘制方式，避免blit相关错误
        self.canvas_widget.draw()
    
    def create_channel_values_display(self):
        """创建通道数值实时显示区域，放置在曲线右侧的红框区域"""
        # 创建容器
        values_frame = ttk.LabelFrame(self.scrollable_frame, text="通道数值实时显示", padding=(10, 5))
        # 放置在曲线右侧，与曲线同一行，占据右侧5列
        values_frame.grid(row=3, column=5, columnspan=5, sticky="nsew", padx=5, pady=5)
        
        # 设置grid权重
        values_frame.grid_columnconfigure(0, weight=1)
        values_frame.grid_rowconfigure(0, weight=1)
        
        # 创建样式
        style = ttk.Style()
        # 配置Treeview样式，设置字体和行高
        style.configure("Treeview", 
                       font=('Arial', 10),
                       rowheight=25,
                       background="white",
                       fieldbackground="white",
                       foreground="black")
        # 配置表头样式
        style.configure("Treeview.Heading", 
                       font=('Arial', 11, 'bold'),
                       background="#f0f0f0",
                       foreground="black",
                       relief="flat")
        # 配置选中行样式
        style.map("Treeview", 
                 background=[('selected', '#0078d7')],
                 foreground=[('selected', 'white')])
        
        # 创建Treeview表格
        columns = ('channel', 'value')
        # 增加表格高度，充分利用红框区域的空间
        self.channel_values_tree = ttk.Treeview(values_frame, columns=columns, show='headings', height=20, style="Treeview")
        
        # 设置列标题
        self.channel_values_tree.heading('channel', text='通道名称', anchor='center')
        self.channel_values_tree.heading('value', text='数值', anchor='center')
        
        # 设置列宽和对齐方式，适应右侧空间
        self.channel_values_tree.column('channel', width=150, anchor='center', stretch=False)
        self.channel_values_tree.column('value', width=100, anchor='center', stretch=False)
        
        # 添加垂直滚动条
        values_scrollbar = ttk.Scrollbar(values_frame, orient="vertical", command=self.channel_values_tree.yview)
        self.channel_values_tree.configure(yscrollcommand=values_scrollbar.set)
        
        # 布局表格和滚动条
        self.channel_values_tree.grid(row=0, column=0, sticky="nsew", padx=(0, 0))
        values_scrollbar.grid(row=0, column=1, sticky="ns")
    
    def clear_data(self):
        """清除数据和曲线"""
        # 清除数据缓存
        self.data_cache.clear()
        
        # 清除曲线
        for line in self.lines.values():
            line.set_data([], [])
        
        # 清空通道按钮
        for button in self.channel_buttons.values():
            button.destroy()
        
        self.channel_buttons.clear()
        self.channel_visibility.clear()
        self.lines.clear()
        
        # 清空通道数值表格
        for item in self.channel_values_tree.get_children():
            self.channel_values_tree.delete(item)
        
        # 重置初始时间
        self.start_time = time.time()
        
        # 重绘
        self.ax.clear()
        self.ax.grid(True, linestyle='--', alpha=0.7)
        self.ax.set_xlabel('时间 (ms)')
        self.ax.set_ylabel('数值')
        self.ax.set_title('实时数据曲线')
        self.ax.legend()
        self.canvas_widget.draw()
        
        self.log_message("数据已清除")
    
    def create_log_area(self):
        """创建日志区域，减少与其他组件的间距"""
        log_frame = ttk.LabelFrame(self.scrollable_frame, text="日志", padding=(10, 5))
        # 调整位置，减少与调试控制区域的间距，占据整个宽度
        log_frame.grid(row=6, column=0, columnspan=10, sticky="ew", padx=5, pady=2)
        
        # 日志文本框，调整高度，减少不必要的垂直空间
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, width=80)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        # 设置网格权重
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)
    
    def log_message(self, msg):
        """记录日志"""
        timestamp = time.strftime("[%Y-%m-%d %H:%M:%S] ")
        log_entry = timestamp + "[UI] " + msg + "\n"
        
        # 显示到UI
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)
        self.log_text.update_idletasks()
        
        # 写入到统一日志文件
        try:
            with open("log.txt", "a", encoding="utf-8") as f:
                f.write(log_entry)
                f.flush()
        except Exception as e:
            # 捕获异常，确保程序不会崩溃
            pass
    
    def on_device_type_changed(self, event=None):
        """处理设备类型变更"""
        # DEBUG设备不需要处理设备类型变更
        pass
    
    def update_ui(self):
        """更新UI显示"""
        super().update_ui()
        # DEBUG设备的UI更新逻辑
    
    def destroy(self):
        """清理资源"""
        # 关闭通信连接
        if self.device.is_connected():
            self.device.communication_controller.close()
        
        # 清理matplotlib资源
        plt.close(self.fig)
        
        super().destroy()
