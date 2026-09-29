"""KuR512B 协议层与流式拆帧测试。"""

from __future__ import annotations

import math

import pytest

from soft_hertz_tool.devices.kur512 import protocol
from soft_hertz_tool.devices.kur512.models import Polarity
from soft_hertz_tool.devices.kur512.stream import KUR512StreamParser


def _checksum(frame: bytes) -> int:
    return sum(frame[:-1]) & 0xFF


def test_build_frame_matches_manual_construction():
    body = b"\x50\x53\x41\x01\x01\x9C"  # 不含 checksum
    expected_checksum = sum(body) & 0xFF
    frame = protocol.build_frame(0x01, 0x9C)
    assert frame == body + bytes([expected_checksum])
    assert frame[-1] == expected_checksum
    assert len(frame) == 7


def test_build_frame_rejects_invalid_device_id_and_addr():
    with pytest.raises(ValueError):
        protocol.build_frame(-1, 0x9C)
    with pytest.raises(ValueError):
        protocol.build_frame(0x01, -1)
    with pytest.raises(ValueError):
        protocol.build_frame(0x01, 0x9C, b"\x00" * 256)


def test_parse_response_round_trip():
    frame = protocol.build_status_query_frame(0x01)
    parsed, message = protocol.parse_response(frame)
    assert message == "OK"
    assert parsed["device_id"] == 0x01
    assert parsed["addr"] == protocol.ADDR_STATUS_QUERY
    assert parsed["payload"] == b""


def test_parse_response_rejects_bad_header_length_and_checksum():
    bad_header = b"\x50\x53\x42\x01\x01\x9C" + bytes([0])
    assert protocol.parse_response(bad_header)[0] is None
    short = b"\x50\x53\x41\x01\x01"
    assert protocol.parse_response(short)[0] is None
    bad_len = b"\x50\x53\x41\x01\x03\x9C" + bytes([0, 0])
    assert protocol.parse_response(bad_len)[0] is None
    bad_csum = b"\x50\x53\x41\x01\x01\x9C\x00"
    assert protocol.parse_response(bad_csum)[0] is None
    empty = b"\x50\x53\x41\x01\x00" + bytes([protocol.calculate_checksum(b"\x50\x53\x41\x01\x00")])
    assert protocol.parse_response(empty)[0] is None


def test_quantize_frequency_grid():
    assert protocol.quantize_frequency(10700) == (0, 10700)
    assert protocol.quantize_frequency(12750) == (41, 12750)
    assert protocol.quantize_frequency(11700) == (20, 11700)
    assert protocol.quantize_frequency(11725)[0] == 20  # 量化到 50 MHz 步进


def test_quantize_frequency_rejects_out_of_range():
    with pytest.raises(ValueError):
        protocol.quantize_frequency(10699)
    with pytest.raises(ValueError):
        protocol.quantize_frequency(12751)
    with pytest.raises(ValueError):
        protocol.quantize_frequency(float("nan"))


def test_angle_to_code_12bit_matches_protocol_table():
    assert protocol.angle_to_code_12bit(0) == 0
    assert protocol.angle_to_code_12bit(180) == 2048
    assert protocol.angle_to_code_12bit(-180) == 2048
    assert protocol.angle_to_code_12bit(90) == 1024
    # 受控原件表 11700 MHz, θ=30, φ=90 → BeamV=958
    beam_h, beam_v = protocol.calculate_beam_values(30, 90, 11700)
    assert beam_v == 958
    assert beam_h == 0


def test_beam_payload_packs_freq_pol_beam():
    payload = protocol.build_beam_command(20, Polarity.LINEAR, 30, 0, 958)
    freq_code, pol_byte, beam_h, beam_v = protocol.unpack_beam_payload(payload)
    assert freq_code == 20
    assert pol_byte == 30
    assert beam_h == 0
    assert beam_v == 958
    # 12500 MHz θ=30 φ=45 → BeamV/H=724 受控原件表
    setting = protocol.make_beam_setting(12500, 30, 45, Polarity.RHCP, 0)
    frame = protocol.build_beam_frame(0x01, setting)
    parsed, _ = protocol.parse_response(frame)
    assert parsed["device_id"] == 0x01
    assert parsed["addr"] == protocol.ADDR_RX_BEAM
    freq_code, pol_byte, beam_h, beam_v = protocol.unpack_beam_payload(parsed["payload"])
    assert freq_code == 36
    assert pol_byte == protocol.POL_RHCP
    assert beam_v == 724
    assert beam_h == 724


