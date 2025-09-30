import threading
import queue
import time
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
        
        # 添加内部缓冲区，用于累积接收数据
        self._receive_buffer = bytearray()
    
    def on_received_data(self, data: bytearray):
        print(f"kaudc004a callback [DEBUG] 收到原始数据: {data.hex().upper()}")
        """处理接收到的数据，改进的帧解析逻辑"""
        # 防御性检查
        if not hasattr(self, '_receive_buffer'):
            self._receive_buffer = bytearray()
        
        # 将新数据添加到内部缓冲区
        self._receive_buffer.extend(data)
        
        # 帧解析逻辑
        while len(self._receive_buffer) >= 2:
            # 查找帧头 (0xAA 0x55)
            frame_start = -1
            for i in range(len(self._receive_buffer) - 1):
                if self._receive_buffer[i] == 0xAA and self._receive_buffer[i+1] == 0x55:
                    frame_start = i
                    break
            
            # 如果没有找到帧头，清理缓冲区
            if frame_start < 0:
                if len(self._receive_buffer) > 1024:  # 防止缓冲区无限增长
                    self._receive_buffer.clear()
                break
            
            # 如果帧头之前有无效数据，清除
            if frame_start > 0:
                # 记录无效数据（可选）
                if len(self._receive_buffer[:frame_start]) > 0:
                    self.serial_controller.log(f"[警告] 清除无效数据: {self._receive_buffer[:frame_start].hex().upper()}")
                del self._receive_buffer[:frame_start]
            
            # 检查是否有足够的数据构成完整帧（KauDC004A帧长度为12字节）
            if len(self._receive_buffer) < 12:
                break
            
            # 提取完整帧
            frame = bytes(self._receive_buffer[:12])
            del self._receive_buffer[:12]
            
            # 解析帧
            try:
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
            except Exception as e:
                self.serial_controller.log(f"[错误] 解析帧时出错: {str(e)}, 帧数据: {frame.hex().upper()}")
    
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
        """发送命令到设备，改进的命令发送和错误处理逻辑"""
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
            
            # 添加内部缓冲区检查和初始化
            if not hasattr(self, '_receive_buffer'):
                self._receive_buffer = bytearray()
            
            # 清空内部缓冲区，确保不会有旧数据干扰新命令的响应
            self._receive_buffer.clear()
            
            # 清空响应队列
            try:
                while not self.response_queue.empty():
                    try:
                        self.response_queue.get_nowait()
                    except queue.Empty:
                        break
            except:
                pass
            
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
            
            # 如果命令是查询类命令，等待短暂时间让设备有机会响应
            if success and command_name in ["版本回读", "温度查询", "本振查询", "衰减查询"]:
                # 短暂延迟，给设备时间处理命令并发送响应
                time.sleep(0.1)
            
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
        """设备信息查询工作线程，改进的查询和响应处理逻辑"""
        # 防御性检查
        if not hasattr(self, 'serial_controller') or self.serial_controller is None:
            return
        
        if not self.serial_controller.is_connected():
            return
        
        # 添加内部缓冲区检查和初始化
        if not hasattr(self, '_receive_buffer'):
            self._receive_buffer = bytearray()
        
        queries = [
            (0x0B, b'\x0B\x00\x00\x00\x00\x00', "版本回读"),
            (0x0C, b'\x0C\x00\x00\x00\x00\x00', "温度查询"),
            (0x13, b'\x13\x00\x00\x00\x00\x00', "本振查询"),
            (0x16, b'\x16\x00\x00\x00\x00\x00', "衰减查询")
        ]
        
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
            
            # 清空内部缓冲区，确保没有残留数据影响本次查询
            if hasattr(self, '_receive_buffer'):
                self._receive_buffer.clear()
            
            # 清空响应队列
            try:
                while not self.response_queue.empty():
                    try:
                        self.response_queue.get_nowait()
                    except queue.Empty:
                        break
            except:
                pass
            
            # 发送所有查询命令，然后等待响应
            sent_commands = []
            for cmd_byte, payload, name in queries:
                safe_log(f"查询: {name}")
                
                # 检查protocol对象是否存在
                if not hasattr(self, 'protocol') or self.protocol is None:
                    safe_log("错误: protocol对象不存在")
                    all_ok = False
                    continue
                
                try:
                    frame = self.protocol.build_frame(payload)
                    
                    # 再次检查serial_controller连接状态
                    if hasattr(self.serial_controller, 'send_data') and self.serial_controller.is_connected():
                        success, msg = self.serial_controller.send_data(frame)
                        if success:
                            sent_commands.append((cmd_byte, name))
                        else:
                            safe_log(f"发送查询指令失败: {msg}")
                            all_ok = False
                    safe_log(f">>> 发送查询指令: {payload.hex().upper()}")
                except Exception as e:
                    safe_log(f"发送查询指令时出错: {str(e)}")
                    all_ok = False
            
            # 等待响应，为每个命令分配更长的超时时间
            if sent_commands:
                safe_log(f"等待{len(sent_commands)}个命令的响应...")
                received_commands = set()
                
                # 总共等待5秒，足够所有命令响应
                start_time = time.time()
                while time.time() - start_time < 5 and len(received_commands) < len(sent_commands):
                    try:
                        # 使用较短的超时，以便能够检查多个命令的响应
                        got_cmd, parsed = self.response_queue.get(timeout=0.5)
                        
                        # 查找对应的命令名称
                        cmd_name = "未知命令"
                        for cmd_byte, name in sent_commands:
                            if cmd_byte == got_cmd:
                                cmd_name = name
                                break
                        
                        safe_log(f"{cmd_name} 查询成功，回复正常")
                        received_commands.add(got_cmd)
                    except queue.Empty:
                        # 继续等待，不立即判定超时
                        continue
                    except Exception as e:
                        safe_log(f"处理响应时出错: {str(e)}")
                
                # 检查是否所有命令都收到了响应
                for cmd_byte, name in sent_commands:
                    if cmd_byte not in received_commands:
                        all_ok = False
                        safe_log(f"{name} 查询超时无响应")
            
            if all_ok:
                safe_log("✅ 所有查询成功完成！")
                break
            else:
                safe_log("❌ 本轮查询有失败，重试...")
                time.sleep(0.5)  # 重试前短暂暂停
        
        if not all_ok:
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