"""
串口通信优化测试用例
"""

import pytest
import time
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from protocol import build_frame, parse_response, crc16_ccitt
from afdt1024_protocol import (
    build_frame as afdt_build_frame,
    parse_response as afdt_parse_response,
    parse_status_response,
    parse_rx_status_response,
    calculate_checksum,
    FRAME_HEADER,
)


class TestProtocolParsing:
    """协议解析测试"""

    def test_aa55_frame_build_and_parse(self):
        """测试AA55帧构建和解析"""
        payload = b"\x0b\x00\x00\x00\x00\x00"
        frame = build_frame(payload)

        assert frame[:2] == b"\xaa\x55"
        assert len(frame) == 12

        parsed, msg = parse_response(frame)
        assert msg == "OK"
        assert parsed[0] == 0x0B

    def test_aa55_frame_invalid_length(self):
        """测试AA55帧长度不足"""
        frame = b"\xaa\x55\x0c\x00\x0b"
        parsed, msg = parse_response(frame)
        assert msg == "长度不足"

    def test_aa55_frame_invalid_header(self):
        """测试AA55帧帧头错误"""
        frame = b"\xab\x55\x0c\x00\x0b\x00\x00\x00\x00\x00\x00\x00"
        parsed, msg = parse_response(frame)
        assert msg == "帧头错误"

    def test_aa55_frame_crc_error(self):
        """测试AA55帧CRC错误"""
        payload = b"\x0b\x00\x00\x00\x00\x00"
        frame = build_frame(payload)
        frame = frame[:-1] + b"\xff\xff"
        parsed, msg = parse_response(frame)
        assert len(msg) > 0

    def test_afdt_frame_build(self):
        """测试AFDT帧构建"""
        device_id = 1
        addr = 0x5C
        payload = b"\x00\x01\x2a\x19\x01"
        frame = afdt_build_frame(device_id, addr, payload)

        assert frame[:3] == FRAME_HEADER
        assert frame[3] == device_id
        assert frame[4] == len(payload) + 1

    def test_afdt_frame_parse(self):
        """测试AFDT帧解析"""
        device_id = 1
        addr = 0x5C
        payload = b"\x00\x01\x2a\x19\x01"
        frame = afdt_build_frame(device_id, addr, payload)

        parsed, msg = afdt_parse_response(frame)
        assert msg == "OK"
        assert parsed["device_id"] == device_id
        assert parsed["addr"] == addr

    def test_status_response_parsing(self):
        """测试TX状态响应解析
        格式: [Rev][state][SysVcc][SysTemp][ATT_Tc][MCU_VER]
        """
        payload = b"\x00\x01\x77\x77\x01\x02"
        status, msg = parse_status_response(payload)

        assert msg == "OK"
        assert status["rev"] == 0
        assert status["state"] == 1
        assert status["sys_vcc"] == 11.9  # 119 * 0.1
        assert status["sys_temp"] == 39  # 119 - 80

    def test_rx_status_response_parsing(self):
        """测试RX状态响应解析
        格式: [Rev][SysVcc][SysTemp][ATT_Tc][MCU_VER] (5字节)
        """
        payload = b"\x01\xc8\x96\x50\x03"
        status, msg = parse_rx_status_response(payload)

        assert msg == "OK"
        assert status["rev"] == 1
        assert status["sys_vcc"] == 20.0
        assert status["sys_temp"] == 70


class TestBufferOverflow:
    """Buffer边界测试"""

    def test_length_field_overflow(self):
        """测试长度字段异常大"""
        malicious_frame = b"\x50\x53\x41\x01\xff" + b"\x00" * 255 + b"\x00"

        length = malicious_frame[4]
        assert length == 0xFF

        parsed, msg = afdt_parse_response(malicious_frame)
        assert msg in ["长度不匹配", "校验和错误"]

    def test_frame_max_length(self):
        """测试最大帧长限制"""
        max_payload = b"\x00" * 255
        frame = b"\x50\x53\x41\x01\xff" + max_payload + b"\x00"

        assert len(frame) == 3 + 1 + 1 + 255 + 1

    def test_incomplete_frame(self):
        """测试不完整帧"""
        incomplete_frame = b"\x50\x53\x41\x01\x0a"

        parsed, msg = afdt_parse_response(incomplete_frame)
        assert msg == "长度不匹配"


