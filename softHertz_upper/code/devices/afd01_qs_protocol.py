import struct
from common.protocol_base import ProtocolBase
import struct

class AFD01_QSProtocol(ProtocolBase):
    """AFD01_QS设备的协议实现类"""
    
    # 帧头定义
    FRAME_HEADER = 0x55
    
    # 命令类型定义
    CMD_DATA_REPORT = 0x01
    CMD_SEARCH_PARAM = 0x02
    CMD_TX_ENABLE = 0x03
    CMD_TRACKING_MODE = 0x05
    CMD_TX_BEAM_CTRL = 0x07
    CMD_RX_BEAM_CTRL = 0x09
    CMD_BOTH_BEAM_CTRL = 0x0A
    CMD_TLE_CONFIG = 0x08
    CMD_ANTENNA_STATUS_REPORT = 0xA0  # 天线状态上报命令
    
    def build_frame(self, command, params=None):
        """构建协议帧"""
        try:
            # 根据命令类型构建不同的帧
            if command == self.CMD_DATA_REPORT:
                frame = self.build_report_data_cmd(params)
            elif command == self.CMD_SEARCH_PARAM:
                frame = self.build_search_param_cmd(*params)
            elif command == self.CMD_TX_ENABLE:
                frame = self.build_tx_enable_cmd(params)
            elif command == self.CMD_TRACKING_MODE:
                frame = self.build_tracking_mode_cmd(params)
            elif command in [self.CMD_TX_BEAM_CTRL, self.CMD_RX_BEAM_CTRL, self.CMD_BOTH_BEAM_CTRL]:
                frame = self.build_beam_control_cmd(command, *params)
            elif command == self.CMD_TLE_CONFIG:
                frame = self.build_tle_cmd(*params)
            else:
                raise ValueError(f"未知的命令类型: {command}")
            
            return frame
        except Exception as e:
            print(f"构建帧失败: {e}")
            return None
    
    def parse_response(self, frame):
        """解析响应帧"""
        try:
            # 检查帧是否为空或类型错误
            if not frame or not isinstance(frame, bytes):
                print(f"[DEBUG] 无效的帧数据")
                return None, "无效的帧数据"
                
            # 检查帧头和最小长度（至少需要包含帧头+命令+长度+CRC = 6字节）
            if len(frame) < 6 or frame[0] != self.FRAME_HEADER:
                print(f"[DEBUG] 无效的帧头或长度不足: {frame.hex().upper()}")
                return None, "无效的帧头或长度不足"
            
            # 提取命令类型
            command = frame[1]
            
            # 确保有足够的数据解析长度字段（至少需要frame[2:4]存在）
            if len(frame) < 4:
                print(f"[DEBUG] 帧长度不足，无法解析数据长度: {frame.hex().upper()}")
                return None, "帧长度不足，无法解析数据长度"
                
            # 尝试提取数据长度（2字节，高字节先）
            try:
                data_length = struct.unpack('>H', frame[2:4])[0]
            except struct.error as se:
                print(f"[DEBUG] 解析数据长度失败: {frame.hex().upper()}, 错误: {str(se)}")
                return None, f"解析数据长度失败: {str(se)}"
            
            # 数据长度合理性检查
            if data_length > 1024 or data_length < 0:
                print(f"[DEBUG] 数据长度不合理: {data_length}, 帧数据: {frame.hex().upper()}")
                return None, f"数据长度不合理: {data_length}"
            
            # 计算并检查完整帧长度
            total_frame_length = 5 + data_length  # 帧头(1)+命令(1)+长度(2)+数据(N)+CRC(2)
            if len(frame) < total_frame_length:
                print(f"[DEBUG] 帧长度不足: 当前{len(frame)}字节, 需要{total_frame_length}字节, 帧数据: {frame.hex().upper()}")
                return None, f"帧长度不足: 当前{len(frame)}字节, 需要{total_frame_length}字节"

            # 提取数据部分
            data = frame[4:4+data_length]

            # 确保有足够的数据解析校验和
            crc_start = 4 + data_length
            crc_end = 5 + data_length
            if len(frame) < crc_end:
                print(f"[DEBUG] 帧长度不足，无法解析校验和: {frame.hex().upper()}")
                return None, "帧长度不足，无法解析校验和"
                
            # 尝试提取校验和（2字节，高字节先）
            try:
                received_checksum = struct.unpack('>H', frame[crc_start:crc_end])[0]
            except struct.error as se:
                print(f"[DEBUG] 解析校验和失败: {frame.hex().upper()}, 错误: {str(se)}")
                return None, f"解析校验和失败: {str(se)}"

            # 计算校验和：指令(1字节) + 数据长度(2字节) + 数据内容
            checksum_data = frame[1:crc_start]  # 从命令字节到数据内容末尾
            calculated_checksum = 0
            for byte in checksum_data:
                calculated_checksum += byte
                # 保持为16位无符号整数
                calculated_checksum &= 0xFFFF

            # 检查校验和
            if received_checksum != calculated_checksum:
                print(f"[DEBUG] 校验和失败: 帧数据: {frame.hex().upper()}")
                return None, f"校验和失败，期望: {calculated_checksum:#04x}, 实际: {received_checksum:#04x}"

            return (command, data), "解析成功"
        except Exception as e:
            print(f"[DEBUG] 解析失败: {frame.hex().upper()}")
            return None, f"解析失败: {str(e)}"
    
    def extract_data(self, command, data):
        """从解析后的数据中提取有用信息"""
        result = {}
        try:
            if command == self.CMD_DATA_REPORT:
                # 解析数据上报帧（根据协议规范，数据长度为7字节）
                if len(data) == 7:
                    # 字节0-3: 信噪比（4字节float，大端序）
                    snr = struct.unpack('>f', data[0:4])[0]
                    
                    # 字节4: 基带状态
                    baseband_status = data[4]
                    # 解析基带状态中的bit位
                    power_status = "打开" if (baseband_status & 0x02) else "关闭"  # bit1
                    broadcast_lock_status = "已锁定" if (baseband_status & 0x04) else "未锁定"  # bit2
                    
                    # 字节5: 节能状态
                    power_save_status = "支持" if data[5] != 0x00 else "不支持"  # 若基带无此功能，可固定发0x00
                    
                    # 字节6: 重启命令
                    reboot_cmd = "重启" if data[6] == 0x01 else "正常工作"
                    
                    result.update({
                        "snr": f"{snr:.2f}",
                        "power_status": power_status,
                        "broadcast_lock_status": broadcast_lock_status,
                        "power_save_status": power_save_status,
                        "reboot_cmd": reboot_cmd,
                        "display_text": f"数据上报: 信噪比={snr:.2f}dB, 电源={power_status}, 广播={broadcast_lock_status}"
                    })
                    
            elif command == self.CMD_ANTENNA_STATUS_REPORT:
                print(f"天线状态上报数据长度: {len(data)}")
                # 解析天线状态上报帧（根据协议规范，数据长度为42字节）
                # 为了兼容性，当数据长度大于等于42字节时也尝试解析
                if len(data) >= 42:
                    print(f"天线状态上报数据内容: {data.hex()}")
                    # 字节0: GPS锁定状态 (协议表格第5列)
                    gps_lock_status = "已锁定" if data[0] == 0x01 else "未锁定"
                    
                    # 字节1-2: GPS经度（2字节整数，范围[-180°~180°] * 100，东经为正）(协议表格第6-7列)
                    gps_lng_raw = struct.unpack('>h', data[1:3])[0]
                    gps_lng = gps_lng_raw / 100.0
                    
                    # 字节3-4: GPS纬度（2字节整数，范围[-90°~90°] * 100，北纬为正）(协议表格第8-9列)
                    gps_lat_raw = struct.unpack('>h', data[3:5])[0]
                    gps_lat = gps_lat_raw / 100.0
                    
                    # 字节5-6: GPS高度（2字节整数，单位为米）(协议表格第10-11列)
                    gps_alt = struct.unpack('>h', data[5:7])[0]
                    
                    # 字节7-10: 接收频点（4字节float，大端序，单位为MHz）(协议表格第12-15列)
                    # 注意：根据用户提供的数据和协议，这里需要重新排列字节顺序
                    rx_freq_bytes = bytes([data[10], data[9], data[8], data[7]])
                    rx_freq = struct.unpack('<f', rx_freq_bytes)[0]
                    
                    # 字节11-14: 发射频点（4字节float，大端序，单位为MHz）(协议表格第16-19列)
                    tx_freq_bytes = bytes([data[14], data[13], data[12], data[11]])
                    tx_freq = struct.unpack('<f', tx_freq_bytes)[0]
                    
                    # 字节15-18: 接收本振（4字节float，大端序，单位为MHz）(协议表格第20-23列)
                    rx_lo_bytes = bytes([data[18], data[17], data[16], data[15]])
                    rx_lo = struct.unpack('<f', rx_lo_bytes)[0]
                    
                    # 字节19-22: 发射本振（4字节float，大端序，单位为MHz）(协议表格第24-27列)
                    tx_lo_bytes = bytes([data[22], data[21], data[20], data[19]])
                    tx_lo = struct.unpack('<f', tx_lo_bytes)[0]
                    
                    # 字节23: 发射状态(协议表格第28列)
                    tx_enable = "开启" if data[23] == 0x01 else "关闭"
                    
                    # 字节24: 极化方式(协议表格第29列)
                    polarization = "左旋" if data[24] == 0x00 else "右旋"
                    
                    # 字节25-26: 俯仰角（2字节整数，范围[-90°~90°] * 100）(协议表格第30-31列)
                    pitch = struct.unpack('>h', data[25:27])[0] / 100.0
                    
                    # 字节27-28: 横滚角（2字节整数，范围[-180°~180°] * 100）(协议表格第32-33列)
                    roll = struct.unpack('>h', data[27:29])[0] / 100.0
                    
                    # 字节29-30: 方位角（2字节整数，范围[0°~360°] * 100）(协议表格第34-35列)
                    heading = struct.unpack('>h', data[29:31])[0] / 100.0
                    
                    # 字节31-32: 波束偏轴角（2字节整数，范围[0°~90°] * 100）(协议表格第36-37列)
                    beam_off_axis = struct.unpack('>h', data[31:33])[0] / 100.0
                    
                    # 字节33-34: 波束航向角（2字节整数，范围[0°~360°] * 100）(协议表格第38-39列)
                    beam_heading = struct.unpack('>h', data[33:35])[0] / 100.0
                    
                    # 字节35: 对星模式(协议表格第40列)
                    tracking_mode = "自动" if data[35] == 0x00 else "手动"
                    
                    # 字节36: 跟踪模式（bit5表示天线搜星完成状态）(协议表格第41列)
                    tracking_state = data[36]
                    antenna_search_status = "搜星完成" if (tracking_state & 0x20) else "搜星未完成"
                    
                    # 字节37: 设备通讯状态(协议表格第42列)
                    comm_status = data[37]
                    
                    # 字节38-41: ACU运行时间（4字节整数，单位为秒）(协议表格第43-46列)
                    runtime = struct.unpack('>I', data[38:42])[0]
                    
                    result.update({
                        "gps_lock_status": gps_lock_status,
                        "gps_lng": f"{gps_lng:.2f}",
                        "gps_lat": f"{gps_lat:.2f}",
                        "gps_alt": f"{gps_alt}",
                        "rx_freq": f"{rx_freq:.2f}",
                        "tx_freq": f"{tx_freq:.2f}",
                        "rx_lo": f"{rx_lo:.2f}",
                        "tx_lo": f"{tx_lo:.2f}",
                        "tx_enable": tx_enable,
                        "tx_polarization": polarization,
                        "pitch": f"{pitch:.2f}",
                        "roll": f"{roll:.2f}",
                        "heading": f"{heading:.2f}",
                        "beam_off_axis": f"{beam_off_axis:.2f}",
                        "beam_heading": f"{beam_heading:.2f}",
                        "tracking_mode": tracking_mode,
                        "antenna_search_status": antenna_search_status,
                        "comm_status": f"{comm_status}",
                        "runtime": f"{runtime}s"
                    })
                    
                    # 打印解析结果
                    print("===== 天线状态上报数据解析结果 =====")
                    print(f"GPS锁定状态: {gps_lock_status}")
                    print(f"GPS经度: {gps_lng:.2f}°")
                    print(f"GPS纬度: {gps_lat:.2f}°")
                    print(f"GPS高度: {gps_alt}米")
                    print(f"接收频点: {rx_freq:.2f} MHz")
                    print(f"发射频点: {tx_freq:.2f} MHz")
                    print(f"接收本振: {rx_lo:.2f} MHz")
                    print(f"发射本振: {tx_lo:.2f} MHz")
                    print(f"发射状态: {tx_enable}")
                    print(f"极化方式: {polarization}")
                    print(f"俯仰角: {pitch:.2f}°")
                    print(f"横滚角: {roll:.2f}°")
                    print(f"方位角: {heading:.2f}°")
                    print(f"波束偏轴角: {beam_off_axis:.2f}°")
                    print(f"波束航向角: {beam_heading:.2f}°")
                    print(f"对星模式: {tracking_mode}")
                    print(f"天线搜星状态: {antenna_search_status}")
                    print(f"设备通讯状态: {comm_status}")
                    print(f"ACU运行时间: {runtime}秒")
                    print("====================================")
                    
            elif command == self.CMD_SEARCH_PARAM:
                # 解析搜星参数设置响应
                if len(data) >= 1:
                    success = data[0] == 0x01
                    result.update({
                        "comm_status": "设置成功" if success else "设置失败",
                        "display_text": f"搜星参数设置{'成功' if success else '失败'}"
                    })
                    
            elif command == self.CMD_TX_ENABLE:
                # 解析发射开关设置响应
                if len(data) >= 1:
                    success = data[0] == 0x01
                    result.update({
                        "comm_status": "设置成功" if success else "设置失败",
                        "tx_enable": "开启" if (data[0] & 0x01) else "关闭",
                        "display_text": f"发射开关{'开启' if (data[0] & 0x01) else '关闭'}"
                    })
                    
            elif command == self.CMD_TRACKING_MODE:
                # 解析对星模式设置响应
                if len(data) >= 1:
                    success = data[0] == 0x01
                    mode_str = {0: "手动", 1: "自动", 2: "TLE跟踪"}.get(data[0] & 0x03, "未知")
                    result.update({
                        "comm_status": "设置成功" if success else "设置失败",
                        "tracking_mode": mode_str,
                        "display_text": f"对星模式设置为{mode_str}"
                    })
                    
            elif command in [self.CMD_TX_BEAM_CTRL, self.CMD_RX_BEAM_CTRL, self.CMD_BOTH_BEAM_CTRL]:
                # 解析波束控制设置响应
                if len(data) >= 1:
                    success = data[0] == 0x01
                    cmd_name = {self.CMD_TX_BEAM_CTRL: "发射波束", self.CMD_RX_BEAM_CTRL: "接收波束", self.CMD_BOTH_BEAM_CTRL: "收发波束"}.get(command, "波束")
                    result.update({
                        "comm_status": "设置成功" if success else "设置失败",
                        "display_text": f"{cmd_name}控制{'成功' if success else '失败'}"
                    })
                    
            elif command == self.CMD_TLE_CONFIG:
                # 解析TLE星历配置响应
                if len(data) >= 1:
                    success = data[0] == 0x01
                    result.update({
                        "comm_status": "设置成功" if success else "设置失败",
                        "display_text": f"TLE星历配置{'成功' if success else '失败'}"
                    })
                    
        except Exception as e:
            print(f"提取数据失败: {e}")
        
        return result if result else None
    
    def build_report_data_cmd(self, params=None):
        """构建数据上报命令
        根据协议规范：数据长度为7字节
        - 信噪比(4字节float)
        - 基带状态(1字节): bit1=电源状态(0=关闭,1=打开), bit2=广播锁定状态(0=未锁定,1=锁定)
        - 节能状态(1字节): 若基带无此功能，可固定发0x00
        - 重启命令(1字节): 0x00=正常工作, 0x01=重启
        """
        command = self.CMD_DATA_REPORT
        
        # 默认参数值
        snr = 0.0  # 默认信噪比
        baseband_status = 0x00  # 默认基带状态: 电源关闭, 未锁定
        power_save_status = 0x00  # 默认节能状态
        reboot_cmd = 0x00  # 默认正常工作
        
        # 如果提供了参数，则更新默认值
        if params:
            if isinstance(params, dict):
                snr = params.get('snr', snr)
                baseband_status = params.get('baseband_status', baseband_status)
                power_save_status = params.get('power_save_status', power_save_status)
                reboot_cmd = params.get('reboot_cmd', reboot_cmd)
        
        # 打包参数：信噪比(4字节float，大端序) + 基带状态(1字节) + 节能状态(1字节) + 重启命令(1字节)
        data = struct.pack('>fBBB', snr, baseband_status, power_save_status, reboot_cmd)
        # 构建完整帧
        return self._build_common_frame(command, data)
    
    def build_search_param_cmd(self, satellite_lng, polarization, rx_freq, tx_freq):
        """构建搜星参数命令
        根据协议规范：数据长度为11字节
        - 卫星经度(2字节整数): 范围[-180°~180°] * 100，东经为正
        - 极化(1字节): 0x00=左旋, 0x01=右旋
        - 接收频点(4字节float, MHz): 大端序
        - 发射频点(4字节float, MHz): 大端序
        """
        command = self.CMD_SEARCH_PARAM
        
        # 将卫星经度转换为2字节整数：[-180°~180°] * 100
        # 限制范围在有效区间内
        satellite_lng = max(-180.0, min(180.0, satellite_lng))
        # 转换为整数并确保在2字节有符号整数范围内
        lng_int = int(round(satellite_lng * 100))
        lng_int = max(-32768, min(32767, lng_int))  # 2字节有符号整数范围
        
        # 极化方式限制为0或1
        polarization = 0 if polarization == 0 else 1
        
        # 打包参数：卫星经度(2字节整数，大端序) + 极化(1字节) + 接收频率(4字节float，大端序) + 发射频率(4字节float，大端序)
        data = struct.pack('>hBff', lng_int, polarization, rx_freq, tx_freq)
        # 构建完整帧
        return self._build_common_frame(command, data)
    
    def build_tx_enable_cmd(self, enable):
        """构建发射开关命令"""
        command = self.CMD_TX_ENABLE
        # 打包参数：启用状态(1字节，0-关闭，1-开启)
        data = bytes([enable & 0x01])
        # 构建完整帧
        return self._build_common_frame(command, data)
    
    def build_tracking_mode_cmd(self, mode):
        """构建对星模式命令"""
        command = self.CMD_TRACKING_MODE
        # 打包参数：模式(1字节，0-手动，1-自动，2-TLE跟踪)
        data = bytes([mode & 0x03])
        # 构建完整帧
        return self._build_common_frame(command, data)
    
    def build_beam_control_cmd(self, cmd_type, pitch, heading):
        """构建波束控制命令
        根据协议规范：数据长度为4字节
        - 俯仰角(2字节整数): 范围[0°~90°] * 100
        - 方位角(2字节整数): 范围[0°~360°] * 100
        """
        command = cmd_type  # 0x07-发射波束, 0x09-接收波束, 0x0A-收发波束
        
        # 将俯仰角转换为2字节整数：[0°~90°] * 100
        # 限制范围在有效区间内
        pitch = max(0.0, min(90.0, pitch))
        # 转换为整数并确保在2字节有符号整数范围内
        pitch_int = int(round(pitch * 100))
        pitch_int = max(-32768, min(32767, pitch_int))  # 2字节有符号整数范围
        
        # 将方位角转换为2字节整数：[0°~360°] * 100
        # 限制范围在有效区间内
        heading = max(0.0, min(360.0, heading))
        # 转换为整数并确保在2字节有符号整数范围内
        heading_int = int(round(heading * 100))
        heading_int = max(-32768, min(32767, heading_int))  # 2字节有符号整数范围
        
        # 打包参数：俯仰角(2字节整数，大端序)、方位角(2字节整数，大端序)
        data = struct.pack('>hh', pitch_int, heading_int)
        # 构建完整帧
        return self._build_common_frame(command, data)
    
    def build_tle_cmd(self, tle_line1, tle_line2):
        """构建TLE星历配置命令，符合协议要求（TLE0和TLE1各占69字节）"""
        command = self.CMD_TLE_CONFIG
        # 处理TLE数据：TLE行1(69字节) + TLE行2(69字节)，符合协议4.6章节要求
        tle1_bytes = tle_line1.ljust(69, '\x00')[:69].encode('utf-8')
        tle2_bytes = tle_line2.ljust(69, '\x00')[:69].encode('utf-8')
        data = tle1_bytes + tle2_bytes
        # 构建完整帧
        return self._build_common_frame(command, data)
    
    def _build_common_frame(self, command, data):
        """构建通用帧结构"""
        # 计算数据长度（2字节）
        data_length = len(data)
        # 构建帧头和数据部分：帧头(1字节) + 指令(1字节) + 数据长度(2字节，高字节先) + 数据内容
        frame_part = bytes([self.FRAME_HEADER, command]) + struct.pack('>H', data_length) + data
        # 计算校验和（不含帧头和帧尾）
        # 校验范围：指令(1字节) + 数据长度(2字节) + 数据内容
        checksum_data = frame_part[1:]
        checksum = 0
        for byte in checksum_data:
            checksum += byte
            # 保持为16位无符号整数
            checksum &= 0xFFFF
        # 构建完整帧：添加校验和(2字节，高字节先)
        frame = frame_part + struct.pack('>H', checksum)
        return frame