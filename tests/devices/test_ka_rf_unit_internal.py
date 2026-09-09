"""内部 20260909 协议黄金帧、流解析与模拟器控制独立性。"""
import struct

import pytest

from soft_hertz_tool.devices.ka_rf_unit import protocol as p
from soft_hertz_tool.devices.ka_rf_unit.simulator import KaRfUnitDeviceSimulator
from soft_hertz_tool.devices.ka_rf_unit.stream import FrameStreamParser


@pytest.mark.parametrize("frame, expected", [
    (p.build_internal_switch(p.CMD_SET_PA, True), "50 53 41 01 40 01 01 56 1d"),
    (p.build_array_mask(3, 1, 128, 255, 255), "50 53 41 01 43 05 03 01 80 ff ff 99 d1"),
    (p.build_beam_angles(3, 30, 45, 30, 45), "50 53 41 01 44 09 03 0b b8 11 94 0b b8 11 94 b6 55"),
    (p.build_internal_status_query(), "50 53 41 01 45 00 58 45"),
    (p.build_array_attenuation(3, 8, 7.5, 4.5, 2.5), "50 53 41 01 46 05 03 10 0f 09 05 6d 3c"),
    (p.build_array_attenuation_query(), "50 53 41 01 47 00 3e 27"),
])
def test_golden_and_every_split(frame, expected):
    assert frame == bytes.fromhex(expected)
    for split in range(len(frame) + 1):
        stream = FrameStreamParser()
        events = stream.feed(b"noise" + frame[:split]) + stream.feed(frame[split:] + frame)
        assert [e.data for e in events if e.kind == "frame"] == [frame, frame]
    bad = frame[:-1] + bytes([frame[-1] ^ 1])
    assert p.parse_response(bad)[0] is None
    assert p.parse_response(p.encode_frame(frame[4], frame[6:-2], protocol_version=2))[0] is None


@pytest.mark.parametrize("cmd,data,result", [
    (0x40, b"\x02", p.RESULT_OUT_OF_RANGE), (0x41, b"", p.RESULT_BAD_LENGTH),
    (0x42, b"\x01", p.RESULT_OK), (0x43, b"\x00\xff\xff\xff\xff", p.RESULT_OUT_OF_RANGE),
    (0x44, struct.pack(">BHHHH", 1, 9000, 35999, 65535, 65535), p.RESULT_OK),
    (0x44, struct.pack(">BHHHH", 3, 9000, 35999, 65535, 65535), p.RESULT_OUT_OF_RANGE),
    (0x44, struct.pack(">BHHHH", 1, 9001, 0, 0, 0), p.RESULT_OUT_OF_RANGE),
    (0x45, b"\x00", p.RESULT_BAD_LENGTH), (0x48, b"", p.RESULT_UNSUPPORTED),
])
def test_validation(cmd, data, result):
    assert p.validate_internal_payload(cmd, data) == result


class Port:
    def __init__(self):
        self.frames = []

    def write(self, data):
        self.frames.append(bytes(data))
        return len(data)


def test_independent_controls_and_customer_override():
    port = Port()
    sim = KaRfUnitDeviceSimulator(port)
    sim.process_input(p.build_internal_switch(p.CMD_SET_PA, True))
    assert sim.pa_enabled and not sim.tx_enabled and sim.tx_if_enabled
    sim.process_input(p.build_internal_switch(p.CMD_SET_TX_IF, False))
    sim.process_input(p.build_internal_switch(p.CMD_SET_RX_IF, False))
    sim.process_input(p.build_array_mask(1, 1, 128, 0, 0))
    assert sim.pa_enabled and sim.tx_enabled and sim.rx_enabled
    sim.process_input(p.build_set_tx_en(False))
    assert not sim.pa_enabled and sim.tx_rows == sim.tx_cols == 0
    assert not sim.tx_if_enabled and not sim.rx_if_enabled
    sim.process_input(p.build_set_conv_freq(19966, 0, 31000, 0, 1, 0))
    sim.process_input(p.build_set_ext_ref(50))
    assert not sim.tx_if_enabled and not sim.rx_if_enabled
    sim.process_input(p.build_internal_status_query())
    parsed, _ = p.parse_response(port.frames[-1])
    status = parsed["decoded"]
    assert status["requested_flags"] == 16 and status["sent_value_flags"] == 16
    assert status["sent_valid_flags"] == 31
    assert status["rx_sent_rows"] == 255


