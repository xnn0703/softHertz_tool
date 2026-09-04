"""KA_RF_UNIT 设备包级回归测试。"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, Signal
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


def test_panel_apply_freq_sends_default_0x10_values(qt_app):
    """0x10 页面回调应完成 LO 解析并进入 Driver 语义发送接口。"""

    class _SpyDriver(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.running = True
            self.calls: list[tuple[int, int, int, int, int, int]] = []

        def set_conv_freq(
            self,
            rx_rf_mhz: int,
            rx_lo_mhz: int,
            tx_rf_mhz: int,
            tx_lo_mhz: int,
            rx_polar: int,
            tx_polar: int,
        ) -> bool:
            self.calls.append((rx_rf_mhz, rx_lo_mhz, tx_rf_mhz, tx_lo_mhz, rx_polar, tx_polar))
            return True

    panel = KaRfUnitPanel()
    spy = _SpyDriver()
    panel._driver = spy  # type: ignore[assignment]

    panel._apply_freq()

    assert spy.calls == [(19966, 0, 29500, 0, 0, 0)]


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


# ---------------------------------------------------------------------------
# 波束角度换算（协议层）
# ---------------------------------------------------------------------------


def test_angle_u_to_code_conversion_matches_protocol_spec():
    assert protocol.angle_u_to_code(0.0) == 0
    assert protocol.angle_u_to_code(90.0) == 1024  # 90*2048/180
    assert protocol.angle_u_to_code(180.0) == 2048  # 文档边界
    assert protocol.angle_u_to_code(-0.5) == 4090  # 接近 0 的负值折回高码
    assert protocol.angle_u_to_code(-180.0) == 2048
    # 固件 lroundf(-0.5) = -1，之后 modulo 4096，不能先加 4096 再做半上舍入。
    assert protocol.angle_u_to_code(-0.0439453125) == 4095
    # 高于一个半周的相位与 KA256 V2 一样按 12 bit 回绕。
    assert protocol.angle_u_to_code(186.0) == 2116
    with pytest.raises(ValueError):
        protocol.angle_u_to_code(float("nan"))


def test_compute_beam_pair_matches_formula():
    # θ=0 任何 φ 必然 (0, 0)
    assert protocol.compute_beam_pair(0.0, 45.0, freq_mhz=30000, f0=30000) == (0, 0)
    # θ=30, φ=0: ux=180*sin30*cos0=90, uy=0
    assert protocol.compute_beam_pair(30.0, 0.0, freq_mhz=30000, f0=30000) == (1024, 0)
    # θ=30, φ=90: ux=0, uy=90
    assert protocol.compute_beam_pair(30.0, 90.0, freq_mhz=30000, f0=30000) == (0, 1024)
    # θ=90, φ=0: ux=180, uy=0
    assert protocol.compute_beam_pair(90.0, 0.0, freq_mhz=30000, f0=30000) == (
        protocol.angle_u_to_code(180.0),
        0,
    )
    # 与 KA256 V2 固件 codec 的黄金点逐项一致。
    assert protocol.compute_beam_pair(30.0, 45.0, freq_mhz=29500, f0=protocol.TX_BEAM_F0) == (712, 712)
    assert protocol.compute_beam_pair(30.0, 135.0, freq_mhz=29500, f0=protocol.TX_BEAM_F0) == (3384, 712)
    assert protocol.compute_beam_pair(30.0, 45.0, freq_mhz=19450, f0=protocol.RX_BEAM_F0) == (695, 695)


def test_compute_beam_pair_validates_ranges():
    with pytest.raises(ValueError):
        protocol.compute_beam_pair(120.0, 0.0, freq_mhz=30000, f0=30000)
    with pytest.raises(ValueError):
        protocol.compute_beam_pair(0.0, 400.0, freq_mhz=30000, f0=30000)
    with pytest.raises(ValueError):
        protocol.compute_beam_pair(0.0, 0.0, freq_mhz=0, f0=30000)
    with pytest.raises(ValueError):
        protocol.compute_beam_pair(0.0, 0.0, freq_mhz=30000, f0=0)


def test_build_set_beam_from_angles_matches_explicit_beam():
    # θ=30 φ=90 在 f/f0=1.0 时为 (0, 1024)
    from_angles = protocol.build_set_beam_from_angles(
        0x03, 30.0, 90.0, tx_rf_mhz=30000, rx_rf_mhz=20270
    )
    explicit = protocol.build_set_beam(0x03, 0, 1024, 0, 1024)
    assert from_angles == explicit
    parsed, message = protocol.parse_response(from_angles)
    assert message == "OK"
    assert parsed is not None
    decoded = parsed["decoded"]


def test_build_set_beam_from_angles_rejects_invalid_mask():
    with pytest.raises(ValueError):
        protocol.build_set_beam_from_angles(
            0, 30.0, 90.0, tx_rf_mhz=30000, rx_rf_mhz=20270
        )
    with pytest.raises(ValueError):
        protocol.build_set_beam_from_angles(
            0x04, 30.0, 90.0, tx_rf_mhz=30000, rx_rf_mhz=20270
        )


# ---------------------------------------------------------------------------
# 波束扫描（Panel 状态机）
# ---------------------------------------------------------------------------


def test_scan_params_and_count(qt_app):
    panel = KaRfUnitPanel()
    # 默认范围 0..30 step5 × 0..90 step10 = 7 × 10 = 70
    params = panel._scan_params()
    assert params is not None
    assert panel._scan_count(params) == 70
    pairs = list(panel._scan_iter_pairs(params))
    assert pairs[0] == (0.0, 0.0)
    assert pairs[-1] == (30.0, 90.0)
    assert len(pairs) == 70


def test_scan_params_rejects_zero_step(qt_app):
    from unittest.mock import patch
    panel = KaRfUnitPanel()
    # QDoubleSpinBox 已设 min=0.1，setValue(0.0) 会被夹到 0.1。
    # 临时放宽 min 边界以设置 0 触发校验。
    panel.scan_theta_step.setMinimum(0.0)
    panel.scan_theta_step.setValue(0.0)
    with patch("soft_hertz_tool.devices.ka_rf_unit.panel.QMessageBox.warning"):
        assert panel._scan_params() is None
    panel.scan_theta_step.setMinimum(0.1)
    panel.scan_theta_step.setValue(5.0)
    panel.scan_phi_step.setMinimum(0.0)
    panel.scan_phi_step.setValue(0.0)
    with patch("soft_hertz_tool.devices.ka_rf_unit.panel.QMessageBox.warning"):
        assert panel._scan_params() is None


def test_scan_target_mask_and_freq_source(qt_app):
    panel = KaRfUnitPanel()
    panel.beam_tx_check.setChecked(False)
    panel.beam_rx_check.setChecked(False)
    assert panel._scan_target_mask() == 0
    panel.beam_tx_check.setChecked(True)
    assert panel._scan_target_mask() & protocol.BEAM_TARGET_TX
    # 默认自动频点，未收到 STATUS 时应失败。
    assert panel._scan_resolve_freq(protocol.BEAM_TARGET_TX)[2]
    # 手动 TX/RX 双频分别解析。
    panel.scan_freq_source.setCurrentIndex(1)
    panel.scan_tx_rf.setValue(29500)
    panel.scan_rx_rf.setValue(19966)
    tx, rx, err = panel._scan_resolve_freq(protocol.BEAM_TARGET_ALL)
    assert err == "" and tx == 29500 and rx == 19966


def test_scan_rejects_stale_status_frequency(qt_app):
    panel = KaRfUnitPanel()
    panel._latest_status = {"tx_rf_mhz": 29500, "rx_rf_mhz": 19966}
    panel._last_status_time = time.monotonic() - 1.1
    assert "超时" in panel._scan_resolve_freq(protocol.BEAM_TARGET_ALL)[2]


def test_scan_requires_target_and_driver(qt_app):
    from unittest.mock import patch
    panel = KaRfUnitPanel()
    panel.beam_tx_check.setChecked(False)
    panel.beam_rx_check.setChecked(False)
    # 启动会因 mask=0 终止；QMessageBox.warning 阻塞测试，monkeypatch 屏蔽
    with patch("soft_hertz_tool.devices.ka_rf_unit.panel.QMessageBox.warning"):
        panel._on_scan_start()
    assert panel._scan_state == "IDLE"
    panel.beam_tx_check.setChecked(True)
    panel.scan_freq_source.setCurrentIndex(1)
    panel.scan_tx_rf.setValue(29500)
    with patch("soft_hertz_tool.devices.ka_rf_unit.panel.QMessageBox.warning"):
        panel._on_scan_start()
    # 仍未连接 Driver，按设计仍进入 RUNNING，但每拍会跳过并累计错误
    assert panel._scan_state == "RUNNING"
    # 主动停止以避免后续测试场景中残留 timer
    panel._on_scan_stop()
    assert panel._scan_state == "IDLE"
    panel.scan_interval_ms.setValue(5)


class _StubScanDriver(QObject):
    """最小 Driver 替身：仅暴露 set_beam 与 send_bytes 的状态。"""

    log_signal = Signal(str)
    opened_signal = Signal(bool, str)
    frame_signal = Signal(object)
    status_signal = Signal(dict)
    result_signal = Signal(int, str)
    report_rate_signal = Signal(float)
    finished = Signal()

    def __init__(self, port="spy://", baudrate=460800):
        super().__init__()
        self.port_name = port
        self.baudrate = baudrate
        self.running = True
        self.beam_calls: list[tuple] = []

    def stop(self, timeout_ms=3000):
        self.running = False
        return True

    def start(self):
        return None

    def set_beam(self, target_mask, tx_bh, tx_bv, rx_bh, rx_bv):
        self.beam_calls.append((target_mask, tx_bh, tx_bv, rx_bh, rx_bv))
        return True


def _install_stub_driver(panel, qt_app, target_mask_value=0x03, tx_rf=30000, status_rf=0):
    """注入一个 _StubScanDriver，并完成 connect_device 流程。"""
    driver = _StubScanDriver()
    captured = {}

    def _factory(port, baudrate):
        captured["port"] = port
        captured["baudrate"] = baudrate
        return driver

    panel._driver_factory = _factory
    panel.beam_tx_check.setChecked(True)
    panel.beam_rx_check.setChecked(bool(target_mask_value & 0x02))
    panel.scan_freq_source.setCurrentIndex(1)
    panel.scan_tx_rf.setValue(tx_rf)
    # 提供 STATUS_REPORT 中的 RF，确保 frequency source=auto 时也能跑
    if status_rf:
        panel._latest_status = {
            "tx_rf_mhz": status_rf,
            "rx_rf_mhz": status_rf,
        }
    panel._connect_device("spy://", 460800)
    panel._connection_generation += 0  # keep simple
    # 触发 opened_signal 让 serial_connection 切到已连接
    for slot, msg in [
        (panel._on_driver_opened, True),
    ]:
        try:
            slot(driver, panel._connection_generation, True, "已打开")
        except TypeError:
            slot(driver, panel._connection_generation, True, "已打开")
    qt_app.processEvents()
    return driver


def test_scan_emit_expected_angle_sequence(qt_app):
    panel = KaRfUnitPanel()
    panel.scan_theta_start.setValue(0.0)
    panel.scan_theta_end.setValue(10.0)
    panel.scan_theta_step.setValue(10.0)
    panel.scan_phi_start.setValue(0.0)
    panel.scan_phi_end.setValue(20.0)
    panel.scan_phi_step.setValue(10.0)
    panel.scan_interval_ms.setValue(5)
    driver = _install_stub_driver(panel, qt_app, target_mask_value=0x03, tx_rf=30000)
    panel._on_scan_start()
    # 模拟 QTimer 触发：直接调用 _scan_tick 直到结束
    for _ in range(panel._scan_total + 2):
        if panel._scan_state != "RUNNING":
            break
        panel._scan_tick()
    assert panel._scan_state == "FINISHED"
    assert panel._scan_index == 6  # 2 θ × 3 φ = 6 拍
    # FINISHED 时控件可重新启动
    assert panel.scan_start_btn.isEnabled()
    # 验证最后一次调用是 (10, 20)
    mask, tx_bh, tx_bv, rx_bh, rx_bv = driver.beam_calls[-1]
    assert mask == 0x03
    expected_tx = protocol.compute_beam_pair(10.0, 20.0, freq_mhz=30000, f0=protocol.TX_BEAM_F0)
    assert (tx_bh, tx_bv) == expected_tx
    panel.shutdown()
    panel._driver = None  # avoid teardown warnings


def test_scan_tx_only_does_not_calculate_rx_from_tx_frequency(qt_app):
    panel = KaRfUnitPanel()
    panel.scan_theta_start.setValue(90.0)
    panel.scan_theta_end.setValue(90.0)
    panel.scan_phi_start.setValue(0.0)
    panel.scan_phi_end.setValue(0.0)
    panel.scan_interval_ms.setValue(5)
    driver = _install_stub_driver(panel, qt_app, target_mask_value=0x01, tx_rf=31000)
    panel._on_scan_start()
    panel._scan_tick()
    assert driver.beam_calls == [(0x01, 2116, 0, 0, 0)]
    panel.shutdown()
    panel._driver = None


def test_scan_pause_and_resume(qt_app):
    panel = KaRfUnitPanel()
    panel.scan_theta_start.setValue(0.0)
    panel.scan_theta_end.setValue(10.0)
    panel.scan_theta_step.setValue(10.0)
    panel.scan_phi_start.setValue(0.0)
    panel.scan_phi_end.setValue(0.0)
    panel.scan_phi_step.setValue(10.0)
    panel.scan_interval_ms.setValue(5)
    _install_stub_driver(panel, qt_app, target_mask_value=0x01, tx_rf=30000)
    panel._on_scan_start()
    panel._scan_tick()  # 跑 1 拍
    panel._on_scan_pause()
    assert panel._scan_state == "PAUSED"
    paused_index = panel._scan_index
    # 暂停期间手动 tick 不应改变状态（_scan_tick 内 RUNNING 检查会直接 return）
    panel._scan_tick()
    assert panel._scan_index == paused_index
    panel._on_scan_pause()  # 继续
    assert panel._scan_state == "RUNNING"
    while panel._scan_state == "RUNNING":
        panel._scan_tick()
    assert panel._scan_state == "FINISHED"
    assert panel._scan_index == 2  # 0..10 × 0 = 2 拍
    assert panel.scan_start_btn.isEnabled()
    panel.shutdown()
    panel._driver = None


def test_scan_stop_resets_state(qt_app):
    panel = KaRfUnitPanel()
    panel.scan_interval_ms.setValue(5)
    _install_stub_driver(panel, qt_app, target_mask_value=0x01, tx_rf=30000)
    panel._on_scan_start()
    panel._scan_tick()
    panel._on_scan_stop()
    # 用户主动结束 → IDLE 且按钮复位
    assert panel._scan_state == "IDLE"
    assert panel.scan_start_btn.isEnabled()
    assert not panel.scan_pause_btn.isEnabled()
    panel.shutdown()
    panel._driver = None


def test_scan_disconnect_stops_timer(qt_app):
    panel = KaRfUnitPanel()
    panel.scan_interval_ms.setValue(5)
    _install_stub_driver(panel, qt_app, target_mask_value=0x01, tx_rf=30000)
    panel._on_scan_start()
    panel._scan_tick()
    # deactivate 强制停 timer 并把状态切到 PAUSED
    panel.deactivate()
    assert not panel._scan_timer.isActive()
    assert panel._scan_state == "PAUSED"
    # shutdown 后回到 IDLE
    panel.shutdown()
    assert panel._scan_state == "IDLE"
    panel._driver = None


def test_scan_skips_when_driver_not_running(qt_app):
    panel = KaRfUnitPanel()
    panel.scan_interval_ms.setValue(5)
    _install_stub_driver(panel, qt_app, target_mask_value=0x01, tx_rf=30000)
    # 把 driver 标记为未运行
    panel._driver.running = False
    panel._on_scan_start()
    panel._scan_tick()
    assert panel._scan_skipped >= 1
    assert panel._scan_index == 1
    panel.shutdown()
    panel._driver = None


# ---------------------------------------------------------------------------
# Simulator 接收角度帧
# ---------------------------------------------------------------------------


def test_simulator_applies_beam_from_angle_frame():
    fake = _FakePort()
    sim = KaRfUnitDeviceSimulator(fake)
    frame = protocol.build_set_beam_from_angles(
        0x03, 30.0, 90.0, tx_rf_mhz=30000, rx_rf_mhz=20270
    )
    sim.process_input(frame)
    expected_tx = protocol.compute_beam_pair(30.0, 90.0, freq_mhz=30000, f0=protocol.TX_BEAM_F0)
    expected_rx = protocol.compute_beam_pair(30.0, 90.0, freq_mhz=20270, f0=protocol.RX_BEAM_F0)
    assert (sim.tx_beam_h, sim.tx_beam_v) == expected_tx
    assert (sim.rx_beam_h, sim.rx_beam_v) == expected_rx
    assert fake._written and fake._written[-1][-3] == protocol.RESULT_OK
