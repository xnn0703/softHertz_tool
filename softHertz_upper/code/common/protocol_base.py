from abc import ABC, abstractmethod

class ProtocolBase(ABC):
    """协议处理的抽象基类"""
    
    @abstractmethod
    def build_frame(self, payload: bytes) -> bytes:
        """构建数据包帧"""
        pass
    
    @abstractmethod
    def parse_response(self, data: bytes) -> tuple:
        """解析接收到的数据包"""
        pass
    
    @abstractmethod
    def extract_data(self, cmd_byte: int, data: bytes) -> dict:
        """从解析后的数据中提取有用信息"""
        pass

class CRC16Calculator:
    """CRC16校验计算器"""
    
    @staticmethod
    def crc16_ccitt(data: bytes, poly=0x1021, init_val=0xFFFF) -> int:
        """计算CRC16-CCITT校验值"""
        crc = init_val
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ poly
                else:
                    crc <<= 1
                crc &= 0xFFFF
        return crc