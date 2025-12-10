import sys
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, 
    QTableWidget, QTableWidgetItem, QPushButton, QComboBox, 
    QLineEdit, QTextEdit, QLabel, QMessageBox, QScrollArea
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QFont
from ui.qt_base_ui import QBaseUI

class QKauDC004AUI(QBaseUI):
    """KauDC004A设备的PyQt5 UI实现"""
    
    def __init__(self, parent=None, device=None):
        super().__init__(parent, device)
        
        # 保存定时器ID
        self.status_timer = None
        
        # 创建设备特定的UI组件
        self.create_specific_widgets()
        
        # 定时更新设备状态
        self._schedule_status_update()
    
    def create_specific_widgets(self):
        """创建设备特定的UI组件"""
        # 状态表格
        self.status_table = QTableWidget(8, 2)
        self.status_table.setHorizontalHeaderLabels(["参数", "值"])
        self.status_table.horizontalHeader().setStretchLastSection(True)
        
        # 填充初始参数行
        parameters = ["版本", "温度", "TxLO", "RxLO", "Tx衰减", "Rx衰减", "锁定状态"]
        for row, param in enumerate(parameters):
            self.status_table.setItem(row, 0, QTableWidgetItem(param))
            self.status_table.setItem(row, 1, QTableWidgetItem("N/A"))
        
        # 添加状态表格到滚动布局
        status_group = QGroupBox("设备状态")
        status_layout = QVBoxLayout()
        status_layout.addWidget(self.status_table)
        status_group.setLayout(status_layout)
        self.scroll_layout.addWidget(status_group)
        
        # 本振设置区域
        lo_group = QGroupBox("本振设置")
        lo_layout = QGridLayout()
        
        # 发射本振设置
        self.txlo_label = QLabel("发射本振:")
        self.txlo_cb = QComboBox()
        self.txlo_cb.addItems(self.device.get_supported_txlo_values())
        self.txlo_btn = QPushButton("设置发射本振")
        self.txlo_btn.clicked.connect(self.set_txlo)
        
        lo_layout.addWidget(self.txlo_label, 0, 0)
        lo_layout.addWidget(self.txlo_cb, 0, 1)
        lo_layout.addWidget(self.txlo_btn, 0, 2)
        
        # 接收本振设置
        self.rxlo_label = QLabel("接收本振:")
        self.rxlo_cb = QComboBox()
        self.rxlo_cb.addItems(self.device.get_supported_rxlo_values())
        self.rxlo_btn = QPushButton("设置接收本振")
        self.rxlo_btn.clicked.connect(self.set_rxlo)
        
        lo_layout.addWidget(self.rxlo_label, 1, 0)
        lo_layout.addWidget(self.rxlo_cb, 1, 1)
        lo_layout.addWidget(self.rxlo_btn, 1, 2)
        
        lo_group.setLayout(lo_layout)
        self.scroll_layout.addWidget(lo_group)
        
        # 命令发送区域
        cmd_group = QGroupBox("命令发送")
        cmd_layout = QHBoxLayout()
        
        # 命令选择
        cmd_values = [cmd for cmd in self.device.get_supported_commands() 
                      if cmd not in ["设置发射本振", "设置接收本振"]]
        self.cmd_cb = QComboBox()
        self.cmd_cb.addItems(cmd_values)
        self.cmd_cb.setCurrentText("本振查询")
        self.cmd_cb.currentTextChanged.connect(self.update_input_type)
        
        # 参数输入
        self.param_entry = QLineEdit()
        self.param_entry.setPlaceholderText("参数值")
        self.param_entry.setVisible(False)
        
        # 发送按钮
        self.send_btn = QPushButton("发送指令")
        self.send_btn.clicked.connect(self.send_command)
        
        cmd_layout.addWidget(self.cmd_cb)
        cmd_layout.addWidget(self.param_entry)
        cmd_layout.addWidget(self.send_btn)
        
        cmd_group.setLayout(cmd_layout)
        self.scroll_layout.addWidget(cmd_group)
        
        # 设备操作区域
        ops_group = QGroupBox("设备操作")
        ops_layout = QHBoxLayout()
        
        # 设备查询按钮
        self.device_query_btn = QPushButton("设备查询")
        self.device_query_btn.clicked.connect(self.query_device)
        
        # 清除数据按钮
        self.clear_btn = QPushButton("清除数据")
        self.clear_btn.clicked.connect(self.clear_data)
        
        ops_layout.addWidget(self.device_query_btn)
        ops_layout.addWidget(self.clear_btn)
        ops_group.setLayout(ops_layout)
        self.scroll_layout.addWidget(ops_group)
        
        # 日志区域
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.NoWrap)
        
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        self.scroll_layout.addWidget(log_group)
    
    @pyqtSlot()
    def update_input_type(self, cmd):
        """根据选择的命令更新输入类型"""
        if cmd in ("发射衰减设置", "接收衰减设置"):
            self.param_entry.setVisible(True)
        else:
            self.param_entry.setVisible(False)
    
    @pyqtSlot()
    def set_txlo(self):
        """设置发射本振"""
        # 多重防御性检查
        if not self.device or not hasattr(self.device, 'is_connected'):
            QMessageBox.critical(self, "错误", "设备对象不存在")
            return
        
        if not self.device.is_connected():
            QMessageBox.warning(self, "未连接", "请先打开连接")
            return
        
        try:
            txlo_value = self.txlo_cb.currentText()
            success, msg = self.device.send_command("设置发射本振", txlo_value)
            if success:
                self.log_message(msg)
            else:
                QMessageBox.critical(self, "发送错误", msg)
        except Exception as e:
            error_msg = f"发送命令时发生错误: {str(e)}"
            QMessageBox.critical(self, "错误", error_msg)
    
    @pyqtSlot()
    def set_rxlo(self):
        """设置接收本振"""
        # 多重防御性检查
        if not self.device or not hasattr(self.device, 'is_connected'):
            QMessageBox.critical(self, "错误", "设备对象不存在")
            return
        
        if not self.device.is_connected():
            QMessageBox.warning(self, "未连接", "请先打开连接")
            return
        
        try:
            rxlo_value = self.rxlo_cb.currentText()
            success, msg = self.device.send_command("设置接收本振", rxlo_value)
            if success:
                self.log_message(msg)
            else:
                QMessageBox.critical(self, "发送错误", msg)
        except Exception as e:
            error_msg = f"发送命令时发生错误: {str(e)}"
            QMessageBox.critical(self, "错误", error_msg)
    
    @pyqtSlot()
    def send_command(self):
        """发送命令"""
        # 多重防御性检查
        if not self.device or not hasattr(self.device, 'is_connected'):
            QMessageBox.critical(self, "错误", "设备对象不存在")
            return
        
        if not self.device.is_connected():
            QMessageBox.warning(self, "未连接", "请先打开连接")
            return
        
        try:
            cmd = self.cmd_cb.currentText()
            param = None
            if cmd in ("发射衰减设置", "接收衰减设置"):
                param = self.param_entry.text().strip()
                if not param:
                    QMessageBox.warning(self, "参数为空", "请输入参数值")
                    return
            
            success, msg = self.device.send_command(cmd, param)
            if success:
                self.log_message(msg)
            else:
                QMessageBox.critical(self, "发送错误", msg)
        except Exception as e:
            error_msg = f"发送命令时发生错误: {str(e)}"
            QMessageBox.critical(self, "错误", error_msg)
    
    @pyqtSlot()
    def query_device(self):
        """查询设备信息"""
        if not self.device.is_connected():
            QMessageBox.warning(self, "未连接", "请先打开连接")
            return
        
        self.device.query_device_info()
        self.log_message("开始查询设备信息...")
    
    @pyqtSlot()
    def clear_data(self):
        """清除数据"""
        # 清除日志
        self.log_text.clear()
        
        # 重置状态表格
        for row in range(self.status_table.rowCount()):
            if self.status_table.item(row, 0):
                param = self.status_table.item(row, 0).text()
                self.status_table.setItem(row, 1, QTableWidgetItem("N/A"))
        
        # 记录日志
        self.log_message("已清除所有数据和缓存")
    
    def _schedule_status_update(self):
        """安排下一次状态更新"""
        if self.status_timer is not None:
            self.status_timer.stop()
            self.status_timer.deleteLater()
        
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_device_status_timer)
        self.status_timer.start(500)
    
    @pyqtSlot()
    def update_device_status_timer(self):
        """定时更新设备状态"""
        if self.device.is_connected():
            device_info = self.device.device_info
            
            # 更新状态表格，添加异常处理
            try:
                # 版本
                if self.status_table.item(0, 0):
                    self.status_table.setItem(0, 1, QTableWidgetItem(f"{device_info['version']}"))
                
                # 温度
                if self.status_table.item(1, 0):
                    self.status_table.setItem(1, 1, QTableWidgetItem(f"{device_info['temperature']}°C"))
                
                # TxLO
                if self.status_table.item(2, 0):
                    self.status_table.setItem(2, 1, QTableWidgetItem(f"{device_info['txlo']} MHz"))
                
                # RxLO
                if self.status_table.item(3, 0):
                    self.status_table.setItem(3, 1, QTableWidgetItem(f"{device_info['rxlo']} MHz"))
                
                # Tx衰减
                if self.status_table.item(4, 0):
                    tx_attenuation = device_info.get('tx_attenuation', 'N/A')
                    try:
                        tx_attenuation = float(tx_attenuation)
                        tx_attenuation_str = f"{tx_attenuation:.1f} dB"
                    except (ValueError, TypeError):
                        tx_attenuation_str = f"{tx_attenuation} dB"
                    self.status_table.setItem(4, 1, QTableWidgetItem(tx_attenuation_str))
                
                # Rx衰减
                if self.status_table.item(5, 0):
                    rx_attenuation = device_info.get('rx_attenuation', 'N/A')
                    try:
                        rx_attenuation = float(rx_attenuation)
                        rx_attenuation_str = f"{rx_attenuation:.1f} dB"
                    except (ValueError, TypeError):
                        rx_attenuation_str = f"{rx_attenuation} dB"
                    self.status_table.setItem(5, 1, QTableWidgetItem(rx_attenuation_str))
                
                # 锁定状态
                if self.status_table.item(6, 0):
                    self.status_table.setItem(6, 1, QTableWidgetItem(device_info.get('lock_status', '未知')))
            except Exception as e:
                print(f"[DEBUG] QKauDC004AUI: 更新设备状态时出错: {e}")
    
    def log_message(self, msg):
        """在日志区域显示消息"""
        self.log_text.append(msg)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    def destroy(self):
        """清理资源，停止定时器"""
        print("[DEBUG] QKauDC004AUI: 清理资源，停止定时器")
        
        # 停止状态更新定时器
        if self.status_timer:
            self.status_timer.stop()
            self.status_timer.deleteLater()
            self.status_timer = None
        
        # 调用父类的destroy方法
        super().destroy()
