import socket
import time
import struct

class DebugProtocolSimulator:
    """DEBUG协议模拟器，用于测试DEBUG设备功能"""
    
    def __init__(self):
        # 协议常量
        self.FRAME_HEADER = b'\xAA\x55'
        self.DEVICE_TYPE = b'\x0D'
        self.CMD_DATA_REPORT = 0x01
        self.FRAME_TAIL = b'\xEE'
    
    def calculate_crc16(self, data):
        """计算CRC16-CCITT校验值"""
        crc = 0xFFFF
        poly = 0x1021
        
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ poly
                else:
                    crc <<= 1
                crc &= 0xFFFF
        
        return crc
    
    def build_data_report(self, timestamp, channel_data):
        """构建数据上报帧"""
        # 命令类型
        command = self.CMD_DATA_REPORT
        
        # 构建数据内容
        data_content = b''
        
        # 时间戳(4字节，小端序)
        data_content += timestamp.to_bytes(4, byteorder='little')
        
        # 通道数量(1字节)
        channel_count = len(channel_data)
        data_content += channel_count.to_bytes(1, byteorder='little')
        
        # 通道数据
        for channel in channel_data:
            # 通道名称(32字节，不足补0)
            channel_name = channel['name'].encode('utf-8', errors='ignore')[:32]
            channel_name += b'\x00' * (32 - len(channel_name))
            
            # 通道数据(4字节float，小端序)
            channel_value = struct.pack('<f', channel['value'])
            
            data_content += channel_name + channel_value
        
        # 数据长度(2字节，小端序)
        data_length = len(data_content)
        data_length_bytes = data_length.to_bytes(2, byteorder='little')
        
        # 构建帧头到数据部分
        frame_part = self.FRAME_HEADER + self.DEVICE_TYPE + bytes([command]) + data_length_bytes + data_content
        
        # 计算校验和
        crc = self.calculate_crc16(frame_part)
        crc_bytes = crc.to_bytes(2, byteorder='little')
        
        # 构建完整帧
        frame = frame_part + crc_bytes + self.FRAME_TAIL
        
        return frame
    
    def send_udp_data(self, host, port, channel_data, count=10, interval=0.1):
        """发送UDP数据"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        try:
            for i in range(count):
                timestamp = int(time.time() * 1000)
                frame = self.build_data_report(timestamp, channel_data)
                sock.sendto(frame, (host, port))
                print(f"发送UDP数据: {frame.hex()}")
                time.sleep(interval)
        finally:
            sock.close()
    
    def send_tcp_data(self, host, port, channel_data, count=10, interval=0.1):
        """发送TCP数据"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        try:
            port_int = int(port)
            sock.connect((host, port_int))
            
            for i in range(count):
                timestamp = int(time.time() * 1000)
                frame = self.build_data_report(timestamp, channel_data)
                sock.sendall(frame)
                print(f"发送TCP数据: {frame.hex()}")
                time.sleep(interval)
        except Exception as e:
            print(f"TCP发送错误: {e}")
        finally:
            sock.close()

# 测试代码
if __name__ == "__main__":
    simulator = DebugProtocolSimulator()
    
    # 模拟通道数据，使用变化的数据
    def get_dynamic_channel_data(i):
        import math
        return [
            {'name': '正弦波', 'value': math.sin(i * 0.1) * 10},
            {'name': '余弦波', 'value': math.cos(i * 0.1) * 10},
            {'name': '方波', 'value': 10 if (i % 10) < 5 else -10},
            {'name': '锯齿波', 'value': (i % 20) - 10}
        ]
    
    # 选择发送方式
    send_mode = input("请选择发送方式 (udp/tcp): ").strip().lower()
    
    if send_mode == "udp":
        host = "127.0.0.1"  # 固定使用本地回环地址
        port = int(input("请输入目标端口 (默认: 8080): ").strip() or "8080")
        count = int(input("请输入发送次数 (默认: 100): ").strip() or "100")
        interval = float(input("请输入发送间隔(秒) (默认: 0.1): ").strip() or "0.1")
        
        print(f"\n开始发送UDP数据到 {host}:{port}")
        for i in range(count):
            channel_data = get_dynamic_channel_data(i)
            simulator.send_udp_data(host, port, channel_data, count=1, interval=interval)
            time.sleep(interval)
        print("UDP数据发送完成")
    
    elif send_mode == "tcp":
        host = "127.0.0.1"  # 固定使用本地回环地址
        port = int(input("请输入目标端口 (默认: 8080): ").strip() or "8080")
        count = int(input("请输入发送次数 (默认: 100): ").strip() or "100")
        interval = float(input("请输入发送间隔(秒) (默认: 0.1): ").strip() or "0.1")
        
        print(f"\n开始发送TCP数据到 {host}:{port}")
        for i in range(count):
            channel_data = get_dynamic_channel_data(i)
            simulator.send_tcp_data(host, port, channel_data, count=1, interval=interval)
            time.sleep(interval)
        print("TCP数据发送完成")
    
    else:
        print("无效的发送方式")
