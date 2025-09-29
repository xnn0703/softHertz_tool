import serial
import serial.tools.list_ports
import threading
import datetime
import queue
import time

class SerialController:
    def __init__(self):
        self.ser = None
        self.running = False
        self.logfile = open("serial_log.txt", "a", encoding="utf-8")
        self.response_queue = queue.Queue()
        self.received_data_callback = None
        self.receive_thread = None
        
    def update_ports(self):
        """获取当前可用的串口列表"""
        return [p.device for p in serial.tools.list_ports.comports()]
    
    def log(self, msg):
        """记录日志到文件"""
        ts = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")
        self.logfile.write(ts + msg + "\n")
        self.logfile.flush()
    
    def toggle_serial(self, port, baud_rate):
        """打开或关闭串口"""
        if self.ser and self.ser.is_open:
            self.running = False
            if self.receive_thread and self.receive_thread.is_alive():
                self.receive_thread.join(timeout=1.0)
            self.ser.close()
            return True, "串口已关闭"
        else:
            try:
                self.ser = serial.Serial(port, int(baud_rate), timeout=0.1)
                self.running = True
                self.receive_thread = threading.Thread(target=self.read_thread, daemon=True)
                self.receive_thread.start()
                return True, "串口已打开"
            except Exception as e:
                return False, str(e)
    
    def send_data(self, data):
        """发送数据到串口"""
        if not self.ser or not self.ser.is_open:
            return False, "串口未打开"
        try:
            self.ser.write(data)
            line = f">>> 发送: {data.hex().upper()}"
            self.log(line)
            return True, line
        except Exception as e:
            error_msg = f"发送错误: {str(e)}"
            self.log(error_msg)
            return False, error_msg
    
    def read_thread(self):
        """接收数据的线程函数"""
        buffer = bytearray()
        while self.running:
            try:
                if self.ser and self.ser.is_open:
                    chunk = self.ser.read(1)
                    if chunk:
                        buffer.extend(chunk)
                        if self.received_data_callback:
                            self.received_data_callback(buffer)
                time.sleep(0.001)  # 防止CPU占用过高
            except Exception as e:
                err = f"[接收错误] {e}"
                self.log(err)
                time.sleep(0.1)
    
    def close(self):
        """关闭串口和日志文件"""
        self.running = False
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)
        if self.ser and self.ser.is_open:
            self.ser.close()
        if self.logfile:
            self.logfile.close()
            self.logfile = None
    
    def is_connected(self):
        """检查串口是否连接"""
        return self.ser is not None and self.ser.is_open