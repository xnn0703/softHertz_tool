import serial
import serial.tools.list_ports
import threading
import datetime
import queue
import time
from common.communication_base import CommunicationBase

class SerialController(CommunicationBase):
    def __init__(self):
        super().__init__()
        self.ser = None
        self.current_device_type = "KauDC004A"
        # 设置通信类型
        self.comm_type = "serial"
        
    def update_ports(self):
        """获取当前可用的串口列表"""
        return [p.device for p in serial.tools.list_ports.comports()]
    
    def log(self, msg):
        """记录日志到文件"""
        # 防御性检查，确保logfile存在
        if not hasattr(self, 'logfile') or self.logfile is None:
            # 如果日志文件不存在，尝试重新打开或输出到控制台
            try:
                print(f"[日志] {msg}")
                # 尝试重新打开日志文件
                try:
                    self.logfile = open("serial_log.txt", "a", encoding="utf-8")
                    self.log(f"[系统] 重新打开了日志文件")
                except:
                    pass
            except:
                # 终极防御，避免任何异常
                pass
            return
        
        try:
            ts = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")
            self.logfile.write(ts + msg + "\n")
            self.logfile.flush()
        except Exception as e:
            # 捕获所有可能的异常，确保程序不会崩溃
            try:
                print(f"[日志错误] 无法写入日志: {str(e)}, 消息: {msg}")
                # 发生异常时关闭并重置日志文件
                if self.logfile:
                    self.logfile.close()
                self.logfile = None
            except:
                pass
    
    def toggle_serial(self, port, baud_rate):
        """打开或关闭串口（兼容旧接口）"""
        return self.toggle_connection(port, baud_rate)
    
    def toggle_connection(self, port, baud_rate):
        """打开或关闭串口"""
        if self.ser and self.ser.is_open:
            self.close()
            return True, "串口已关闭"
        else:
            try:
                self.ser = serial.Serial(port, int(baud_rate), timeout=0.1)
                self.running = True
                self.receive_thread = threading.Thread(target=self.read_thread, daemon=True)
                self.receive_thread.start()
                return True, "串口已打开"
            except Exception as e:
                self.ser = None  # 发生异常时确保为None
                return False, str(e)
    
    def send_data(self, data):
        """发送数据到串口"""
        # 基本状态检查
        if self.ser is None or not hasattr(self.ser, 'is_open') or not self.ser.is_open:
            error_msg = "串口未打开或无效"
            if not self.performance_test_mode:
                self.log(f"[错误] {error_msg}")
            # 重置状态
            self.ser = None
            return False, error_msg
            
        try:
            # 性能测试模式下减少状态检查冗余
            if not self.performance_test_mode:
                # 非性能模式下的额外状态检查
                if not self.ser or not self.ser.is_open:
                    error_msg = "串口状态已变化"
                    self.log(f"[错误] {error_msg}")
                    self.ser = None
                    return False, error_msg
                
            # 发送数据
            self.ser.write(data)
            
            # 性能测试模式下减少日志
            if not self.performance_test_mode:
                line = f">>> 发送: {data.hex().upper()}"
                self.log(line)
                return True, line
            else:
                return True, "发送成功"
                
        except Exception as e:
            error_msg = f"发送错误: {str(e)}"
            if not self.performance_test_mode:
                self.log(f"[错误] {error_msg}")
            # 发生异常时，强制重置串口对象确保状态一致
            self.ser = None
            # 强制更新运行状态
            self.running = False
            return False, error_msg
    
    def read_thread(self):
        """接收数据的线程函数，改进的数据接收逻辑"""
        buffer = bytearray()
        while self.running:
            try:
                if self.ser and self.ser.is_open:
                    # 一次读取更多数据，而不是单字节读取
                    chunk = self.ser.read(1024)  # 增加读取缓冲区大小
                    if chunk:
                        buffer.extend(chunk)
                        
                        # 性能测试模式下减少或关闭原始数据日志
                        if not self.performance_test_mode:
                            # 实时记录接收到的数据
                            line = f"<<< 原始接收: {chunk.hex().upper()}"
                            self.log(line)
                        
                        # 检查是否有足够的数据来处理
                        if self.received_data_callback:
                            # 根据当前设备类型动态选择帧头检测策略
                            trigger_callback = False
                            
                            if self.current_device_type == "KauDC004A":
                                # KauDC004A设备使用双字节帧头0xAA 0x55
                                trigger_callback = len(buffer) >= 2 and buffer[-2:] == b'\xAA\x55'
                            elif self.current_device_type == "AFD01_QS":
                                # AFD01_QS设备使用单字节帧头0x55
                                trigger_callback = len(buffer) >= 1 and buffer[-1:] == b'\x55'
                            elif self.current_device_type == "DEBUG":
                                # DEBUG设备使用双字节帧头0xAA 0x55和帧尾0xEE
                                trigger_callback = b'\xAA\x55' in buffer and b'\xEE' in buffer
                            
                            # 安全机制：当缓冲区足够大时也触发回调，防止数据堆积
                            trigger_callback = trigger_callback or len(buffer) >= 64
                            
                            if trigger_callback:
                                try:
                                    # 创建buffer的副本传递给回调，避免回调中的操作影响当前buffer
                                    self.received_data_callback(bytearray(buffer))
                                except Exception as e:
                                    if not self.performance_test_mode:
                                        self.log(f"[回调错误] {str(e)}")
                
                # 调整睡眠时间，性能测试模式下增加睡眠时间减少CPU占用
                sleep_time = 0.01 if self.performance_test_mode else 0.005
                time.sleep(sleep_time)
            except Exception as e:
                # 性能测试模式下减少错误日志
                if not self.performance_test_mode:
                    err = f"[接收错误] {e}"
                    self.log(err)
                time.sleep(0.1)
    
    def close(self):
        """关闭串口和日志文件"""
        print(f"[DEBUG] SerialController: 开始关闭串口")
        
        # 停止接收线程
        self.running = False
        if self.receive_thread and self.receive_thread.is_alive():
            print(f"[DEBUG] SerialController: 等待接收线程结束")
            self.receive_thread.join(timeout=1.0)
            print(f"[DEBUG] SerialController: 接收线程已结束")
        
        # 关闭串口连接
        if hasattr(self, 'ser') and self.ser:
            try:
                if self.ser.is_open:
                    print(f"[DEBUG] SerialController: 关闭串口连接")
                    self.ser.close()
            except Exception as e:
                print(f"[DEBUG] SerialController: 关闭串口时发生异常: {str(e)}")
            finally:
                # 无论如何都确保设置为None
                self.ser = None
                print(f"[DEBUG] SerialController: 串口对象已设置为None")
        else:
            self.ser = None
            print(f"[DEBUG] SerialController: 串口对象不存在，已设置为None")
        
        # 重置回调
        self.received_data_callback = None
        
        # 关闭日志文件
        if hasattr(self, 'logfile') and self.logfile:
            try:
                self.logfile.flush()
                self.logfile.close()
                print(f"[DEBUG] SerialController: 日志文件已关闭")
            except Exception as e:
                print(f"[DEBUG] SerialController: 关闭日志文件时发生异常: {str(e)}")
            finally:
                self.logfile = None
                
        print(f"[DEBUG] SerialController: 关闭过程完成")
    
    def is_connected(self):
        """检查串口是否连接"""
        return self.ser is not None and self.ser.is_open