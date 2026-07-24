"""KaUDC004A 新包的协议、流解析、Driver 与面板测试。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from soft_hertz_tool.devices.kaudc004a import protocol
from soft_hertz_tool.devices.kaudc004a.driver import KaUDCDriver
from soft_hertz_tool.devices.kaudc004a.panel import KaUDCPanel
from soft_hertz_tool.devices.kaudc004a.stream import KaUDCStreamParser


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_all_command_builders_use_fixed_frame_and_valid_crc() -> None:
    frames = (
        protocol.build_reset_frame(),
        protocol.build_version_query_frame(),
        protocol.build_temp_query_frame(),
        protocol.build_rx_lo_frame(17250),
        protocol.build_tx_lo_frame(28050),
        protocol.build_lo_query_frame(),
        protocol.build_tx_att_frame(150),
        protocol.build_rx_att_frame(200),
        protocol.build_att_query_frame(),
    )

    assert [frame[4] for frame in frames] == [0x0A, 0x0B, 0x0C, 0x0E, 0x12, 0x13, 0x14, 0x15, 0x16]
    for frame in frames:
        payload, message = protocol.parse_response(frame)
        assert len(frame) == protocol.FRAME_SIZE
        assert frame.startswith(protocol.FRAME_HEADER)
        assert payload is not None
        assert message == "OK"


def test_lo_and_attenuation_fields_are_big_endian() -> None:
    assert protocol.build_rx_lo_frame(17250)[8:10] == (17250).to_bytes(2, "big")
    assert protocol.build_tx_lo_frame(28050)[8:10] == (28050).to_bytes(2, "big")
    assert protocol.build_tx_att_frame(150)[8:10] == b"\x00\x96"
    assert protocol.build_rx_att_frame(300)[8:10] == b"\x01\x2C"

    with pytest.raises(ValueError):
        protocol.build_tx_att_frame(301)


def test_parse_response_rejects_bad_crc() -> None:
    frame = protocol.build_version_query_frame()
    payload, message = protocol.parse_response(frame[:-1] + bytes([frame[-1] ^ 0xFF]))
    assert payload is None
    assert "CRC错误" in message


def test_temperature_keeps_raw_byte_behavior() -> None:
    status = protocol.parse_response_data(bytes([protocol.CMD_TEMP_QUERY, 0x80, 0, 0, 0, 0]))
    assert status["temperature_raw"] == 0x80
    assert status["temperature"] == 0x80


def test_query_responses_decode_structured_values() -> None:
    lo = protocol.parse_response_data(bytes([protocol.CMD_LO_QUERY, 0x6D, 0x92, 0x43, 0x62, 0x07]))
    attenuation = protocol.parse_response_data(bytes([protocol.CMD_ATT_QUERY, 0, 150, 0, 200, 0]))

    assert lo == {
        "cmd": protocol.CMD_LO_QUERY,
        "command_name": "本振查询",
        "tx_lo": 28050,
        "rx_lo": 17250,
        "lock_status": 7,
        "rx_locked": True,
        "tx_locked": True,
        "ref_locked": True,
    }
    assert attenuation["tx_att_db"] == 15.0
    assert attenuation["rx_att_db"] == 20.0


def test_stream_parser_handles_fragmentation_and_sticky_frames() -> None:
    parser = KaUDCStreamParser()
    first = protocol.build_version_query_frame()
    second = protocol.build_temp_query_frame()

    assert parser.feed(first[:5]) == []
    events = parser.feed(first[5:] + second)

    assert [event.raw for event in events if event.is_frame] == [first, second]
    assert parser.buffered_bytes == b""


def test_stream_parser_reports_garbage_and_preserves_partial_header() -> None:
    parser = KaUDCStreamParser()
    frame = protocol.build_version_query_frame()

    first_events = parser.feed(b"\x00\x01\xAA")
    second_events = parser.feed(frame[1:])

    assert [(event.kind, event.raw) for event in first_events] == [("drop", b"\x00\x01")]
    assert [event.raw for event in second_events if event.is_frame] == [frame]


def test_driver_emits_frame_records_and_structured_status() -> None:
    driver = KaUDCDriver("loop://", 115200)
    records = []
    statuses = []
    driver.frame_signal.connect(records.append)
    driver.status_signal.connect(statuses.append)
    valid = protocol.build_frame(bytes([protocol.CMD_TEMP_QUERY, 0x3C, 0, 0, 0, 0]))
    invalid = valid[:-1] + bytes([valid[-1] ^ 0xFF])

    driver.handle_bytes(b"noise" + invalid + valid)

    assert [record.direction for record in records] == ["DROP", "RX", "RX"]
    assert all(record.model == "KaUDC004A" for record in records)
    assert records[1].level == "ERROR"
    assert records[2].command == "温度查询"
    assert statuses == [
        {
            "cmd": protocol.CMD_TEMP_QUERY,
            "command_name": "温度查询",
            "temperature_raw": 0x3C,
            "temperature": 0x3C,
        }
    ]


def test_driver_semantic_commands_delegate_to_protocol_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = KaUDCDriver("loop://", 115200)
    queued = []
    monkeypatch.setattr(driver, "send_bytes", lambda frame: queued.append(frame) or True)

    assert driver.send_reset()
    assert driver.set_tx_lo(28050)
    assert driver.set_rx_attenuation(200)

    assert queued == [
        protocol.build_reset_frame(),
        protocol.build_tx_lo_frame(28050),
        protocol.build_rx_att_frame(200),
    ]


def test_panel_displays_raw_temperature_and_shutdown_is_idempotent(qapp: QApplication) -> None:
    panel = KaUDCPanel()
    panel._on_status(
        {
            "cmd": protocol.CMD_TEMP_QUERY,
            "temperature_raw": 0x80,
            "temperature": 0x80,
        }
    )

    row = panel._status_rows["温度(原始值)"]
    assert panel.status_table.item(row, 1).text() == "128"
    panel.shutdown()
    panel.shutdown()