class TestMultiFrameHandling:
    """多帧处理测试"""

    def test_consecutive_aa55_frames(self):
        """测试连续AA55帧解析"""
        frame1 = build_frame(b"\x0b\x00\x00\x00\x00\x00")
        frame2 = build_frame(b"\x0c\x00\x00\x00\x00\x00")

        combined = frame1 + frame2

        buffer = bytearray(combined)
        frames = []

        while len(buffer) >= 12:
            if buffer[:2] == b"\xaa\x55":
                frame = bytes(buffer[:12])
                frames.append(frame)
                buffer = buffer[12:]
            else:
                break

        assert len(frames) == 2
        assert frames[0][4] == 0x0B
        assert frames[1][4] == 0x0C

    def test_consecutive_afdt_frames(self):
        """测试连续AFDT帧解析"""
        frame1 = afdt_build_frame(1, 0x5C, b"\x00\x01\x00\x00")
        frame2 = afdt_build_frame(2, 0x5C, b"\x00\x02\x00\x00")

        combined = frame1 + frame2

        buffer = bytearray(combined)
        frames = []

        while len(buffer) >= 5:
            if buffer[:3] == FRAME_HEADER:
                length = buffer[4]
                total = 5 + length + 1
                if len(buffer) >= total:
                    frame = bytes(buffer[:total])
                    frames.append(frame)
                    buffer = buffer[total:]
                else:
                    break
            else:
                break

        assert len(frames) == 2

    def test_mixed_frames(self):
        """测试混合帧解析"""
        afdt_frame = afdt_build_frame(1, 0x5C, b"\x00\x01")
        aa55_frame = build_frame(b"\x0b\x00\x00\x00\x00\x00")

        combined = afdt_frame + aa55_frame

        buffer = bytearray(combined)

        afdt_parsed = False
        aa55_parsed = False

        while len(buffer) >= 3:
            if buffer[:3] == FRAME_HEADER:
                length = buffer[4]
                total = 5 + length + 1
                if len(buffer) >= total:
                    frame = bytes(buffer[:total])
                    parsed, msg = afdt_parse_response(frame)
                    if msg == "OK":
                        afdt_parsed = True
                    buffer = buffer[total:]
                else:
                    break
            elif len(buffer) >= 2 and buffer[:2] == b"\xaa\x55":
                if len(buffer) >= 12:
                    frame = bytes(buffer[:12])
                    parsed, msg = parse_response(frame)
                    if msg == "OK":
                        aa55_parsed = True
                    buffer = buffer[12:]
                else:
                    break
            else:
                break

        assert afdt_parsed == True
        assert aa55_parsed == True


class TestPerformance:
    """性能测试"""

    def test_crc16_efficiency(self):
        """测试CRC16计算效率"""
        data = bytes(range(256)) * 100

        start = time.time()
        for _ in range(100):
            crc = crc16_ccitt(data)
        elapsed = time.time() - start

        assert elapsed < 10.0

    def test_checksum_efficiency(self):
        """测试校验和计算效率"""
        data = bytes(range(256)) * 100

        start = time.time()
        for _ in range(1000):
            cs = calculate_checksum(data)
        elapsed = time.time() - start

        assert elapsed < 0.5


class TestErrorHandling:
    """错误处理测试"""

    def test_parse_empty_data(self):
        """测试解析空数据"""
        parsed, msg = parse_response(b"")
        assert msg == "长度不足"

    def test_parse_single_byte(self):
        """测试解析单字节"""
        parsed, msg = parse_response(b"\xaa")
        assert msg == "长度不足"

    def test_afdt_parse_empty(self):
        """测试AFDT解析空数据"""
        parsed, msg = afdt_parse_response(b"")
        assert msg == "无效的帧头"

    def test_afdt_parse_truncated(self):
        """测试AFDT解析截断数据"""
        parsed, msg = afdt_parse_response(b"\x50\x53")
        assert msg == "无效的帧头"


