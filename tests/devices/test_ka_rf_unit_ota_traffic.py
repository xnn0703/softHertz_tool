"""V2 自动安装合同回归；替换旧草稿的 READY/COMMIT 测试，不代表实板刷机验收。"""
from __future__ import annotations

import binascii
import struct
import threading
import time

import pytest
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from soft_hertz_tool.devices.ka_rf_unit import protocol as p
from soft_hertz_tool.devices.ka_rf_unit.driver import KaRfUnitDriver
from soft_hertz_tool.devices.ka_rf_unit.ota_panel import OtaPanel
from soft_hertz_tool.devices.ka_rf_unit.ota_traffic import OtaConfig, OtaTrafficEngine, image_version
from soft_hertz_tool.devices.ka_rf_unit.simulator import KaRfUnitDeviceSimulator
from soft_hertz_tool.devices.ka_rf_unit.stream import FrameStreamParser

NAME = "ka_rf_unit_app_0.3.0_release.bin"


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def status(version=(0, 2, 0), *, health=1, phase=0, candidate=0, last=0, requested=0):
    payload = struct.pack(">BBHHHBBBB", 0, phase, *version, health, requested, candidate, last)
    if candidate:
        name = NAME.encode()
        payload += struct.pack(">IIB", 3, 0x12345678, len(name)) + name
    return p.encode_frame(p.RES_OTA_STATUS, payload)


def response(engine, raw):
    parsed, message = p.parse_response(raw)
    assert parsed, message
    engine.on_response(parsed, raw)


class Session:
    def __init__(self, size=200, before=(0, 2, 0)):
        self.clock = Clock()
        self.sent, self.events = [], []
        self.data = bytes(i & 255 for i in range(size))
        self.engine = OtaTrafficEngine(OtaConfig(
            NAME, self.data, self.sent.append, lambda k, v: self.events.append((k, v)), self.clock))
        self.before = before

    def tick(self, seconds):
        self.clock.advance(seconds)
        self.engine.poll()

    def begin(self):
        e = self.engine
        e.start()
        response(e, p.encode_frame(p.RES_STATUS, KaRfUnitDeviceSimulator(Port())._status_payload()))
        response(e, status(self.before))
        assert self.sent[-1] == p.build_ota_begin()
        response(e, p.encode_frame(p.RES_OTA_BEGIN, b"\x00"))
        assert e.state == "WAIT_C"
        assert self.sent[-1] == p.build_ota_begin()  # 主站没有发送 C。

    def upload(self):
        self.begin()
        e = self.engine
        e.on_raw(b"C")
        assert self.sent[-1][0:3] == b"\x01\x00\xff"
        assert NAME.encode() + b"\x00" + str(len(self.data)).encode() + b"\x00" in self.sent[-1]
        e.on_raw(b"\x06")
        assert e.state == "HEADER_C"
        e.on_raw(b"C")
        collected = bytearray()
        sequence = 1
        while e.state == "DATA":
            packet = self.sent[-1]
            assert packet[1] == sequence & 255 and packet[2] == (sequence & 255) ^ 255
            assert int.from_bytes(packet[-2:], "big") == binascii.crc_hqx(packet[3:-2], 0)
            collected.extend(packet[3:3 + e.chunk_size])
            self.tick(0.01)
            e.on_raw(b"\x06")
            sequence += 1
        assert collected == self.data
        assert self.sent[-1] == b"\x04" and e.state == "EOT1"
        e.on_raw(b"\x15")
        assert e.state == "EOT2" and self.sent[-1] == b"\x04"
        e.on_raw(b"\x06C")
        assert e.state == "END_ACK"
        assert self.sent[-1][0:3] == b"\x01\x00\xff"
        assert self.sent[-1][3:-2] == bytes(128)


class Port:
    is_open = True
    in_waiting = 0

    def __init__(self):
        self.written = []
        self.short = False

    def write(self, data):
        self.written.append(bytes(data))
        return len(data) - int(self.short)


