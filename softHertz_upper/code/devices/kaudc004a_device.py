import threading
import queue
from common.device_base import DeviceBase
from devices.kaudc004a_protocol import KauDC004AProtocol

class KauDC004ADevice(DeviceBase):
    """KauDC004A设备的具体实现类"""
    
    def __init__(self, serial_controller):
        protocol = KauDC004AProtocol()
        super().__init__(serial_controller, protocol)
        
        # 命令映射
        self._cmd_name_map = {
            0x0B: "版本回读", 0x0C: "温度查询", 0x13: "本振查询", 0x16: "衰减查询"
        }
        
        # 设备状态信息
        self.device_info = {
            "version": "N/A",
            "temperature": "N/A",
            "txlo": "N/A",
            "rxlo": "N/A",
            "tx_attenuation": "N/A",
            "rx_attenuation": "N/A",
            "lock_status": "N/A"
        }
        
    def on_received_data(self, data: bytearray):
        """处理接收到的数据"""
        buffer = bytearray(data)
        while len(buffer) >= 2:
            if buffer[0] != 0xAA or buffer[1] != 0x55:
                buffer.pop(0)
                continue
            if len(buffer) < 12:
                break
            frame = bytes(buffer[:12])
            del buffer[:12]

            parsed, msg = self.protocol.parse_response(frame)
            line = f"<<< 收到: {frame.hex().upper()} [{msg}]"
            
            if msg == "OK" and parsed:
                cmd = parsed[0]
                # 放入响应队列
                self.response_queue.put((cmd, parsed))
                # 提取数据并更新设备信息
                data_dict = self.protocol.extract_data(cmd, parsed)
                if data_dict:
                    # 更新设备信息
                    self._update_device_info(cmd, data_dict)
                    
                    # 记录日志
                    if 'display_text' in data_dict:
                        self.serial_controller.log("    " + data_dict['display_text'])
            
            # 记录日志
            self.serial_controller.log(line)
    
    def _update_device_info(self, cmd: int, data_dict: dict):
        """更新设备信息"""
        if cmd == 0x0B and 'version' in data_dict:
            self.device_info["version"] = data_dict['version']
        elif cmd == 0x0C and 'temperature' in data_dict:
            self.device_info["temperature"] = data_dict['temperature']
        elif cmd == 0x13:
            if 'txlo' in data_dict:
                self.device_info["txlo"] = data_dict['txlo']
            if 'rxlo' in data_dict:
                self.device_info["rxlo"] = data_dict['rxlo']
            if 'lock' in data_dict:
                self.device_info["lock_status"] = data_dict['lock']
        elif cmd == 0x16:
            if 'tx_attenuation' in data_dict:
                self.device_info["tx_attenuation"] = data_dict['tx_attenuation']
            if 'rx_attenuation' in data_dict:
                self.device_info["rx_attenuation"] = data_dict['rx_attenuation']
    
    def send_command(self, command_name: str, params=None) -> bool:
        """发送命令到设备"""
        # 多重防御性检查，确保serial_controller存在且连接状态一致
        if not hasattr(self, 'serial_controller') or self.serial_controller is None:
            return False, "串口控制器不存在"
        
        # 即使is_connected返回True，也要再次检查serial_controller.ser是否存在
        if not self.serial_controller.is_connected() or (hasattr(self.serial_controller, 'ser') and self.serial_controller.ser is None):
            # 强制同步状态
            if hasattr(self.serial_controller, 'ser'):
                self.serial_controller.ser = None
            return False, "串口未连接或连接已断开"
        
        try:
            # 构建命令帧前再检查一次连接状态，防止竞态条件
            if not self.serial_controller.is_connected() or (hasattr(self.serial_controller, 'ser') and self.serial_controller.ser is None):
                return False, "串口连接状态已变化"
            
            payload = b''
            
            if command_name == "复位设备":
                payload = b'\x0A\x00\x00\x00\x00\x00'
            elif command_name == "版本回读":
                payload = b'\x0B\x00\x00\x00\x00\x00'
            elif command_name == "温度查询":
                payload = b'\x0C\x00\x00\x00\x00\x00'
            elif command_name == "本振查询":
                payload = b'\x13\x00\x00\x00\x00\x00'
            elif command_name == "衰减查询":
                payload = b'\x16\x00\x00\x00\x00\x00'
            elif command_name == "发射衰减设置" and params is not None:
                try:
                    att = float(params)
                    if 0 <= att <= 30:
                        # 将衰减值转换为 2 字节，并且乘以 10 来实现 dB 单位
                        tmp = int(att * 10).to_bytes(2, 'big')
                        payload = b'\x14\x00\x00\x00' + tmp
                    else:
                        return False, "发射衰减值必须在0到30之间"
                except ValueError:
                    return False, "请输入有效的数字"
            elif command_name == "接收衰减设置" and params is not None:
                try:
                    att = float(params)
                    if 0 <= att <= 30:
                        # 将衰减值转换为 2 字节，并且乘以 10 来实现 dB 单位
                        tmp = int(att * 10).to_bytes(2, 'big')
                        payload = b'\x15\x00\x00\x00' + tmp
                    else:
                        return False, "接收衰减值必须在0到30之间"
                except ValueError:
                    return False, "请输入有效的数字"
            elif command_name == "设置发射本振" and params is not None:
                # params 应该是频率字符串
                freq = self.protocol.extract_frequency(params)
                payload = b'\x12\x00\x00\x00' + int(freq).to_bytes(2, 'big')
            elif command_name == "设置接收本振" and params is not None:
                # params 应该是频率字符串
                freq = self.protocol.extract_frequency(params)
                payload = b'\x0E\x00\x00\x00' + int(freq).to_bytes(2, 'big')
            else:
                return False, "未知命令或参数错误"
            
            # 构建并发送帧
            frame = self.protocol.build_frame(payload)
            
            # 发送命令前最后一次检查连接状态
            if not self.serial_controller.is_connected() or (hasattr(self.serial_controller, 'ser') and self.serial_controller.ser is None):
                return False, "串口连接状态已变化"
            
            success, msg = self.serial_controller.send_data(frame)
            return success, msg
        except Exception as e:
            error_msg = f"发送命令时发生错误: {str(e)}"
            # 发生NoneType错误时，强制同步状态
            if "'NoneType' object has no attribute" in str(e) and hasattr(self.serial_controller, 'ser'):
                self.serial_controller.ser = None
            return False, error_msg
    
    def query_device_info(self) -> dict:
        """查询设备信息"""
        # 启动一个线程来异步查询设备信息
        threading.Thread(target=self._query_device_worker, daemon=True).start()
        # 返回当前的设备信息
        return self.device_info.copy()
    
    def _query_device_worker(self):
        """设备信息查询工作线程"""
        if not self.serial_controller.is_connected():
            return
        
        queries = [
            (0x0B, b'\x0B\x00\x00\x00\x00\x00', "版本回读"),
            (0x0C, b'\x0C\x00\x00\x00\x00\x00', "温度查询"),
            (0x13, b'\x13\x00\x00\x00\x00\x00', "本振查询"),
            (0x16, b'\x16\x00\x00\x00\x00\x00', "衰减查询")
        ]
        
        # 防御性检查，确保serial_controller存在
        if not hasattr(self, 'serial_controller') or self.serial_controller is None:
            return
        
        # 安全的日志记录函数
        def safe_log(msg):
            if hasattr(self.serial_controller, 'log'):
                try:
                    self.serial_controller.log(msg)
                except Exception as e:
                    try:
                        print(f"[日志错误] {msg}, 原错误: {str(e)}")
                    except:
                        pass
        
        for attempt in range(3):
            safe_log(f"尝试查询设备，第 {attempt+1} 次...")
            all_ok = True
            
            for cmd_byte, payload, name in queries:
                safe_log(f"查询: {name}")
                
                # 检查protocol对象是否存在
                if not hasattr(self, 'protocol') or self.protocol is None:
                    safe_log("错误: protocol对象不存在")
                    all_ok = False
                    continue
                
                try:
                    frame = self.protocol.build_frame(payload)
                    
                    # 再次检查serial_controller
                    if hasattr(self.serial_controller, 'send_data'):
                        self.serial_controller.send_data(frame)
                    safe_log(f">>> 发送查询指令: {payload.hex().upper()}")
                except Exception as e:
                    safe_log(f"发送查询指令时出错: {str(e)}")
                    all_ok = False
                    continue
                
                # 清空旧回复
                try:
                    while not self.response_queue.empty():
                        try:
                            self.response_queue.get_nowait()
                        except queue.Empty:
                            break
                except:
                    pass
                
                try:
                    # 等待响应
                    got_cmd, parsed = self.response_queue.get(timeout=2)
                    if got_cmd == cmd_byte:
                        safe_log(f"{name} 查询成功，回复正常")
                    else:
                        all_ok = False
                        safe_log(f"{name} 收到错帧: 0x{got_cmd:02X}")
                except queue.Empty:
                    all_ok = False
                    safe_log(f"{name} 查询超时无响应")
                except Exception as e:
                    all_ok = False
                    safe_log(f"等待响应时出错: {str(e)}")
            
            if all_ok:
                safe_log("✅ 设备查询完成，全部成功！")
                break
            else:
                safe_log("❌ 本轮查询有失败，重试...")
        else:
            safe_log("❌ 所有查询尝试失败！请检查设备连接或协议配置。")
    
    def get_supported_commands(self) -> list:
        """获取设备支持的命令列表"""
        return [
            "复位设备", "版本回读", "温度查询", "本振查询", 
            "衰减查询", "发射衰减设置", "接收衰减设置", 
            "设置发射本振", "设置接收本振"
        ]
    
    def get_supported_txlo_values(self) -> list:
        """获取支持的发射本振频率值"""
        return [
            "26.55GHz (27.5-28.35)", 
            "27.40GHz (28.35-29.2)", 
            "28.05GHz (29.00-30.0)", 
            "29.05GHz (30.00-31.0)"
        ]
    
    def get_supported_rxlo_values(self) -> list:
        """获取支持的接收本振频率值"""
        return [
            "16.75GHz (17.7-18.2)", 
            "17.25GHz (18.2-19.2)", 
            "18.25GHz (19.2-20.2)", 
            "19.25GHz (20.2-21.2)"
        ]