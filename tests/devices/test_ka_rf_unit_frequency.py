"""固定/自由频点分段及实际 UI 发帧合同。"""
import struct

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


@pytest.mark.parametrize('tx,bands', [
    (False, [(17700, 18199, 16750), (18200, 19199, 17250), (19200, 20199, 18250), (20200, 21200, 19250)]),
    (True, [(27500, 28349, 26550), (28350, 28999, 27400), (29000, 29999, 28050), (30000, 31000, 29050)]),
])
def test_fixed_band_endpoints_and_wrong_band(tx, bands):
    port = Port()
    sim = KaRfUnitDeviceSimulator(port)
    for low, high, lo in bands:
        for rf in (low, high):
            assert p.fixed_lo(rf, tx=tx) == lo
            values = [19966, 18250, 29500, 28050, 1, 0]
            offset = 2 if tx else 0
            values[offset:offset + 2] = [rf, lo]
            sim.process_input(p.build_set_conv_freq(*values))
            assert port.frames[-1][4:7] == bytes([0x90, 1, 0])
            before = (sim.rx_rf_mhz, sim.rx_lo_mhz, sim.tx_rf_mhz, sim.tx_lo_mhz, sim.rx_polar, sim.tx_polar)
            for wrong in (0, lo + 2, bands[(bands.index((low, high, lo)) + 1) % 4][2]):
                values[offset + 1] = wrong
                with pytest.raises(ValueError):
                    p.build_set_conv_freq(*values)
                sim.process_input(p.encode_frame(0x10, struct.pack('>HHHHBB', *values)))
                assert port.frames[-1][4:7] == bytes([0x90, 1, 3])
                assert before == (sim.rx_rf_mhz, sim.rx_lo_mhz, sim.tx_rf_mhz, sim.tx_lo_mhz, sim.rx_polar, sim.tx_polar)


@pytest.mark.parametrize('cmd', [0x10, 0x16])
@pytest.mark.parametrize('field,value', [(0,17699),(0,21201),(2,27499),(2,31001),(1,16749),(1,19251),
                                      (3,26549),(3,29051),(1,18251),(3,28051),(4,2),(5,2)])
def test_invalid_frequency_rejected_atomically(cmd, field, value):
    port = Port()
    sim = KaRfUnitDeviceSimulator(port)
    before = (sim.rx_rf_mhz, sim.rx_lo_mhz, sim.tx_rf_mhz, sim.tx_lo_mhz, sim.rx_polar, sim.tx_polar)
    values = [19966, 18250, 29500, 28050, 1, 0]
    values[field] = value
    sim.process_input(p.encode_frame(cmd, struct.pack('>HHHHBB', *values)))
    assert port.frames[-1][4:7] == bytes([cmd | 0x80, 1, 3])
    assert before == (sim.rx_rf_mhz, sim.rx_lo_mhz, sim.tx_rf_mhz, sim.tx_lo_mhz, sim.rx_polar, sim.tx_polar)
    sim.process_input(p.encode_frame(cmd, b''))
    assert port.frames[-1][6] == 2


def test_free_auto_manual_and_response_stream():
    frame = p.build_set_conv_freq_free(19966, 0, 29500, 0, 1, 0)
    assert frame.hex(' ') == '50 53 41 01 16 0a 4d fe 00 00 73 3c 00 00 01 00 cb d7'
    port = Port()
    sim = KaRfUnitDeviceSimulator(port)
    for rx_lo, tx_lo in ((0, 0), (16750, 26550), (19250, 29050), (18000, 27000)):
        sim.process_input(p.build_set_conv_freq_free(19966, rx_lo, 29500, tx_lo, 1, 0))
        response = port.frames[-1]
        assert response[4:7] == bytes([0x96, 1, 0])
        assert p.parse_response(response)[0]['decoded']['result'] == 0
        for split in range(len(response) + 1):
            parser = FrameStreamParser()
            events = parser.feed(response[:split]) + parser.feed(response[split:])
            assert [e.data for e in events if e.kind == 'frame'] == [response]


def test_panel_modes_send_real_driver_frames():
    app = QApplication.instance() or QApplication([])
    panel = KaRfUnitPanel()
    frames = []
    driver = KaRfUnitDriver('test', 460800)
    driver._queue_frame = lambda frame: frames.append(frame) or True
    panel._safe_send = lambda action: action(driver)
    try:
        panel.rx_rf.setValue(18200)
        panel.tx_rf.setValue(30000)
        assert panel.rx_lo.isReadOnly() and panel.rx_lo.text() == '17250'
        panel._apply_freq()
        assert frames[-1] == p.build_set_conv_freq(18200, 17250, 30000, 29050, 0, 0)
        panel.freq_mode.setCurrentIndex(1)
        assert not panel.rx_lo.isReadOnly()
        panel._apply_freq()
        assert frames[-1] == p.build_set_conv_freq_free(18200, 0, 30000, 0, 0, 0)
        panel.rx_lo.setText('18000')
        panel.tx_lo.setText('27000')
        panel._apply_freq()
        assert frames[-1] == p.build_set_conv_freq_free(18200, 18000, 30000, 27000, 0, 0)
    finally:
        panel.shutdown()
        panel.close()
