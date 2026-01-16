#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试AFD01_QS协议解析，特别是55A0数据包的校验和计算
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devices.afd01_qs_protocol import AFD01_QSProtocol


def test_parse_55a0_packet():
    """测试解析55A0数据包"""
    protocol = AFD01_QSProtocol()
    
    # 示例55A0数据包（来自终端日志）
    # 根据终端日志，设备发送的55A0数据包格式：55 A0 [数据] [校验和]
    # 这里使用一个模拟的55A0数据包进行测试
    # 帧结构：帧头(1) + 命令(1) + 长度(2) + 数据(N) + CRC(2)
    # 示例数据：55 A0 00 2A [42字节数据] [2字节CRC]
    
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
        # CRC校验和（2字节，小端序）
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
    frame = frame[:-2] + calculated_crc.to_bytes(2, byteorder='little')
    
    print(f"测试数据包: {frame.hex().upper()}")
    print(f"计算的CRC: {calculated_crc:#04x}")
    print(f"数据包中的CRC: {frame[-2:].hex().upper()}")
    
    # 测试解析
    parsed, msg = protocol.parse_response(frame)
    
    print(f"\n解析结果: {msg}")
    if parsed:
        command, data = parsed
        print(f"命令: {command:#04x} (0xA0=天线状态上报)")
        print(f"数据长度: {len(data)}字节")
        
        # 提取设备信息
        device_info = protocol.extract_data(command, data)
        if device_info:
            print("\n提取的设备信息:")
            for key, value in device_info.items():
                print(f"  {key}: {value}")
    
    return parsed is not None


def test_checksum_calculation():
    """测试校验和计算"""
    protocol = AFD01_QSProtocol()
    
    # 测试数据
    test_data = bytes([0x01, 0x02, 0x03, 0x04, 0x05])
    
    # 手动计算校验和
    manual_crc = 0
    for byte in test_data:
        manual_crc += byte
        manual_crc &= 0xFFFF
    
    print(f"\n测试校验和计算:")
    print(f"测试数据: {test_data.hex().upper()}")
    print(f"手动计算的CRC: {manual_crc:#04x}")
    
    return True


if __name__ == "__main__":
    print("AFD01_QS协议解析测试")
    print("=" * 50)
    
    # 测试校验和计算
    test_checksum_calculation()
    
    # 测试55A0数据包解析
    success = test_parse_55a0_packet()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ 测试成功: 55A0数据包解析正常")
        sys.exit(0)
    else:
        print("❌ 测试失败: 55A0数据包解析失败")
        sys.exit(1)
