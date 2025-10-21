import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from ui.ui_base import UIBase

class AFD01_QS_UI(UIBase):
    """AFD01_QS设备的UI实现类"""
    
    def __init__(self, master, device):
        # 定义布局配置
        self.layout_config = {
            # 设备状态表格
            "status_table": {"row": 1, "column": 0, "columnspan": 7, "padx": 5, "pady": 5},
            
            # 分组框
            "report_data_frame": {"row": 3, "column": 0, "columnspan": 7, "padx": 5, "pady": 5, "sticky": "ew"},
            "satellite_param_frame": {"row": 8, "column": 0, "columnspan": 7, "padx": 5, "pady": 5, "sticky": "ew"},
            "beam_control_frame": {"row": 10, "column": 0, "columnspan": 7, "padx": 5, "pady": 5, "sticky": "ew"},
            "tracking_mode_frame": {"row": 11, "column": 0, "columnspan": 7, "padx": 5, "pady": 5, "sticky": "ew"},
            "tx_enable_frame": {"row": 12, "column": 0, "columnspan": 7, "padx": 5, "pady": 5, "sticky": "ew"},
            "tle_frame": {"row": 13, "column": 0, "columnspan": 7, "padx": 5, "pady": 5, "sticky": "ew"},
            "log_frame": {"row": 16, "column": 0, "columnspan": 7, "padx": 5, "pady": 5, "sticky": "nsew"},
        }
        
        super().__init__(master, device)
        
        # 配置主窗口的行和列权重，使UI可以适当缩放
        self.master.grid_rowconfigure(17, weight=1)
        self.master.grid_columnconfigure(0, weight=1)
        
    def create_widgets(self):
        """创建UI组件"""
        # 调用父类方法创建设备选择和串口设置组件
        super().create_widgets()
        
        # 创建特定于AFD01_QS设备的UI组件
        self.create_specific_widgets()
    
    def create_specific_widgets(self):
        """创建特定于AFD01_QS设备的UI组件"""
        # 设备状态表格
        self.status_frame = ttk.Frame(self.master)
        self.status_frame.grid(**self.layout_config["status_table"])
        
        # 创建状态标签和值标签
        self.status_labels = {}
        status_items = [
            "GPS状态: ", "GPS经度: ", "GPS纬度: ", "GPS高度: ",
            "接收频率: ", "发射频率: ", "接收本振: ", "发射本振: ",
            "发射状态: ", "极化方式: ", "俯仰角: ", "横滚角: ",
            "方位角: ", "波束偏角: ", "波束方位: ", "对星模式: ",
            "通信状态: ", "运行时间: "
        ]
        
        row = 0
        col = 0
        for item in status_items:
            ttk.Label(self.status_frame, text=item).grid(row=row, column=col*2, sticky="w", padx=5, pady=2)
            value_label = ttk.Label(self.status_frame, text="N/A", width=15)
            value_label.grid(row=row, column=col*2+1, sticky="w", padx=5, pady=2)
            self.status_labels[item] = value_label
            
            col += 1
            if col >= 3:
                col = 0
                row += 1
        
        # 创建分组框
        # 数据上报参数分组框
        self.report_data_frame = ttk.LabelFrame(self.master, text="数据上报参数", padding=(10, 5))
        self.report_data_frame.grid(**self.layout_config["report_data_frame"])
        
        # 信噪比输入
        ttk.Label(self.report_data_frame, text="信噪比(dB): ").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.report_snr_entry = ttk.Entry(self.report_data_frame, width=10)
        self.report_snr_entry.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        self.report_snr_entry.insert(0, "0.0")  # 默认信噪比
        
        # 电源状态选择
        ttk.Label(self.report_data_frame, text="电源状态: ").grid(row=0, column=2, sticky="w", padx=5, pady=5)
        self.report_power_status_var = tk.IntVar(value=0)  # 默认为关闭
        self.report_power_status_off_rb = ttk.Radiobutton(self.report_data_frame, text="关闭", variable=self.report_power_status_var, value=0)
        self.report_power_status_off_rb.grid(row=0, column=3, sticky="w", padx=5, pady=5)
        self.report_power_status_on_rb = ttk.Radiobutton(self.report_data_frame, text="打开", variable=self.report_power_status_var, value=1)
        self.report_power_status_on_rb.grid(row=0, column=4, sticky="w", padx=5, pady=5)
        
        # 广播锁定状态
        ttk.Label(self.report_data_frame, text="广播锁定: ").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.report_broadcast_lock_var = tk.IntVar(value=0)  # 默认为未锁定
        self.report_broadcast_lock_no_rb = ttk.Radiobutton(self.report_data_frame, text="未锁定", variable=self.report_broadcast_lock_var, value=0)
        self.report_broadcast_lock_no_rb.grid(row=1, column=1, sticky="w", padx=5, pady=5)
        self.report_broadcast_lock_yes_rb = ttk.Radiobutton(self.report_data_frame, text="已锁定", variable=self.report_broadcast_lock_var, value=1)
        self.report_broadcast_lock_yes_rb.grid(row=1, column=2, sticky="w", padx=5, pady=5)
        
        # 节能状态
        ttk.Label(self.report_data_frame, text="节能状态: ").grid(row=1, column=3, sticky="w", padx=5, pady=5)
        self.report_power_save_var = tk.IntVar(value=0)  # 默认为不支持
        self.report_power_save_no_rb = ttk.Radiobutton(self.report_data_frame, text="不支持", variable=self.report_power_save_var, value=0)
        self.report_power_save_no_rb.grid(row=1, column=4, sticky="w", padx=5, pady=5)
        self.report_power_save_yes_rb = ttk.Radiobutton(self.report_data_frame, text="支持", variable=self.report_power_save_var, value=1)
        self.report_power_save_yes_rb.grid(row=1, column=5, sticky="w", padx=5, pady=5)
        
        # 重启命令
        ttk.Label(self.report_data_frame, text="重启命令: ").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.report_reboot_var = tk.IntVar(value=0)  # 默认为正常工作
        self.report_reboot_no_rb = ttk.Radiobutton(self.report_data_frame, text="正常工作", variable=self.report_reboot_var, value=0)
        self.report_reboot_no_rb.grid(row=2, column=1, sticky="w", padx=5, pady=5)
        self.report_reboot_yes_rb = ttk.Radiobutton(self.report_data_frame, text="重启", variable=self.report_reboot_var, value=1)
        self.report_reboot_yes_rb.grid(row=2, column=2, sticky="w", padx=5, pady=5)
        
        # 数据上报命令发送按钮 - 放在分组框的右下角
        self.report_data_btn = ttk.Button(self.report_data_frame, text="发送数据上报命令", command=self.on_report_data)
        self.report_data_btn.grid(row=2, column=5, sticky="e", padx=5, pady=5)
        
        # 卫星参数分组框
        self.satellite_param_frame = ttk.LabelFrame(self.master, text="卫星参数与频率设置", padding=(10, 5))
        self.satellite_param_frame.grid(**self.layout_config["satellite_param_frame"])
        
        # 卫星参数输入
        ttk.Label(self.satellite_param_frame, text="卫星经度: ").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.satellite_lng_entry = ttk.Entry(self.satellite_param_frame, width=10)
        self.satellite_lng_entry.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        self.satellite_lng_entry.insert(0, "118.2")
        
        ttk.Label(self.satellite_param_frame, text="极化方式: ").grid(row=0, column=2, sticky="w", padx=5, pady=5)
        self.polarization_var = tk.StringVar(value="左旋")
        self.polarization_left_rb = ttk.Radiobutton(self.satellite_param_frame, text="左旋", variable=self.polarization_var, value="左旋")
        self.polarization_left_rb.grid(row=0, column=3, sticky="w", padx=5, pady=5)
        self.polarization_right_rb = ttk.Radiobutton(self.satellite_param_frame, text="右旋", variable=self.polarization_var, value="右旋")
        self.polarization_right_rb.grid(row=0, column=4, sticky="w", padx=5, pady=5)
        
        # 频率设置
        ttk.Label(self.satellite_param_frame, text="接收频率(MHz): ").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.rx_freq_entry = ttk.Entry(self.satellite_param_frame, width=10)
        self.rx_freq_entry.grid(row=1, column=1, sticky="w", padx=5, pady=5)
        self.rx_freq_entry.insert(0, "19798.0")
        
        ttk.Label(self.satellite_param_frame, text="发射频率(MHz): ").grid(row=1, column=2, sticky="w", padx=5, pady=5)
        self.tx_freq_entry = ttk.Entry(self.satellite_param_frame, width=10)
        self.tx_freq_entry.grid(row=1, column=3, sticky="w", padx=5, pady=5)
        self.tx_freq_entry.insert(0, "29788.0")
        
        # 搜星参数发送按钮 - 放在分组框的右下角
        self.search_param_btn = ttk.Button(self.satellite_param_frame, text="设置搜星参数", command=self.on_search_param)
        self.search_param_btn.grid(row=1, column=5, sticky="e", padx=5, pady=5)
        
        # 波束控制分组框
        self.beam_control_frame = ttk.LabelFrame(self.master, text="波束控制", padding=(10, 5))
        self.beam_control_frame.grid(**self.layout_config["beam_control_frame"])
        
        # 波束控制参数
        ttk.Label(self.beam_control_frame, text="俯仰角(°): ").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.pitch_entry = ttk.Entry(self.beam_control_frame, width=10)
        self.pitch_entry.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        self.pitch_entry.insert(0, "30.5")
        
        ttk.Label(self.beam_control_frame, text="方位角(°): ").grid(row=0, column=2, sticky="w", padx=5, pady=5)
        self.heading_entry = ttk.Entry(self.beam_control_frame, width=10)
        self.heading_entry.grid(row=0, column=3, sticky="w", padx=5, pady=5)
        self.heading_entry.insert(0, "30.5")
        
        # 波束控制按钮组 - 放在右侧，紧挨着参数
        self.tx_beam_btn = ttk.Button(self.beam_control_frame, text="发射波束配置", command=self.on_tx_beam_config)
        self.tx_beam_btn.grid(row=0, column=4, sticky="w", padx=5, pady=5)
        
        self.rx_beam_btn = ttk.Button(self.beam_control_frame, text="接收波束配置", command=self.on_rx_beam_config)
        self.rx_beam_btn.grid(row=0, column=5, sticky="w", padx=5, pady=5)
        
        self.both_beam_btn = ttk.Button(self.beam_control_frame, text="收发波束同时控制", command=self.on_both_beam_config)
        self.both_beam_btn.grid(row=0, column=6, sticky="w", padx=5, pady=5)
        
        # 对星模式分组框
        self.tracking_mode_frame = ttk.LabelFrame(self.master, text="对星模式", padding=(10, 5))
        self.tracking_mode_frame.grid(**self.layout_config["tracking_mode_frame"])
        
        # 对星模式选择
        ttk.Label(self.tracking_mode_frame, text="选择模式: ").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.tracking_mode_var = tk.IntVar(value=0)
        self.tracking_mode_manual_rb = ttk.Radiobutton(self.tracking_mode_frame, text="手动", variable=self.tracking_mode_var, value=1)
        self.tracking_mode_manual_rb.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        self.tracking_mode_auto_rb = ttk.Radiobutton(self.tracking_mode_frame, text="自动", variable=self.tracking_mode_var, value=0)
        self.tracking_mode_auto_rb.grid(row=0, column=2, sticky="w", padx=5, pady=5)
        # TLE生效方式：卫星经度设置为0（在卫星参数部分设置）
        
        # 对星模式发送按钮
        self.tracking_mode_btn = ttk.Button(self.tracking_mode_frame, text="设置对星模式", command=self.on_tracking_mode)
        self.tracking_mode_btn.grid(row=0, column=4, sticky="w", padx=5, pady=5)
        
        # 发射开关分组框
        self.tx_enable_frame = ttk.LabelFrame(self.master, text="发射开关", padding=(10, 5))
        self.tx_enable_frame.grid(**self.layout_config["tx_enable_frame"])
        
        # 发射开关选项
        ttk.Label(self.tx_enable_frame, text="状态设置: ").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.tx_enable_var = tk.IntVar(value=0)  # 默认为关闭
        self.tx_enable_off_rb = ttk.Radiobutton(self.tx_enable_frame, text="关闭", variable=self.tx_enable_var, value=0)
        self.tx_enable_off_rb.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        self.tx_enable_on_rb = ttk.Radiobutton(self.tx_enable_frame, text="开启", variable=self.tx_enable_var, value=1)
        self.tx_enable_on_rb.grid(row=0, column=2, sticky="w", padx=5, pady=5)
        
        # 发射开关发送按钮
        self.tx_enable_btn = ttk.Button(self.tx_enable_frame, text="设置发射开关", command=self.on_tx_enable)
        self.tx_enable_btn.grid(row=0, column=3, sticky="w", padx=5, pady=5)
        
        # TLE配置分组框
        self.tle_frame = ttk.LabelFrame(self.master, text="TLE配置", padding=(10, 5))
        self.tle_frame.grid(**self.layout_config["tle_frame"])
        
        # TLE输入区域
        ttk.Label(self.tle_frame, text="TLE数据行1: ").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.tle0_entry = ttk.Entry(self.tle_frame, width=70)
        self.tle0_entry.grid(row=0, column=1, columnspan=6, sticky="ew", padx=5, pady=5)
        self.tle0_entry.insert(0, "1 24876U 97035A   25265.46410208  .00000032  00000+0  00000+0 0  9999")
        
        ttk.Label(self.tle_frame, text="TLE数据行2: ").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.tle1_entry = ttk.Entry(self.tle_frame, width=70)
        self.tle1_entry.grid(row=1, column=1, columnspan=6, sticky="ew", padx=5, pady=5)
        self.tle1_entry.insert(0, "2 24876  55.8521 109.0478 0095461  56.3876 304.6077  2.00563039206580")
        
        # TLE设置按钮 - 放在分组框的右下角
        self.tle_btn = ttk.Button(self.tle_frame, text="设置TLE", command=self.on_tle_config)
        self.tle_btn.grid(row=2, column=6, sticky="e", padx=5, pady=5)
        
        # 日志区域分组框
        self.log_frame = ttk.LabelFrame(self.master, text="日志", padding=(10, 5))
        self.log_frame.grid(**self.layout_config["log_frame"])
        
        # 滚动文本框用于显示日志
        self.log_text = scrolledtext.ScrolledText(self.log_frame, width=80, height=10)
        self.log_text.grid(row=0, column=0, columnspan=7, sticky="nsew", padx=5, pady=5)
        self.log_text.config(state=tk.DISABLED)
        
        # 清除日志按钮 - 放在分组框的右上角
        self.clear_log_btn = ttk.Button(self.log_frame, text="清除日志", command=self.clear_log)
        self.clear_log_btn.grid(row=0, column=7, sticky="ne", padx=5, pady=5)
        
        # 配置日志框架的行列权重，使日志文本框可以自动调整大小
        self.log_frame.grid_rowconfigure(0, weight=1)
        self.log_frame.grid_columnconfigure(0, weight=1)
    
    def on_report_data(self):
        """处理数据上报命令"""
        cmd_name = "数据上报"
        try:
            # 从输入控件获取用户设置的参数
            snr = float(self.report_snr_entry.get())  # 信噪比
            power_status = self.report_power_status_var.get()  # 电源状态
            broadcast_lock_status = self.report_broadcast_lock_var.get()  # 广播锁定状态
            power_save_status = self.report_power_save_var.get()  # 节能状态
            reboot_cmd = self.report_reboot_var.get()  # 重启命令
            
            # 构建基带状态字节（bit1=电源状态，bit2=广播锁定状态）
            baseband_status = 0x00
            if power_status == 1:
                baseband_status |= 0x02  # 设置bit1
            if broadcast_lock_status == 1:
                baseband_status |= 0x04  # 设置bit2
            
            # 构建参数字典，符合协议规范
            params = {
                'snr': snr,
                'baseband_status': baseband_status,
                'power_save_status': power_save_status,
                'reboot_cmd': reboot_cmd
            }
            
            # 发送命令
            success, msg = self.device.send_command(cmd_name, params)
            if success:
                power_status_text = "打开" if power_status == 1 else "关闭"
                broadcast_lock_text = "已锁定" if broadcast_lock_status == 1 else "未锁定"
                power_save_text = "支持" if power_save_status == 1 else "不支持"
                reboot_cmd_text = "重启" if reboot_cmd == 1 else "正常工作"
                
                self.log_message(f"[成功] 命令发送成功: {cmd_name} - {msg}")
                self.log_message(f"  信噪比: {snr:.2f}dB")
                self.log_message(f"  电源状态: {power_status_text}")
                self.log_message(f"  广播锁定: {broadcast_lock_text}")
                self.log_message(f"  节能状态: {power_save_text}")
                self.log_message(f"  重启命令: {reboot_cmd_text}")
            else:
                self.log_message(f"[错误] 命令发送失败: {cmd_name} - {msg}")
        except ValueError as e:
            self.log_message(f"[错误] {cmd_name}参数格式错误: {str(e)}")
        except Exception as e:
            self.log_message(f"[错误] {cmd_name}命令执行失败: {str(e)}")
    
    def on_search_param(self):
        """处理搜星参数命令"""
        cmd_name = "搜星参数"
        try:
            # 搜星参数命令，参数包括卫星经度、极化方式、接收频率、发射频率
            satellite_lng = float(self.satellite_lng_entry.get())
            polarization = 0 if self.polarization_var.get() == "左旋" else 1
            rx_freq = float(self.rx_freq_entry.get())
            tx_freq = float(self.tx_freq_entry.get())
            params = {
                'satellite_lng': satellite_lng,
                'polarization': polarization,
                'rx_freq': rx_freq,
                'tx_freq': tx_freq
            }
            
            # 发送命令
            success, msg = self.device.send_command(cmd_name, params)
            if success:
                self.log_message(f"[成功] 命令发送成功: {cmd_name} - {msg}")
            else:
                self.log_message(f"[错误] 命令发送失败: {cmd_name} - {msg}")
        except ValueError as e:
            self.log_message(f"[错误] {cmd_name}参数格式错误: {str(e)}")
        except Exception as e:
            self.log_message(f"[错误] {cmd_name}命令执行失败: {str(e)}")
    
    def on_tracking_mode(self):
        """处理对星模式命令"""
        cmd_name = "对星模式"
        try:
            # 对星模式命令，参数是模式编号 (0=自动, 1=手动)
            mode = self.tracking_mode_var.get()
            
            # 发送命令
            success, msg = self.device.send_command(cmd_name, mode)
            if success:
                mode_text = "自动" if mode == 0 else "手动"
                self.log_message(f"[成功] 命令发送成功: {cmd_name} - {mode_text} - {msg}")
            else:
                self.log_message(f"[错误] 命令发送失败: {cmd_name} - {msg}")
        except Exception as e:
            self.log_message(f"[错误] {cmd_name}命令执行失败: {str(e)}")
    
    def on_tx_beam_config(self):
        """处理发射波束配置命令"""
        cmd_name = "发射波束配置"
        try:
            # 波束控制命令，参数包括俯仰角和方位角
            pitch = float(self.pitch_entry.get())
            heading = float(self.heading_entry.get())
            params = {
                'pitch': pitch,
                'heading': heading
            }
            
            # 发送命令
            success, msg = self.device.send_command(cmd_name, params)
            if success:
                self.log_message(f"[成功] 命令发送成功: {cmd_name} - {msg}")
            else:
                self.log_message(f"[错误] 命令发送失败: {cmd_name} - {msg}")
        except ValueError as e:
            self.log_message(f"[错误] {cmd_name}参数格式错误: {str(e)}")
        except Exception as e:
            self.log_message(f"[错误] {cmd_name}命令执行失败: {str(e)}")
    
    def on_rx_beam_config(self):
        """处理接收波束配置命令"""
        cmd_name = "接收波束配置"
        try:
            # 波束控制命令，参数包括俯仰角和方位角
            pitch = float(self.pitch_entry.get())
            heading = float(self.heading_entry.get())
            params = {
                'pitch': pitch,
                'heading': heading
            }
            
            # 发送命令
            success, msg = self.device.send_command(cmd_name, params)
            if success:
                self.log_message(f"[成功] 命令发送成功: {cmd_name} - {msg}")
            else:
                self.log_message(f"[错误] 命令发送失败: {cmd_name} - {msg}")
        except ValueError as e:
            self.log_message(f"[错误] {cmd_name}参数格式错误: {str(e)}")
        except Exception as e:
            self.log_message(f"[错误] {cmd_name}命令执行失败: {str(e)}")
    
    def on_both_beam_config(self):
        """处理收发波束同时控制命令"""
        cmd_name = "收发波束同时控制"
        try:
            # 波束控制命令，参数包括俯仰角和方位角
            pitch = float(self.pitch_entry.get())
            heading = float(self.heading_entry.get())
            params = {
                'pitch': pitch,
                'heading': heading
            }
            
            # 发送命令
            success, msg = self.device.send_command(cmd_name, params)
            if success:
                self.log_message(f"[成功] 命令发送成功: {cmd_name} - {msg}")
            else:
                self.log_message(f"[错误] 命令发送失败: {cmd_name} - {msg}")
        except ValueError as e:
            self.log_message(f"[错误] {cmd_name}参数格式错误: {str(e)}")
        except Exception as e:
            self.log_message(f"[错误] {cmd_name}命令执行失败: {str(e)}")
    
    def on_tx_enable(self):
        """处理发射开关命令"""
        cmd_name = "发射开关"
        try:
            # 发射开关命令，从tx_enable_var获取当前设置的状态
            enable = self.tx_enable_var.get()
            
            # 发送命令
            success, msg = self.device.send_command(cmd_name, enable)
            if not success:
                # 如果设置失败，恢复到原来的状态
                self.tx_enable_var.set(1 - enable)
                self.log_message(f"[错误] {cmd_name}设置失败: {msg}")
            else:
                self.log_message(f"[成功] {cmd_name}设置{'开启' if enable == 1 else '关闭'}成功")
                self.log_message(f"[成功] 命令发送成功: {cmd_name} - {msg}")
        except Exception as e:
            self.log_message(f"[错误] {cmd_name}命令执行失败: {str(e)}")
    
    def on_tle_config(self):
        """处理TLE配置按钮点击事件"""
        tle0 = self.tle0_entry.get().strip()
        tle1 = self.tle1_entry.get().strip()
        
        if not tle0 or not tle1:
            self.log_message("[错误] TLE数据不能为空")
            return
        
        params = {'tle0': tle0, 'tle1': tle1}
        success, msg = self.device.send_command("TLE星历配置", params)
        if success:
            self.log_message(f"[成功] TLE星历配置成功: {msg}")
        else:
            self.log_message(f"[错误] TLE星历配置失败: {msg}")
    
    def update_ui(self):
        """更新UI显示"""
        # 调用父类方法更新串口列表
        super().update_ui()
        
        # 更新设备状态信息
        if self.device:
            device_info = self.device.query_device_info()
            
            status_mapping = {
                "GPS状态: ": "gps_lock_status",
                "GPS经度: ": "gps_lng",
                "GPS纬度: ": "gps_lat",
                "GPS高度: ": "gps_alt",
                "接收频率: ": "rx_freq",
                "发射频率: ": "tx_freq",
                "接收本振: ": "rx_lo",
                "发射本振: ": "tx_lo",
                "发射状态: ": "tx_enable",
                "极化方式: ": "tx_polarization",
                "俯仰角: ": "pitch",
                "横滚角: ": "roll",
                "方位角: ": "heading",
                "波束偏角: ": "beam_off_axis",
                "波束方位: ": "beam_heading",
                "对星模式: ": "tracking_mode",
                "通信状态: ": "comm_status",
                "运行时间: ": "runtime"
            }
            
            for label_text, info_key in status_mapping.items():
                if label_text in self.status_labels and info_key in device_info:
                    self.status_labels[label_text].config(text=device_info[info_key])
    
    def log_message(self, message):
        """记录日志消息"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def clear_log(self):
        """清除日志"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def on_device_type_changed(self, event=None):
        """处理设备类型变更事件"""
        new_device_type = self.device_type_cb.get()
        print(f"[DEBUG] AFD01_QS_UI: 检测到设备类型变更，新类型: {new_device_type}, 当前类型: {self.current_device_type}")
        if new_device_type != self.current_device_type:
            self.current_device_type = new_device_type
            print(f"[DEBUG] AFD01_QS_UI: 更新当前设备类型为: {new_device_type}")
            # 这里应该有一个回调函数来通知应用程序切换设备
            if hasattr(self, 'device_type_change_callback'):
                print(f"[DEBUG] AFD01_QS_UI: 调用回调函数切换设备类型")
                self.device_type_change_callback(new_device_type)
            else:
                print(f"[DEBUG] AFD01_QS_UI: 没有设置device_type_change_callback")