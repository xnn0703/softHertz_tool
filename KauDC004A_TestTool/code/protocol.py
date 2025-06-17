def crc16_ccitt(data: bytes, poly=0x1021, init_val=0xFFFF):
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
    assert len(payload) == 6
    header = b'\xAA\x55\x0C\x00'
    body = header + payload
    crc = crc16_ccitt(body)
    return body + crc.to_bytes(2, 'big')

def parse_response(data: bytes):
    if len(data) != 12:
        return None, "长度不足"
    if data[:2] != b'\xAA\x55':
        return None, "帧头错误"
    crc_recv = int.from_bytes(data[-2:], 'big')
    crc_calc = crc16_ccitt(data[:-2])
    if crc_recv != crc_calc:
        return None, "CRC错误"
    return data[4:10], "OK"
