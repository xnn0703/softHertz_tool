"""QS 协议、阵列、模拟器和报文日志回归测试。"""

import os
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(__file__))

from PySide6.QtWidgets import QApplication

from frame_monitor import AsyncFrameLogger, FrameMonitorWidget, FrameRecord
from qs_device_simulator import QSDeviceSimulator
from qs_panel import ArrayGridWidget, QSPanel, ReportRateMeter
from qs_protocol import (
    FrameStreamParser,
    build_array_query,
    build_array_set,
    build_beam_angle,
    build_frame,
    build_snr_report,
    parse_frame,
)


def _a0_payload() -> bytes:
    return struct.pack(
        ">BhhHffffBBhhhhhBBBI",
        1, 12345, -2345, 88, 19798.0, 29797.5, 19250.0, 29050.0,
        1, 0, 123, -456, 789, 1234, 2345, 0, 0, 0x20, 42,
    )


def test_qs_frame_build_and_a0_decode():
    frame = build_frame(0xA0, _a0_payload())
    parsed, message = parse_frame(frame)
    assert message == "OK"
    assert len(frame) == 48
    assert parsed["command"] == 0xA0
    assert parsed["decoded"]["lon"] == 123.45
    assert parsed["decoded"]["lat"] == -23.45
    assert parsed["decoded"]["theta"] == 12.34
    assert parsed["decoded"]["status"] == 0x20


def test_a0_report_rate_meter_uses_sliding_window():
    meter = ReportRateMeter(window_seconds=2.0)
    rates = [meter.add(index * 0.01) for index in range(301)]
    assert 99.9 <= rates[-1] <= 100.1
    assert len(meter.timestamps) == 201


def test_qs_stream_parser_handles_split_sticky_bad_crc_and_garbage():
    parser = FrameStreamParser()
    one = build_snr_report(2.5, 1, 0, 0)
    two = build_array_query()
    assert parser.feed(one[:3]) == []
    events = parser.feed(one[3:] + two)
    assert [event.kind for event in events] == ["frame", "frame"]

    broken = bytearray(two)
    broken[-1] ^= 0xFF
    events = parser.feed(b"\x01\x02" + broken)
    assert [event.kind for event in events] == ["garbage", "bad_frame"]
    assert "校验和" in events[1].message


def test_qs_array_config_has_no_sequence_field():
    query = build_array_query()
    parsed, _ = parse_frame(query)
    assert parsed["payload"] == b"\x00\x00\x00"
    setting = build_array_set(7, None)
    parsed, _ = parse_frame(setting)
    assert parsed["payload"] == b"\x01\x07\xFF"
    setting_4x4 = build_array_set(4, 4)
    parsed, _ = parse_frame(setting_4x4)
    assert parsed["payload"] == b"\x01\x04\x04"


def test_qs_manual_beam_payload_scale():
    frame = build_beam_angle(0x07, 12.34, 234.56)
    parsed, _ = parse_frame(frame)
    assert parsed["payload"] == struct.pack(">HH", 1234, 23456)


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


def test_qs_simulator_array_status_and_100hz_no_burst():
    serial = FakeSerial()
    simulator = QSDeviceSimulator(serial)
    simulator.process_input(build_array_set(7, 6))
    a1 = serial.writes[-1][1]
    parsed, message = parse_frame(a1)
    assert message == "OK"
    assert parsed["decoded"]["tx_size"] == 7
    assert parsed["decoded"]["rx_size"] == 6

    simulator.process_input(build_array_set(4, 4))
    parsed, message = parse_frame(serial.writes[-1][1])
    assert message == "OK"
    assert parsed["decoded"]["tx_size"] == 4
    assert parsed["decoded"]["rx_size"] == 4

    serial.writes.clear()
    simulator.run(duration=0.31)
    a0_writes = [(stamp, data) for stamp, data in serial.writes if data[1] == 0xA0]
    assert 29 <= len(a0_writes) <= 33
    intervals = [b[0] - a[0] for a, b in zip(a0_writes, a0_writes[1:])]
    assert intervals and min(intervals) > 0.004


def test_async_logger_rotates_without_deleting_history(tmp_path: Path):
    logger = AsyncFrameLogger(tmp_path, max_bytes=260)
    for index in range(20):
        logger.write(FrameRecord("AFD01_QS", "COM1", "RX", "0xA0", bytes(range(20)), f"line {index}"))
    logger.close()
    files = sorted(tmp_path.glob("frames_*.log"))
    assert len(files) >= 2
    content = "".join(path.read_text(encoding="utf-8") for path in files)
    assert "line 0" in content and "line 19" in content


def test_frame_monitor_flushes_batch_and_keeps_ui_limit(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    monitor = FrameMonitorWidget(logger=AsyncFrameLogger(tmp_path), max_lines=5)
    for index in range(8):
        monitor.add_record(FrameRecord("AFD01_QS", "SIM", "RX", "0xA0", b"\x55", f"line {index}"))
    monitor._flush_pending()
    assert len(monitor.records) == 5
    assert monitor.text.document().blockCount() <= 5
    assert "line 7" in monitor.text.toPlainText()
    assert "line 0" not in monitor.text.toPlainText()
    monitor.close()
    monitor.deleteLater()
    app.processEvents()


def test_array_grid_has_64_cells_and_pending_color():
    app = QApplication.instance() or QApplication([])
    grid = ArrayGridWidget("TX")
    grid.set_state(7, powered=True, state="pending")
    assert sum(len(row) for row in grid.cells) == 64
    assert "#f2c94c" in grid.cells[1][1].styleSheet()
    assert "#d6d6d6" in grid.cells[0][0].styleSheet()
    grid.set_state(4, powered=True, state="active")
    active_cells = sum("#4f9dd9" in cell.styleSheet() for row in grid.cells for cell in row)
    assert active_cells == 16
    grid.deleteLater()
    app.processEvents()


class FakeWorker:
    running = True

    def __init__(self):
        self.frames = []

    def send_frame(self, frame):
        self.frames.append(frame)
        return True


def test_qs_panel_allows_only_one_array_request():
    app = QApplication.instance() or QApplication([])
    panel = QSPanel()
    fake = FakeWorker()
    panel.worker = fake
    panel._begin_array_request(build_array_query())
    panel._begin_array_request(build_array_query())
    assert len(fake.frames) == 1
    assert panel._array_pending is True
    assert not panel.array_apply_btn.isEnabled()
    panel._array_timeout.stop()
    panel.worker = None
    panel.deleteLater()
    app.processEvents()


def test_qs_panel_displays_report_rate_and_timeout():
    app = QApplication.instance() or QApplication([])
    panel = QSPanel()
    panel._on_report_rate(100.02)
    assert "100.0 Hz" in panel.report_rate_label.text()
    panel._last_a0_time = time.monotonic() - 1.1
    panel._refresh_telemetry()
    assert "0.0 Hz" in panel.report_rate_label.text()
    assert "超时" in panel.report_rate_label.text()
    panel.deleteLater()
    app.processEvents()
