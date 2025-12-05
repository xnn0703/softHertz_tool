from abc import ABC, abstractmethod
import queue
from common.protocol_base import ProtocolBase

class DeviceBase(ABC):
    """设备抽象基类"""
    
    def __init__(self, communication_controller, protocol: ProtocolBase):
        self.communication_controller = communication_controller
        self.protocol = protocol
        self.communication_controller.received_data_callback = self.on_received_data
        self.response_queue = queue.Queue()
    
    @abstractmethod
    def on_received_data(self, data: bytearray):
        """处理接收到的数据"""
        pass
    
    @abstractmethod
    def send_command(self, command_name: str, params=None) -> bool:
        """发送命令到设备"""
        pass
    
    @abstractmethod
    def query_device_info(self) -> dict:
        """查询设备信息"""
        pass
    
    @abstractmethod
    def get_supported_commands(self) -> list:
        """获取设备支持的命令列表"""
        pass
    
    def is_connected(self) -> bool:
        """检查设备是否连接"""
        return self.communication_controller.is_connected()