def test_polarity_bytes_have_special_values():
    assert protocol.build_beam_command(0, Polarity.LHCP, 0, 0, 0)[1] == protocol.POL_LHCP
    assert protocol.build_beam_command(0, Polarity.RHCP, 0, 0, 0)[1] == protocol.POL_RHCP
    with pytest.raises(ValueError):
        protocol.build_beam_command(0, Polarity.LINEAR, 181, 0, 0)
    with pytest.raises(ValueError):
        protocol.build_beam_command(0, Polarity.LINEAR, -1, 0, 0)


def test_enable_command_uses_16bit_en_row_and_low_12bit_fff():
    on = protocol.build_enable_command(True)
    off = protocol.build_enable_command(False)
    # 4 字节载荷
    assert len(on) == 4
    assert len(off) == 4
    # 低 12 bit 必须固定为 0xFFF
    assert (on[2] & 0x0F) == 0x0F and on[3] == 0xFF
    assert (off[2] & 0x0F) == 0x0F and off[3] == 0xFF
    # 高 16 bit 差异
    on_row = ((on[0] & 0x0F) << 12) | (on[1] << 4) | ((on[2] >> 4) & 0x0F)
    off_row = ((off[0] & 0x0F) << 12) | (off[1] << 4) | ((off[2] >> 4) & 0x0F)
    assert on_row == 0xFFFF
    assert off_row == 0x0000


def test_phase_cal_command_clamps_ps_align_to_6_bits():
    cmd = protocol.build_phase_cal_command(10)
    assert len(cmd) == 4
    assert cmd[3] == 10
    with pytest.raises(ValueError):
        protocol.build_phase_cal_command(64)
    with pytest.raises(ValueError):
        protocol.build_phase_cal_command(-1)


def test_id_update_command_uses_common_id():
    frame = protocol.build_id_update_frame(0x00, 0x05)
    parsed, _ = protocol.parse_response(frame)
    assert parsed["device_id"] == 0x00
    assert parsed["addr"] == protocol.ADDR_ID_UPDATE
    assert parsed["payload"][1] == 0x05


def test_status_query_command_is_empty_payload():
    frame = protocol.build_status_query_frame(0x01)
    parsed, _ = protocol.parse_response(frame)
    assert parsed["payload"] == b""


def test_parse_status_response_applies_scaling():
    payload = bytes([0x00, 119, 110, 1])  # 11.9V, 30℃, MCU=1
    info, message = protocol.parse_status_response(payload)
    assert message == "OK"
    assert info["rev"] == 0
    assert info["sys_vcc"] == pytest.approx(11.9)
    assert info["sys_temp"] == 30
    assert info["mcu_ver"] == 1


def test_parse_status_response_rejects_short_payload():
    assert protocol.parse_status_response(b"\x00\x01")[0] is None


def test_status_response_frame_round_trip():
    frame = protocol.build_status_response_frame(0x02, sys_vcc_raw=120, sys_temp_raw=130, mcu_ver=7)
    parsed, _ = protocol.parse_response(frame)
    info, _ = protocol.parse_status_response(parsed["payload"])
    assert info["sys_vcc"] == pytest.approx(12.0)
    assert info["sys_temp"] == 50
    assert info["mcu_ver"] == 7


def test_parse_status_response_accepts_four_byte_device_format():
    """设备实测：状态响应 4 字节，无尾部 0x9C。"""
    payload = bytes([0x0A, 0x72, 0x66, 0x05])  # Rev=10, SysVcc=11.4V, SysTemp=22℃, MCU=5
    info, message = protocol.parse_status_response(payload)
    assert message == "OK"
    assert info["rev"] == 0x0A
    assert info["sys_vcc"] == pytest.approx(11.4)
    assert info["sys_temp"] == 22
    assert info["mcu_ver"] == 5


