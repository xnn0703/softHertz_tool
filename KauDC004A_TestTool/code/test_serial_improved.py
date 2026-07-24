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
    calculate_beam_values,
    build_tx_beam_frame,
    build_rx_beam_frame,
    angle_to_code_12bit,
    ADDR_STATUS_QUERY,
    ADDR_RX_STATUS_QUERY,
    ADDR_TX_BEAM,
    ADDR_RX_BEAM,
    ADDR_TX_BEAM_QUERY,
    ADDR_RX_BEAM_QUERY,
    build_tx_beam_query_frame,
    build_rx_beam_query_frame,
    parse_beam_query_response,
    beam_code_to_angle,
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
        """测试AA55帧长度不足（协议固定12字节）"""
        frame = b"\xaa\x55\x0c\x00\x0b"
        parsed, msg = parse_response(frame)
        assert parsed is None
        assert "长度" in msg

    def test_aa55_frame_invalid_header(self):
        """测试AA55帧帧头错误"""
        frame = b"\xab\x55\x0c\x00\x0b\x00\x00\x00\x00\x00\x00\x00"
        parsed, msg = parse_response(frame)
        assert parsed is None
        assert "帧头错误" in msg

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
        assert parsed is None
        assert "长度" in msg

    def test_parse_single_byte(self):
        """测试解析单字节"""
        parsed, msg = parse_response(b"\xaa")
        assert parsed is None
        assert "长度" in msg

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
        """测试Tx LO设置命令构建 - CMD=0x12, TxLO_Freq 在 Byte8-9(大端, MHz)"""
        from protocol import build_tx_lo_frame, CMD_TX_LO

        frame = build_tx_lo_frame(28050)

        assert frame[4] == CMD_TX_LO
        assert int.from_bytes(frame[8:10], "big") == 28050

    def test_kaudc_build_rx_lo_setting(self):
        """测试Rx LO设置命令构建 - CMD=0x0E, RxLO_Freq 在 Byte8-9(大端, MHz)"""
        from protocol import build_rx_lo_frame, CMD_RX_LO

        frame = build_rx_lo_frame(17250)

        assert frame[4] == CMD_RX_LO
        assert int.from_bytes(frame[8:10], "big") == 17250

    def test_kaudc_build_tx_atten_setting(self):
        """测试Tx衰减设置命令构建 - CMD=0x14, Tx_ATT 在 Byte8-9(大端, 0~300)"""
        from protocol import build_tx_att_frame, CMD_TX_ATT, ATT_MIN, ATT_MAX

        frame = build_tx_att_frame(150)

        assert frame[4] == CMD_TX_ATT
        assert int.from_bytes(frame[8:10], "big") == 150
        assert ATT_MIN == 0
        assert ATT_MAX == 300

    def test_kaudc_build_rx_atten_setting(self):
        """测试Rx衰减设置命令构建 - CMD=0x15, Rx_ATT 在 Byte8-9(大端, 0~300)"""
        from protocol import build_rx_att_frame, CMD_RX_ATT

        frame = build_rx_att_frame(200)

        assert frame[4] == CMD_RX_ATT
        assert int.from_bytes(frame[8:10], "big") == 200

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


def _build_afdt_frame(device_id, payload):
    """按 V2.1 组帧（payload 含末尾指令号），返回完整帧"""
    frame = FRAME_HEADER + bytes([device_id, len(payload)]) + payload
    return frame + bytes([calculate_checksum(frame)])


class TestV21StatusFrame:
    """V2.1 查询返回帧：末尾含指令号、正常全字段校验和"""

    def test_tx_status_frame_end_to_end(self):
        # [Rev][STATE][Vcc=119][Temp=119][ATT][MCU][0x5C]，数据长度=7
        payload = bytes([0x01, 0x01, 0x77, 0x77, 0x01, 0x02, ADDR_STATUS_QUERY])
        frame = _build_afdt_frame(1, payload)

        parsed, msg = afdt_parse_response(frame)
        assert msg == "OK"
        assert parsed["addr"] == ADDR_STATUS_QUERY
        assert len(parsed["payload"]) == 6

        status, smsg = parse_status_response(parsed["payload"])
        assert smsg == "OK"
        assert status["sys_vcc"] == 11.9
        assert status["sys_temp"] == 39
        assert status["pa_en"] == 1

    def test_rx_status_frame_end_to_end(self):
        # [Rev][Vcc=200][Temp=150][ATT][MCU][0x9C]，数据长度=6
        payload = bytes([0x4A, 0xC8, 0x96, 0x04, 0x02, ADDR_RX_STATUS_QUERY])
        frame = _build_afdt_frame(1, payload)

        parsed, msg = afdt_parse_response(frame)
        assert msg == "OK"
        assert parsed["addr"] == ADDR_RX_STATUS_QUERY
        assert len(parsed["payload"]) == 5

        status, smsg = parse_rx_status_response(parsed["payload"])
        assert smsg == "OK"
        assert status["sys_vcc"] == 20.0
        assert status["sys_temp"] == 70

    def test_tx_status_data_length_is_7(self):
        payload = bytes([0x01, 0x01, 0x77, 0x77, 0x01, 0x02, ADDR_STATUS_QUERY])
        assert _build_afdt_frame(1, payload)[4] == 7

    def test_rx_status_data_length_is_6(self):
        payload = bytes([0x4A, 0xC8, 0x96, 0x04, 0x02, ADDR_RX_STATUS_QUERY])
        assert _build_afdt_frame(1, payload)[4] == 6


