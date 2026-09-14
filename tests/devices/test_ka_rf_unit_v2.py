"""设备客户协议 V2 的独立线值回归，不以构帧器自证布局。"""
import binascii
import struct

import pytest

from soft_hertz_tool.devices.ka_rf_unit import protocol as p


def frame(cmd, payload=b"", version=2):
    raw = b"PSA" + bytes((version, cmd, len(payload))) + payload
    return raw + binascii.crc_hqx(raw, 0xFFFF).to_bytes(2, "big")


def test_empty_queries_and_begin_v2():
    assert p.build_status_query() == frame(0x20)
    assert p.build_ota_begin() == frame(0x21)
    assert p.build_ota_abort() == frame(0x23)
    assert p.build_ota_status() == frame(0x24)
    assert 0x22 not in p.CMD_NAMES


def test_status_wire_offsets_signed_temperature_and_full_version():
    payload = struct.pack(">BIHBBBHHHHHHHHHHhhhHHHHBB", 0, 12345, 7, 0, 1, 1,
                          256, 300, 65535, 19966, 18250, 29500, 28050, 15, 100, 50,
                          -32768, -125, 32767, 1, 2, 3, 4095, 1, 0)
    assert len(payload) == 46
    parsed, message = p.parse_response(frame(0xA0, payload))
    assert parsed, message
    d = parsed["decoded"]
    assert (d["fw_major"], d["fw_minor"], d["fw_revision"]) == (256, 300, 65535)
    assert d["conv_temp_x10"] == -32768
    assert d["tx_array_temp_x10"] == -125
    assert d["rx_beam_v"] == 4095
    assert "status_report_rate_hz" not in d
    assert p.parse_response(frame(0xA0, payload, version=1))[0] is None


@pytest.mark.parametrize("payload", [b"", b"\x00", bytes(43), bytes(45), bytes(47), b"\x06\x00"])
def test_status_rejects_wrong_lengths(payload):
    assert p.parse_response(frame(0xA0, payload))[0] is None


def test_ota_status_new_layout_and_candidate():
    base = struct.pack(">BBHHHBBBB", 0, 2, 0, 3, 0, 1, 0, 0, 10)
    d = p.decode_ota_status_response(base)
    assert d["last_result"] == 10
    name = b"ka_rf_unit_app_0.3.0_release.bin"
    candidate = base[:10] + b"\x01" + base[11:] + struct.pack(">IIB", 100, 0x12345678, len(name)) + name
    d = p.decode_ota_status_response(candidate)
    assert (d["size"], d["crc32"], d["filename"]) == (100, 0x12345678, name.decode())
    assert d["name"] == "OK"


@pytest.mark.parametrize("payload", [bytes(11), bytes(13), b"\x06\x00", bytes(10) + b"\x01\x00",
                                    b"\x00\x04" + bytes(10), bytes(8) + b"\x03" + bytes(3)])
def test_ota_status_rejects_malformed(payload):
    with pytest.raises(ValueError):
        p.decode_ota_status_response(payload)
