import socket
import threading
import time
from common.communication_base import CommunicationBase

class TCPController(CommunicationBase):
    """TCP通信控制器"""
    
    def __init__(self):
        super().__init__()
        self.socket = None
        self.is_server = False
        self.server_socket = None
        self.client_address = None
        self.current_device_type = "KauDC004A"  # 默认设备类型
        # 设置通信类型
        self.comm_type = "tcp"
        
    def toggle_connection(self, host, port, is_server_mode=False):
        """打开或关闭TCP连接"""
        if self.is_connected():
            self.close()
            return True, "TCP连接已关闭"
        else:
            try:
                self.is_server = is_server_mode
                
                if is_server_mode:
                    # 服务器模式
                    self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    self.server_socket.bind((host, int(port)))
                    self.server_socket.listen(1)
                    self.running = True
                    self.receive_thread = threading.Thread(target=self.server_listen_thread, daemon=True)
                    self.receive_thread.start()
                    return True, f"TCP服务器已启动，监听 {host}:{port}"
                else:
                    # 客户端模式
                    self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.socket.connect((host, int(port)))
                    self.running = True
                    self.receive_thread = threading.Thread(target=self.read_thread, daemon=True)
                    self.receive_thread.start()
                    return True, f"TCP客户端已连接到 {host}:{port}"
            except Exception as e:
                self.close()
                return False, str(e)
    
    def is_connected(self):
        """检查TCP连接状态"""
        if self.is_server:
            return self.server_socket is not None and self.running
        else:
            return self.socket is not None and self.running
    
    def close(self):
        """关闭TCP连接"""
        self.running = False
        
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
            self.server_socket = None
        
        self.client_address = None
    
    def send_data(self, data):
        """发送数据到TCP连接"""
        if not self.is_connected():
            return False, "TCP连接未打开"
        
        try:
            if self.is_server:
                # 服务器模式下，发送数据到连接的客户端
                if self.socket:
                    self.socket.sendall(data)
                else:
                    return False, "未连接到任何客户端"
            else:
                # 客户端模式下直接发送
                self.socket.sendall(data)
            
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
    
    def server_listen_thread(self):
        """TCP服务器监听线程"""
        while self.running:
            try:
                # 接受客户端连接
                self.socket, self.client_address = self.server_socket.accept()
                self.log(f"[TCP服务器] 客户端已连接: {self.client_address}")
                
                # 启动数据接收线程
                self.receive_thread = threading.Thread(target=self.read_thread, daemon=True)
                self.receive_thread.start()
            except Exception as e:
                if self.running:  # 只有在运行状态下才记录错误
                    self.log(f"[TCP服务器] 监听错误: {str(e)}")
                time.sleep(0.1)
    
    def read_thread(self):
        """读取TCP数据的线程"""
        buffer = bytearray()
        while self.running:
            try:
                if self.socket:
                    # 接收数据
                    data = self.socket.recv(1024)
                    if data:
                        buffer.extend(data)
                        
                        if not self.performance_test_mode:
                            line = f"<<< 接收: {data.hex().upper()}"
                            self.log(line)
                        
                        # 触发回调
                        if self.received_data_callback:
                            try:
                                self.received_data_callback(bytearray(buffer))
                            except Exception as e:
                                if not self.performance_test_mode:
                                    self.log(f"[回调错误] {str(e)}")
                    else:
                        # 连接关闭
                        self.log(f"[TCP] 连接已关闭")
                        self.close()
                
                time.sleep(0.005)
            except Exception as e:
                if self.running:  # 只有在运行状态下才记录错误
                    self.log(f"[接收错误] {e}")
                time.sleep(0.1)
