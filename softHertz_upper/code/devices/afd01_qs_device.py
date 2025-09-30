import threading
import queue
from common.device_base import DeviceBase
from devices.afd01_qs_protocol import AFD01_QSProtocol

class AFD01_QS_Device(DeviceBase):
    """AFD01_QS设备的具体实现类"""
    
    def __init__(self, serial_controller):
        protocol = AFD01_QSProtocol()
        super().__init__(serial_controller, protocol)
        
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
        
    def on_received_data(self, data: bytearray):
        """处理接收到的数据"""
        # 将新数据添加到缓冲区
        self.buffer.extend(data)
        
        # 持续解析缓冲区中的数据
        while len(self.buffer) >= 1:
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
            
            # 2. 检查是否有足够的数据解析长度字段（至少需要4字节：帧头+命令+长度高+长度低）
            if len(self.buffer) < 4:
                break
            
            # 3. 提取命令类型和数据长度（2字节，高字节先）
            command = self.buffer[1]
            data_length = (self.buffer[2] << 8) | self.buffer[3]
            
            # 数据长度合理性检查
            if data_length > 1024:  # 设置最大长度限制
                print(f"afd01 callback [DEBUG] 数据长度不合理: {data_length}，丢弃当前帧头")
                self.buffer.pop(0)  # 丢弃当前帧头，继续查找下一个
                continue
            
            # 4. 计算完整帧长度：帧头(1)+命令(1)+长度(2)+数据(N)+CRC(2)
            total_frame_length = 6 + data_length  # 6 = 1(帧头) + 1(命令) + 2(长度) + 2(CRC)
            
            # 5. 检查是否有完整的帧数据
            if len(self.buffer) < total_frame_length:
                break
            
            # 6. 提取单个完整帧
            frame = bytes(self.buffer[:total_frame_length])
            print(f"afd01 callback [DEBUG] 尝试解析完整帧: {frame.hex().upper()}")
            
            try:
                # 7. 解析帧数据
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
                    
                    # 记录日志
                    self.serial_controller.log(f"<<< 收到: {frame.hex().upper()} [{msg}]")
                    
                    # 8. 从缓冲区中移除已解析的完整帧
                    self.buffer = self.buffer[total_frame_length:]
                else:
                    # 解析失败，丢弃当前帧头，继续查找下一个
                    print(f"afd01 callback [DEBUG] 帧解析失败: {msg}")
                    self.buffer.pop(0)
            except Exception as e:
                # 发生异常，丢弃当前帧头，继续查找下一个
                print(f"afd01 callback [DEBUG] 解析异常: {str(e)}")
                self.buffer.pop(0)
                # 注意：异常发生时不应该尝试移除完整帧长度，因为帧解析失败可能意味着长度计算有误
            # 移除多余的else分支，因为在try-except中已经处理了成功和失败的情况
    
    def _update_device_info(self, data_dict: dict):
        """更新设备信息"""
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
                    frame = self.protocol.build_search_param_cmd(satellite_lng, polarization, rx_freq, tx_freq)
                else:
                    frame = self.protocol.build_search_param_cmd(118.2, 0, 19798.0, 29788.0)
            elif command_name == "发射开关":
                if params and isinstance(params, int):
                    frame = self.protocol.build_tx_enable_cmd(params)
                else:
                    frame = self.protocol.build_tx_enable_cmd(0)
            elif command_name == "对星模式":
                if params and isinstance(params, int):
                    frame = self.protocol.build_tracking_mode_cmd(params)
                else:
                    frame = self.protocol.build_tracking_mode_cmd(0)
            elif command_name == "发射波束配置":
                if params and isinstance(params, dict):
                    pitch = params.get('pitch', 30.5)
                    heading = params.get('heading', 30.5)
                    frame = self.protocol.build_beam_control_cmd(0x07, pitch, heading)
                else:
                    frame = self.protocol.build_beam_control_cmd(0x07, 30.5, 30.5)
            elif command_name == "接收波束配置":
                if params and isinstance(params, dict):
                    pitch = params.get('pitch', 30.5)
                    heading = params.get('heading', 30.5)
                    frame = self.protocol.build_beam_control_cmd(0x09, pitch, heading)
                else:
                    frame = self.protocol.build_beam_control_cmd(0x09, 30.5, 30.5)
            elif command_name == "收发波束同时控制":
                if params and isinstance(params, dict):
                    pitch = params.get('pitch', 30.5)
                    heading = params.get('heading', 30.5)
                    frame = self.protocol.build_beam_control_cmd(0x0A, pitch, heading)
                else:
                    frame = self.protocol.build_beam_control_cmd(0x0A, 30.5, 30.5)
            elif command_name == "TLE星历配置":
                if params and isinstance(params, dict) and 'tle0' in params and 'tle1' in params:
                    frame = self.protocol.build_tle_cmd(params['tle0'], params['tle1'])
                else:
                    # 使用默认的TLE示例数据
                    tle0 = "1 24876U 97035A   25265.46410208  .00000032  00000+0  00000+0 0  9999"
                    tle1 = "2 24876  55.8521 109.0478 0095461  56.3876 304.6077  2.00563039206580"
                    frame = self.protocol.build_tle_cmd(tle0, tle1)
            else:
                return False, "未知命令或参数错误"
            
            # 发送帧
            if frame:
                success, msg = self.serial_controller.send_data(frame)
                return success, msg
            else:
                return False, "命令构建失败"
        except Exception as e:
            return False, f"发送命令时发生错误: {str(e)}"
    
    def query_device_info(self) -> dict:
        """查询设备信息"""
        # AFD01_QS设备会自动上报状态信息，这里直接返回当前的设备信息
        return self.device_info.copy()
    
    def get_supported_commands(self) -> list:
        """获取设备支持的命令列表"""
        return [
            "数据上报", "搜星参数", "发射开关", "对星模式", 
            "发射波束配置", "接收波束配置", "收发波束同时控制", 
            "TLE星历配置"
        ]
    
    def get_supported_rx_freq(self) -> list:
        """获取支持的接收频率列表"""
        return self.supported_rx_freq
    
    def get_supported_tx_freq(self) -> list:
        """获取支持的发射频率列表"""
        return self.supported_tx_freq