def test_parse_status_response_accepts_five_byte_pdf_format():
    """受控原件 V3.1 PDF：状态响应 5 字节，末尾 0x9C。"""
    payload = bytes([0x00, 0x77, 0x6E, 0x03, 0x9C])
    info, message = protocol.parse_status_response(payload)
    assert message == "OK"
    assert info["rev"] == 0x00
    assert info["sys_vcc"] == pytest.approx(11.9)
    assert info["sys_temp"] == 30
    assert info["mcu_ver"] == 3


def test_parse_polarity_round_trip():
    assert protocol.parse_polarity(254) == (Polarity.LHCP, 0)
    assert protocol.parse_polarity(255) == (Polarity.RHCP, 0)
    assert protocol.parse_polarity(0) == (Polarity.LINEAR, 0)
    assert protocol.parse_polarity(180) == (Polarity.LINEAR, 180)


def test_beam_code_to_angle_round_trip():
    beam_h, beam_v = protocol.calculate_beam_values(30, 45, 11700)
    theta, phi = protocol.beam_code_to_angle(beam_v, beam_h, 11700)
    # 12 bit 波控量化引入 ≈0.02° 误差
    assert math.isclose(theta, 30, abs_tol=0.02)
    assert math.isclose(phi, 45, abs_tol=0.02)


# ----- 流式拆帧 -----
def test_stream_feeds_complete_frame():
    parser = KUR512StreamParser()
    frame = protocol.build_status_query_frame(0x01)
    events = parser.feed(frame)
    assert len(events) == 1
    assert events[0].is_frame
    assert events[0].raw == frame


def test_stream_handles_split_packets():
    parser = KUR512StreamParser()
    frame = protocol.build_beam_frame(
        0x01,
        protocol.make_beam_setting(11700, 30, 45, Polarity.LINEAR, 0),
    )
    events = parser.feed(frame[:3])
    assert events == []
    events = parser.feed(frame[3:])
    assert len(events) == 1
    assert events[0].raw == frame


def test_stream_handles_garbage_prefix():
    parser = KUR512StreamParser()
    garbage = b"\x00\x01\x02"
    frame = protocol.build_status_query_frame(0x01)
    events = parser.feed(garbage + frame)
    drop_events = [e for e in events if not e.is_frame]
    frame_events = [e for e in events if e.is_frame]
    assert any("异常字节已丢弃" in e.reason for e in drop_events)
    assert len(frame_events) == 1


def test_stream_recovers_after_bad_checksum():
    """流式拆帧只切字节边界；校验失败由 ``parse_response`` 拒绝。"""
    parser = KUR512StreamParser()
    bad = b"\x50\x53\x41\x01\x01\x9C\x00"  # 校验位为 0
    good = protocol.build_status_query_frame(0x01)
    events = parser.feed(bad + good)
    frame_events = [e for e in events if e.is_frame]
    assert len(frame_events) == 2
    bad_frame = frame_events[0].raw
    good_frame = frame_events[1].raw
    assert protocol.parse_response(bad_frame)[0] is None
    assert protocol.parse_response(good_frame)[0] is not None


def test_stream_drops_zero_length_frame():
    parser = KUR512StreamParser()
    bad = b"\x50\x53\x41\x01\x00" + bytes([protocol.calculate_checksum(b"\x50\x53\x41\x01\x00")])
    good = protocol.build_status_query_frame(0x02)
    events = parser.feed(bad + good)
    drop_reasons = [e.reason for e in events if not e.is_frame]
    assert "非法帧长度" in drop_reasons or "数据区为空" in drop_reasons
    assert sum(1 for e in events if e.is_frame) == 1


def test_stream_keeps_partial_header_suffix():
    parser = KUR512StreamParser()
    partial = b"\x50\x53"  # 缺帧头最后一字节 'A'
    events = parser.feed(partial)
    assert events == []
    assert parser.buffered_bytes == partial
    # 补上 'A' 后立刻成帧
    full = partial + b"\x41" + protocol.build_status_query_frame(0x01)[3:]
    events = parser.feed(full)
    assert len([e for e in events if e.is_frame]) == 1
