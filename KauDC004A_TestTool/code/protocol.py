def crc16_ccitt(data: bytes, poly=0x1021, init_val=0xFFFF):
    """CRC-16/CCITT checksum calculation.

    Polynomial: G(X) = X^16 + X^12 + X^5 + 1 (0x1021)
    Initial value: 0xFFFF
    CRC covers bytes 0-9 (header + payload)
    """
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


def build_frame(payload: bytes) -> bytes:
    """Build KaUDC004A frame.

    Frame structure (12 bytes total):
    - Header: 0xAA 0x55 0x0C 0x00 (4 bytes)
    - Payload: Byte4-Byte9 (6 bytes)
    - CRC: 2 bytes (covers header + payload = bytes 0-9)
    """
    assert len(payload) == 6, f"Payload must be 6 bytes, got {len(payload)}"
    header = b"\xaa\x55\x0c\x00"
    body = header + payload
    crc = crc16_ccitt(body)
    return body + crc.to_bytes(2, "big")


def parse_response(data: bytes):
    """Parse KaUDC004A response frame.

    Returns:
        tuple: (payload_data[4:10], status_message)
    """
    if len(data) != 12:
        return None, f"帧长度错误: 期望12字节, 收到{len(data)}字节"
    if data[:2] != b"\xaa\x55":
        return None, "帧头错误: 期望 AA 55"
    if data[2:4] != b"\x0c\x00":
        return None, f"帧头错误: 期望 0C 00, 收到 {data[2:4].hex()}"
    crc_recv = int.from_bytes(data[-2:], "big")
    crc_calc = crc16_ccitt(data[:-2])
    if crc_recv != crc_calc:
        return None, f"CRC错误: 计算={crc_calc:04X}, 接收={crc_recv:04X}"
    return data[4:10], "OK"


# =============================================================================
# Command Constants (from official protocol DOC\KauDC004A_protocol.md)
# =============================================================================

# Command codes
CMD_RESET = 0x0A  # 复位命令
CMD_VERSION = 0x0B  # 版本回读
CMD_TEMP_QUERY = 0x0C  # 温度查询
CMD_RX_LO = 0x0E  # 接收本振设置
CMD_TX_LO = 0x12  # 发射本振设置
CMD_LO_QUERY = 0x13  # 本振查询
CMD_TX_ATT = 0x14  # 发射衰减
CMD_RX_ATT = 0x15  # 接收衰减
CMD_ATT_QUERY = 0x16  # 衰减查询

# Attenuation range: 0-300 (value/10 = dB, e.g., 300 = 30.0 dB)
ATT_MIN = 0
ATT_MAX = 300
ATT_STEP = 0.1  # dB per unit

# Temperature encoding: 0x80 = 0°C, <0x80 negative, >0x80 positive
TEMP_OFFSET = 0x80
TEMP_RESOLUTION = 1  # °C per bit


def decode_temperature(byte_val: int) -> int:
    """Decode temperature from KaUDC004A response.

    Args:
        byte_val: Temperature byte from response (Byte5/data[1])

    Returns:
        Temperature in degrees Celsius
    """
    return byte_val 
    # if byte_val >= TEMP_OFFSET:
    #     return byte_val - TEMP_OFFSET  # Positive temperature
    # else:
    #     return -(TEMP_OFFSET - byte_val)  # Negative temperature


def decode_att_db(byte_val: int) -> float:
    """Decode attenuation from KaUDC004A response.

    Args:
        byte_val: Attenuation byte from response

    Returns:
        Attenuation in dB
    """
    return byte_val / 10.0


def build_reset_frame() -> bytes:
    """Build reset command frame (0x0A)."""
    return build_frame(bytes([CMD_RESET, 0x00, 0x00, 0x00, 0x00, 0x00]))


def build_version_query_frame() -> bytes:
    """Build version query command frame (0x0B)."""
    return build_frame(bytes([CMD_VERSION, 0x00, 0x00, 0x00, 0x00, 0x00]))


def build_temp_query_frame() -> bytes:
    """Build temperature query command frame (0x0C)."""
    return build_frame(bytes([CMD_TEMP_QUERY, 0x00, 0x00, 0x00, 0x00, 0x00]))


def build_rx_lo_frame(freq_mhz: int) -> bytes:
    """Build RX LO frequency setting command frame (0x0E).

    Args:
        freq_mhz: RX LO frequency in MHz (e.g., 17250 for 17.25 GHz)

    Returns:
        12-byte command frame
    """
    freq_bytes = freq_mhz.to_bytes(2, "big")
    return build_frame(bytes([CMD_RX_LO, 0x00, 0x00, 0x00]) + freq_bytes)


