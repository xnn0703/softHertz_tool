"""AFD01_QS 设备包级回归测试。"""

from __future__ import annotations

import os
import struct
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from soft_hertz_tool.devices.afd01_qs.driver import Afd01QsDriver
from soft_hertz_tool.devices.afd01_qs.models import ReportRateMeter
from soft_hertz_tool.devices.afd01_qs.panel import Afd01QsPanel, QSPanel
from soft_hertz_tool.devices.afd01_qs.protocol import (
    build_angle_command,
    build_array_query,
    build_array_set,
    build_beam_angle,
    build_beam_config,
    build_frame,
    build_snr_report,
    build_tle,
    build_u8_command,
    parse_frame,
)
from soft_hertz_tool.devices.afd01_qs.simulator import QSDeviceSimulator
from soft_hertz_tool.devices.afd01_qs.stream import FrameStreamParser
from soft_hertz_tool.devices.afd01_qs.widgets import ArrayGridWidget
from soft_hertz_tool.shared.observability import FrameRecord
from soft_hertz_tool.shared.transport import SerialThread
from soft_hertz_tool.shared.ui.serial_connection import SerialConnectionWidget


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def _a0_payload() -> bytes:
    return struct.pack(
        ">BhhHffffBBhhhhhBBBI",
        1,
        12345,
        -2345,
        88,
        19798.0,
        29797.5,
        19250.0,
        29050.0,
        1,
        0,
        123,
        -456,
        789,
        1234,
        2345,
        0,
        0,
        0x20,
        42,
    )


def _parse_ok(frame: bytes):
    parsed, message = parse_frame(frame)
    assert message == "OK"
    assert parsed is not None
    return parsed


def test_protocol_builders_cover_commands_01_through_0b():
    frames = {
        0x01: build_snr_report(2.5, 3, 1, 0),
        0x02: build_beam_config(125.25, 1, 19798.0, 29797.5),
        0x03: build_u8_command(0x03, 1),
        0x04: build_angle_command(0x04, 359.99),
        0x05: build_u8_command(0x05, 1),
        0x06: build_angle_command(0x06, 12.34),
        0x07: build_beam_angle(0x07, 12.34, 234.56),
        0x08: build_tle("1 00005U 58002B", "2 00005  34.2682"),
        0x09: build_beam_angle(0x09, 1.23, 45.67),
        0x0A: build_beam_angle(0x0A, 90.0, 360.0),
        0x0B: build_array_query(),
    }

    assert set(frames) == set(range(0x01, 0x0C))
    for command, frame in frames.items():
        parsed = _parse_ok(frame)
        assert parsed["command"] == command

    assert _parse_ok(frames[0x01])["payload"] == struct.pack(">fBBB", 2.5, 3, 1, 0)
    assert _parse_ok(frames[0x02])["payload"] == struct.pack(">hBff", 12525, 1, 19798.0, 29797.5)
    assert _parse_ok(frames[0x04])["payload"] == struct.pack(">H", 35999)
    assert _parse_ok(frames[0x07])["payload"] == struct.pack(">HH", 1234, 23456)
    assert len(_parse_ok(frames[0x08])["payload"]) == 138
    assert _parse_ok(frames[0x0B])["payload"] == b"\x00\x00\x00"


@pytest.mark.parametrize(
    ("builder", "message"),
    [
        (lambda: build_beam_config(181, 0, 1, 1), "-180~180"),
        (lambda: build_u8_command(0x03, 256), "uint8"),
        (lambda: build_angle_command(0x04, -0.01), "0~360"),
        (lambda: build_beam_angle(0x07, 90.01, 0), "theta"),
        (lambda: build_beam_angle(0x06, 0, 0), "无效"),
        (lambda: build_tle("X" * 70, ""), "69"),
        (lambda: build_array_set(3, 8), "4~8"),
    ],
)
def test_protocol_rejects_invalid_control_parameters(builder, message):
    with pytest.raises((ValueError, UnicodeEncodeError), match=message):
        builder()


