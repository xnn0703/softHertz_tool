"""KA_RF_UNIT 设备包级回归测试。"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from soft_hertz_tool.devices.ka_rf_unit import protocol
from soft_hertz_tool.devices.ka_rf_unit.driver import KaRfUnitDriver, MODEL_NAME
from soft_hertz_tool.devices.ka_rf_unit.panel import KaRfUnitPanel
from soft_hertz_tool.devices.ka_rf_unit.simulator import KaRfUnitDeviceSimulator
from soft_hertz_tool.devices.ka_rf_unit.stream import FrameStreamParser


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


# ---------------------------------------------------------------------------
# 协议层
# ---------------------------------------------------------------------------


def test_crc16_ccitt_false_matches_reference_vector():
    assert protocol.crc16_ccitt_false(b"123456789") == 0x29B1


def test_builders_match_doc_samples():
    expected_frames = {
        "0x10": (
            protocol.build_set_conv_freq(19966, 0, 29500, 0, 1, 0),
            "50 53 41 01 10 0A 4D FE 00 00 73 3C 00 00 01 00 C0 E9",
        ),
        "0x11": (
            protocol.build_set_conv_att(12.5, 4.5),
            "50 53 41 01 11 04 00 7D 00 2D 96 00",
        ),
        "0x12": (
            protocol.build_set_tx_en(True),
            "50 53 41 01 12 01 01 66 B3",
        ),
        "0x13": (
            protocol.build_set_rx_en(True),
            "50 53 41 01 13 01 01 51 83",
        ),
        "0x14": (
            protocol.build_set_beam(0x03, 314, 314, 302, 302),
            "50 53 41 01 14 09 03 01 3A 01 3A 01 2E 01 2E A5 43",
        ),
        "0x15": (
            protocol.build_set_ext_ref(10),
            "50 53 41 01 15 02 00 0A 25 66",
        ),
        "0x20": (
            protocol.build_set_report_hz(50),
            "50 53 41 01 20 02 00 32 02 91",
        ),
    }
    for name, (frame, sample) in expected_frames.items():
        assert frame.hex(" ").upper() == sample, name


def test_validators_enforce_protocol_ranges():
    assert protocol.rx_rf_valid(17700) and protocol.rx_rf_valid(21200)
    assert not protocol.rx_rf_valid(17699) and not protocol.rx_rf_valid(21201)
    assert protocol.tx_rf_valid(27500) and protocol.tx_rf_valid(31000)
    assert not protocol.tx_rf_valid(27499)
    assert protocol.rx_lo_valid(0) and protocol.rx_lo_valid(16750) and protocol.rx_lo_valid(19250)
    assert not protocol.rx_lo_valid(16751) and not protocol.rx_lo_valid(19249)
    assert protocol.tx_lo_valid(0) and protocol.tx_lo_valid(26550) and protocol.tx_lo_valid(29050)
    assert not protocol.tx_lo_valid(26551)
    assert protocol.conv_att_valid(0) and protocol.conv_att_valid(315) and protocol.conv_att_valid(5)
    assert not protocol.conv_att_valid(1) and not protocol.conv_att_valid(316)
    assert protocol.ext_ref_valid(10) and protocol.ext_ref_valid(100)
    assert not protocol.ext_ref_valid(50)


def test_beam_builder_rejects_invalid_target_mask():
    with pytest.raises(ValueError):
        protocol.build_set_beam(0, 0, 0, 0, 0)
    with pytest.raises(ValueError):
        protocol.build_set_beam(0x04, 0, 0, 0, 0)


def test_beam_builder_rejects_out_of_range_beam_codes():
    with pytest.raises(ValueError):
        protocol.build_set_beam(0x01, 4096, 0, 0, 0)


def test_conv_freq_builder_rejects_out_of_range_rf():
    with pytest.raises(ValueError):
        protocol.build_set_conv_freq(17699, 0, 29500, 0, 0, 0)
    with pytest.raises(ValueError):
        protocol.build_set_conv_freq(19966, 0, 31001, 0, 0, 0)


def test_status_report_decode_full_payload():
    status = protocol.build_status_report(
        uptime_ms=12345,
        conv_lock_mask=0x0007,
        pa_enable=True,
        tx_enable=True,
        rx_enable=False,
        status_report_rate_hz=50,
        unit_sw=0x0100,
        rx_rf_mhz=19966,
        rx_lo_mhz=19250,
        tx_rf_mhz=29500,
        tx_lo_mhz=28050,
        rx_conv_att_x10=125,
        tx_conv_att_x10=45,
        ext_ref_mhz=100,
        conv_temp_x10=350,
        tx_array_temp_x10=410,
        rx_array_temp_x10=405,
        tx_beam_h=314,
        tx_beam_v=314,
        rx_beam_h=302,
        rx_beam_v=302,
        rx_polar=1,
        tx_polar=0,
    )
    parsed, message = protocol.parse_response(status)
    assert message == "OK"
    assert parsed is not None
    assert parsed["command"] == protocol.CMD_STATUS_REPORT
    decoded = parsed["decoded"]
    assert decoded["uptime_ms"] == 12345
    assert decoded["conv_lock_mask"] == 0x0007
    assert decoded["conv_lock"] == protocol.LockMask(True, True, True)
    assert decoded["rx_rf_mhz"] == 19966
    assert decoded["unit_sw"] == 0x0100
    assert decoded["conv_temp_x10"] == 350
    assert decoded["tx_beam_h"] == 314


def test_response_with_bad_payload_length_is_rejected():
    # 错长度的 0x30 帧应被 parse_response 拒绝
    bad_payload = b"\x00" * 42  # STATUS_REPORT 必须为 43 B
    bad_frame = protocol.encode_frame(protocol.CMD_STATUS_REPORT, bad_payload)
    parsed, message = protocol.parse_response(bad_frame)
    assert parsed is None
    assert "载荷长度" in message

    # 控制响应 payload 长度不为 1 时也应被拒绝
    bad_response = protocol.encode_frame(protocol.RES_SET_TX_EN, b"\x00\x00")
    parsed, message = protocol.parse_response(bad_response)
    assert parsed is None
    assert "载荷长度" in message


def test_parse_response_rejects_bad_magic_and_crc():
    payload = b"\x00\x00\x00\x01\x10\x00"
    parsed, message = protocol.parse_response(payload + b"\x00\x00")
    assert parsed is None
    assert "帧头" in message

    valid = protocol.build_set_conv_freq(19966, 0, 29500, 0, 0, 0)
    broken = bytearray(valid)
    broken[-1] ^= 0xFF
    parsed, message = protocol.parse_response(bytes(broken))
    assert parsed is None
    assert "CRC" in message


def test_describe_summarizes_status_and_results():
    parsed, _ = protocol.parse_response(
        protocol.build_status_report(
            uptime_ms=1, conv_lock_mask=0x0002, pa_enable=False, tx_enable=False, rx_enable=False,
            status_report_rate_hz=0, unit_sw=0,
            rx_rf_mhz=19966, rx_lo_mhz=19250, tx_rf_mhz=29500, tx_lo_mhz=0,
            rx_conv_att_x10=0, tx_conv_att_x10=0, ext_ref_mhz=10,
            conv_temp_x10=0, tx_array_temp_x10=0, rx_array_temp_x10=0,
            tx_beam_h=0, tx_beam_v=0, rx_beam_h=0, rx_beam_v=0,
            rx_polar=0, tx_polar=0,
        )
    )
    assert parsed is not None
    text = protocol.describe(parsed, "OK")
    assert "0x30" in text and "RX_LO=L" in text

    parsed, _ = protocol.parse_response(protocol.encode_frame(protocol.RES_SET_TX_EN, b"\x00"))
    assert parsed is not None
    assert protocol.describe(parsed, "OK") == "0x92 OK"


# ---------------------------------------------------------------------------
# 流解析层
# ---------------------------------------------------------------------------


def test_stream_parser_handles_garbage_split_and_bad_length():
    parser = FrameStreamParser()
    valid = protocol.build_set_tx_en(True)

    # 异常字节 + 完整帧
    events = parser.feed(b"\x00\x55" + valid)
    assert [event.kind for event in events][:1] == ["garbage"]
    assert any(event.kind == "frame" for event in events)

    # 分包
    parser.reset()
    half = len(valid) // 2
    events = parser.feed(valid[:half])
    assert events == []
    events = parser.feed(valid[half:])
    assert [event.kind for event in events] == ["frame"]

    # 坏长度触发 bad_length，但保留剩余字节用于重新同步
    parser.reset()
    bad_header = b"\x50\x53\x41\x01\x10\xff"  # length > MAX_PAYLOAD
    events = parser.feed(bad_header + valid)
    assert events[0].kind == "bad_length"
    assert any(event.kind == "frame" for event in events[1:])

    # CRC 错误产生 bad_frame
    parser.reset()
    broken = bytearray(valid)
    broken[-1] ^= 0xFF
    events = parser.feed(bytes(broken))
    assert events[0].kind == "bad_frame"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


class _RecordingSerial:
    """pyserial 替身，捕获写入并按需暴露已读取字节。"""

    def __init__(self):
        self.in_waiting = 0
        self._buffer = bytearray()
        self._written: list[bytes] = []
        self.is_open = True
        self.timeout = 0

    def write(self, data: bytes) -> int:
        self._written.append(bytes(data))
        return len(data)

    def read(self, count: int) -> bytes:
        if not self._buffer:
            return b""
        chunk = bytes(self._buffer[:count])
        del self._buffer[:count]
        return chunk

    def feed(self, data: bytes) -> None:
        self._buffer.extend(data)
        self.in_waiting = len(self._buffer)


def test_driver_emits_status_signal_for_status_report(qt_app):
    received = []

    class _SpyDriver(KaRfUnitDriver):
        def run(self):  # type: ignore[override]
            return None

        def stop(self, timeout_ms=3000):  # type: ignore[override]
            return True

    driver = _SpyDriver("spy://port", 460800)
    driver.status_signal.connect(lambda status: received.append(status))

    status = protocol.build_status_report(
        uptime_ms=7, conv_lock_mask=0x0001, pa_enable=False, tx_enable=False, rx_enable=True,
        status_report_rate_hz=10, unit_sw=0x0100,
        rx_rf_mhz=19966, rx_lo_mhz=19250, tx_rf_mhz=29500, tx_lo_mhz=28050,
        rx_conv_att_x10=0, tx_conv_att_x10=0, ext_ref_mhz=10,
        conv_temp_x10=0, tx_array_temp_x10=0, rx_array_temp_x10=0,
        tx_beam_h=0, tx_beam_v=0, rx_beam_h=0, rx_beam_v=0,
        rx_polar=0, tx_polar=0,
    )
    driver.handle_bytes(status)
    qt_app.processEvents()
    assert received and received[0]["rx_enable"] == 1
    assert received[0]["conv_lock"].ref_valid is True


def test_driver_emits_result_signal_for_command_response(qt_app):
    results = []

    class _SpyDriver(KaRfUnitDriver):
        def run(self):  # type: ignore[override]
            return None

        def stop(self, timeout_ms=3000):  # type: ignore[override]
            return True

    driver = _SpyDriver("spy://port", 460800)
    driver.result_signal.connect(lambda command, name: results.append((command, name)))

    response = protocol.encode_frame(protocol.RES_SET_BEAM, b"\x00")
    driver.handle_bytes(response)
    qt_app.processEvents()
    assert results == [(protocol.RES_SET_BEAM, "OK")]


def test_driver_queue_frame_uses_send_bytes(qt_app):
    from PySide6.QtCore import QObject

    class _SpyDriver(KaRfUnitDriver):
        def __init__(self, port, baudrate, parent=None):
            super().__init__(port, baudrate, parent=parent)
            self._sent: list[bytes] = []

        def run(self):  # type: ignore[override]
            return None

        def stop(self, timeout_ms=3000):  # type: ignore[override]
            return True

        def send_bytes(self, frame: bytes) -> bool:
            self._sent.append(bytes(frame))
            return True

    # 直接调 _queue_frame 跳过 send_bytes 的 running 检查
    spy = _SpyDriver("spy://port", 460800)
    spy._queue_frame(protocol.build_set_tx_en(False))
    spy._queue_frame(protocol.build_set_report_hz(10))
    assert len(spy._sent) == 2


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------


class _FakePort:
    def __init__(self):
        self.in_waiting = 0
        self._buffer = bytearray()
        self._written: list[bytes] = []

    def write(self, data):
        self._written.append(bytes(data))
        return len(data)

    def read(self, count):
        chunk = bytes(self._buffer[:count])
        del self._buffer[:count]
        return chunk


def test_simulator_acknowledges_valid_commands_and_rejects_invalid():
    fake = _FakePort()
    sim = KaRfUnitDeviceSimulator(fake)
    sim.report_hz = 0  # 关闭主动上报，便于断言

    # 0x10 合法
    sim.process_input(protocol.build_set_conv_freq(19966, 0, 29500, 0, 0, 0))
    # 0x11 合法
    sim.process_input(protocol.build_set_conv_att(10.0, 5.0))
    # 0x12 开启 TX
    sim.process_input(protocol.build_set_tx_en(True))
    # 0x14 设置波束 (target=0x03 TX+RX; tx_bh/v=100; rx_bh/v=200)
    sim.process_input(protocol.build_set_beam(0x03, 100, 100, 200, 200))
    # 0x15 外参
    sim.process_input(protocol.build_set_ext_ref(10))
    # 0x20 上报频率
    sim.process_input(protocol.build_set_report_hz(50))
    # 0x13 RX
    sim.process_input(protocol.build_set_rx_en(True))

    assert sim.tx_enabled is True and sim.rx_enabled is True
    assert sim.pa_enabled is True
    assert sim.tx_att_x10 == 50
    assert sim.tx_beam_h == 100 and sim.tx_beam_v == 100
    assert sim.rx_beam_h == 200 and sim.rx_beam_v == 200
    assert sim.ext_ref_mhz == 10

    # 至少 6 条响应写入，最后一条为 0x93
    responses = [frame for frame in fake._written]
    commands = [frame[4] for frame in responses]
    assert commands[-1] == protocol.RES_SET_RX_EN
    assert all(frame[-3] == protocol.RESULT_OK for frame in responses)

    # 非法 0x11 应返回 OUT_OF_RANGE（手动构造一个无效衰减帧，绕过构帧器校验）
    fake._written.clear()
    bad_att_frame = protocol.encode_frame(
        protocol.CMD_SET_CONV_ATT, protocol.be16_write(500) + protocol.be16_write(0)
    )
    sim.process_input(bad_att_frame)
    assert fake._written and fake._written[0][-3] == protocol.RESULT_OUT_OF_RANGE


def test_simulator_emits_status_report_when_running(qt_app):
    import threading

    fake = _FakePort()
    sim = KaRfUnitDeviceSimulator(fake)
    sim.report_hz = 200
    thread = threading.Thread(target=sim.run, kwargs={"duration": 0.1}, daemon=True)
    thread.start()
    thread.join(timeout=0.5)
    sim.stop()
    thread.join(timeout=0.2)
    assert fake._written, "模拟器在 200 Hz 下应至少发出一帧 STATUS_REPORT"
    status_frame = fake._written[-1]
    parsed, message = protocol.parse_response(status_frame)
    assert message == "OK"
    assert parsed is not None
    assert parsed["command"] == protocol.CMD_STATUS_REPORT
    assert parsed["decoded"]["status_report_rate_hz"] == 200


# ---------------------------------------------------------------------------
# Panel 生命周期
# ---------------------------------------------------------------------------


def test_panel_shutdown_is_idempotent_and_disconnects(qt_app):
    from PySide6.QtCore import QObject

    panel = KaRfUnitPanel()

    called = {"stop": 0}

    class _StubDriver(QObject):
        def __init__(self):
            super().__init__()
            self.running = False

        def stop(self, timeout_ms=3000):
            called["stop"] += 1
            return True

    panel._driver = _StubDriver()

    assert panel.shutdown() is True
    assert panel.shutdown() is True
    assert called["stop"] == 1


def test_panel_close_event_ignores_when_stop_fails(qt_app):
    from PySide6.QtCore import QObject

    class _Event:
        def __init__(self):
            self.ignored = False

        def ignore(self):
            self.ignored = True

    panel = KaRfUnitPanel()

    class _StubDriver(QObject):
        def __init__(self):
            super().__init__()
            self.running = False

        def stop(self, timeout_ms=3000):
            return False

    panel._driver = _StubDriver()
    event = _Event()
    panel.closeEvent(event)  # type: ignore[arg-type]
    assert event.ignored is True


def test_panel_connection_generation_drops_stale_signals(qt_app):
    from PySide6.QtCore import QObject

    panel = KaRfUnitPanel()

    class _StubDriver(QObject):
        def __init__(self):
            super().__init__()
            self.running = True

        def stop(self, timeout_ms=3000):
            self.running = False
            return True

    old_driver = _StubDriver()
    panel._driver = old_driver
    panel._connection_generation = 3

    # 模拟新一代际已经建立
    new_driver = _StubDriver()
    panel._driver = new_driver
    panel._connection_generation = 4

    # 用旧代际 3 调用：应当不污染 UI
    panel._on_driver_log(old_driver, 3, "旧日志")
    panel._on_driver_opened(old_driver, 3, True, "旧串口打开")
    panel._on_driver_status(old_driver, 3, {"uptime_ms": 1})

    # 因为是新代际，旧信号不应写日志/状态/串口
    assert panel._latest_status is None


def test_panel_uses_factory_for_driver_creation(qt_app):
    from PySide6.QtCore import QObject, Signal

    captured: dict[str, object] = {}

    class _StubDriver(QObject):
        log_signal = Signal(str)
        opened_signal = Signal(bool, str)
        frame_signal = Signal(object)
        status_signal = Signal(dict)
        result_signal = Signal(int, str)
        report_rate_signal = Signal(float)
        finished = Signal()

        def __init__(self, port, baudrate):
            super().__init__()
            captured["port"] = port
            captured["baudrate"] = baudrate
            self.running = False

        def stop(self, timeout_ms=3000):
            return True

        def start(self):
            return None

    panel = KaRfUnitPanel(driver_factory=_StubDriver)  # type: ignore[arg-type]
    panel._connect_device("COM5", 460800)  # type: ignore[arg-type]
    assert captured == {"port": "COM5", "baudrate": 460800}
    panel._stop_driver()


# ---------------------------------------------------------------------------
# 字段 / 协议导出
# ---------------------------------------------------------------------------


def test_module_level_aliases_and_metadata():
    from soft_hertz_tool.devices import ka_rf_unit as pkg

    assert pkg.KaRfUnitPanel is pkg.DevicePanel
    assert pkg.KaRfUnitDriver is pkg.DeviceDriver
    assert MODEL_NAME == "KA_RF_UNIT"


def test_model_name_in_serial_thread_record(qt_app):
    class _SpyDriver(KaRfUnitDriver):
        def run(self):  # type: ignore[override]
            return None

        def stop(self, timeout_ms=3000):  # type: ignore[override]
            return True

    driver = _SpyDriver("spy://", 460800)
    records = []

    driver.frame_signal.connect(lambda record: records.append(record))
    driver.handle_bytes(protocol.build_set_tx_en(True))
    qt_app.processEvents()
    assert records and records[0].model == MODEL_NAME


def test_qsettings_storage_for_workspace_settings(qt_app, tmp_path):
    settings = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    settings.setValue("device_model", "KA_RF_UNIT")
    settings.sync()
    reread = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    assert reread.value("device_model") == "KA_RF_UNIT"