def build_tx_lo_frame(freq_mhz: int) -> bytes:
    """Build TX LO frequency setting command frame (0x12).

    Args:
        freq_mhz: TX LO frequency in MHz (e.g., 28050 for 28.05 GHz)

    Returns:
        12-byte command frame
    """
    freq_bytes = freq_mhz.to_bytes(2, "big")
    return build_frame(bytes([CMD_TX_LO, 0x00, 0x00, 0x00]) + freq_bytes)


def build_lo_query_frame() -> bytes:
    """Build LO frequency query command frame (0x13)."""
    return build_frame(bytes([CMD_LO_QUERY, 0x00, 0x00, 0x00, 0x00, 0x00]))


def build_tx_att_frame(att_value: int) -> bytes:
    """Build TX attenuation setting command frame (0x14).

    Args:
        att_value: Attenuation value (0-300, represents 0-30.0 dB)

    Returns:
        12-byte command frame
    """
    assert ATT_MIN <= att_value <= ATT_MAX, f"Attenuation must be {ATT_MIN}-{ATT_MAX}"
    att_bytes = att_value.to_bytes(2, "big")
    # Payload: [CMD][0x00][0x00][0x00][ATT_H][ATT_L]
    return build_frame(bytes([CMD_TX_ATT, 0x00, 0x00, 0x00]) + att_bytes)


def build_rx_att_frame(att_value: int) -> bytes:
    """Build RX attenuation setting command frame (0x15).

    Args:
        att_value: Attenuation value (0-300, represents 0-30.0 dB)

    Returns:
        12-byte command frame
    """
    assert ATT_MIN <= att_value <= ATT_MAX, f"Attenuation must be {ATT_MIN}-{ATT_MAX}"
    att_bytes = att_value.to_bytes(2, "big")
    # Payload: [CMD][0x00][0x00][0x00][ATT_H][ATT_L]
    return build_frame(bytes([CMD_RX_ATT, 0x00, 0x00, 0x00]) + att_bytes)


def build_att_query_frame() -> bytes:
    """Build attenuation query command frame (0x16)."""
    return build_frame(bytes([CMD_ATT_QUERY, 0x00, 0x00, 0x00, 0x00, 0x00]))


def parse_response_data(data: bytes) -> dict:
    """Parse KaUDC004A response payload and return structured data.

    Args:
        data: 6-byte payload (data[4:10] from parsed frame)

    Returns:
        dict with keys: 'cmd', 'values', 'temperature', 'lo', 'att', etc.
    """
    result = {"cmd": data[0]}

    cmd = data[0]

    if cmd == CMD_VERSION:
        # Response: [0x0B][版本号][0x00][0x00][0x00][0x00]
        result["version"] = data[1]

    elif cmd == CMD_TEMP_QUERY:
        # Response: [0x0C][Temp][0x00][0x00][0x00][0x00]
        result["temperature"] = decode_temperature(data[1])

    elif cmd == CMD_RX_LO:
        # Response: [0x0E][0x00][0x00][0x00][RxLO_Freq_H][RxLO_Freq_L]
        result["rx_lo"] = int.from_bytes(data[4:6], "big")

    elif cmd == CMD_TX_LO:
        # Response: [0x12][0x00][0x00][0x00][TxLO_Freq_H][TxLO_Freq_L]
        result["tx_lo"] = int.from_bytes(data[4:6], "big")

    elif cmd == CMD_LO_QUERY:
        # Response: [0x13][TxLO_Freq_H][TxLO_Freq_L][RxLO_Freq_H][RxLO_Freq_L][LOCK_ST]
        result["tx_lo"] = int.from_bytes(data[1:3], "big")
        result["rx_lo"] = int.from_bytes(data[3:5], "big")
        result["lock_status"] = data[5]

    elif cmd == CMD_TX_ATT:
        # Response: [0x14][0x00][0x00][0x00][Tx_ATT_H][Tx_ATT_L]
        result["tx_att"] = int.from_bytes(data[4:6], "big")
        result["tx_att_db"] = decode_att_db(result["tx_att"])

    elif cmd == CMD_RX_ATT:
        # Response: [0x15][0x00][0x00][0x00][Rx_ATT_H][Rx_ATT_L]
        result["rx_att"] = int.from_bytes(data[4:6], "big")
        result["rx_att_db"] = decode_att_db(result["rx_att"])

    elif cmd == CMD_ATT_QUERY:
        # Response: [0x16][Tx_ATT_H][Tx_ATT_L][Rx_ATT_H][Rx_ATT_L][0x00]
        result["tx_att"] = int.from_bytes(data[1:3], "big")
        result["rx_att"] = int.from_bytes(data[3:5], "big")
        result["tx_att_db"] = decode_att_db(result["tx_att"])
        result["rx_att_db"] = decode_att_db(result["rx_att"])

    elif cmd == CMD_RESET:
        # Response: [0x0A][0xFF][0x00][0x00][0x00][0x00]
        result["status"] = "reset_complete" if data[1] == 0xFF else "reset_failed"

    return result
