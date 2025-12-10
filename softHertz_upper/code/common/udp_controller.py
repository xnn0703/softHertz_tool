import socket
import threading
import time
from common.communication_base import CommunicationBase

class UDPController(CommunicationBase):
    """UDP通信控制器"""
    
    def __init__(self):
        super().__init__()
        self.socket = None
        self.remote_address = None  # 远程地址，用于发送数据
        self.is_broadcast = False
        self.current_device_type = "KauDC004A"  # 默认设备类型
        # 设置通信类型
        self.comm_type = "udp"
        
    def toggle_connection(self, host, remote_port, local_port=None, is_broadcast_mode=False):
        """打开或关闭UDP连接"""
        if self.is_connected():
            self.close()
            return True, "UDP连接已关闭"
        else:
            try:
                self.is_broadcast = is_broadcast_mode
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                
                # 设置UDP接收缓冲区大小为16KB，提高接收效率
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)
                
                # 如果未指定本地端口，则使用远程端口
                bind_port = int(local_port) if local_port else int(remote_port)
                
                if is_broadcast_mode:
                    # 广播模式
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    self.socket.bind(("0.0.0.0", bind_port))
                    self.remote_address = (host, int(remote_port))
                else:
                    # 单播模式
                    self.socket.bind(("0.0.0.0", bind_port))
                    self.remote_address = (host, int(remote_port))
                
                self.running = True
                self.receive_thread = threading.Thread(target=self.read_thread, daemon=True)
                self.receive_thread.start()
                
                mode_text = "广播" if is_broadcast_mode else "单播"
                return True, f"UDP {mode_text}模式已启动，绑定端口 {bind_port}"
            except Exception as e:
                self.close()
                return False, str(e)
    
    def is_connected(self):
        """检查UDP连接状态"""
        return self.socket is not None and self.running
    
    def close(self):
        """关闭UDP连接"""
        self.running = False
        
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        self.remote_address = None
    
    def send_data(self, data):
        """发送数据到UDP目标"""
        if not self.is_connected():
            return False, "UDP连接未打开"
        
        try:
            if self.remote_address:
                self.socket.sendto(data, self.remote_address)
            
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
            self.close()
            return False, error_msg
    
    def read_thread(self):
        """读取UDP数据的线程"""
        while self.running:
            try:
                if self.socket:
                    # 接收数据
                    data, addr = self.socket.recvfrom(1024)
                    if data:
                        if not self.performance_test_mode:
                            line = f"<<< 接收: {data.hex().upper()} 来自 {addr}"
                            self.log(line)
                        
                        # 触发回调，只传递新接收的数据，不累积buffer
                        if self.received_data_callback:
                            try:
                                self.received_data_callback(bytearray(data))
                            except Exception as e:
                                if not self.performance_test_mode:
                                    self.log(f"[回调错误] {str(e)}")
                
                time.sleep(0.005)
            except Exception as e:
                if self.running:  # 只有在运行状态下才记录错误
                    self.log(f"[接收错误] {e}")
                time.sleep(0.1)