# 协议示例表 (freq, theta=离轴角, phi=方位角, 期望 BeamV, 期望 BeamH)
TX_BEAM_CASES = [
    (29500, 0, 0, 0, 0),
    (29500, 30, 0, 0, 1007),
    (29500, 30, 45, 712, 712),
    (29500, 30, 90, 1007, 0),
    (29500, 30, 135, 712, 3384),
    (29500, 30, 225, 3384, 3384),
    (29500, 30, 315, 3384, 712),
    (30000, 30, 45, 724, 724),
]

RX_BEAM_CASES = [
    (19450, 0, 0, 0, 0),
    (19450, 30, 0, 0, 983),
    (19450, 30, 45, 695, 695),
    (19450, 30, 90, 983, 0),
    (19450, 30, 135, 695, 3401),
    (19450, 30, 225, 3401, 3401),
    (19450, 30, 315, 3401, 695),
    (20000, 30, 45, 714, 714),
]


class TestV21BeamCalc:
    """V2.1 波控值计算（与协议示例表逐行一致）"""

    @pytest.mark.parametrize("freq,theta,phi,exp_v,exp_h", TX_BEAM_CASES)
    def test_tx_beam_values(self, freq, theta, phi, exp_v, exp_h):
        beam_h, beam_v = calculate_beam_values(theta, phi, freq, is_tx=True)
        assert beam_v == exp_v
        assert beam_h == exp_h

    @pytest.mark.parametrize("freq,theta,phi,exp_v,exp_h", RX_BEAM_CASES)
    def test_rx_beam_values(self, freq, theta, phi, exp_v, exp_h):
        beam_h, beam_v = calculate_beam_values(theta, phi, freq, is_tx=False)
        assert beam_v == exp_v
        assert beam_h == exp_h

    def test_angle_to_code_basic(self):
        assert angle_to_code_12bit(0) == 0
        assert angle_to_code_12bit(180) == 2048
        assert angle_to_code_12bit(-180) == 2048  # -2048+4096
        assert 0 <= angle_to_code_12bit(123.4) < 4096


class TestV21BeamFrame:
    """V2.1 波束帧构建与 12bit 打包"""

    def test_tx_beam_frame_structure(self):
        frame = build_tx_beam_frame(1, 0, 712, 712)  # (id, freq, beam_h, beam_v)
        assert frame[:3] == FRAME_HEADER
        assert frame[3] == 1
        assert frame[4] == 5
        assert frame[5:-1][-1] == ADDR_TX_BEAM
        assert frame[-1] == calculate_checksum(frame[:-1])

    def test_rx_beam_frame_structure(self):
        frame = build_rx_beam_frame(2, 0, 695, 695)
        assert frame[:3] == FRAME_HEADER
        assert frame[3] == 2
        assert frame[4] == 5
        assert frame[5:-1][-1] == ADDR_RX_BEAM
        assert frame[-1] == calculate_checksum(frame[:-1])

    def test_beam_pack_no_bit_loss(self):
        # 验证 12bit BeamV/BeamH 完整打包，无丢位
        beam_v, beam_h = 0xABC, 0x123
        data = build_tx_beam_frame(1, 5, beam_h, beam_v)[5:-1]  # [FREQ][B2][B1][B0][ADDR]
        assert data[0] == 5  # FREQ
        v = (data[1] << 4) | (data[2] >> 4)
        h = ((data[2] & 0x0F) << 8) | data[3]
        assert v == beam_v
        assert h == beam_h


class TestMultiSubarray:
    """多子阵：状态回复按 device_id 路由"""

    def test_sim_tx_status_per_id(self):
        """TX 模拟器对不同 ID 返回带对应 device_id 的状态帧"""
        from device_simulator import TXSimulator

        sim = TXSimulator("dummy", ids=[1, 2, 3])
        for sid in (1, 2, 3):
            frame = sim.build_status_response(sid)
            parsed, msg = afdt_parse_response(frame)
            assert msg == "OK"
            assert parsed["device_id"] == sid
            assert parsed["addr"] == ADDR_STATUS_QUERY
            st, sm = parse_status_response(parsed["payload"])
            assert sm == "OK"
            # 电压随 ID 递增：115+sid → ×0.1
            assert abs(st["sys_vcc"] - (115 + sid) * 0.1) < 1e-6

    def test_sim_rx_status_per_id(self):
        """RX 模拟器对不同 ID 返回带对应 device_id 的状态帧"""
        from device_simulator import RXSimulator

        sim = RXSimulator("dummy", ids=[1, 2, 3])
        for sid in (1, 2, 3):
            frame = sim.build_rx_status_response(sid)
            parsed, msg = afdt_parse_response(frame)
            assert msg == "OK"
            assert parsed["device_id"] == sid
            assert parsed["addr"] == ADDR_RX_STATUS_QUERY
            st, sm = parse_rx_status_response(parsed["payload"])
            assert sm == "OK"
            assert abs(st["sys_vcc"] - (115 + sid) * 0.1) < 1e-6

    def test_status_frame_with_plus128_id(self):
        """用 ID+128 查询时，回复帧 device_id 低 7 位仍能匹配子阵 ID"""
        from device_simulator import TXSimulator

        sim = TXSimulator("dummy", ids=[5])
        frame = sim.build_status_response(5)
        parsed, _ = afdt_parse_response(frame)
        # UI 路由用 device_id & 0x7F
        assert (parsed["device_id"] & 0x7F) == 5


