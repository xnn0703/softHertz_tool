from common.protocol_base import ProtocolBase, CRC16Calculator

class KauDC004AProtocol(ProtocolBase):
    """KauDC004A设备的协议实现"""
    
    def build_frame(self, payload: bytes) -> bytes:
        """构建KauDC004A设备的数据包帧"""
        assert len(payload) == 6
        header = b'\xAA\x55\x0C\x00'
        body = header + payload
        crc = CRC16Calculator.crc16_ccitt(body)
        return body + crc.to_bytes(2, 'big')
    
    def parse_response(self, data: bytes) -> tuple:
        """解析KauDC004A设备的响应数据包"""
        if len(data) != 12:
            return None, "长度不足"
        if data[:2] != b'\xAA\x55':
            return None, "帧头错误"
        crc_recv = int.from_bytes(data[-2:], 'big')
        crc_calc = CRC16Calculator.crc16_ccitt(data[:-2])
        if crc_recv != crc_calc:
            return None, "CRC错误"
        return data[4:10], "OK"
    
    def extract_data(self, cmd_byte: int, data: bytes) -> dict:
        """从解析后的数据中提取有用信息"""
        result = {}
        
        if cmd_byte == 0x0B:
            # 提取版本号：Byte5 到 Byte7，合并成一个 24 位的整数
            version_bytes = data[1:5]  # 取 Byte5, Byte6, Byte7 Byte8
            version = int.from_bytes(version_bytes, byteorder='big')  # 转换为十进制
            result['version'] = version
            result['display_text'] = f"版本号: {version}"
        elif cmd_byte == 0x0C:
            temp_c = data[1]
            result['temperature'] = temp_c
            result['display_text'] = f"温度: {temp_c}°C"
        elif cmd_byte == 0x13:
            tx = int.from_bytes(data[1:3], 'big')
            rx = int.from_bytes(data[3:5], 'big')
            bits = f"{data[5]:08b}"
            result['txlo'] = tx
            result['rxlo'] = rx
            result['lock'] = bits
            result['display_text'] = f"TxLO: {tx} MHz, RxLO: {rx} MHz, LOCK: {bits}"
        elif cmd_byte in (0x14, 0x15):
            att = int.from_bytes(data[4:6], 'big') / 10
            result['attenuation'] = att
            result['display_text'] = f"衰减: {att:.1f} dB"
        elif cmd_byte == 0x16:
            tx = int.from_bytes(data[1:3], 'big') / 10
            rx = int.from_bytes(data[3:5], 'big') / 10
            result['tx_attenuation'] = tx
            result['rx_attenuation'] = rx
            result['display_text'] = f"Tx衰减: {tx:.1f} dB, Rx衰减: {rx:.1f} dB"
        
        return result

    def extract_frequency(self, freq_str: str) -> int:
        """从频率字符串中提取频率值（MHz）"""
        try:
            ghz_part = freq_str.split()[0].replace("GHz", "")
            mhz = int(float(ghz_part) * 1000)
            return mhz
        except Exception:
            return 0