class TestKaUDC004AProtocol:
    """KaUDC004A 协议测试"""

    def test_kaudc_build_version_query(self):
        """测试版本回读命令构建"""
        from protocol import build_version_query_frame, CMD_VERSION

        frame = build_version_query_frame()

        assert frame[:2] == b"\xaa\x55"
        assert frame[2] == 0x0C
        assert frame[3] == 0x00
        assert frame[4] == CMD_VERSION

    def test_kaudc_build_temperature_query(self):
        """测试温度查询命令构建"""
        from protocol import build_temp_query_frame, CMD_TEMP_QUERY

        frame = build_temp_query_frame()

        assert frame[:2] == b"\xaa\x55"
        assert frame[4] == CMD_TEMP_QUERY

    def test_kaudc_build_tx_lo_setting(self):
        """测试Tx LO设置命令构建 - CMD=0x12, freq at Byte8"""
        from protocol import build_tx_lo_frame, CMD_TX_LO

        frame = build_tx_lo_frame(0x02)

        assert frame[4] == CMD_TX_LO
        assert frame[8] == 0x02

    def test_kaudc_build_rx_lo_setting(self):
        """测试Rx LO设置命令构建 - CMD=0x0E, freq at Byte8"""
        from protocol import build_rx_lo_frame, CMD_RX_LO

        frame = build_rx_lo_frame(0x01)

        assert frame[4] == CMD_RX_LO
        assert frame[8] == 0x01

    def test_kaudc_build_tx_atten_setting(self):
        """测试Tx衰减设置命令构建 - CMD=0x14, att at Byte8"""
        from protocol import build_tx_att_frame, CMD_TX_ATT, ATT_MIN, ATT_MAX

        frame = build_tx_att_frame(150)

        assert frame[4] == CMD_TX_ATT
        assert frame[8] == 150
        assert ATT_MIN == 0
        assert ATT_MAX == 300

    def test_kaudc_build_rx_atten_setting(self):
        """测试Rx衰减设置命令构建 - CMD=0x15, att at Byte8"""
        from protocol import build_rx_att_frame, CMD_RX_ATT

        frame = build_rx_att_frame(200)

        assert frame[4] == CMD_RX_ATT
        assert frame[8] == 200

    def test_kaudc_parse_temperature_response(self):
        """测试温度响应解析"""
        from protocol import crc16_ccitt, parse_response, CMD_TEMP_QUERY

        header = b"\xaa\x55\x0c\x00"
        payload = bytes([CMD_TEMP_QUERY, 0x3C, 0x00, 0x00, 0x00, 0x00])
        crc = crc16_ccitt(header + payload)
        frame = header + payload + crc.to_bytes(2, "big")

        parsed, msg = parse_response(frame)
        assert msg == "OK"
        assert parsed[0] == CMD_TEMP_QUERY

    def test_kaudc_parse_lo_query_response(self):
        """测试本振查询响应解析"""
        from protocol import crc16_ccitt, parse_response, CMD_LO_QUERY

        header = b"\xaa\x55\x0c\x00"
        payload = bytes([CMD_LO_QUERY, 0x02, 0x01, 0x07, 0x00, 0x00])
        crc = crc16_ccitt(header + payload)
        frame = header + payload + crc.to_bytes(2, "big")

        parsed, msg = parse_response(frame)
        assert msg == "OK"
        assert parsed[0] == CMD_LO_QUERY

    def test_kaudc_parse_atten_query_response(self):
        """测试衰减查询响应解析"""
        from protocol import crc16_ccitt, parse_response, CMD_ATT_QUERY

        header = b"\xaa\x55\x0c\x00"
        payload = bytes([CMD_ATT_QUERY, 0x96, 0x64, 0x00, 0x00, 0x00])
        crc = crc16_ccitt(header + payload)
        frame = header + payload + crc.to_bytes(2, "big")

        parsed, msg = parse_response(frame)
        assert msg == "OK"
        assert parsed[0] == CMD_ATT_QUERY


class TestKaUDC004AChecksum:
    """KaUDC004A CRC 校验测试"""

    def test_crc_calculation(self):
        """测试CRC16计算"""
        data = b"\xaa\x55\x0c\x00\x0b\x00\x00\x00"
        crc = crc16_ccitt(data)

        assert isinstance(crc, int)
        assert 0 <= crc <= 0xFFFF

    def test_crc_consistency(self):
        """测试CRC计算一致性"""
        data = bytes(range(20))
        crc1 = crc16_ccitt(data)
        crc2 = crc16_ccitt(data)

        assert crc1 == crc2

    def test_frame_with_valid_crc(self):
        """测试带有效CRC的帧"""
        payload = b"\x0b\x00\x00\x00\x00\x00"
        frame = build_frame(payload)

        crc_recv = int.from_bytes(frame[-2:], "big")
        crc_calc = crc16_ccitt(frame[:-2])

        assert crc_recv == crc_calc


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