@pytest.mark.parametrize("theta,phi", [(0, 0), (90, 0), (45, 90), (30, 180), (30, 270), (90, 359.99)])
def test_angles_match_raw_and_preserve_unselected(theta, phi):
    sim = KaRfUnitDeviceSimulator(Port())
    sim.process_input(p.build_beam_angles(3, theta, phi, theta, phi))
    tx = p.compute_beam_pair(theta, phi, freq_mhz=sim.tx_rf_mhz, f0=p.TX_BEAM_F0)
    rx = p.compute_beam_pair(theta, phi, freq_mhz=sim.rx_rf_mhz, f0=p.RX_BEAM_F0)
    assert (sim.tx_beam_h, sim.tx_beam_v, sim.rx_beam_h, sim.rx_beam_v) == (*tx, *rx)
    sim.process_input(p.build_beam_angles(1, 0, 0, float("nan"), float("inf")))
    assert (sim.rx_beam_h, sim.rx_beam_v) == rx
    assert p.angle_u_to_code(-0.0439453125) == 4095


def test_internal_query_errors():
    sim = KaRfUnitDeviceSimulator(Port())
    sim.process_input(p.encode_frame(p.CMD_GET_INTERNAL_STATUS, b"x"))
    parsed, _ = p.parse_response(sim.serial.frames[-1])
    assert parsed["decoded"]["result"] == p.RESULT_BAD_LENGTH
    assert p.parse_response(p.encode_frame(0xC5, b"\x00"))[0] is None


@pytest.mark.parametrize("value", [-1, 90.01, float("nan"), float("inf")])
def test_invalid_theta(value):
    with pytest.raises(ValueError):
        p.build_beam_angles(1, value, 0, 0, 0)


def test_driver_and_panel_internal_controls():
    from PySide6.QtWidgets import QApplication
    from soft_hertz_tool.devices.ka_rf_unit.driver import KaRfUnitDriver
    from soft_hertz_tool.devices.ka_rf_unit.panel import KaRfUnitPanel

    app = QApplication.instance() or QApplication([])

    class Driver(KaRfUnitDriver):
        def send_bytes(self, frame):
            self.sent.append(frame)
            return True

    driver = Driver("test", 460800)
    driver.sent = []
    driver.running = True
    panel = KaRfUnitPanel()
    assert not panel.internal_group.isEnabled()
    panel._driver = driver
    panel.internal_target.setCurrentIndex(1)  # TX
    panel._set_mask_boxes(panel.internal_masks["TX 行"], False)
    panel.internal_masks["TX 行"][2].setChecked(True)
    panel._apply_internal_mask()
    assert driver.sent[-1] == p.build_array_mask(1, 4, 255, 255, 255)
    panel.internal_angles[0].setValue(30)
    panel.internal_angles[1].setValue(45)
    panel._apply_internal_angles()
    assert driver.sent[-1] == p.build_beam_angles(1, 30, 45, 0, 0)
    panel._query_internal_status()
    assert driver.sent[-1] == p.build_internal_status_query()
    panel.array_att_inputs[0].setValue(8)
    panel.array_att_inputs[1].setValue(7.5)
    panel._apply_array_attenuation(1)
    assert driver.sent[-1] == p.build_array_attenuation(1, 8, 7.5, 0, 0)
    panel._query_array_attenuation()
    assert driver.sent[-1] == p.build_array_attenuation_query()
    att_received = []
    driver.array_attenuation_signal.connect(att_received.append)
    driver.handle_bytes(p.encode_frame(0xC7, bytes((0, 1, 3, 0, 1, 1, 16, 15, 0, 0))))
    panel._on_array_attenuation(driver, panel._connection_generation, att_received[0])
    assert "BF0" in panel.array_att_status_label.text()
    assert "8 / 支路 7.5" in panel.array_att_status_label.text()
    assert panel.array_att_inputs[0].value() == 8
    text = panel.array_att_status_label.text()
    panel._on_array_attenuation(driver, panel._connection_generation - 1, att_received[0])
    assert panel.array_att_status_label.text() == text
    received = []
    driver.internal_status_signal.connect(received.append)
    response = p.encode_frame(0xC5, bytes((0, 1, 22, 31, 22, 0, 0, 255, 255, 0, 0, 255, 255)))
    driver.handle_bytes(response)
    assert received[0]["sent_valid_flags"] == 31
    panel._on_internal_status(driver, panel._connection_generation, received[0])
    assert "TX IF 请求开 / 发送开" in panel.internal_status_label.text()
    assert panel.internal_angles[0].value() == 30  # 查询不覆盖操作输入
    panel._driver = None
    panel.shutdown()
    driver.running = False
    driver.deleteLater()
    panel.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("bf,common,branch,valid", [(0,0,0,True), (0,16,15,True), (0,1,0,False),
    (1,15,15,True), (1,16,0,False), (1,0,16,False), (255,0,0,False)])
