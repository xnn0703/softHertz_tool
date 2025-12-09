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
        
        # 数据去重相关
        self.last_timestamp = 0  # 记录最后处理的时间戳，用于去重
        self.last_processed_data = None  # 记录最后处理的数据，用于去重
    
    def on_received_data(self, data: bytearray):
        """处理接收到的数据，并将解析结果存储到日志"""
        # 严格检查连接状态：只有设备连接时才处理数据
        if not self.communication_controller.is_connected():
            return
        
        # 将新数据添加到缓冲区
        self.buffer.extend(data)
        
        # 记录原始接收到的数据
        self.communication_controller.log(f"<<< 接收到数据: {data.hex(' ')}")
        
        # 持续解析缓冲区中的数据
        while len(self.buffer) >= 10:  # 最小帧长度：帧头(2) + 设备类型(1) + 命令(1) + 数据长度(2) + 校验和(2) + 帧尾(1)
            # 查找帧头
            frame_start = self.buffer.find(b'\xAA\x55')
            if frame_start < 0:
                # 没有找到帧头，清空缓冲区
                self.communication_controller.log(f"[解析错误] 未找到帧头，清空缓冲区")
                self.buffer.clear()
                break
            
            # 移除帧头之前的无效数据
            if frame_start > 0:
                invalid_data = bytes(self.buffer[:frame_start])
                self.communication_controller.log(f"[解析错误] 帧头前有无效数据: {invalid_data.hex(' ')}")
                self.buffer = self.buffer[frame_start:]
                continue
            
            # 检查缓冲区长度是否足够读取基本帧信息
            if len(self.buffer) < 10:
                # 数据不足，等待更多数据
                break
            
            # 读取帧基本信息（不依赖帧尾）
            try:
                # 帧结构：AA55 + 设备类型(1) + 命令(1) + 数据长度(2) + 数据 + 校验和(2) + EE
                device_type = self.buffer[2]
                command = self.buffer[3]
                data_length = int.from_bytes(self.buffer[4:6], byteorder='little')
                
                # 计算完整帧长度
                # 帧头(2) + 设备类型(1) + 命令(1) + 数据长度(2) + 数据(data_length) + 校验和(2) + 帧尾(1)
                expected_frame_length = 2 + 1 + 1 + 2 + data_length + 2 + 1
                
                # 检查缓冲区是否包含完整帧
                if len(self.buffer) < expected_frame_length:
                    # 数据不足，等待更多数据
                    break
                
                # 提取完整帧
                frame = bytes(self.buffer[:expected_frame_length])
                
                # 检查帧尾
                if not frame.endswith(b'\xEE'):
                    # 帧尾错误，跳过当前帧
                    self.communication_controller.log(f"[解析错误] 帧尾错误，预期EE，实际{frame[-1:].hex(' ')}，跳过当前帧")
                    # 从缓冲区移除当前帧头，继续查找下一个帧头
                    self.buffer = self.buffer[2:]
                    continue
                
                # 解析帧
                parsed_result, msg = self.protocol.parse_response(frame)
                if parsed_result:
                    command, data_part = parsed_result
                    
                    # 提取数据
                    extracted_data = self.protocol.extract_data(command, data_part)
                    
                    # 数据去重：检查时间戳，避免重复处理相同数据
                    if 'timestamp' in extracted_data:
                        current_timestamp = extracted_data['timestamp']
                        # 如果是相同的时间戳，跳过处理
                        if current_timestamp <= self.last_timestamp:
                            # 移除已解析的帧
                            self.buffer = self.buffer[expected_frame_length:]
                            continue
                        # 更新最后处理的时间戳
                        self.last_timestamp = current_timestamp
                    
                    # 更新设备状态
                    self._update_device_status(extracted_data)
                    
                    # 调用数据回调函数
                    if self.data_callback and 'channel_data' in extracted_data:
                        self.data_callback(extracted_data)
                    
                    # 记录完整解析结果
                    if 'channel_data' in extracted_data:
                        # 构建更清晰的通道数据记录
                        channel_info = []
                        for channel in extracted_data['channel_data']:
                            channel_info.append(f"{channel['name']}: {channel['value']:.2f}")
                        channel_str = ', '.join(channel_info)
                        self.communication_controller.log(f"<<< 解析成功: 时间戳={extracted_data['timestamp']}, 通道数={extracted_data['channel_count']}, 通道数据=[{channel_str}]")
                    else:
                        self.communication_controller.log(f"<<< 解析成功: {extracted_data}")
                else:
                    # 解析失败，记录帧数据
                    self.communication_controller.log(f"[解析错误] {msg}，帧数据: {frame.hex(' ')}")
                
                # 移除已解析的帧
                self.buffer = self.buffer[expected_frame_length:]
                
            except Exception as e:
                # 解析失败，记录异常和帧数据
                self.communication_controller.log(f"[解析异常] {str(e)}")
                # 从缓冲区移除当前帧头，继续查找下一个帧头
                self.buffer = self.buffer[2:]
                continue
    
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
    
    def close(self):
        """关闭设备连接，清理资源"""
        # 清空接收缓冲区
        self.buffer.clear()
        # 清除历史数据
        self.clear_history()
        # 确保回调不再被调用
        self.data_callback = None
        # 重置去重相关变量
        self.last_timestamp = 0
        self.last_processed_data = None