def test_a0_and_a1_are_decoded_to_semantic_fields():
    a0 = _parse_ok(build_frame(0xA0, _a0_payload()))
    assert len(build_frame(0xA0, _a0_payload())) == 48
    assert a0["decoded"]["lon"] == 123.45
    assert a0["decoded"]["lat"] == -23.45
    assert a0["decoded"]["theta"] == 12.34
    assert a0["decoded"]["status"] == 0x20

    a1 = _parse_ok(build_frame(0xA1, b"\x00\x07\x06\x03\x03"))
    assert a1["decoded"] == {
        "result": 0,
        "tx_size": 7,
        "rx_size": 6,
        "power_flags": 3,
        "apply_flags": 3,
    }


def test_parser_recovers_split_sticky_bad_checksum_garbage_and_bad_length():
    parser = FrameStreamParser()
    first = build_snr_report(2.5, 1, 0, 0)
    second = build_array_query()
    assert parser.feed(first[:3]) == []
    events = parser.feed(first[3:] + second)
    assert [event.kind for event in events] == ["frame", "frame"]

    broken = bytearray(second)
    broken[-1] ^= 0xFF
    events = parser.feed(b"\x01\x02" + broken)
    assert [event.kind for event in events] == ["garbage", "bad_frame"]
    assert "校验和" in events[1].message

    # 非法长度之后仍能重新同步到下一帧。
    events = parser.feed(b"\x55\x01\x04\x01" + second)
    assert events[0].kind == "bad_length"
    assert events[-1].kind == "frame"
    assert events[-1].parsed["command"] == 0x0B


def test_parse_frame_rejects_wrong_shape_and_a0_length():
    assert parse_frame(b"\x55\x01")[1] == "帧长度不足"
    assert parse_frame(b"\x54\x01\x00\x00\x00\x01")[1] == "帧头错误"
    parsed, message = parse_frame(build_frame(0xA0, b"\x00"))
    assert parsed is None
    assert "载荷长度应为 42" in message


def test_report_rate_meter_keeps_two_second_100hz_window():
    meter = ReportRateMeter(window_seconds=2.0)
    rates = [meter.add(index * 0.01) for index in range(301)]
    assert 99.9 <= rates[-1] <= 100.1
    assert len(meter.timestamps) == 201
    meter.reset()
    assert not meter.timestamps


def test_driver_uses_shared_transport_and_dispatches_a0_a1_records():
    assert issubclass(Afd01QsDriver, SerialThread)
    driver = Afd01QsDriver("SIM", 921600)
    telemetry = []
    array_status = []
    records = []
    driver.telemetry_signal.connect(telemetry.append)
    driver.array_status_signal.connect(array_status.append)
    driver.frame_signal.connect(records.append)

    driver.handle_bytes(build_frame(0xA0, _a0_payload()) + build_frame(0xA1, b"\x00\x08\x07\x03\x01"))
    assert telemetry[-1]["heading"] == 7.89
    assert array_status[-1]["rx_size"] == 7
    assert len(records) == 2
    assert all(isinstance(record, FrameRecord) for record in records)
    assert records[0].model == "AFD01_QS"
    assert records[0].direction == "RX"

    driver.handle_bytes(b"\x99")
    assert records[-1].direction == "DROP"
    assert records[-1].level == "ERROR"
    driver.stop()


class FakeSerial:
    def __init__(self):
        self.writes = []
        self.input = bytearray()

    @property
    def in_waiting(self):
        return len(self.input)

    def read(self, count):
        data = bytes(self.input[:count])
        del self.input[:count]
        return data

    def write(self, data):
        self.writes.append((time.monotonic(), bytes(data)))
        return len(data)


