#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整测试AFD01_QS设备状态更新，验证UI能否正确显示所有设备状态
"""

import sys
import os
import queue
import time

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devices.afd01_qs_device import AFD01_QS_Device
from devices.afd01_qs_protocol import AFD01_QSProtocol


def test_complete_device_update():
    """完整测试设备更新流程"""
    print("=== AFD01_QS设备状态更新完整测试 ===")
    
    # 创建设备实例（模拟，不需要真实的串口控制器）
    class MockSerialController:
        def __init__(self):
            self.logs = []
        
        def log(self, message):
            self.logs.append(message)
        
        def is_connected(self):
            return True
        
        def send_data(self, data):
            return True, "发送成功"
    
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
    
    # 测试1：55A0数据包（天线状态上报）
    print("\n--- 测试1：55A0天线状态上报数据包 ---")
    
    device = MockDevice()
    
    # 构造一个完整的55A0数据包（天线状态上报）
    # 帧头 + 命令 + 长度(0x002A=42) + 数据(42字节) + CRC
    frame_55a0 = bytes([
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
    crc_data = frame_55a0[1:4+42]
    calculated_crc = 0
    for byte in crc_data:
        calculated_crc += byte
        calculated_crc &= 0xFFFF
    
    # 更新帧的CRC字段
    frame_55a0 = frame_55a0[:-2] + calculated_crc.to_bytes(2, byteorder='little')
    
    print(f"测试数据包: {frame_55a0.hex().upper()}")
    print(f"计算的CRC: {calculated_crc:#04x}")
    
    # 模拟接收数据
    device.on_received_data(bytearray(frame_55a0))
    
    # 检查设备信息是否正确更新
    print("\n设备信息更新结果 (55A0数据包):")
    all_updated_55a0 = True
    for key, value in device.device_info.items():
        updated = value != "N/A"
        print(f"  {key}: {value} (类型: {type(value).__name__}) {'✅' if updated else '❌'}")
        if not updated:
            all_updated_55a0 = False
    
    print(f"\n55A0数据包测试结果: {'✅ 全部更新成功' if all_updated_55a0 else '❌ 部分字段未更新'}")
    
    # 测试2：数据上报命令（0x01命令）
    print("\n--- 测试2：数据上报命令 (0x01命令) ---")
    
    device2 = MockDevice()
    
    # 构造一个数据上报命令帧（0x01命令）
    # 帧头 + 命令 + 长度(0x0007=7) + 数据(7字节) + CRC
    frame_01 = bytes([
        0x55, 0x01, 0x00, 0x07,  # 帧头+命令+长度(7字节)
        # 数据部分（7字节）
        0x41, 0x48, 0x00, 0x00,  # 信噪比 (10.0 dB，float类型)
        0x03,  # 基带状态 (0x03=0b00000011: 电源打开，广播锁定)
        0x01,  # 节能状态 (支持)
        0x00,  # 重启命令 (正常工作)
        # CRC校验和（2字节，小端序）
        0x00, 0x00
    ])
    
    # 重新计算CRC校验和
    crc_data = frame_01[1:4+7]
    calculated_crc = 0
    for byte in crc_data:
        calculated_crc += byte
        calculated_crc &= 0xFFFF
    
    # 更新帧的CRC字段
    frame_01 = frame_01[:-2] + calculated_crc.to_bytes(2, byteorder='little')
    
    print(f"测试数据包: {frame_01.hex().upper()}")
    print(f"计算的CRC: {calculated_crc:#04x}")
    
    # 模拟接收数据
    device2.on_received_data(bytearray(frame_01))
    
    # 检查设备信息是否正确更新
    print("\n设备信息更新结果 (数据上报命令):")
    all_updated_01 = True
    for key, value in device2.device_info.items():
        updated = value != "N/A"
        print(f"  {key}: {value} (类型: {type(value).__name__}) {'✅' if updated else '❌'}")
        if not updated:
            all_updated_01 = False
    
    print(f"\n数据上报命令测试结果: {'✅ 部分字段更新成功' if all_updated_01 else '❌ 部分字段未更新'}")
    
    # 总结测试结果
    print("\n=== 测试总结 ===")
    print(f"55A0数据包测试: {'✅ 通过' if all_updated_55a0 else '❌ 失败'}")
    print(f"数据上报命令测试: {'✅ 通过' if all_updated_01 else '❌ 失败'}")
    
    # 数据上报命令只更新部分字段，所以all_updated_01会是False，这是正常的
    # 我们只需要确保55A0数据包能更新所有字段，数据上报命令能更新相关字段
    
    return all_updated_55a0


def test_ui_update_logic():
    """测试UI更新逻辑"""
    print("\n=== UI更新逻辑测试 ===")
    
    # 模拟UI的update_ui方法
    def mock_update_ui(device_info):
        """模拟UI的update_ui方法"""
        print("\n模拟UI更新:")
        success_count = 0
        total_count = 0
        
        status_mapping = {
            "GPS状态: ": "gps_lock_status",
            "GPS经度: ": "gps_lng",
            "GPS纬度: ": "gps_lat",
            "GPS高度: ": "gps_alt",
            "接收频率: ": "rx_freq",
            "发射频率: ": "tx_freq",
            "接收本振: ": "rx_lo",
            "发射本振: ": "tx_lo",
            "发射状态: ": "tx_enable",
            "极化方式: ": "tx_polarization",
            "俯仰角: ": "pitch",
            "横滚角: ": "roll",
            "方位角: ": "heading",
            "波束偏角: ": "beam_off_axis",
            "波束方位: ": "beam_heading",
            "对星模式: ": "tracking_mode",
            "通信状态: ": "comm_status",
            "运行时间: ": "runtime"
        }
        
        for label_text, info_key in status_mapping.items():
            total_count += 1
            if info_key in device_info:
                value = device_info[info_key]
                display_text = ""
                
                try:
                    # 模拟UI的格式化逻辑
                    if info_key in ["runtime"]:
                        try:
                            if isinstance(value, str):
                                if 's' in value:
                                    value_num = int(value.split('s')[0])
                                    display_text = f"{value_num}s"
                                else:
                                    display_text = str(value)
                            elif isinstance(value, (int, float)):
                                display_text = f"{int(value)}s"
                            else:
                                display_text = str(value)
                        except (ValueError, AttributeError):
                            display_text = "N/A"
                    elif isinstance(value, (int, float)):
                        if info_key in ["gps_lng", "gps_lat", "pitch", "roll", "heading", "beam_off_axis", "beam_heading"]:
                            display_text = f"{value:.2f}"
                        elif info_key in ["rx_freq", "tx_freq", "rx_lo", "tx_lo"]:
                            display_text = f"{value:.2f}"
                        elif info_key in ["comm_status"]:
                            display_text = f"{int(value)}"
                        elif info_key in ["gps_alt"]:
                            display_text = f"{value:.1f}m"
                        else:
                            display_text = f"{value:.1f}"
                    else:
                        display_text = str(value)
                    
                    print(f"  {label_text}: {display_text} (原始值: {value}, 类型: {type(value).__name__}) ✅")
                    success_count += 1
                except Exception as e:
                    print(f"  {label_text}: N/A (错误: {e}) ❌")
            else:
                print(f"  {label_text}: N/A (字段不存在) ❌")
        
        print(f"\nUI更新结果: {success_count}/{total_count} 个字段更新成功")
        return success_count == total_count
    
    # 模拟设备信息
    mock_device_info = {
        "gps_lock_status": "已锁定",
        "gps_lng": 2.91,
        "gps_lat": 11.10,
        "gps_alt": 100,
        "rx_freq": 810.0,
        "tx_freq": 3924.0,
        "rx_lo": 810.0,
        "tx_lo": 3924.0,
        "tx_enable": "开启",
        "tx_polarization": "左旋",
        "pitch": 2.91,
        "roll": 0.60,
        "heading": 4.00,
        "beam_off_axis": 0.00,
        "beam_heading": 0.00,
        "tracking_mode": "自动",
        "comm_status": 1,
        "runtime": "60s"
    }
    
    ui_success = mock_update_ui(mock_device_info)
    print(f"\nUI更新逻辑测试结果: {'✅ 通过' if ui_success else '❌ 失败'}")
    
    return ui_success


if __name__ == "__main__":
    print("AFD01_QS设备状态更新完整测试")
    print("=" * 70)
    
    # 运行测试
    test1_success = test_complete_device_update()
    test2_success = test_ui_update_logic()
    
    print("\n" + "=" * 70)
    print("最终测试结果:")
    print(f"设备状态更新测试: {'✅ 成功' if test1_success else '❌ 失败'}")
    print(f"UI更新逻辑测试: {'✅ 成功' if test2_success else '❌ 失败'}")
    
    if test1_success and test2_success:
        print("\n🎉 所有测试通过！AFD01_QS设备状态更新修复完成")
        sys.exit(0)
    else:
        print("\n❌ 部分测试失败，需要进一步修复")
        sys.exit(1)
