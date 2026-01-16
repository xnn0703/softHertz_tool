#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试AFD01_QS设备状态更新，验证UI能否正确显示设备状态
"""

import sys
import os
import queue

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devices.afd01_qs_device import AFD01_QS_Device
from devices.afd01_qs_protocol import AFD01_QSProtocol


def test_device_info_update():
    """测试设备信息更新"""
    # 创建设备实例（模拟，不需要真实的串口控制器）
    class MockSerialController:
        def __init__(self):
            self.logs = []
        
        def log(self, message):
            self.logs.append(message)
    
    class MockDevice(AFD01_QS_Device):
        def __init__(self):
            self.serial_controller = MockSerialController()
            self.protocol = AFD01_QSProtocol()
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
            self.buffer = bytearray()
            self.response_queue = queue.Queue()
    
    device = MockDevice()
    
    # 构造一个完整的55A0数据包（天线状态上报）
    # 帧头 + 命令 + 长度(0x002A=42) + 数据(42字节) + CRC
    frame = bytes([
        0x55, 0xA0, 0x00, 0x2A,  # 帧头+命令+长度(42字节)
        # 数据部分（42字节）
        0x01,  # GPS锁定状态
        0x01, 0x23,  # GPS经度 (0x0123 = 291 → 2.91°)
        0x04, 0x56,  # GPS纬度 (0x0456 = 1110 → 11.10°)
        0x00, 0x64,  # GPS高度 (0x0064 = 100 → 100m)
        # 接收频点（4字节float，大端序，需要转换）
        0x44, 0x4A, 0x80, 0x00,  # 19798.0 MHz (转换为小端序)
        # 发射频点（4字节float，大端序）
        0x45, 0x75, 0x40, 0x00,  # 29788.0 MHz
        # 接收本振（4字节float，大端序）
        0x44, 0x4A, 0x80, 0x00,  # 19798.0 MHz
        # 发射本振（4字节float，大端序）
        0x45, 0x75, 0x40, 0x00,  # 29788.0 MHz
        0x01,  # 发射状态（开启）
        0x00,  # 极化方式（左旋）
        0x01, 0x23,  # 俯仰角 (0x0123 = 291 → 2.91°)
        0x00, 0x3C,  # 横滚角 (0x003C = 60 → 0.60°)
        0x01, 0x90,  # 方位角 (0x0190 = 400 → 4.00°)
        0x00, 0x00,  # 波束偏轴角
        0x00, 0x00,  # 波束航向角
        0x00,  # 对星模式（自动）
        0x20,  # 跟踪模式（搜星完成）
        0x01,  # 设备通讯状态
        0x00, 0x00, 0x00, 0x3C,  # ACU运行时间（60秒）
        # CRC校验和（2字节，大端序）
        # 这里的CRC是手动计算的，用于测试
        0x00, 0x00
    ])
    
    # 重新计算CRC校验和
    # 校验范围：命令(1字节) + 数据长度(2字节) + 数据内容(42字节)
    crc_data = frame[1:4+42]
    calculated_crc = 0
    for byte in crc_data:
        calculated_crc += byte
        calculated_crc &= 0xFFFF
    
    # 更新帧的CRC字段
    frame = frame[:-2] + calculated_crc.to_bytes(2, byteorder='big')
    
    print(f"测试数据包: {frame.hex().upper()}")
    print(f"计算的CRC: {calculated_crc:#04x}")
    
    # 模拟接收数据
    device.on_received_data(bytearray(frame))
    
    # 检查设备信息是否正确更新
    print("\n设备信息更新结果:")
    for key, value in device.device_info.items():
        print(f"  {key}: {value} (类型: {type(value).__name__})")
        
        # 验证值是否已从"N/A"更新
        if value == "N/A":
            print(f"    ❌ 错误: {key} 仍然是 N/A")
        elif key != "runtime" and isinstance(value, str) and not isinstance(value, (int, float)):
            # 除了runtime字段外，其他字段应该是数值类型
            if key in ["gps_lock_status", "tx_enable", "tx_polarization", "tracking_mode", "antenna_search_status"]:
                # 这些字段是字符串类型，是正常的
                print(f"    ✅ 正确: {key} 是字符串类型")
            else:
                print(f"    ❌ 错误: {key} 应该是数值类型，实际是 {type(value).__name__}")
        else:
            print(f"    ✅ 正确: {key} 已更新为 {type(value).__name__} 类型")
    
    # 检查是否所有数值字段都已更新
    updated_count = sum(1 for v in device.device_info.values() if v != "N/A")
    total_fields = len(device.device_info)
    
    print(f"\n更新统计: {updated_count}/{total_fields} 个字段已更新")
    
    return updated_count == total_fields


if __name__ == "__main__":
    print("AFD01_QS设备信息更新测试")
    print("=" * 50)
    
    success = test_device_info_update()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ 测试成功: 所有设备状态字段已正确更新")
        sys.exit(0)
    else:
        print("❌ 测试失败: 部分设备状态字段未更新")
        sys.exit(1)