@pytest.mark.parametrize("size", [1, 128, 129, 1024, 1025, 262145, p.OTA_APP_MAX_SIZE])
def test_transfer_crc_sizes_wrap_and_complete(size):
    s = Session(size)
    s.upload()
    s.engine.on_raw(b"\x06")
    assert s.engine.active
    s.tick(0.19)
    assert s.engine.state == "QUIET"
    s.tick(0.02)
    assert s.sent[-1] == p.build_ota_status()
    response(s.engine, status((0, 3, 0)))
    assert s.engine.state == "DONE"
    assert not any(raw.startswith(b"PSA") and raw[4] == 0x22 for raw in s.sent)


@pytest.mark.parametrize("name", ["other.bin", "ka_rf_unit_factory_0.3.0_release.bin",
                                 "/tmp/" + NAME, "C:\\" + NAME, "../" + NAME,
                                 "ka_rf_unit_app_1.2.65536_release.bin",
                                 "ka_rf_unit_app_1.2.3_old.bin", "中文.bin", "", "x" * 64])
def test_reject_filename(name):
    with pytest.raises(ValueError):
        image_version(name)


@pytest.mark.parametrize("size", [0, p.OTA_APP_MAX_SIZE + 1])
def test_reject_size(size):
    with pytest.raises(ValueError):
        OtaConfig(NAME, bytes(size), lambda _: None, lambda *_: None)


def test_beta_and_crc_reference():
    assert image_version("ka_rf_unit_app_65535.0.1_beta.bin") == (65535, 0, 1)
    assert p.crc16_ccitt_false(b"123456789") == 0x29B1
    assert p.crc16_ccitt_ymodem(b"123456789") == 0x31C3
    assert p.crc32_iso_hdlc(b"123456789") == 0xCBF43926


@pytest.mark.parametrize("result", range(1, 13))
def test_probe_failure_never_sends_begin(result):
    s = Session()
    s.engine.start()
    response(s.engine, p.encode_frame(p.RES_STATUS, bytes((result,))))
    assert s.engine.state == "FAILED"
    assert len(s.sent) == 1


@pytest.mark.parametrize("options", [{"candidate": 1}, {"health": 0}, {"requested": 1}, {"phase": 1}])
def test_device_not_ready_rejects_begin(options):
    s = Session()
    s.engine.start()
    response(s.engine, p.encode_frame(p.RES_STATUS, KaRfUnitDeviceSimulator(Port())._status_payload()))
    response(s.engine, status(**options))
    assert s.engine.state == "FAILED"
    assert len(s.sent) == 2


def test_begin_ack_lost_no_raw_until_window_expires():
    s = Session()
    s.engine.start()
    response(s.engine, p.encode_frame(p.RES_STATUS, KaRfUnitDeviceSimulator(Port())._status_payload()))
    response(s.engine, status())
    s.tick(2)
    assert s.engine.state == "QUIET"
    s.engine.on_raw(b"C")
    assert len(s.sent) == 3
    s.tick(9.9)
    assert len(s.sent) == 3
    s.tick(0.2)
    assert s.sent[-1] == p.build_ota_status()


def test_block0_erase_deadline_and_data_retry_no_progress_extension():
    s = Session()
    s.begin()
    s.engine.on_raw(b"C")
    s.tick(9)
    assert s.engine.state == "HEADER"
    s.engine.on_raw(b"\x06C")
    packet = s.sent[-1]
    s.tick(2)
    assert s.sent[-1] == packet
    for _ in range(4):
        s.tick(2)
    assert s.engine.state == "QUIET"
    assert s.sent[-1] == b"\x18\x18"


def test_nak_retries_are_bounded_and_same_sequence():
    s = Session()
    s.begin()
    s.engine.on_raw(b"C\x06C")
    packet = s.sent[-1]
    for _ in range(10):
        s.engine.on_raw(b"\x15")
        assert s.sent[-1] == packet
    s.engine.on_raw(b"\x15")
    assert s.engine.state == "QUIET"