def test_array_att_bf_contract(bf, common, branch, valid):
    assert p.array_attenuation_valid(bf, common, branch) is valid


def test_array_attenuation_simulator_and_errors():
    sim = KaRfUnitDeviceSimulator(Port())
    for frame in (p.build_array_attenuation(1,8,7.5,float('nan'),float('nan')),
                  p.build_array_attenuation(2,0,0,4.5,2.5)):
        for split in range(len(frame) + 1):
            stream = FrameStreamParser()
            events = stream.feed(frame[:split]) + stream.feed(frame[split:] + frame)
            assert len([e for e in events if e.kind == "frame"]) == 2
        sim.process_input(frame)
    assert sim.array_att == [16,15,9,5]
    assert not sim.pa_enabled and sim.tx_if_enabled and sim.rx_att_x10 == 0
    sim.process_input(p.build_array_attenuation_query())
    status = p.parse_response(sim.serial.frames[-1])[0]["decoded"]
    assert status["attenuation_sent_valid_mask"] == 3 and status["rx_common"] == 9
    sim.process_input(p.build_array_attenuation(3,0.5,0,0,0))
    assert p.parse_response(sim.serial.frames[-1])[0]["decoded"]["result"] == p.RESULT_OUT_OF_RANGE
    assert sim.array_att == [16,15,9,5]  # 双侧先全校验，拒绝时都保持原值
    sim.array_bf_valid = 0
    sim.process_input(p.build_array_attenuation(1,0,0,0,0))
    assert p.parse_response(sim.serial.frames[-1])[0]["decoded"]["result"] == p.RESULT_UNSUPPORTED
    for cmd, data, result in ((0x46,b"",p.RESULT_BAD_LENGTH), (0x46,bytes((0,0,0,0,0)),p.RESULT_OUT_OF_RANGE),
                              (0x46,bytes((1,17,0,0,0)),p.RESULT_OUT_OF_RANGE),
                              (0x46,bytes((1,16,15,255,255)),p.RESULT_OK), (0x47,b"x",p.RESULT_BAD_LENGTH)):
        assert p.validate_internal_payload(cmd,data) == result
    for data in (b'\x00', bytes((0,2,0,0,0,0,0,0,0,0)), bytes((0,1,4,0,0,0,0,0,0,0))):
        assert p.parse_response(p.encode_frame(0xC7,data))[0] is None


@pytest.mark.parametrize("value", [-0.5,8.5,0.25,float('nan'),float('inf')])
def test_array_att_rejects_invalid_input(value):
    with pytest.raises(ValueError):
        p.build_array_attenuation(1,value,0,0,0)
