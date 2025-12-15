import threading
import queue
from PyQt5.QtCore import pyqtSignal, QObject
from common.device_base import DeviceBase
from devices.afd01_qs_protocol import AFD01_QSProtocol

# 添加数据到达信号类
class DataSignal(QObject):
    # 定义数据到达信号
    data_updated = pyqtSignal()

class AFD01_QS_Device(DeviceBase):
    """AFD01_QS设备的具体实现类"""
    
    def __init__(self, serial_controller):
        protocol = AFD01_QSProtocol()
        super().__init__(serial_controller, protocol)
        # 保持向后兼容，同时支持基类的communication_controller和子类的serial_controller
        self.serial_controller = self.communication_controller
        
        # 创建数据到达信号实例
        self.data_signal = DataSignal()
        
        # 命令映射
        self._cmd_name_map = {
            0x01: "数据上报", 0x02: "搜星参数", 0x03: "发射开关", 
            0x05: "对星模式", 0x07: "发射波束配置", 
            0x09: "接收波束配置", 0x0A: "收发波束同时控制", 
            0x08: "TLE星历配置",
            0xA0: "天线状态上报"
        }
        
        # 设备状态信息
        self.device_info = {
            "gps_lock_status": "N/A",
            "gps_lng": "N/A",
            "gps_lat": "N/A",
            "gps_alt": "N/A",
            "rx_freq": "N/A",
            "tx_freq": "N/A",
            "rx_lo": "N/A",
            "tx_lo": "N/A",
            "tx_enable": "N/A",
            "tx_polarization": "N/A",
            "pitch": "N/A",
            "roll": "N/A",
            "heading": "N/A",
            "beam_off_axis": "N/A",
            "beam_heading": "N/A",
            "tracking_mode": "N/A",
            "comm_status": "N/A",
            "runtime": "N/A"
        }
        
        # 支持的频率范围和默认值
        self.supported_rx_freq = [19798.0]  # 默认接收频点
        self.supported_tx_freq = [29788.0]  # 默认发射频点
        
        # 接收数据缓冲区
        self.buffer = bytearray()
        
        # 添加线程锁，保护device_info字典的并发访问
        self.device_info_lock = threading.Lock()
    
    def on_received_data(self, data: bytearray):
        """处理接收到的数据，优化后的高效解析逻辑"""
        # 将新数据添加到缓冲区
        self.buffer.extend(data)
        
        # 持续解析缓冲区中的数据
        while len(self.buffer) >= 4:  # 至少需要帧头+命令+长度高+长度低
            # 1. 查找帧头 (0x55)
            frame_start_index = -1
            for i in range(len(self.buffer)):
                if self.buffer[i] == 0x55:
                    frame_start_index = i
                    break
            
            # 如果没有找到帧头，清空缓冲区并退出
            if frame_start_index == -1:
                self.buffer.clear()
                break
            
            # 如果帧头不在缓冲区起始位置，移除前面的无效数据
            if frame_start_index > 0:
                self.buffer = self.buffer[frame_start_index:]
                continue
            
            # 2. 提取命令类型和数据长度（2字节，高字节先）
            command = self.buffer[1]
            data_length = (self.buffer[2] << 8) | self.buffer[3]
            
            # 数据长度合理性检查
            if data_length > 1024:  # 设置最大长度限制
                self.buffer.pop(0)  # 丢弃当前帧头，继续查找下一个
                continue
            
            # 3. 计算完整帧长度：帧头(1)+命令(1)+长度(2)+数据(N)+CRC(2)
            total_frame_length = 6 + data_length  # 6 = 1(帧头) + 1(命令) + 2(长度) + 2(CRC)
            
            # 4. 检查是否有完整的帧数据
            if len(self.buffer) < total_frame_length:
                break
            
            # 5. 提取单个完整帧
            frame = bytes(self.buffer[:total_frame_length])
            
            try:
                # 6. 解析帧数据
                parsed, msg = self.protocol.parse_response(frame)
                
                if parsed is not None:
                    # 成功解析一帧
                    cmd = parsed[0]
                    # 放入响应队列
                    self.response_queue.put((cmd, parsed))
                    # 提取数据并更新设备信息
                    data_dict = self.protocol.extract_data(cmd, parsed[1])
                    if data_dict:
                        # 更新设备信息
                        self._update_device_info(data_dict)
                        # 记录日志
                        if 'display_text' in data_dict:
                            self.serial_controller.log("    " + data_dict['display_text'])
                        # 触发数据更新信号
                        self.data_signal.data_updated.emit()
                    
                    # 记录日志（只在调试模式下记录详细日志）
                    if hasattr(self.serial_controller, 'debug_mode') and self.serial_controller.debug_mode:
                        self.serial_controller.log(f"<<< 收到: {frame.hex().upper()} [{msg}]")
                    
                    # 7. 从缓冲区中移除已解析的完整帧
                    self.buffer = self.buffer[total_frame_length:]
                else:
                    # 解析失败，丢弃当前帧头，继续查找下一个
                    self.buffer.pop(0)
            except Exception as e:
                # 发生异常，丢弃当前帧头，继续查找下一个
                self.buffer.pop(0)
    
    def _update_device_info(self, data_dict: dict):
        """更新设备信息"""
        with self.device_info_lock:
            for key, value in data_dict.items():
                if key in self.device_info:
                    self.device_info[key] = value
    
    def send_command(self, command_name: str, params=None) -> tuple:
        """发送命令到设备"""
        if not self.serial_controller.is_connected():
            return False, "设备未连接"
        
        try:
            frame = None
            
            if command_name == "数据上报":
                # 构建参数字典，符合协议规范
                report_params = {
                    'snr': 0.0,  # 信噪比默认值
                    'baseband_status': 0x00,  # 基带状态默认值：电源关闭, 未锁定
                    'power_save_status': 0x00,  # 节能状态默认值
                    'reboot_cmd': 0x00  # 重启命令默认值：正常工作
                }
                
                # 如果提供了参数，更新默认值
                if params:
                    if isinstance(params, dict):
                        report_params.update(params)
                    elif isinstance(params, float):
                        # 兼容旧的调用方式，忽略周期参数，使用默认值
                        pass
                        
                frame = self.protocol.build_report_data_cmd(report_params)
            elif command_name == "搜星参数":
                if params and isinstance(params, dict):
                    satellite_lng = params.get('satellite_lng', 118.2)
                    polarization = params.get('polarization', 0)
                    rx_freq = params.get('rx_freq', 19798.0)
                    tx_freq = params.get('tx_freq', 29788.0)
                    frame = self.protocol.build_satellite_param_cmd(satellite_lng, polarization, rx_freq, tx_freq)
            elif command_name == "发射开关":
                enable = 0
                if isinstance(params, dict):
                    enable = params.get('enable', 0)
                elif isinstance(params, int):
                    enable = params
                frame = self.protocol.build_tx_enable_cmd(enable)
            elif command_name == "对星模式":
                mode = 0
                if isinstance(params, dict):
                    mode = params.get('mode', 0)
                elif isinstance(params, int):
                    mode = params
                frame = self.protocol.build_tracking_mode_cmd(mode)
            elif command_name == "发射波束配置":
                if params and isinstance(params, dict):
                    pitch = params.get('pitch', 0.0)
                    heading = params.get('heading', 0.0)
                    frame = self.protocol.build_beam_control_cmd(0x07, pitch, heading)
            elif command_name == "接收波束配置":
                if params and isinstance(params, dict):
                    pitch = params.get('pitch', 0.0)
                    heading = params.get('heading', 0.0)
                    frame = self.protocol.build_beam_control_cmd(0x09, pitch, heading)
            elif command_name == "收发波束同时控制":
                if params and isinstance(params, dict):
                    pitch = params.get('pitch', 0.0)
                    heading = params.get('heading', 0.0)
                    frame = self.protocol.build_beam_control_cmd(0x0A, pitch, heading)
            elif command_name == "TLE星历配置":
                if params and isinstance(params, dict):
                    tle0 = params.get('tle0', '')
                    tle1 = params.get('tle1', '')
                    frame = self.protocol.build_tle_cmd(tle0, tle1)
            else:
                return False, f"不支持的命令: {command_name}"
            
            if frame:
                # 发送命令
                self.serial_controller.send_data(frame)
                # 记录日志（只在调试模式下记录详细日志）
                if hasattr(self.serial_controller, 'debug_mode') and self.serial_controller.debug_mode:
                    self.serial_controller.log(f">>> 发送: {frame.hex().upper()}")
                return True, f"命令发送成功: {command_name}"
            else:
                return False, f"命令构建失败: {command_name}"
        except Exception as e:
            return False, f"发送命令时发生错误: {str(e)}"
    
    def query_device_info(self) -> dict:
        """查询设备信息"""
        with self.device_info_lock:
            # 返回深拷贝，避免外部修改影响内部状态
            device_info_copy = self.device_info.copy()
            
            # 添加数据验证和格式化，确保数据类型一致
            for key, value in device_info_copy.items():
                # 尝试将数值字符串转换为数值类型
                if isinstance(value, str):
                    try:
                        # 尝试转换为浮点数
                        device_info_copy[key] = float(value)
                    except (ValueError, TypeError):
                        # 如果转换失败，保持原字符串
                        pass
            
            return device_info_copy
    
    def get_supported_commands(self) -> list:
        """获取设备支持的命令列表"""
        return [
            "数据上报", "搜星参数", "发射开关", "对星模式", 
            "发射波束配置", "接收波束配置", "收发波束同时控制", "TLE星历配置"
        ]
    
    def get_supported_rx_freq(self) -> list:
        """获取支持的接收频率列表"""
        return self.supported_rx_freq
    
    def get_supported_tx_freq(self) -> list:
        """获取支持的发射频率列表"""
        return self.supported_tx_freq
