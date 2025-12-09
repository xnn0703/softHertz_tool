import threading
import datetime
import queue

class CommunicationBase:
    """通信控制器基类，定义统一的通信接口"""
    
    def __init__(self):
        self.running = False
        # 使用统一的日志文件
        self.logfile = open("log.txt", "a", encoding="utf-8")
        self.response_queue = queue.Queue()
        self.received_data_callback = None
        self.receive_thread = None
        # 性能测试模式标志
        self.performance_test_mode = False
        # 通信类型标志，由子类设置
        self.comm_type = "base"
        
    def log(self, msg):
        """记录日志到文件"""
        # 防御性检查，确保logfile存在
        if not hasattr(self, 'logfile') or self.logfile is None:
            # 如果日志文件不存在，尝试重新打开或输出到控制台
            try:
                print(f"[日志] {msg}")
                # 尝试重新打开日志文件
                try:
                    self.logfile = open("log.txt", "a", encoding="utf-8")
                    self.log(f"[系统] 重新打开了日志文件")
                except:
                    pass
            except:
                # 终极防御，避免任何异常
                pass
            return
        
        try:
            ts = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")
            # 添加通信类型tag
            self.logfile.write(ts + f"[{self.comm_type}] " + msg + "\n")
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
    
    def set_callback(self, callback):
        """设置数据接收回调函数"""
        self.received_data_callback = callback
    
    def send_data(self, data):
        """发送数据，子类必须实现"""
        raise NotImplementedError("send_data method must be implemented by subclass")
    
    def toggle_connection(self, *args, **kwargs):
        """打开或关闭连接，子类必须实现"""
        raise NotImplementedError("toggle_connection method must be implemented by subclass")
    
    def is_connected(self):
        """检查连接状态，子类必须实现"""
        raise NotImplementedError("is_connected method must be implemented by subclass")
    
    def close(self):
        """关闭连接，子类必须实现"""
        raise NotImplementedError("close method must be implemented by subclass")
    
    def read_thread(self):
        """接收数据线程，子类必须实现"""
        raise NotImplementedError("read_thread method must be implemented by subclass")
