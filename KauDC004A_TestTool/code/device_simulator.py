#!/usr/bin/env python3
"""
AFDT1024/AFDR1024 设备模拟器
用于测试上位机功能
TX模拟器监听COM10，RX模拟器监听COM11
"""

import serial
import serial.tools.list_ports
import threading
import time
import sys
import datetime

# 帧头定义
FRAME_HEADER = b"\x50\x53\x41"

# TX设备命令地址
ADDR_TX_BEAM = 0x50
ADDR_TX_ENABLE = 0x51
ADDR_TX_POLARIZATION = 0x53
ADDR_PA_ENABLE = 0x56
ADDR_STATUS_QUERY = 0x5C

# RX设备命令地址
ADDR_RX_BEAM = 0x90
ADDR_RX_ENABLE = 0x91
ADDR_RX_POLARIZATION = 0x93
ADDR_RX_STATUS_QUERY = 0x9C


def calculate_checksum(data):
    """计算校验和（低8位求和）"""
    return sum(data) & 0xFF


def timestamp():
    """返回当前时间戳字符串，格式与上位机log一致"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def parse_frame(data):
    """解析帧，返回(device_id, length, payload, addr)"""
    if len(data) < 6:
        return None

    header = data[:3]
    if header != FRAME_HEADER:
        return None

    device_id = data[3]
    length = data[4]
    payload_and_addr = data[5:-1]  # 去掉checksum
    checksum_recv = data[-1]

    if len(payload_and_addr) != length:
        return None

    addr = payload_and_addr[-1]
    payload = payload_and_addr[:-1]

    return {
        "device_id": device_id,
        "length": length,
        "payload": payload,
        "addr": addr,
        "checksum_recv": checksum_recv,
        "raw": data,
    }


class TXSimulator:
    """TX设备模拟器"""

    def __init__(self, port, device_id=1):
        self.port = port
        self.device_id = device_id
        self.running = False
        self.ser = None

    def start(self):
        """启动模拟器"""
        try:
            self.ser = serial.Serial(self.port, 460800, timeout=0.1)
            self.running = True
            print(f"[{timestamp()}] [TX模拟器] 启动，监听 {self.port}")
            self.run()
        except Exception as e:
            print(f"[{timestamp()}] [TX模拟器] 启动失败: {e}")

    def stop(self):
        """停止模拟器"""
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()
        print(f"[{timestamp()}] [TX模拟器] 已停止")

    def run(self):
        """主循环"""
        buffer = bytearray()

        while self.running:
            try:
                # 读取数据 - 真实设备响应us级别，这里用无阻塞读取
                if self.ser.in_waiting > 0:
                    chunk = self.ser.read(self.ser.in_waiting)
                    buffer.extend(chunk)

                    # 处理帧
                    while len(buffer) >= 3:
                        if buffer[:3] != FRAME_HEADER:
                            buffer.pop(0)
                            continue

                        # 尝试解析完整帧
                        if len(buffer) >= 6:
                            length = buffer[4]
                            total_len = 5 + length + 1

                            if total_len > 263:
                                buffer.clear()
                                continue

                            if len(buffer) >= total_len:
                                frame = bytes(buffer[:total_len])
                                del buffer[:total_len]

                                # 处理收到的帧（真实设备处理时间约10-100us）
                                self.handle_frame(frame)
                            else:
                                break
                        else:
                            break
                else:
                    # 无数据时短暂休眠，避免CPU空转（真实设备无延迟）
                    time.sleep(0.0001)  # 100us
            except Exception as e:
                print(f"[{timestamp()}] [TX模拟器] 错误: {e}")
                time.sleep(0.1)

    def handle_frame(self, frame):
        """处理收到的帧"""
        print(f"[{timestamp()}] [TX] 收到: {frame.hex().upper()}")

        parsed = parse_frame(frame)
        if not parsed:
            print(f"[{timestamp()}] [TX] 帧解析失败")
            return

        addr = parsed["addr"]

        # 根据地址处理
        if addr == ADDR_STATUS_QUERY:
            # 状态查询回复
            response = self.build_status_response()
            print(f"[{timestamp()}] [TX] 发送状态回复: {response.hex().upper()}")
        else:
            # Echo回复
            response = frame
            print(f"[{timestamp()}] [TX] 发送Echo: {response.hex().upper()}")

        self.ser.write(response)

    def build_status_response(self):
        """构建TX状态查询回复"""
        # TX状态回复格式 (5字节payload)
        # [Rev][state][SysVcc][SysTemp][ATT_TC]
        # 注意：状态查询回复没有addr字段！
        # Rev=0x01, state=0x77, Vcc=11.9V(0x77), Temp=39°C(0x77-80=39), ATT_TC=0x01
        payload = bytes([0x01, 0x77, 0x77, 0x77, 0x01])

        # 构建帧（不包含checksum）
        # 注意：length字段等于payload长度，没有addr
        frame_data = (
            FRAME_HEADER
            + bytes([self.device_id])
            + bytes([len(payload)])  # length = 5，payload长度
            + payload
        )
        checksum = calculate_checksum(frame_data)

        return frame_data + bytes([checksum])


class RXSimulator:
    """RX设备模拟器"""

    def __init__(self, port, device_id=1):
        self.port = port
        self.device_id = device_id
        self.running = False
        self.ser = None

    def start(self):
        """启动模拟器"""
        try:
            self.ser = serial.Serial(self.port, 460800, timeout=0.1)
            self.running = True
            print(f"[{timestamp()}] [RX模拟器] 启动，监听 {self.port}")
            self.run()
        except Exception as e:
            print(f"[{timestamp()}] [RX模拟器] 启动失败: {e}")

    def stop(self):
        """停止模拟器"""
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()
        print(f"[{timestamp()}] [RX模拟器] 已停止")

    def run(self):
        """主循环"""
        buffer = bytearray()

        while self.running:
            try:
                # 读取数据 - 真实设备响应us级别，这里用无阻塞读取
                if self.ser.in_waiting > 0:
                    chunk = self.ser.read(self.ser.in_waiting)
                    buffer.extend(chunk)

                    # 处理帧
                    while len(buffer) >= 3:
                        if buffer[:3] != FRAME_HEADER:
                            buffer.pop(0)
                            continue

                        # 尝试解析完整帧
                        if len(buffer) >= 6:
                            length = buffer[4]
                            total_len = 5 + length + 1

                            if total_len > 263:
                                buffer.clear()
                                continue

                            if len(buffer) >= total_len:
                                frame = bytes(buffer[:total_len])
                                del buffer[:total_len]

                                # 处理收到的帧（真实设备处理时间约10-100us）
                                self.handle_frame(frame)
                            else:
                                break
                        else:
                            break
                else:
                    # 无数据时短暂休眠，避免CPU空转（真实设备无延迟）
                    time.sleep(0.0001)  # 100us
            except Exception as e:
                print(f"[{timestamp()}] [RX模拟器] 错误: {e}")
                time.sleep(0.1)

    def handle_frame(self, frame):
        """处理收到的帧"""
        print(f"[{timestamp()}] [RX] 收到: {frame.hex().upper()}")

        parsed = parse_frame(frame)
        if not parsed:
            print(f"[{timestamp()}] [RX] 帧解析失败")
            return

        addr = parsed["addr"]

        # 根据地址处理
        if addr == ADDR_RX_STATUS_QUERY:
            # RX状态查询回复（带校验和bug）
            response = self.build_rx_status_response_with_bug()
            print(f"[{timestamp()}] [RX] 发送状态回复(含bug): {response.hex().upper()}")
        else:
            # Echo回复
            response = frame
            print(f"[{timestamp()}] [RX] 发送Echo: {response.hex().upper()}")

        self.ser.write(response)

    def build_rx_status_response_with_bug(self):
        """构建RX状态查询回复（带校验和bug：不包含mcu_ver）"""
        # Rev=0x4A, Vcc=11.5V(0x73), Temp=14°C(0x8E), ATT_TC=0x04, MCU_VER=0x02
        payload = bytes([0x4A, 0x73, 0x8E, 0x04, 0x02])

        # 构建帧（不包含checksum）- 状态查询回复没有addr字段
        frame_data = (
            FRAME_HEADER + bytes([self.device_id]) + bytes([len(payload)]) + payload
        )

        # 设备端bug：校验和计算时不包含mcu_ver（payload的最后一个字节）
        # 正常计算: sum(frame_data) & 0xFF
        # bug计算: sum(frame_data[:-1]) & 0xFF  (不包含mcu_ver)
        checksum = calculate_checksum(frame_data[:-1])

        return frame_data + bytes([checksum])


def list_com_ports():
    """列出可用串口"""
    ports = serial.tools.list_ports.comports()
    if ports:
        print("可用串口:")
        for p in ports:
            print(f"  {p.device} - {p.description}")
    else:
        print("未找到可用串口")
    return [p.device for p in ports]


def main():
    print("=" * 50)
    print("AFDT1024/AFDR1024 设备模拟器")
    print("=" * 50)

    # 列出可用串口
    list_com_ports()
    print()

    # 默认端口
    tx_port = "COM10"
    rx_port = "COM11"

    # 如果命令行参数指定了端口
    if len(sys.argv) >= 3:
        tx_port = sys.argv[1]
        rx_port = sys.argv[2]
    elif len(sys.argv) >= 2:
        tx_port = sys.argv[1]

    print(f"TX模拟器端口: {tx_port}")
    print(f"RX模拟器端口: {rx_port}")
    print()
    print("按 Ctrl+C 停止模拟器")
    print("=" * 50)

    # 创建模拟器
    tx_sim = TXSimulator(tx_port, device_id=1)
    rx_sim = RXSimulator(rx_port, device_id=1)

    # 启动线程
    tx_thread = threading.Thread(target=tx_sim.start, daemon=True)
    rx_thread = threading.Thread(target=rx_sim.start, daemon=True)

    try:
        tx_thread.start()
        rx_thread.start()

        # 保持运行
        while True:
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n正在停止模拟器...")
    finally:
        tx_sim.stop()
        rx_sim.stop()


if __name__ == "__main__":
    main()
