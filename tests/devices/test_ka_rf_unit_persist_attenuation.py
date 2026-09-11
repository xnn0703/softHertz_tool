"""变频持久化与客户临时覆盖的确定性协议回归。"""
import pytest
from PySide6.QtWidgets import QApplication
from soft_hertz_tool.devices.ka_rf_unit import protocol as p
from soft_hertz_tool.devices.ka_rf_unit.driver import KaRfUnitDriver
from soft_hertz_tool.devices.ka_rf_unit.panel import KaRfUnitPanel
from soft_hertz_tool.devices.ka_rf_unit.simulator import KaRfUnitDeviceSimulator
from soft_hertz_tool.devices.ka_rf_unit.stream import FrameStreamParser


class Port:
    def __init__(self):
        self.frames = []

    def write(self, frame):
        self.frames.append(frame)
        return len(frame)


def test_golden_and_stream():
    request = p.build_set_conv_att_persist(0, 10)
    reply = p.encode_frame(p.RES_CONV_ATT_PERSIST, b'\x00')
    assert request.hex(' ') == '50 53 41 01 48 04 00 00 00 64 ed c2'
    assert reply.hex(' ') == '50 53 41 01 c8 01 00 d4 c7'
    for frame in (request, reply):
        for cut in range(len(frame) + 1):
            parser = FrameStreamParser()
            events = parser.feed(frame[:cut]) + parser.feed(frame[cut:])
            assert [e.data for e in events if e.kind == 'frame'] == [frame]
    for result in range(6):
        assert p.parse_response(p.encode_frame(0xC8, bytes([result])))[0]['decoded']['result'] == result
    for payload in (b'', b'\x00\x00', b'\x06'):
        assert p.parse_response(p.encode_frame(0xC8, payload))[0] is None


@pytest.mark.parametrize('value', [-0.5, 31.6, 0.1, 0.01, float('inf'), float('nan')])
def test_invalid_ui_values(value):
    with pytest.raises(ValueError):
        p.build_set_conv_att_persist(value, 10)
    with pytest.raises(ValueError):
        p.build_set_conv_att_persist(0, value)


def test_persistence_failure_and_temporary_override():
    port = Port()
    sim = KaRfUnitDeviceSimulator(port)
    assert sim.saved_conv_att == (0, 100)
    assert (sim.rx_att_x10, sim.tx_att_x10) == (0, 100)
    sim.process_input(p.build_set_conv_att_persist(31.5, 0))
    assert sim.saved_conv_att == (315, 0)
    assert (sim.rx_att_x10, sim.tx_att_x10) == (315, 0)
    assert port.frames[-1][4:7] == bytes([0xC8, 1, 0])
    sim.process_input(p.build_set_conv_att(2, 3))
    assert (sim.rx_att_x10, sim.tx_att_x10) == (20, 30)
    assert sim.saved_conv_att == (315, 0)
    sim.persistence_available = False
    sim.process_input(p.build_set_conv_att_persist(4, 5))
    assert port.frames[-1][4:7] == bytes([0xC8, 1, 5])
    assert sim.saved_conv_att == (315, 0)
    assert (sim.rx_att_x10, sim.tx_att_x10) == (20, 30)
    for payload, expected in ((b'', 2), (b'\0\x01\0\x64', 3), (b'\1\x40\0\x64', 3)):
        assert p.validate_internal_payload(0x48, payload) == expected
        sim.process_input(p.encode_frame(0x48, payload))
        assert port.frames[-1][6] == expected
        assert sim.saved_conv_att == (315, 0)
        assert (sim.rx_att_x10, sim.tx_att_x10) == (20, 30)


def test_panel_sends_persistent_command_without_changing_customer_controls():
    app = QApplication.instance() or QApplication([])
    panel = KaRfUnitPanel()
    frames = []
    driver = KaRfUnitDriver('test', 460800)
    driver._queue_frame = lambda frame: frames.append(frame) or True
    panel._safe_send = lambda action: action(driver)
    try:
        panel.persist_conv_att_inputs[0].setValue(2.5)
        panel.persist_conv_att_inputs[1].setValue(10)
        panel._apply_persistent_conv_att()
        assert frames[-1] == p.build_set_conv_att_persist(2.5, 10)
        panel._apply_att()
        assert frames[-1][4] == 0x11
    finally:
        panel.shutdown()
        panel.close()