class TestV22BeamQuery:
    """V2.2 查询指令2（波束参数）"""

    def test_beam_query_frame_build(self):
        f = build_tx_beam_query_frame(1)
        assert f[:3] == FRAME_HEADER
        assert f[3] == 1
        assert f[4] == 1  # 数据长度=1
        assert f[5] == ADDR_TX_BEAM_QUERY  # 0x5F
        assert f[-1] == calculate_checksum(f[:-1])
        assert build_rx_beam_query_frame(2)[5] == ADDR_RX_BEAM_QUERY  # 0x9F

    def test_beam_query_parse_roundtrip(self):
        # 用模拟器构造含已知配置的查询2返回帧，再解析回读
        from device_simulator import (
            build_beam_query_response,
            record_config,
            ADDR_TX_BEAM,
            ADDR_TX_ENABLE,
            ADDR_TX_POLARIZATION,
        )

        states = {}
        bv, bh = 712, 712
        beam_payload = bytes(
            [40, (bv >> 4) & 0xFF, ((bv & 0x0F) << 4) | ((bh >> 8) & 0x0F), bh & 0xFF]
        )
        record_config(states, 2, ADDR_TX_BEAM, beam_payload)
        record_config(states, 2, ADDR_TX_ENABLE, bytes([0xFF, 0xFF, 0xFF, 0xFF]))
        record_config(states, 2, ADDR_TX_POLARIZATION, bytes([0, 0, 0, 1]))  # RHCP

        frame = build_beam_query_response(2, 2, states, ADDR_TX_BEAM_QUERY)
        parsed, msg = afdt_parse_response(frame)
        assert msg == "OK"
        assert parsed["addr"] == ADDR_TX_BEAM_QUERY
        assert parsed["device_id"] == 2

        info, imsg = parse_beam_query_response(parsed["payload"], is_tx=True)
        assert imsg == "OK"
        assert info["pol"] == 1
        assert info["en_row"] == 0xFFFF
        assert info["beam_v"] == 712
        assert info["beam_h"] == 712
        assert info["freq_mhz"] == 27500 + 50 * 40  # 29500

    def test_beam_code_to_angle(self):
        # 协议示例: 29500, BeamV=712, BeamH=712 -> θ≈30, φ≈45
        theta, phi = beam_code_to_angle(712, 712, 29500, is_tx=True)
        assert abs(theta - 30) < 0.5
        assert abs(phi - 45) < 0.5
        # BeamH=3384 (负) -> φ≈135
        theta2, phi2 = beam_code_to_angle(712, 3384, 29500, is_tx=True)
        assert abs(theta2 - 30) < 0.5
        assert abs(phi2 - 135) < 0.5
        # 全 0 -> θ=0
        t0, _ = beam_code_to_angle(0, 0, 29500, is_tx=True)
        assert abs(t0) < 0.5

    def test_beam_roundtrip_with_quantized_freq(self):
        # UI频率20270不在50MHz网格上 -> 量化到20250；用量化频率算波束才能往返自洽
        freq_num = int((20270 - 17700) / 50)
        actual = 17700 + 50 * freq_num
        assert actual == 20250
        bh, bv = calculate_beam_values(50.2, 10.0, actual, is_tx=False)
        th, ph = beam_code_to_angle(bv, bh, actual, is_tx=False)
        assert abs(th - 50.2) < 0.05  # 自洽，仅剩亚码量化误差
        assert abs(ph - 10.0) < 0.1

    def test_sim_config_readback(self):
        # 配置回读闭环：LHCP + 使能关
        from device_simulator import (
            build_beam_query_response,
            record_config,
            ADDR_RX_POLARIZATION,
            ADDR_RX_ENABLE,
        )

        states = {}
        record_config(states, 5, ADDR_RX_POLARIZATION, bytes([0, 0, 0, 0]))  # LHCP
        record_config(states, 5, ADDR_RX_ENABLE, bytes([0x00, 0x00, 0xFF, 0xFF]))  # off
        frame = build_beam_query_response(5, 5, states, ADDR_RX_BEAM_QUERY)
        parsed, _ = afdt_parse_response(frame)
        info, _ = parse_beam_query_response(parsed["payload"], is_tx=False)
        assert info["pol"] == 0
        assert info["en_row"] == 0x0000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