def test_missing_header_c_retries_header_not_data():
    s = Session()
    s.begin()
    s.engine.on_raw(b"C")
    header = s.sent[-1]
    s.engine.on_raw(b"\x06")
    s.tick(2)
    assert s.sent[-1] == header
    s.engine.on_raw(b"\x06C")
    assert s.engine.state == "DATA"


def test_raw_total_deadline_is_not_extended_by_progress():
    s = Session()
    s.begin()
    s.engine.on_raw(b"C\x06C")
    s.engine.progress_at = s.clock.now + 119
    s.tick(120)
    assert s.engine.state == "QUIET"


def test_duplicate_header_ack_does_not_extend_progress():
    s = Session()
    s.begin()
    s.engine.on_raw(b"C\x06")
    for _ in range(4):
        s.tick(2)
        s.engine.on_raw(b"\x06")
    s.tick(2)
    assert s.engine.state == "QUIET"


def test_eot2_ack_lost_but_c_arrives():
    s = Session(1)
    s.begin()
    s.engine.on_raw(b"C\x06C\x06\x15")
    assert s.engine.state == "EOT2"
    s.engine.on_raw(b"C")
    assert s.engine.state == "END_ACK"


def test_end_c_wait_does_not_send_eot_again_and_late_c_cannot_authorize():
    s = Session(1)
    s.begin()
    s.engine.on_raw(b"C\x06C\x06\x15\x06")
    assert s.engine.state == "END_C"
    count = len(s.sent)
    s.tick(2)
    assert len(s.sent) == count
    s.clock.advance(8)
    s.engine.on_raw(b"C")
    assert not s.engine.authorized_finish
    assert s.engine.state == "QUIET"


def test_final_ack_lost_no_retransmit_and_recovery_single_inflight():
    s = Session()
    s.upload()
    count = len(s.sent)
    s.tick(2)
    assert s.engine.state == "QUIET" and len(s.sent) == count
    s.tick(0.21)
    assert len(s.sent) == count + 1
    for _ in range(19):
        s.tick(0.1)
    assert len(s.sent) == count + 1
    s.tick(0.2)  # 查询超时，间隔 1 秒后才能再发。
    s.tick(0.9)
    assert len(s.sent) == count + 1
    s.tick(0.11)
    assert len(s.sent) == count + 2


@pytest.mark.parametrize("reply", [
    p.encode_frame(p.RES_OTA_STATUS, b"\x06"), status(),
    status((0, 3, 0), health=0), status((0, 3, 0), health=2),
    status((0, 3, 0), requested=1),
])
def test_busy_pending_old_version_not_false_success(reply):
    s = Session()
    s.upload()
    s.engine.on_raw(b"\x06")
    s.tick(0.21)
    response(s.engine, reply)
    assert s.engine.state == "RECOVERY"
    s.tick(181)
    assert s.engine.state == "UNCONFIRMED"


@pytest.mark.parametrize("last", [5, 9, 10, 11])
def test_auto_install_failure_is_visible(last):
    s = Session()
    s.upload()
    s.engine.on_raw(b"\x06")
    s.tick(0.21)
    response(s.engine, status(last=last, candidate=1))
    assert s.engine.state == "FAILED"
    assert p.RESULT_NAMES[last] in s.events[-1][1]


def test_same_version_never_proves_reinstallation():
    s = Session(before=(0, 3, 0))
    s.upload()
    s.engine.on_raw(b"\x06")
    s.tick(0.21)
    response(s.engine, status((0, 3, 0)))
    assert s.engine.state == "UNCONFIRMED"


def test_cancel_uses_can_not_abort_and_keeps_exclusivity():
    s = Session()
    s.begin()
    s.engine.cancel()
    assert s.sent[-1] == b"\x18\x18" and s.engine.active
    s.tick(9)
    assert s.engine.state == "QUIET"
    s.tick(1.1)
    response(s.engine, status())
    assert s.engine.state == "CANCELLED"


def test_cancel_after_last_packet_cannot_revoke_install():
    s = Session()
    s.upload()
    count = len(s.sent)
    s.engine.cancel()
    assert len(s.sent) == count and s.engine.state == "END_ACK"


