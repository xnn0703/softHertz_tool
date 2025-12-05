import socket
import time
import struct

# 构建DEBUG设备数据帧
class DebugProtocol:
    FRAME_HEADER = b'\xAA\x55'
    FRAME_TAIL = b'\xEE'
    DEVICE_TYPE = b'\x0D'
    CMD_DATA_REPORT = 0x01
    
    @staticmethod
    def crc16_ccitt(data):
        crc = 0xFFFF
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ 0x1021
                else:
                    crc <<= 1
            crc &= 0xFFFF
        return crc
    
    @classmethod
    def build_data_report(cls, timestamp, channel_data):
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
        payload = cls.CMD_DATA_REPORT.to_bytes(1, byteorder='little') + timestamp_bytes + channel_count + data_bytes
        
        # 构建完整帧
        frame_header = cls.FRAME_HEADER
        device_type = cls.DEVICE_TYPE
        command = payload[0:1]  # 第一个字节是命令类型
        data = payload[1:]  # 剩余部分是数据内容
        data_length = len(data).to_bytes(2, byteorder='little')
        
        # 计算校验和（帧头到数据部分）
        checksum_data = frame_header + device_type + command + data_length + data
        checksum = cls.crc16_ccitt(checksum_data).to_bytes(2, byteorder='little')
        
        # 构建完整帧
        frame = frame_header + device_type + command + data_length + data + checksum + cls.FRAME_TAIL
        
        return frame

# 测试TCP客户端发送数据
def test_tcp_client():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(('127.0.0.1', 8080))
        print("已连接到TCP服务器")
        
        timestamp = 0
        while True:
            # 生成模拟数据
            channel_data = [
                {'name': 'Channel1', 'value': 10 + 5 * (timestamp % 100) / 100.0},
                {'name': 'Channel2', 'value': 20 + 3 * (timestamp % 150) / 150.0},
                {'name': 'Channel3', 'value': 30 + 7 * (timestamp % 200) / 200.0}
            ]
            
            # 构建数据帧
            frame = DebugProtocol.build_data_report(timestamp, channel_data)
            
            # 发送数据
            sock.sendall(frame)
            print(f"发送数据帧: {frame.hex()}")
            
            timestamp += 10
            time.sleep(0.1)
    except ConnectionRefusedError:
        print("无法连接到TCP服务器，请确保DEBUG设备UI已启动并处于TCP服务器模式")
    except KeyboardInterrupt:
        print("测试结束")
    finally:
        sock.close()

# 测试UDP发送数据
def test_udp():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        timestamp = 0
        while True:
            # 生成模拟数据
            channel_data = [
                {'name': 'Channel1', 'value': 10 + 5 * (timestamp % 100) / 100.0},
                {'name': 'Channel2', 'value': 20 + 3 * (timestamp % 150) / 150.0},
                {'name': 'Channel3', 'value': 30 + 7 * (timestamp % 200) / 200.0}
            ]
            
            # 构建数据帧
            frame = DebugProtocol.build_data_report(timestamp, channel_data)
            
            # 发送数据
            sock.sendto(frame, ('127.0.0.1', 8080))
            print(f"发送UDP数据帧: {frame.hex()}")
            
            timestamp += 10
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("测试结束")
    finally:
        sock.close()

if __name__ == "__main__":
    print("DEBUG设备测试工具")
    print("1. TCP客户端测试")
    print("2. UDP测试")
    choice = input("请选择测试类型: ")
    
    if choice == "1":
        test_tcp_client()
    elif choice == "2":
        test_udp()
    else:
        print("无效选择")
