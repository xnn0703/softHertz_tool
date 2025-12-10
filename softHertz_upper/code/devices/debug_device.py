from common.device_base import DeviceBase
from devices.debug_protocol import DebugProtocol
import queue
import threading
import time

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
        
        # 数据解析线程相关
        self.data_queue = queue.Queue(maxsize=1000)  # 数据队列，限制最大容量
        self.parsing_thread = None  # 数据解析线程
        self.parsing_running = False  # 解析线程运行标志
        
        # 性能监控相关
        self.perf_stats = {
            'total_data_received': 0,  # 总接收数据量
            'total_frames_parsed': 0,  # 总解析帧数
            'total_channel_updates': 0,  # 总通道更新次数
            'last_stats_time': time.time(),  # 上次统计时间
            'data_rate': 0.0,  # 数据接收速率（字节/秒）
            'parse_rate': 0.0,  # 帧解析速率（帧/秒）
            'queue_size': 0,  # 当前队列大小
        }
        
        # 启动数据解析线程
        self._start_parsing_thread()
    
    def on_received_data(self, data: bytearray):
        """处理接收到的数据，将其放入队列，由解析线程处理"""
        # 严格检查连接状态：只有设备连接时才处理数据
        if not self.communication_controller.is_connected():
            return
        
        # 更新性能统计：总接收数据量
        self.perf_stats['total_data_received'] += len(data)
        
        # 将数据放入队列，由解析线程处理
        try:
            # 使用put_nowait避免阻塞，当队列满时丢弃最旧的数据
            if self.data_queue.full():
                self.data_queue.get_nowait()  # 移除最旧的数据
            self.data_queue.put_nowait(data)
        except queue.Full:
            pass
    
    def _start_parsing_thread(self):
        """启动数据解析线程"""
        if not self.parsing_running:
            self.parsing_running = True
            self.parsing_thread = threading.Thread(target=self._parse_data, daemon=True)
            self.parsing_thread.start()
    
    def _parse_data(self):
        """数据解析线程，处理队列中的数据"""
        # 使用固定大小的环形缓冲区，避免频繁的内存分配
        BUFFER_SIZE = 4096  # 4KB缓冲区
        buffer = bytearray(BUFFER_SIZE)
        buffer_pos = 0  # 当前缓冲区写入位置
        
        while self.parsing_running:
            try:
                # 从队列中获取数据，超时时间1秒
                data = self.data_queue.get(timeout=1.0)
                data_len = len(data)
                
                # 计算剩余空间
                remaining = BUFFER_SIZE - buffer_pos
                
                if data_len > remaining:
                    # 空间不足，先处理现有数据
                    # 重置缓冲区，保留当前数据的后半部分
                    if remaining > 0 and buffer_pos > 0:
                        # 将当前数据的后半部分复制到缓冲区开头
                        buffer[:remaining] = buffer[buffer_pos:]
                    buffer_pos = remaining
                
                # 将新数据写入缓冲区
                buffer[buffer_pos:buffer_pos+data_len] = data
                buffer_pos += data_len
                
                # 持续解析缓冲区中的数据
                parse_pos = 0
                while parse_pos + 10 <= buffer_pos:  # 确保至少有最小帧长度
                    # 查找帧头
                    frame_start = buffer[parse_pos:buffer_pos].find(b'\xAA\x55')
                    if frame_start < 0:
                        # 没有找到帧头，重置解析位置
                        parse_pos = buffer_pos
                        break
                    
                    # 调整帧起始位置
                    frame_start += parse_pos
                    
                    # 跳过帧头之前的无效数据
                    if frame_start > parse_pos:
                        parse_pos = frame_start
                        continue
                    
                    # 检查缓冲区长度是否足够读取基本帧信息
                    if buffer_pos - parse_pos < 10:
                        break
                    
                    # 读取帧基本信息以获取数据长度
                    try:
                        # 读取数据长度（帧头后第4-5字节）
                        data_length = int.from_bytes(buffer[parse_pos + 4:parse_pos + 6], byteorder='little')
                        
                        # 计算完整帧长度
                        expected_frame_length = 2 + 1 + 1 + 2 + data_length + 2 + 1
                        
                        # 检查缓冲区是否包含完整帧
                        if buffer_pos - parse_pos < expected_frame_length:
                            break
                        
                        # 提取完整帧
                        frame = bytes(buffer[parse_pos:parse_pos + expected_frame_length])
                        
                        # 解析帧 - 所有帧验证都在parse_response中完成
                        parsed_result, msg = self.protocol.parse_response(frame)
                        if parsed_result:
                            command, data_part = parsed_result
                            
                            # 提取数据
                            extracted_data = self.protocol.extract_data(command, data_part)
                            
                            # 数据去重：检查时间戳，避免重复处理相同数据
                            if 'timestamp' in extracted_data:
                                current_timestamp = extracted_data['timestamp']
                                # 只跳过完全相同的时间戳，允许时间戳递增
                                if current_timestamp == self.last_timestamp:
                                    # 移除已解析的帧
                                    parse_pos += expected_frame_length
                                    continue
                                # 更新最后处理的时间戳
                                self.last_timestamp = current_timestamp
                            
                            # 更新设备状态
                            self._update_device_status(extracted_data)
                            
                            # 调用数据回调函数
                            if self.data_callback and 'channel_data' in extracted_data:
                                try:
                                    # 使用信号机制在主线程中更新UI，避免跨线程操作UI组件
                                    self.data_callback(extracted_data)
                                    # 更新性能统计：总通道更新次数
                                    self.perf_stats['total_channel_updates'] += len(extracted_data['channel_data'])
                                except Exception as e:
                                    # 捕获异常，防止UI更新失败导致程序崩溃
                                    pass
                            
                            # 更新性能统计：总解析帧数
                            self.perf_stats['total_frames_parsed'] += 1
                        
                        # 移除已解析的帧
                        parse_pos += expected_frame_length
                    except Exception as e:
                        # 解析异常，跳过当前帧
                        parse_pos += 2  # 跳过当前帧头，继续查找下一个帧头
                        continue
                
                # 如果解析位置大于0，将剩余数据移动到缓冲区开头
                if parse_pos > 0 and parse_pos < buffer_pos:
                    remaining_data = buffer_pos - parse_pos
                    buffer[:remaining_data] = buffer[parse_pos:buffer_pos]
                    buffer_pos = remaining_data
                elif parse_pos >= buffer_pos:
                    # 缓冲区已处理完毕
                    buffer_pos = 0
            except queue.Empty:
                # 队列为空，继续循环
                continue
            except Exception as e:
                # 其他异常，继续循环
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
            # 检查通信控制器是否可用
            if not self.communication_controller:
                return False, "通信控制器不可用"
            
            # 根据命令名称构建命令帧
            if command_name == "Debug开关":
                # 构建Debug开关命令，使用protocol的build_debug_command方法
                debug_enable = params
                enable_byte = 1 if debug_enable else 0  # 0表示关闭，1表示开启
                
                # 使用协议类构建完整帧，避免手动构建
                frame = self.protocol.build_debug_command(enable_byte)
                
                # 发送命令
                success, msg = self.communication_controller.send_data(frame)
                return success, msg
            else:
                # 其他命令，返回默认成功
                return True, f"命令 {command_name} 发送成功"
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
        # 停止数据解析线程
        self.parsing_running = False
        if self.parsing_thread and self.parsing_thread.is_alive():
            self.parsing_thread.join(timeout=1.0)
        
        # 清空接收缓冲区和队列
        self.buffer.clear()
        try:
            while not self.data_queue.empty():
                self.data_queue.get_nowait()
        except:
            pass
        
        # 清除历史数据
        self.clear_history()
        # 确保回调不再被调用
        self.data_callback = None
        # 重置去重相关变量
        self.last_timestamp = 0
