from common.device_base import DeviceBase
from devices.debug_protocol import DebugProtocol

class DebugDevice(DeviceBase):
    """DEBUG设备类，处理通信和数据解析"""
    
    def __init__(self, communication_controller):
        protocol = DebugProtocol()
        super().__init__(communication_controller, protocol)
        
        # 命令映射
        self._cmd_name_map = {
            0x01: "数据上报",
            0x02: "命令响应"
        }
        
        # 设备状态信息
        self.device_info = {
            "connection_status": "N/A",
            "channel_count": 0,
            "last_update_time": "N/A"
        }
        
        # 通道数据历史记录
        self.channel_data_history = {}
        
        # 支持的通信方式
        self.supported_communication = ["serial", "tcp", "udp"]
        
        # 接收数据缓冲区
        self.buffer = bytearray()
        
        # 数据回调函数，用于UI更新
        self.data_callback = None
    
    def on_received_data(self, data: bytearray):
        """处理接收到的数据"""
        # 将新数据添加到缓冲区
        self.buffer.extend(data)
        
        # 持续解析缓冲区中的数据
        while len(self.buffer) >= 10:  # 最小帧长度：帧头(2) + 设备类型(1) + 命令(1) + 数据长度(2) + 校验和(2) + 帧尾(1)
            # 查找帧头
            frame_start = self.buffer.find(b'\xAA\x55')
            if frame_start < 0:
                # 没有找到帧头，清空缓冲区
                self.buffer.clear()
                break
            
            # 移除帧头之前的无效数据
            if frame_start > 0:
                self.buffer = self.buffer[frame_start:]
                continue
            
            # 检查帧尾
            frame_end = self.buffer.find(b'\xEE')
            if frame_end < 0:
                # 没有找到完整的帧，等待更多数据
                break
            
            # 提取完整帧
            frame = bytes(self.buffer[:frame_end + 1])
            
            # 解析帧
            try:
                parsed_result, msg = self.protocol.parse_response(frame)
                if parsed_result:
                    command, data_part = parsed_result
                    
                    # 提取数据
                    extracted_data = self.protocol.extract_data(command, data_part)
                    
                    # 更新设备状态
                    self._update_device_status(extracted_data)
                    
                    # 调用数据回调函数
                    if self.data_callback:
                        self.data_callback(extracted_data)
                    
                    # 记录日志
                    self.communication_controller.log(f"<<< 解析结果: {extracted_data.get('display_text', '未知数据')}")
                
                # 移除已解析的帧
                self.buffer = self.buffer[frame_end + 1:]
                
            except Exception as e:
                # 解析失败，移除当前帧头，继续查找下一个
                self.communication_controller.log(f"[解析错误] {str(e)}")
                self.buffer = self.buffer[2:]
    
    def _update_device_status(self, data):
        """更新设备状态信息"""
        if 'channel_count' in data:
            self.device_info['channel_count'] = data['channel_count']
        
        if 'timestamp' in data:
            self.device_info['last_update_time'] = data['timestamp']
        
        if 'channel_data' in data:
            # 更新通道数据历史
            for channel in data['channel_data']:
                channel_name = channel['name']
                if channel_name not in self.channel_data_history:
                    self.channel_data_history[channel_name] = []
                
                # 限制历史记录长度（最多保存1000个数据点）
                self.channel_data_history[channel_name].append({
                    'timestamp': data['timestamp'],
                    'value': channel['value']
                })
                
                if len(self.channel_data_history[channel_name]) > 1000:
                    self.channel_data_history[channel_name].pop(0)
    
    def send_command(self, command_name: str, params=None) -> bool:
        """发送命令到设备"""
        try:
            # DEBUG设备主要用于接收数据，发送命令功能可以根据需要扩展
            return True, "命令发送成功"
        except Exception as e:
            return False, str(e)
    
    def query_device_info(self) -> dict:
        """查询设备信息"""
        return self.device_info
    
    def get_supported_commands(self) -> list:
        """获取设备支持的命令列表"""
        return list(self._cmd_name_map.values())
    
    def set_data_callback(self, callback):
        """设置数据回调函数，用于UI更新"""
        self.data_callback = callback
    
    def get_channel_history(self, channel_name):
        """获取通道历史数据"""
        return self.channel_data_history.get(channel_name, [])
    
    def get_all_channels(self):
        """获取所有通道名称"""
        return list(self.channel_data_history.keys())
    
    def clear_history(self):
        """清除历史数据"""
        self.channel_data_history.clear()