def test_simulator_applies_array_status_and_emits_100hz_without_burst():
    serial = FakeSerial()
    simulator = QSDeviceSimulator(serial)
    simulator.process_input(build_array_set(7, 6))
    assert _parse_ok(serial.writes[-1][1])["decoded"]["tx_size"] == 7
    assert _parse_ok(serial.writes[-1][1])["decoded"]["rx_size"] == 6

    simulator.process_input(build_array_set(4, 4))
    assert _parse_ok(serial.writes[-1][1])["decoded"]["tx_size"] == 4
    assert _parse_ok(serial.writes[-1][1])["decoded"]["rx_size"] == 4

    serial.writes.clear()
    simulator.run(duration=0.31)
    a0_writes = [(stamp, data) for stamp, data in serial.writes if data[1] == 0xA0]
    assert 29 <= len(a0_writes) <= 33
    intervals = [right[0] - left[0] for left, right in zip(a0_writes, a0_writes[1:])]
    assert intervals and min(intervals) > 0.004


def test_array_grid_preserves_ka256_masks_and_colors(qt_app):
    grid = ArrayGridWidget("TX")
    grid.set_state(7, powered=True, state="pending")
    assert sum(len(row) for row in grid.cells) == 64
    assert "#f2c94c" in grid.cells[1][1].styleSheet()
    assert "#d6d6d6" in grid.cells[0][0].styleSheet()

    grid.set_state(4, powered=True, state="active")
    active_cells = sum(
        "#4f9dd9" in cell.styleSheet() for row in grid.cells for cell in row
    )
    assert active_cells == 16
    grid.deleteLater()
    qt_app.processEvents()


class FakeWorker:
    running = True

    def __init__(self):
        self.frames = []
        self.stop_count = 0

    def send_frame(self, frame):
        self.frames.append(frame)
        return True

    def stop(self):
        self.stop_count += 1
        self.running = False

    def deleteLater(self):
        pass


def test_panel_uses_shared_connection_and_enforces_array_request_timeout(qt_app):
    panel = Afd01QsPanel()
    assert QSPanel is Afd01QsPanel
    assert isinstance(panel.serial_connection, SerialConnectionWidget)
    panel.serial_connection.set_stop_failed("停止超时")
    assert panel.serial_connection._state == SerialConnectionWidget.STOP_FAILED
    assert panel.serial_connection.connect_button.text() == "重试关闭"
    panel.serial_connection.set_disconnected()
    fake = FakeWorker()
    panel.worker = fake
    panel._connection_generation = 7

    panel._on_driver_telemetry(fake, 6, {"heading": 1.0})
    assert panel._latest_telemetry == {}
    panel._on_driver_telemetry(fake, 7, {"heading": 2.0})
    assert panel._latest_telemetry == {"heading": 2.0}

    panel._begin_array_request(build_array_query())
    panel._begin_array_request(build_array_query())
    assert len(fake.frames) == 1
    assert panel._array_pending is True
    assert panel._array_timeout.interval() == 3000
    assert not panel.array_apply_btn.isEnabled()

    panel._on_array_timeout()
    assert not panel._array_pending
    assert not panel.array_apply_btn.isEnabled()
    assert "超时" in panel.array_status_label.text()

    panel.shutdown()
    panel.shutdown()
    assert fake.stop_count == 1
    assert not panel._telemetry_timer.isActive()
    panel.deleteLater()
    qt_app.processEvents()


def test_panel_refreshes_telemetry_at_10hz_and_marks_a0_timeout(qt_app):
    panel = Afd01QsPanel()
    assert panel._telemetry_timer.interval() == 100
    panel._on_telemetry({"gps_lock": 1, "heading": 12.5})
    panel._refresh_telemetry()
    assert panel.telemetry_table.rowCount() == 2

    panel._on_report_rate(100.02)
    assert "100.0 Hz" in panel.report_rate_label.text()
    panel._last_a0_time = time.monotonic() - 1.1
    panel._refresh_telemetry()
    assert "0.0 Hz" in panel.report_rate_label.text()
    assert "超时" in panel.report_rate_label.text()

    panel.shutdown()
    panel.deleteLater()
    qt_app.processEvents()
