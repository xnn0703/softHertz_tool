from common.protocol_base import ProtocolBase, CRC16Calculator
import struct

class DebugProtocol(ProtocolBase):
    """DEBUG设备的协议实现"""
    
    # 帧头和帧尾
    FRAME_HEADER = b'\xAA\x55'
    FRAME_TAIL = b'\xEE'
    
    # 设备类型
    DEVICE_TYPE = b'\x0D'
    
    # 命令类型
    CMD_DATA_REPORT = 0x01
    CMD_COMMAND_RESPONSE = 0x02
    CMD_DEBUG_CONTROL = 0x03  # Debug模式控制命令
    
    def build_frame(self, payload: bytes) -> bytes:
        """构建DEBUG设备的数据包帧"""
        # 帧头 + 设备类型 + 命令类型 + 数据长度 + 数据 + 校验和 + 帧尾
        frame_header = self.FRAME_HEADER
        device_type = self.DEVICE_TYPE
        command = payload[0:1]  # 第一个字节是命令类型
        data = payload[1:]  # 剩余部分是数据内容
        data_length = len(data).to_bytes(2, byteorder='little')
        
        # 计算校验和（帧头到数据部分）
        checksum_data = frame_header + device_type + command + data_length + data
        checksum = CRC16Calculator.crc16_ccitt(checksum_data).to_bytes(2, byteorder='little')
        
        # 构建完整帧
        frame = frame_header + device_type + command + data_length + data + checksum + self.FRAME_TAIL
        
        return frame
    
    def parse_response(self, data: bytes) -> tuple:
        """解析DEBUG设备的响应数据包"""
        try:
            # 检查帧头
            if len(data) < 10:
                return None, f"帧长度不足，预期至少10字节，实际{len(data)}字节"
            
            if not data.startswith(self.FRAME_HEADER):
                return None, f"帧头错误，预期AA55，实际{data[:2].hex(' ')}"
            
            # 检查帧尾
            if not data.endswith(self.FRAME_TAIL):
                return None, f"帧尾错误，预期EE，实际{data[-1:].hex(' ')}"
            
            # 提取设备类型
            device_type = data[2:3]
            if device_type != self.DEVICE_TYPE:
                return None, f"设备类型错误，预期0D，实际{device_type.hex(' ')}"
            
            # 提取命令类型
            command = data[3]
            
            # 提取数据长度
            data_length = int.from_bytes(data[4:6], byteorder='little')
            
            # 验证数据长度合理性 (防止恶意数据)
            if data_length > 1024:  # 设置最大数据长度限制
                return None, f"数据长度过大，预期不超过1024字节，实际{data_length}字节"
            
            # 计算预期帧长度
            expected_length = 2 + 1 + 1 + 2 + data_length + 2 + 1  # 帧头+设备类型+命令+数据长度+数据+校验和+帧尾
            if len(data) != expected_length:
                return None, f"帧长度错误，预期{expected_length}字节，实际{len(data)}字节"
            
            # 提取数据部分
            data_part = data[6:6+data_length]
            
            # 验证数据部分长度
            if len(data_part) != data_length:
                return None, f"数据部分长度错误，预期{data_length}字节，实际{len(data_part)}字节"
            
            # 提取并验证校验和
            checksum_start = 6 + data_length
            received_checksum = int.from_bytes(data[checksum_start:checksum_start+2], byteorder='little')
            calculated_checksum = CRC16Calculator.crc16_ccitt(data[:checksum_start])
            
            if received_checksum != calculated_checksum:
                return None, f"校验和错误，预期{calculated_checksum:04X}，实际{received_checksum:04X}"
            
            return (command, data_part), "解析成功"
        except Exception as e:
            return None, f"解析异常: {str(e)}"
    
    def extract_data(self, command, data):
        """从解析后的数据中提取有用信息"""
        result = {}
        try:
            if command == self.CMD_DATA_REPORT:
                # 解析数据上报帧
                # 确保至少包含时间戳(4字节) + 通道数量(1字节)
                if len(data) < 5:
                    result['error'] = f"数据长度不足，预期至少5字节，实际{len(data)}字节"
                    return result
                
                try:
                    # 提取时间戳
                    timestamp = int.from_bytes(data[0:4], byteorder='little')
                except Exception as e:
                    result['error'] = f"时间戳解析错误: {str(e)}"
                    return result
                
                # 提取通道数量
                channel_count = data[4]
                
                # 检查通道数量是否合理(0-16)
                if channel_count < 0 or channel_count > 16:
                    result['error'] = f"通道数量不合理，预期0-16，实际{channel_count}"
                    # 仍然尝试解析可用的通道数据，而不是直接返回错误
                
                # 提取每个通道的数据
                channel_data = []
                offset = 5
                expected_data_length = 5 + (32 + 4) * channel_count
                
                for i in range(channel_count):
                    # 每个通道数据占32字节名称 + 4字节值
                    if offset + 32 + 4 > len(data):
                        # 数据不足，中断循环，但保留已解析的通道数据
                        break
                    
                    try:
                        # 提取通道名称(32字节)
                        channel_name_bytes = data[offset:offset+32]
                        # 找到第一个空字节的位置
                        null_pos = channel_name_bytes.find(b'\x00')
                        if null_pos >= 0:
                            # 只取空字节前的部分
                            channel_name_bytes = channel_name_bytes[:null_pos]
                        # 使用ASCII编码，更适合单片机环境
                        channel_name = channel_name_bytes.decode('ascii', errors='replace').strip()
                        # 替换不可打印字符为下划线
                        channel_name = ''.join(c if c.isprintable() else '_' for c in channel_name)
                        # 如果通道名称为空，使用默认名称
                        if not channel_name:
                            channel_name = f'Channel{i+1}'
                        offset += 32
                        
                        # 提取通道数据(float，小端序)
                        channel_value = struct.unpack('<f', data[offset:offset+4])[0]
                        offset += 4
                        
                        channel_data.append({
                            'name': channel_name,
                            'value': channel_value
                        })
                    except Exception as e:
                        # 单个通道解析失败，继续尝试解析下一个通道
                        result['warning'] = f"通道{i+1}解析错误: {str(e)}"
                        offset += 36  # 跳过当前通道的32字节名称 + 4字节值
                        continue
                
                # 确保结果包含必要的字段，即使通道数据不完整
                result.update({
                    'timestamp': timestamp,
                    'channel_count': channel_count,
                    'channel_data': channel_data,
                    'actual_channel_count': len(channel_data),
                    'display_text': f"数据上报: 预期{channel_count}个通道，实际解析{len(channel_data)}个，时间戳: {timestamp}"
                })
                
            elif command == self.CMD_COMMAND_RESPONSE:
                # 解析命令响应帧
                result.update({
                    'response_code': data[0] if len(data) > 0 else 0,
                    'response_message': data[1:].decode('utf-8', errors='ignore')
                })
            elif command == self.CMD_DEBUG_CONTROL:
                # 解析调试控制响应
                result.update({
                    'debug_mode': data[0] if len(data) > 0 else 0,
                    'status': '成功' if (data[0] == 1 if len(data) > 0 else 0) else '失败'
                })
            else:
                # 未知命令类型
                result.update({
                    'error': f"未知命令类型: {command}",
                    'raw_data': data.hex(' ')
                })
                
        except Exception as e:
            # 捕获所有异常，但仍然返回包含基本信息的结果
            result.update({
                'error': f"数据解析错误: {str(e)}",
                'command': command,
                'data_length': len(data)
            })
        
        return result
    
    def build_data_report(self, timestamp, channel_data):
        """构建数据上报帧"""
        # 时间戳(4字节，小端序)
        timestamp_bytes = timestamp.to_bytes(4, byteorder='little')
        
        # 通道数量(1字节)
        channel_count = len(channel_data).to_bytes(1, byteorder='little')
        
        # 通道数据
        data_bytes = b''
        for channel in channel_data:
            # 通道名称(32字节，不足补0)
            channel_name = channel['name'].encode('utf-8', errors='ignore')[:32]
            channel_name += b'\x00' * (32 - len(channel_name))
            
            # 通道数据(4字节float，小端序)
            channel_value = struct.pack('<f', channel['value'])
            
            data_bytes += channel_name + channel_value
        
        # 构建payload
        payload = self.CMD_DATA_REPORT.to_bytes(1, byteorder='little') + timestamp_bytes + channel_count + data_bytes
        
        # 构建完整帧
        return self.build_frame(payload)
    
    def build_command_response(self, response_code, message=""):
        """构建命令响应帧"""
        # 响应码(1字节)
        response_code_bytes = response_code.to_bytes(1, byteorder='little')
        
        # 响应消息
        message_bytes = message.encode('utf-8', errors='ignore')
        
        # 构建payload
        payload = self.CMD_COMMAND_RESPONSE.to_bytes(1, byteorder='little') + response_code_bytes + message_bytes
        
        # 构建完整帧
        return self.build_frame(payload)
    
    def build_debug_command(self, enable):
        """构建debug模式控制命令帧"""
        # 命令类型 + 启用/禁用标志(1字节)
        payload = self.CMD_DEBUG_CONTROL.to_bytes(1, byteorder='little') + enable.to_bytes(1, byteorder='little')
        
        # 构建完整帧
        return self.build_frame(payload)
