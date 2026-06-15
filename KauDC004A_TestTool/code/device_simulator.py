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
ADDR_TX_BEAM_QUERY = 0x5F

# RX设备命令地址
ADDR_RX_BEAM = 0x90
ADDR_RX_ENABLE = 0x91
ADDR_RX_POLARIZATION = 0x93
ADDR_RX_STATUS_QUERY = 0x9C
ADDR_RX_BEAM_QUERY = 0x9F


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


def _default_state():
    return {"pol": 0, "en_row": 0, "freq_code": 0, "beam_v": 0, "beam_h": 0}


def record_config(states, sub_id, addr, payload):
    """根据配置帧更新某子阵状态（用于查询指令2回读）。payload 为去掉末尾 ADDR 的数据区。"""
    st = states.setdefault(sub_id, _default_state())
    if addr in (ADDR_TX_BEAM, ADDR_RX_BEAM) and len(payload) >= 4:
        # 波束: [FREQ, BeamV[11:4], BeamV[3:0]|BeamH[11:8], BeamH[7:0]]
        st["freq_code"] = payload[0]
        st["beam_v"] = (payload[1] << 4) | ((payload[2] >> 4) & 0x0F)
        st["beam_h"] = ((payload[2] & 0x0F) << 8) | payload[3]
    elif addr in (ADDR_TX_ENABLE, ADDR_RX_ENABLE) and len(payload) >= 2:
        # 使能: [EN_H, EN_L, 0xFF, 0xFF]
        st["en_row"] = (payload[0] << 8) | payload[1]
    elif addr in (ADDR_TX_POLARIZATION, ADDR_RX_POLARIZATION) and len(payload) >= 4:
        # 极化: [0,0,0,POL]
        st["pol"] = payload[3] & 0x01


def build_beam_query_response(device_id_byte, sub_id, states, ret_addr):
    """构造查询指令2（波束参数）返回帧（V2.2，数据长度17）。"""
    st = states.get(sub_id, _default_state())
    pol = st["pol"] & 0x01
    en = st["en_row"] & 0xFFFF
    freq = st["freq_code"] & 0xFF
    bv = st["beam_v"] & 0xFFF
    bh = st["beam_h"] & 0xFFF
    payload16 = bytes(
        [
            0, 0, 0, 0, 0, 0, 0,  # D127~D72 Rev
            pol,                   # D71~D64, bit0=POL
            (en >> 8) & 0xFF, en & 0xFF,  # EN_ROW
            0xFF, 0xFF,            # 0xFFFF 固定
            freq,                  # FREQ
            (bv >> 4) & 0xFF,      # BeamV[11:4]
            ((bv & 0x0F) << 4) | ((bh >> 8) & 0x0F),  # BeamV[3:0]|BeamH[11:8]
            bh & 0xFF,             # BeamH[7:0]
        ]
    )
    data = payload16 + bytes([ret_addr])  # 17 字节
    frame = FRAME_HEADER + bytes([device_id_byte]) + bytes([len(data)]) + data
    return frame + bytes([calculate_checksum(frame)])