def test_send_failure_stays_exclusive_until_recovery():
    s = Session()
    def fail(_):
        raise IOError("short write")
    s.engine.cfg.on_send = fail
    s.engine.start()
    assert s.engine.active and s.engine.state == "QUIET"
    assert any(k == "send_failed" for k, _ in s.events)


def driver_fixture():
    driver = KaRfUnitDriver("fake", 460800)
    driver.running = True
    driver.serial = Port()
    driver.set_query_hz(0)
    return driver


def test_driver_single_request_timeout_queue_and_observation(qt_app, monkeypatch):
    d = driver_fixture()
    now = Clock()
    monkeypatch.setattr("soft_hertz_tool.devices.ka_rf_unit.driver.time.monotonic", now)
    records = []
    d.frame_signal.connect(records.append)
    assert d.set_tx_enabled(True) and d.set_rx_enabled(True)
    assert records == []  # 入队不是 TX。
    d._flush_tx()
    d._flush_tx()
    assert len(d.serial.written) == 1
    d.handle_bytes(p.encode_frame(p.RES_SET_TX_EN, b"\x00"))
    d._flush_tx()
    assert len(d.serial.written) == 2 and records[0].direction == "TX"
    assert d.query_status()
    now.advance(2)
    d._flush_tx()
    assert len(d.serial.written) == 3


def test_driver_ota_ownership_starts_in_loop_and_routes_glued_begin_c(qt_app):
    d = driver_fixture()
    events = []
    d.ota_busy_signal.connect(events.append)
    assert d.start_ota(filename=NAME, data=b"abc")
    assert d._ota_engine is None and d.ota_active
    assert not d.query_status() and not d.set_tx_enabled(True) and not d.ota_abort()
    d._flush_tx()
    d.handle_bytes(p.encode_frame(p.RES_STATUS, KaRfUnitDeviceSimulator(Port())._status_payload()))
    d.handle_bytes(status())
    d.handle_bytes(p.encode_frame(p.RES_OTA_BEGIN, b"\x00") + b"C")
    assert d._ota_engine.state == "HEADER"
    assert d.serial.written[-1][0] == 1
    assert not d.stop_ota() and d.ota_active
    d._flush_tx()
    assert d.serial.written[-1] == b"\x18\x18"
    d.on_loop_stopped()
    assert not d.ota_active and events == [True, False]


def test_driver_queue_full_short_write_and_busy_start(qt_app):
    d = driver_fixture()
    assert d.query_status()
    assert not d.start_ota(filename=NAME, data=b"a")
    d.serial.short = True
    records = []
    d.frame_signal.connect(records.append)
    d._flush_tx()
    assert records[-1].direction == "DROP"
    assert d._pending_command == p.RES_STATUS
    for _ in range(d._tx_queue.maxsize):
        assert d.query_status()
    assert not d.query_status()


def test_driver_standalone_ota_status_and_no_cross_thread_engine_mutation(qt_app):
    d = driver_fixture()
    received = []
    d.ota_status_signal.connect(received.append)
    d.handle_bytes(status(last=10))
    assert received[-1]["last_result"] == 10
    assert d.start_ota(filename=NAME, data=b"a")
    worker = threading.Thread(target=d.stop_ota)
    worker.start()
    worker.join()
    assert d._ota_engine is None and d.ota_active


def test_slow_write_does_not_hold_ui_reservation_lock(qt_app):
    d = driver_fixture()
    entered = threading.Event()
    release = threading.Event()
    def slow_write(data):
        entered.set()
        release.wait(0.5)
        return len(data)
    d.serial.write = slow_write
    assert d.start_ota(filename=NAME, data=b"a")
    worker = threading.Thread(target=d._flush_tx)
    worker.start()
    try:
        assert entered.wait(1)
        started = time.monotonic()
        assert not d.query_status()
        assert not d.stop_ota()
        assert time.monotonic() - started < 0.2
    finally:
        release.set()
        worker.join(timeout=1)
    assert not worker.is_alive()


