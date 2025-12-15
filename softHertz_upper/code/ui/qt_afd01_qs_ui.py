import sys
import threading
import time
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, 
    QLabel, QLineEdit, QPushButton, QRadioButton, QTextEdit,
    QFrame, QScrollArea, QSplitter, QMessageBox, QComboBox,
    QTableWidget, QTableWidgetItem, QStatusBar
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal, QObject, QEventLoop
from PyQt5.QtGui import QFont, QColor
from ui.qt_base_ui import QBaseUI

class QAFD01_QS_UI(QBaseUI):
    """AFD01_QS设备的PyQt5 UI实现"""
    
    def __init__(self, parent=None, device=None):
        super().__init__(parent, device)
        
        # 性能测试状态跟踪
        self.test_running = False
        self.test_thread = None
        self.test_stop_event = None
        
        # 创建设备特定的UI组件
        self.create_specific_widgets()
        
        # 连接设备数据更新信号
        self._connect_device_signal(device)
    
    def _connect_device_signal(self, device):
        """连接设备数据更新信号"""
        # 注释掉数据更新信号连接，避免UI频繁更新导致卡顿
        # 只依赖定时器进行UI更新，提高性能
        # if device and hasattr(device, 'data_signal'):
        #     # 连接数据更新信号到UI更新槽函数
        #     device.data_signal.data_updated.connect(self.update_ui, Qt.QueuedConnection)
    
    def create_specific_widgets(self):
        """创建特定于AFD01_QS设备的UI组件"""
        # 设备状态标签
        self.status_labels = {}
        
        # 设备状态分组
        status_group = QGroupBox("设备状态")
        status_layout = QGridLayout()
        
        # 状态标签和值标签
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
            label = QLabel(item)
            value_label = QLabel("N/A")
            value_label.setFixedWidth(120)
            value_label.setFrameShape(QFrame.StyledPanel)
            value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            
            status_layout.addWidget(label, row, col*2, 1, 1)
            status_layout.addWidget(value_label, row, col*2+1, 1, 1)
            
            self.status_labels[item] = value_label
            
            col += 1
            if col >= 3:
                col = 0
                row += 1
        
        status_group.setLayout(status_layout)
        self.scroll_layout.addWidget(status_group)
        
        # 数据上报参数分组
        report_group = QGroupBox("数据上报参数")
        report_layout = QGridLayout()
        
        # 信噪比输入
        report_layout.addWidget(QLabel("信噪比(dB): "), 0, 0, 1, 1)
        self.report_snr_entry = QLineEdit()
        self.report_snr_entry.setFixedWidth(100)
        self.report_snr_entry.setText("0.0")
        report_layout.addWidget(self.report_snr_entry, 0, 1, 1, 1)
        
        # 电源状态选择
        report_layout.addWidget(QLabel("电源状态: "), 0, 2, 1, 1)
        self.report_power_status_var = 0
        self.report_power_status_off_rb = QRadioButton("关闭")
        self.report_power_status_off_rb.setChecked(True)
        self.report_power_status_off_rb.toggled.connect(lambda checked: setattr(self, 'report_power_status_var', 0) if checked else None)
        self.report_power_status_on_rb = QRadioButton("打开")
        self.report_power_status_on_rb.toggled.connect(lambda checked: setattr(self, 'report_power_status_var', 1) if checked else None)
        report_layout.addWidget(self.report_power_status_off_rb, 0, 3, 1, 1)
        report_layout.addWidget(self.report_power_status_on_rb, 0, 4, 1, 1)
        
        # 广播锁定状态 - 使用独立的布局确保与其他选项组不互斥
        report_layout.addWidget(QLabel("广播锁定: "), 1, 0, 1, 1)
        broadcast_lock_widget = QWidget()
        broadcast_lock_layout = QHBoxLayout(broadcast_lock_widget)
        broadcast_lock_layout.setContentsMargins(0, 0, 0, 0)
        self.report_broadcast_lock_var = 0
        self.report_broadcast_lock_no_rb = QRadioButton("未锁定")
        self.report_broadcast_lock_no_rb.setChecked(True)
        self.report_broadcast_lock_no_rb.toggled.connect(lambda checked: setattr(self, 'report_broadcast_lock_var', 0) if checked else None)
        self.report_broadcast_lock_yes_rb = QRadioButton("已锁定")
        self.report_broadcast_lock_yes_rb.toggled.connect(lambda checked: setattr(self, 'report_broadcast_lock_var', 1) if checked else None)
        broadcast_lock_layout.addWidget(self.report_broadcast_lock_no_rb)
        broadcast_lock_layout.addWidget(self.report_broadcast_lock_yes_rb)
        report_layout.addWidget(broadcast_lock_widget, 1, 1, 1, 2)
        
        # 节能状态 - 使用独立的布局确保与其他选项组不互斥
        report_layout.addWidget(QLabel("节能状态: "), 1, 3, 1, 1)
        power_save_widget = QWidget()
        power_save_layout = QHBoxLayout(power_save_widget)
        power_save_layout.setContentsMargins(0, 0, 0, 0)
        self.report_power_save_var = 0
        self.report_power_save_no_rb = QRadioButton("不支持")
        self.report_power_save_no_rb.setChecked(True)
        self.report_power_save_no_rb.toggled.connect(lambda checked: setattr(self, 'report_power_save_var', 0) if checked else None)
        self.report_power_save_yes_rb = QRadioButton("支持")
        self.report_power_save_yes_rb.toggled.connect(lambda checked: setattr(self, 'report_power_save_var', 1) if checked else None)
        power_save_layout.addWidget(self.report_power_save_no_rb)
        power_save_layout.addWidget(self.report_power_save_yes_rb)
        report_layout.addWidget(power_save_widget, 1, 4, 1, 2)
        
        # 重启命令 - 使用独立的布局确保与其他选项组不互斥
        report_layout.addWidget(QLabel("重启命令: "), 2, 0, 1, 1)
        reboot_widget = QWidget()
        reboot_layout = QHBoxLayout(reboot_widget)
        reboot_layout.setContentsMargins(0, 0, 0, 0)
        self.report_reboot_var = 0
        self.report_reboot_no_rb = QRadioButton("正常工作")
        self.report_reboot_no_rb.setChecked(True)
        self.report_reboot_no_rb.toggled.connect(lambda checked: setattr(self, 'report_reboot_var', 0) if checked else None)
        self.report_reboot_yes_rb = QRadioButton("重启")
        self.report_reboot_yes_rb.toggled.connect(lambda checked: setattr(self, 'report_reboot_var', 1) if checked else None)
        reboot_layout.addWidget(self.report_reboot_no_rb)
        reboot_layout.addWidget(self.report_reboot_yes_rb)
        report_layout.addWidget(reboot_widget, 2, 1, 1, 2)
        
        # 数据上报命令发送按钮
        self.report_data_btn = QPushButton("发送数据上报命令")
        self.report_data_btn.clicked.connect(self.on_report_data)
        report_layout.addWidget(self.report_data_btn, 2, 5, 1, 1, Qt.AlignRight)
        
        report_group.setLayout(report_layout)
        self.scroll_layout.addWidget(report_group)
        
        # 卫星参数与频率设置分组
        satellite_group = QGroupBox("卫星参数与频率设置")
        satellite_layout = QGridLayout()
        
        # 卫星参数输入
        satellite_layout.addWidget(QLabel("卫星经度: "), 0, 0, 1, 1)
        self.satellite_lng_entry = QLineEdit()
        self.satellite_lng_entry.setFixedWidth(100)
        self.satellite_lng_entry.setText("118.2")
        satellite_layout.addWidget(self.satellite_lng_entry, 0, 1, 1, 1)
        
        # 极化方式
        satellite_layout.addWidget(QLabel("极化方式: "), 0, 2, 1, 1)
        self.polarization_var = "左旋"
        self.polarization_left_rb = QRadioButton("左旋")
        self.polarization_left_rb.setChecked(True)
        self.polarization_left_rb.toggled.connect(lambda checked: setattr(self, 'polarization_var', "左旋") if checked else None)
        self.polarization_right_rb = QRadioButton("右旋")
        self.polarization_right_rb.toggled.connect(lambda checked: setattr(self, 'polarization_var', "右旋") if checked else None)
        satellite_layout.addWidget(self.polarization_left_rb, 0, 3, 1, 1)
        satellite_layout.addWidget(self.polarization_right_rb, 0, 4, 1, 1)
        
        # 频率设置
        satellite_layout.addWidget(QLabel("接收频率(MHz): "), 1, 0, 1, 1)
        self.rx_freq_entry = QLineEdit()
        self.rx_freq_entry.setFixedWidth(100)
        self.rx_freq_entry.setText("19798.0")
        satellite_layout.addWidget(self.rx_freq_entry, 1, 1, 1, 1)
        
        satellite_layout.addWidget(QLabel("发射频率(MHz): "), 1, 2, 1, 1)
        self.tx_freq_entry = QLineEdit()
        self.tx_freq_entry.setFixedWidth(100)
        self.tx_freq_entry.setText("29788.0")
        satellite_layout.addWidget(self.tx_freq_entry, 1, 3, 1, 1)
        
        # 搜星参数发送按钮
        self.search_param_btn = QPushButton("设置搜星参数")
        self.search_param_btn.clicked.connect(self.on_search_param)
        satellite_layout.addWidget(self.search_param_btn, 1, 5, 1, 1, Qt.AlignRight)
        
        satellite_group.setLayout(satellite_layout)
        self.scroll_layout.addWidget(satellite_group)
        
        # 波束控制分组
        beam_group = QGroupBox("波束控制")
        beam_layout = QHBoxLayout()
        
        # 波束控制参数
        beam_layout.addWidget(QLabel("俯仰角(°): "))
        self.pitch_entry = QLineEdit()
        self.pitch_entry.setFixedWidth(100)
        self.pitch_entry.setText("30.5")
        beam_layout.addWidget(self.pitch_entry)
        
        beam_layout.addWidget(QLabel("方位角(°): "))
        self.heading_entry = QLineEdit()
        self.heading_entry.setFixedWidth(100)
        self.heading_entry.setText("30.5")
        beam_layout.addWidget(self.heading_entry)
        
        # 波束控制按钮组
        self.tx_beam_btn = QPushButton("发射波束配置")
        self.tx_beam_btn.clicked.connect(self.on_tx_beam_config)
        beam_layout.addWidget(self.tx_beam_btn)
        
        self.rx_beam_btn = QPushButton("接收波束配置")
        self.rx_beam_btn.clicked.connect(self.on_rx_beam_config)
        beam_layout.addWidget(self.rx_beam_btn)
        
        self.both_beam_btn = QPushButton("收发波束同时控制")
        self.both_beam_btn.clicked.connect(self.on_both_beam_config)
        beam_layout.addWidget(self.both_beam_btn)
        
        beam_group.setLayout(beam_layout)
        self.scroll_layout.addWidget(beam_group)
        
        # 对星模式分组
        tracking_group = QGroupBox("对星模式")
        tracking_layout = QHBoxLayout()
        
        # 对星模式选择
        tracking_layout.addWidget(QLabel("选择模式: "))
        self.tracking_mode_var = 0
        self.tracking_mode_manual_rb = QRadioButton("手动")
        self.tracking_mode_manual_rb.toggled.connect(lambda checked: setattr(self, 'tracking_mode_var', 1) if checked else None)
        self.tracking_mode_auto_rb = QRadioButton("自动")
        self.tracking_mode_auto_rb.setChecked(True)
        self.tracking_mode_auto_rb.toggled.connect(lambda checked: setattr(self, 'tracking_mode_var', 0) if checked else None)
        tracking_layout.addWidget(self.tracking_mode_manual_rb)
        tracking_layout.addWidget(self.tracking_mode_auto_rb)
        
        # 对星模式发送按钮
        self.tracking_mode_btn = QPushButton("设置对星模式")
        self.tracking_mode_btn.clicked.connect(self.on_tracking_mode)
        tracking_layout.addWidget(self.tracking_mode_btn)
        
        tracking_group.setLayout(tracking_layout)
        self.scroll_layout.addWidget(tracking_group)
        
        # 发射开关分组
        tx_enable_group = QGroupBox("发射开关")
        tx_enable_layout = QHBoxLayout()
        
        # 发射开关选项
        tx_enable_layout.addWidget(QLabel("状态设置: "))
        self.tx_enable_var = 0
        self.tx_enable_off_rb = QRadioButton("关闭")
        self.tx_enable_off_rb.setChecked(True)
        self.tx_enable_off_rb.toggled.connect(lambda checked: setattr(self, 'tx_enable_var', 0) if checked else None)
        self.tx_enable_on_rb = QRadioButton("开启")
        self.tx_enable_on_rb.toggled.connect(lambda checked: setattr(self, 'tx_enable_var', 1) if checked else None)
        tx_enable_layout.addWidget(self.tx_enable_off_rb)
        tx_enable_layout.addWidget(self.tx_enable_on_rb)
        
        # 发射开关发送按钮
        self.tx_enable_btn = QPushButton("设置发射开关")
        self.tx_enable_btn.clicked.connect(self.on_tx_enable)
        tx_enable_layout.addWidget(self.tx_enable_btn)
        
        tx_enable_group.setLayout(tx_enable_layout)
        self.scroll_layout.addWidget(tx_enable_group)
        
        # TLE配置分组
        tle_group = QGroupBox("TLE配置")
        tle_layout = QGridLayout()
        
        # TLE输入区域
        tle_layout.addWidget(QLabel("TLE数据行1: "), 0, 0, 1, 1)
        self.tle0_entry = QLineEdit()
        self.tle0_entry.setFixedWidth(500)
        self.tle0_entry.setText("1 24876U 97035A   25265.46410208  .00000032  00000+0  00000+0 0  9999")
        tle_layout.addWidget(self.tle0_entry, 0, 1, 1, 1)
        
        tle_layout.addWidget(QLabel("TLE数据行2: "), 1, 0, 1, 1)
        self.tle1_entry = QLineEdit()
        self.tle1_entry.setFixedWidth(500)
        self.tle1_entry.setText("2 24876  55.8521 109.0478 0095461  56.3876 304.6077  2.00563039206580")
        tle_layout.addWidget(self.tle1_entry, 1, 1, 1, 1)
        
        # TLE设置按钮
        self.tle_btn = QPushButton("设置TLE")
        self.tle_btn.clicked.connect(self.on_tle_config)
        tle_layout.addWidget(self.tle_btn, 2, 1, 1, 1, Qt.AlignRight)
        
        tle_group.setLayout(tle_layout)
        self.scroll_layout.addWidget(tle_group)
        
        # 性能测试分组
        performance_group = QGroupBox("性能测试")
        performance_layout = QGridLayout()
        
        # 测试类型选择
        performance_layout.addWidget(QLabel("测试类型: "), 0, 0, 1, 1)
        self.test_type_var = "接收波束配置"
        self.test_type_combo = QComboBox()
        self.test_type_combo.addItems(["接收波束配置", "发射波束配置", "收发波束同时控制"])
        self.test_type_combo.setCurrentText(self.test_type_var)
        self.test_type_combo.currentTextChanged.connect(lambda text: setattr(self, 'test_type_var', text))
        performance_layout.addWidget(self.test_type_combo, 0, 1, 1, 2)
        
        # 测试参数输入
        performance_layout.addWidget(QLabel("发送间隔(ms): "), 1, 0, 1, 1)
        self.interval_entry = QLineEdit()
        self.interval_entry.setFixedWidth(100)
        self.interval_entry.setText("100")
        performance_layout.addWidget(self.interval_entry, 1, 1, 1, 1)
        
        performance_layout.addWidget(QLabel("发送次数: "), 1, 2, 1, 1)
        self.count_entry = QLineEdit()
        self.count_entry.setFixedWidth(100)
        self.count_entry.setText("10")
        performance_layout.addWidget(self.count_entry, 1, 3, 1, 1)
        
        # 测试控制按钮
        self.start_test_btn = QPushButton("开始测试")
        self.start_test_btn.clicked.connect(self.start_performance_test)
        performance_layout.addWidget(self.start_test_btn, 1, 4, 1, 1)
        
        self.stop_test_btn = QPushButton("停止测试")
        self.stop_test_btn.clicked.connect(self.stop_performance_test)
        self.stop_test_btn.setEnabled(False)
        performance_layout.addWidget(self.stop_test_btn, 1, 5, 1, 1)
        
        # 状态显示
        performance_layout.addWidget(QLabel("测试状态: "), 2, 0, 1, 1)
        self.test_status_var = "空闲"
        self.test_status_label = QLabel(self.test_status_var)
        self.test_status_label.setStyleSheet("color: green")
        performance_layout.addWidget(self.test_status_label, 2, 1, 1, 1)
        
        # 总耗时显示
        performance_layout.addWidget(QLabel("总耗时(ms): "), 2, 2, 1, 1)
        self.total_time_var = "0"
        self.total_time_label = QLabel(self.total_time_var)
        performance_layout.addWidget(self.total_time_label, 2, 3, 1, 1)
        
        performance_group.setLayout(performance_layout)
        self.scroll_layout.addWidget(performance_group)
        
        # 日志区域分组
        log_group = QGroupBox("日志")
        log_layout = QHBoxLayout()
        
        # 滚动文本框用于显示日志
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.NoWrap)
        log_layout.addWidget(self.log_text, 1)
        
        # 清除日志按钮
        self.clear_log_btn = QPushButton("清除日志")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_layout.addWidget(self.clear_log_btn, 0, Qt.AlignTop)
        
        log_group.setLayout(log_layout)
        self.scroll_layout.addWidget(log_group)
    
    @pyqtSlot()
    def on_report_data(self):
        """处理数据上报命令"""
        cmd_name = "数据上报"
        try:
            # 从输入控件获取用户设置的参数
            snr = float(self.report_snr_entry.text())  # 信噪比
            power_status = self.report_power_status_off_rb.isChecked()
            power_status = 0 if power_status else 1
            broadcast_lock_status = self.report_broadcast_lock_no_rb.isChecked()
            broadcast_lock_status = 0 if broadcast_lock_status else 1
            power_save_status = self.report_power_save_no_rb.isChecked()
            power_save_status = 0 if power_save_status else 1
            reboot_cmd = self.report_reboot_no_rb.isChecked()
            reboot_cmd = 0 if reboot_cmd else 1
            
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
    
    @pyqtSlot()
    def on_search_param(self):
        """处理搜星参数命令"""
        cmd_name = "搜星参数"
        try:
            # 搜星参数命令，参数包括卫星经度、极化方式、接收频率、发射频率
            satellite_lng = float(self.satellite_lng_entry.text())
            polarization = 0 if self.polarization_left_rb.isChecked() else 1
            rx_freq = float(self.rx_freq_entry.text())
            tx_freq = float(self.tx_freq_entry.text())
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
    
    @pyqtSlot()
    def on_tracking_mode(self):
        """处理对星模式命令"""
        cmd_name = "对星模式"
        try:
            # 对星模式命令，参数是模式编号 (0=自动, 1=手动)
            mode = 1 if self.tracking_mode_manual_rb.isChecked() else 0
            
            # 发送命令
            success, msg = self.device.send_command(cmd_name, mode)
            if success:
                mode_text = "自动" if mode == 0 else "手动"
                self.log_message(f"[成功] 命令发送成功: {cmd_name} - {mode_text} - {msg}")
            else:
                self.log_message(f"[错误] 命令发送失败: {cmd_name} - {msg}")
        except Exception as e:
            self.log_message(f"[错误] {cmd_name}命令执行失败: {str(e)}")
    
    @pyqtSlot()
    def on_tx_beam_config(self):
        """处理发射波束配置命令"""
        cmd_name = "发射波束配置"
        self._send_beam_command(cmd_name)
    
    @pyqtSlot()
    def on_rx_beam_config(self):
        """处理接收波束配置命令"""
        cmd_name = "接收波束配置"
        self._send_beam_command(cmd_name)
    
    @pyqtSlot()
    def on_both_beam_config(self):
        """处理收发波束同时控制命令"""
        cmd_name = "收发波束同时控制"
        self._send_beam_command(cmd_name)
    
    def _send_beam_command(self, cmd_name):
        """发送波束配置命令"""
        try:
            # 波束控制命令，参数包括俯仰角和方位角
            pitch = float(self.pitch_entry.text())
            heading = float(self.heading_entry.text())
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
    
    @pyqtSlot()
    def on_tx_enable(self):
        """处理发射开关命令"""
        cmd_name = "发射开关"
        try:
            # 发射开关命令，从tx_enable_var获取当前设置的状态
            enable = 0 if self.tx_enable_off_rb.isChecked() else 1
            
            # 发送命令
            success, msg = self.device.send_command(cmd_name, enable)
            if not success:
                # 如果设置失败，恢复到原来的状态
                if enable == 1:
                    self.tx_enable_off_rb.setChecked(True)
                else:
                    self.tx_enable_on_rb.setChecked(True)
                self.log_message(f"[错误] {cmd_name}设置失败: {msg}")
            else:
                self.log_message(f"[成功] {cmd_name}设置{'开启' if enable == 1 else '关闭'}成功")
                self.log_message(f"[成功] 命令发送成功: {cmd_name} - {msg}")
        except Exception as e:
            self.log_message(f"[错误] {cmd_name}命令执行失败: {str(e)}")
    
    @pyqtSlot()
    def on_tle_config(self):
        """处理TLE配置按钮点击事件"""
        tle0 = self.tle0_entry.text().strip()
        tle1 = self.tle1_entry.text().strip()
        
        if not tle0 or not tle1:
            self.log_message("[错误] TLE数据不能为空")
            return
        
        params = {'tle0': tle0, 'tle1': tle1}
        success, msg = self.device.send_command("TLE星历配置", params)
        if success:
            self.log_message(f"[成功] TLE星历配置成功: {msg}")
        else:
            self.log_message(f"[错误] TLE星历配置失败: {msg}")
    
    @pyqtSlot()
    def start_performance_test(self):
        """开始性能测试"""
        try:
            # 验证输入参数
            interval = int(self.interval_entry.text())
            count = int(self.count_entry.text())
            
            if interval < 1:
                self.log_message("[错误] 发送间隔必须大于等于1ms")
                return
            
            if count < 1:
                self.log_message("[错误] 发送次数必须大于等于1")
                return
            
            # 检查设备是否已连接
            if not self.device or not self.device.serial_controller.is_connected():
                self.log_message("[错误] 设备未连接，无法开始性能测试")
                return
            
            # 启用性能测试模式
            if hasattr(self.device, 'serial_controller'):
                self.device.serial_controller.performance_test_mode = True
            
            # 计算超时时间（预估时间 + 50%缓冲），考虑到串口通信的不确定性
            estimated_time = interval * count
            self.test_timeout = estimated_time * 1.5  # 50%缓冲，增加缓冲时间避免误判超时
            self.test_start_time = time.time()  # 记录测试开始时间
            
            # 更新UI状态
            self.test_running = True
            self.test_status_var = "运行中"
            self.test_status_label.setText(self.test_status_var)
            self.test_status_label.setStyleSheet("color: red")
            self.start_test_btn.setEnabled(False)
            self.stop_test_btn.setEnabled(True)
            self.total_time_var = "0"
            self.total_time_label.setText(self.total_time_var)
            
            # 记录日志
            self.log_message(f"[性能测试] 开始测试: 间隔{interval}ms, 发送{count}次, 超时时间{self.test_timeout/1000:.2f}s")
            
            # 创建停止事件
            self.test_stop_event = threading.Event()
            
            # 启动测试线程
            self.test_thread = threading.Thread(
                target=self._run_performance_test,
                args=(interval, count)
            )
            self.test_thread.daemon = True
            self.test_thread.start()
            
        except ValueError as e:
            self.log_message(f"[错误] 参数格式错误: {str(e)}")
        except Exception as e:
            self.log_message(f"[错误] 开始测试失败: {str(e)}")
    
    @pyqtSlot()
    def stop_performance_test(self):
        """停止性能测试"""
        if self.test_running:
            # 设置停止事件（如果存在）
            if self.test_stop_event:
                self.test_stop_event.set()
            
            # 立即重置test_running标志，防止状态不一致
            self.test_running = False
            
            # 更新UI状态为停止中
            self.test_status_var = "停止中"
            self.test_status_label.setText(self.test_status_var)
            self.test_status_label.setStyleSheet("color: orange")
            self.log_message("[性能测试] 正在停止测试...")
            
            # 停止时禁用性能测试模式
            if hasattr(self.device, 'serial_controller'):
                self.device.serial_controller.performance_test_mode = False
            
            # 确保测试线程状态被正确重置
            if hasattr(self, 'test_thread'):
                self.test_thread = None
            
            # 直接更新UI状态为完成，确保UI能正确响应
            def stop_update_ui():
                # 强制更新UI状态为完成
                self.test_status_var = "完成"
                self.test_status_label.setText(self.test_status_var)
                self.test_status_label.setStyleSheet("color: green")
                self.start_test_btn.setEnabled(True)
                self.stop_test_btn.setEnabled(False)
            
            # 使用QTimer.singleShot在主线程中更新UI
            QTimer.singleShot(100, stop_update_ui)
    
    def _run_performance_test(self, interval, count):
        """性能测试线程函数"""
        total_time_ms = 0
        success = True
        error_msg = ""
        
        try:
            # 记录开始时间（使用更精确的perf_counter）
            start_time = time.perf_counter()
            
            # 预计算间隔时间（毫秒转秒）
            target_interval = interval / 1000.0
            
            # 复用params字典（减少内存分配）
            params = {'pitch': 0.0, 'heading': 0.0}
            
            # 获取测试类型
            test_type = self.test_type_combo.currentText()
            
            # 循环发送N次指令，根据测试类型发送不同命令
            for i in range(count):
                # 检查是否需要停止测试
                if hasattr(self, 'test_stop_event') and self.test_stop_event and self.test_stop_event.is_set():
                    # 只在停止时记录一次日志
                    self.log_message("[性能测试] 测试已停止")
                    break
                
                # 交替使用0°和30°角度（优化计算）
                angle = 0.0 if (i & 1) == 0 else 30.0
                
                # 更新参数（复用字典，减少内存分配）
                params['pitch'] = angle
                params['heading'] = angle
                
                # 记录当前循环开始时间
                loop_start = time.perf_counter()
                
                # 发送命令，并检查返回结果
                success_flag, msg = self.device.send_command(test_type, params)
                if not success_flag and hasattr(self, 'test_stop_event') and not self.test_stop_event.is_set():
                    # 只在第一次失败时记录日志，避免日志过多
                    if i == 0:
                        self.log_message(f"[性能测试] 发送命令失败: {msg}")
                    success = False
                    error_msg = msg
                    break
                
                # 等待指定间隔（最后一次发送后不等待）
                if i < count - 1:
                    # 计算已用时间
                    elapsed = time.perf_counter() - loop_start
                    # 计算需要等待的时间，确保总间隔接近目标间隔
                    wait_time = target_interval - elapsed
                    # 如果计算的等待时间为正，则等待相应时间
                    if wait_time > 0:
                        time.sleep(wait_time)
            
            # 计算总耗时（使用perf_counter获取更精确的时间）
            end_time = time.perf_counter()
            total_time_ms = int((end_time - start_time) * 1000)
            
        except Exception as e:
            # 处理异常
            success = False
            error_msg = str(e)
            self.log_message(f"[性能测试] 测试异常: {error_msg}")
        finally:
            # 无论测试成功还是失败，都要禁用性能测试模式
            if hasattr(self.device, 'serial_controller'):
                self.device.serial_controller.performance_test_mode = False
            
            # 确保test_running标志被正确重置
            if hasattr(self, 'test_running'):
                self.test_running = False
            
            # 确保测试线程引用被清除
            if hasattr(self, 'test_thread'):
                self.test_thread = None
            
            # 批量更新UI，减少UI刷新次数
            def update_ui():
                try:
                    if success:
                        self.test_status_var = "完成"
                        self.test_status_label.setText(self.test_status_var)
                        self.test_status_label.setStyleSheet("color: green")
                        self.total_time_var = str(total_time_ms)
                        self.total_time_label.setText(self.total_time_var)
                        
                        # 只在测试成功完成时记录日志
                        self.log_message(f"[性能测试] 测试完成，总耗时: {total_time_ms}ms")
                        self.log_message(f"[性能测试] 平均间隔: {total_time_ms / count:.2f}ms/次")
                        self.log_message(f"[性能测试] 目标间隔: {interval}ms")
                    else:
                        self.test_status_var = "异常"
                        self.test_status_label.setText(self.test_status_var)
                        self.test_status_label.setStyleSheet("color: red")
                    
                    # 恢复按钮状态
                    self.start_test_btn.setEnabled(True)
                    self.stop_test_btn.setEnabled(False)
                except Exception as e:
                    # 防止UI更新时出现异常导致状态无法恢复
                    print(f"[DEBUG] UI更新异常: {e}")
                    # 强制恢复按钮状态
                    self.start_test_btn.setEnabled(True)
                    self.stop_test_btn.setEnabled(False)
            
            # 使用QTimer.singleShot在主线程中更新UI，尝试多次确保更新
            QTimer.singleShot(0, update_ui)
            # 添加一个额外的延迟更新，确保UI能正确更新
            QTimer.singleShot(50, update_ui)
            # 添加第三次更新，确保在所有情况下都能更新UI
            QTimer.singleShot(100, update_ui)
    
    def update_ui(self):
        """更新UI显示"""
        # 检查设备是否已连接
        if not self.device:
            return
            
        # 检查并更新性能测试状态
        if hasattr(self, 'test_running'):
            # 检查测试线程状态
            thread_alive = False
            if hasattr(self, 'test_thread') and self.test_thread:
                thread_alive = self.test_thread.is_alive()
            
            # 只有当测试线程已结束，但test_running仍然为True时，才强制更新UI状态
            # 移除了超时检测导致的强制终止，让测试线程自行完成
            if self.test_running and not thread_alive:
                # 强制更新UI状态
                self.test_running = False
                self.test_status_var = "完成"
                self.test_status_label.setText(self.test_status_var)
                self.test_status_label.setStyleSheet("color: green")
                self.start_test_btn.setEnabled(True)
                self.stop_test_btn.setEnabled(False)
                # 清除测试线程引用
                if hasattr(self, 'test_thread'):
                    self.test_thread = None
            
            # 保留超时日志，但不强制终止测试
            if self.test_running:
                if hasattr(self, 'test_start_time') and hasattr(self, 'test_timeout'):
                    elapsed_time = (time.time() - self.test_start_time) * 1000  # 转换为毫秒
                    if elapsed_time > self.test_timeout:
                        # 只记录超时日志，不终止测试
                        self.log_message(f"[性能测试] 测试已运行{elapsed_time:.0f}ms，超过预估时间{self.test_timeout:.0f}ms")
        
        # 更新设备状态信息
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
        
        # 只更新变化的数据，减少UI刷新开销
        for label_text, info_key in status_mapping.items():
            if label_text in self.status_labels and info_key in device_info:
                try:
                    value = device_info[info_key]
                    display_text = ""
                    
                    # 根据不同类型进行格式化
                    if isinstance(value, (int, float)):
                        # 根据字段类型进行不同的格式化
                        if info_key in ["runtime"]:  # ACU运行时间，以秒为单位，直接显示整数
                            display_text = f"{int(value)}s"
                        elif info_key in ["gps_lng", "gps_lat", "pitch", "roll", "heading", "beam_off_axis", "beam_heading"]:  # 角度类，保留2位小数
                            display_text = f"{value:.2f}"
                        elif info_key in ["rx_freq", "tx_freq", "rx_lo", "tx_lo"]:  # 频率类，保留2位小数
                            display_text = f"{value:.2f}"
                        elif info_key in ["comm_status"]:  # 通信状态，显示整数
                            display_text = f"{int(value)}"
                        elif info_key in ["gps_alt"]:  # 高度类，保留1位小数
                            display_text = f"{value:.1f}m"
                        else:  # 其他数值，保留1位小数
                            display_text = f"{value:.1f}"
                    else:  # 字符串类型，直接显示
                        display_text = str(value)
                    
                    # 只在值变化时更新UI，减少刷新开销
                    current_text = self.status_labels[label_text].text()
                    if current_text != display_text:
                        self.status_labels[label_text].setText(display_text)
                except Exception as e:
                    # 防止数据异常导致UI更新失败
                    print(f"[DEBUG] 更新{label_text}时出错: {e}")
                    # 只在当前显示不是N/A时才更新，减少不必要的刷新
                    current_text = self.status_labels[label_text].text()
                    if current_text != "N/A":
                        self.status_labels[label_text].setText("N/A")
    
    def log_message(self, message):
        """记录日志消息"""
        self.log_text.append(message)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    @pyqtSlot()
    def clear_log(self):
        """清除日志"""
        self.log_text.clear()
    
    def destroy(self):
        """清理资源，停止测试"""
        print("[DEBUG] QAFD01_QS_UI: 清理资源，停止测试")
        
        # 停止性能测试
        if self.test_running:
            self.stop_performance_test()
        
        # 调用父类的destroy方法
        super().destroy()