class TXSimulator:
    """TX设备模拟器"""

    def __init__(self, port, ids=None):
        self.port = port
        self.ids = list(ids) if ids else [1]  # 本总线模拟的子阵 ID 集合
        self.states = {}  # 每个子阵的波束/极化/使能配置（用于查询指令2回读）
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
        target = parsed["device_id"]
        masked = target & 0x7F  # 去掉 +128 位

        # ID=0 广播：所有子阵记录配置但不返回
        if target == 0:
            if addr not in (ADDR_STATUS_QUERY, ADDR_TX_BEAM_QUERY):
                for sid in self.ids:
                    record_config(self.states, sid, addr, parsed["payload"])
            print(f"[{timestamp()}] [TX] 广播(ID=0)，不返回")
            return
        # 仅响应本总线上存在的子阵 ID
        if masked not in self.ids:
            return

        if addr == ADDR_STATUS_QUERY:
            response = self.build_status_response(masked)
            print(f"[{timestamp()}] [TX] ID={masked} 状态回复: {response.hex().upper()}")
        elif addr == ADDR_TX_BEAM_QUERY:
            response = build_beam_query_response(masked, masked, self.states, ADDR_TX_BEAM_QUERY)
            print(f"[{timestamp()}] [TX] ID={masked} 波束参数回复: {response.hex().upper()}")
        else:
            record_config(self.states, masked, addr, parsed["payload"])  # 记录配置
            response = frame  # 配置 echo 原样返回
            print(f"[{timestamp()}] [TX] ID={masked} Echo: {response.hex().upper()}")

        self.ser.write(response)

    def build_status_response(self, sub_id):
        """构建 TX 状态查询回复（V2.1）。电压/温度随 sub_id 变化，便于区分多子阵。"""
        # V2.1 TX 状态回复 (7字节payload，末尾为指令号 0x5C)
        # [Rev][STATE][SysVcc][SysTemp][ATT_Tc][MCU_VER][指令号0x5C]
        vcc = (115 + sub_id) & 0xFF  # 11.6V, 11.7V, ... 按 ID 递增
        temp = (115 + sub_id) & 0xFF  # 36°C, 37°C, ... (值-80)
        payload = bytes([0x01, 0x01, vcc, temp, 0x01, 0x02, ADDR_STATUS_QUERY])

        frame_data = FRAME_HEADER + bytes([sub_id]) + bytes([len(payload)]) + payload
        return frame_data + bytes([calculate_checksum(frame_data)])


class RXSimulator:
    """RX设备模拟器"""

    def __init__(self, port, ids=None):
        self.port = port
        self.ids = list(ids) if ids else [1]  # 本总线模拟的子阵 ID 集合
        self.states = {}  # 每个子阵的波束/极化/使能配置（用于查询指令2回读）
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
        target = parsed["device_id"]
        masked = target & 0x7F

        if target == 0:
            if addr not in (ADDR_RX_STATUS_QUERY, ADDR_RX_BEAM_QUERY):
                for sid in self.ids:
                    record_config(self.states, sid, addr, parsed["payload"])
            print(f"[{timestamp()}] [RX] 广播(ID=0)，不返回")
            return
        if masked not in self.ids:
            return

        if addr == ADDR_RX_STATUS_QUERY:
            response = self.build_rx_status_response(masked)
            print(f"[{timestamp()}] [RX] ID={masked} 状态回复: {response.hex().upper()}")
        elif addr == ADDR_RX_BEAM_QUERY:
            response = build_beam_query_response(masked, masked, self.states, ADDR_RX_BEAM_QUERY)
            print(f"[{timestamp()}] [RX] ID={masked} 波束参数回复: {response.hex().upper()}")
        else:
            record_config(self.states, masked, addr, parsed["payload"])
            response = frame
            print(f"[{timestamp()}] [RX] ID={masked} Echo: {response.hex().upper()}")

        self.ser.write(response)

    def build_rx_status_response(self, sub_id):
        """构建 RX 状态查询回复（V2.1，正常校验和）。电压/温度随 sub_id 变化。"""
        # V2.1 RX 状态回复 (6字节payload，末尾为指令号 0x9C，无 STATE 字段)
        # [Rev][SysVcc][SysTemp][ATT_Tc][MCU_VER][指令号0x9C]
        vcc = (115 + sub_id) & 0xFF
        temp = (130 + sub_id) & 0xFF
        payload = bytes([0x4A, vcc, temp, 0x04, 0x02, ADDR_RX_STATUS_QUERY])

        frame_data = FRAME_HEADER + bytes([sub_id]) + bytes([len(payload)]) + payload
        return frame_data + bytes([calculate_checksum(frame_data)])


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

    # 模拟多子阵（演示用，可按需修改）
    sim_ids = [1, 2, 3]
    print(f"模拟子阵 ID: {sim_ids}")
    tx_sim = TXSimulator(tx_port, ids=sim_ids)
    rx_sim = RXSimulator(rx_port, ids=sim_ids)

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