def test_periodic_queries_do_not_starve_controls_and_scan_does_not_accumulate(qt_app, monkeypatch):
    d = driver_fixture()
    clock = Clock()
    monkeypatch.setattr("soft_hertz_tool.devices.ka_rf_unit.driver.time.monotonic", clock)
    d.set_query_hz(10)
    d._flush_tx()
    assert d.serial.written[-1][4] == 0x20
    assert not d.set_beam(3, 0, 0, 0, 0)
    assert d._tx_queue.empty()
    assert d.set_tx_enabled(True)
    clock.advance(0.5)  # 响应慢于设定查询周期。
    d.handle_bytes(p.encode_frame(p.RES_STATUS, KaRfUnitDeviceSimulator(Port())._status_payload()))
    d._flush_tx()
    assert d.serial.written[-1][4] == 0x12


def test_simulator_v1_rejected_and_removed_commands_silent():
    port = Port()
    sim = KaRfUnitDeviceSimulator(port)
    sim.process_input(p.encode_frame(p.CMD_SET_TX_EN, b"\x01", protocol_version=1))
    assert not sim.tx_enabled
    assert p.parse_response(port.written[-1])[0]["decoded"]["result"] == p.RESULT_BAD_VERSION
    port.written.clear()
    sim.process_input(p.encode_frame(0x22, b"") + p.encode_frame(0x30, b""))
    assert not port.written
    sim.process_input(p.encode_frame(0x20, b"\x00\x32"))
    assert p.parse_response(port.written[-1])[0]["decoded"]["result"] == p.RESULT_BAD_LENGTH


def test_stream_bad_crc_embedded_frame_and_gap():
    clock = Clock()
    parser = FrameStreamParser(clock)
    good = p.encode_frame(p.RES_SET_TX_EN, b"\x00")
    # 错帧的声明长度吞入下一帧；滑窗恢复不丢有效响应。
    bad = b"PSA\x02\x90" + bytes((len(good),)) + b"\x99" + good + b"\x00"
    events = parser.feed(bad)
    assert any(e.kind == "frame" and e.data == good for e in events)
    parser.feed(good[:5])
    clock.advance(0.11)
    events = parser.feed(good)
    assert events[0].kind == "timeout" and events[-1].kind == "frame"


def test_ui_semantic_start_basename_and_generation(qt_app, tmp_path, monkeypatch):
    class Stub(QObject):
        ota_busy_signal = Signal(bool)
        ota_status_signal = Signal(dict)
        ota_event_signal = Signal(str, object)
        ota_progress_signal = Signal(int, int)
        opened_signal = Signal(bool, str)
        finished = Signal()
        running = True
        ota_active = False
        def start_ota(self, **kwargs):
            self.upload = kwargs
            self.ota_busy_signal.emit(True)
            return True
        def stop_ota(self):
            return False
    old, new = Stub(), Stub()
    panel = OtaPanel(old)
    path = tmp_path / NAME
    path.write_bytes(b"abc")
    panel.file_edit.setText(str(path))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    panel._begin()
    assert old.upload == {"filename": NAME, "data": b"abc"}
    assert not panel.begin_btn.isEnabled() and panel.cancel_btn.isEnabled()
    old.ota_event_signal.disconnect(panel._event)
    old.ota_event_signal.connect(panel._event, Qt.QueuedConnection)
    old.ota_event_signal.emit("state", "queued-old-session")
    panel._bind_driver(new)
    qt_app.processEvents()
    assert panel.state_label.text() != "queued-old-session"
    old.ota_event_signal.emit("state", "stale")
    new.ota_event_signal.emit("state", "current")
    qt_app.processEvents()
    assert panel.state_label.text() == "current"
    assert not hasattr(panel, "commit_btn")
    new.ota_status_signal.emit(p.decode_ota_status_response(status((123, 456, 789), last=10)[6:-2]))
    assert "123.456.789" in panel.status_label.text()
    assert "VERIFY_FAILED" in panel.status_label.text()
    panel._bind_driver(None)
    assert not panel.begin_btn.isEnabled()
    panel.close()
