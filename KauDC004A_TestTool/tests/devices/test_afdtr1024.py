"""AFDT1024/AFDR1024 共用设备模块回归测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QLibraryInfo

from soft_hertz_tool.devices.afdtr1024 import protocol
from soft_hertz_tool.devices.afdtr1024.driver import AFDTR1024Driver
from soft_hertz_tool.devices.afdtr1024.models import DeviceVariant
from soft_hertz_tool.devices.afdtr1024.panel import RXPanel, TXPanel
from soft_hertz_tool.devices.afdtr1024.simulator import (
    RXSimulator,
    TXSimulator,
    build_beam_query_response,
    record_config,
)
from soft_hertz_tool.devices.afdtr1024.stream import AFDTR1024StreamParser


def test_controlled_status_query_vector_is_unchanged():
    assert protocol.build_status_query_frame(1).hex() == "50534101015c42"
    assert protocol.build_rx_status_query_frame(2)[5] == 0x9C


def test_old_beam_vectors_and_frequency_quantization_are_unchanged():
    assert protocol.calculate_beam_values(30, 45, 29500, is_tx=True) == (712, 712)
    assert protocol.calculate_beam_values(30, 45, 19450, is_tx=False) == (695, 695)
    setting = protocol.make_beam_setting(20270, 50.2, 10.0, DeviceVariant.RX)
    assert (setting.frequency_code, setting.actual_frequency_mhz) == (51, 20250)
    theta, phi = protocol.beam_code_to_angle(
        setting.beam_v,
        setting.beam_h,
        setting.actual_frequency_mhz,
        is_tx=False,
    )
    assert theta == pytest.approx(50.2, abs=0.05)
    assert phi == pytest.approx(10.0, abs=0.1)


def test_tx_rx_status_fields_and_pa_difference_are_unchanged():
    tx_frame = protocol.build_tx_status_response_frame(1, state=1, sys_vcc_raw=119, sys_temp_raw=119)
    parsed, message = protocol.parse_response(tx_frame)
    assert message == "OK"
    tx, message = protocol.parse_status_response(parsed["payload"])
    assert message == "OK"
    assert tx["sys_vcc"] == pytest.approx(11.9)
    assert tx["sys_temp"] == 39
    assert tx["pa_en"] == 1

    rx_frame = protocol.build_rx_status_response_frame(1, sys_vcc_raw=200, sys_temp_raw=150)
    parsed, _ = protocol.parse_response(rx_frame)
    rx, message = protocol.parse_rx_status_response(parsed["payload"])
    assert message == "OK"
    assert rx["sys_vcc"] == pytest.approx(20.0)
    assert rx["sys_temp"] == 70
    assert "pa_en" not in rx


def test_stream_handles_fragmentation_sticky_frames_and_garbage():
    parser = AFDTR1024StreamParser()
    first = protocol.build_status_query_frame(1)
    second = protocol.build_tx_beam_query_frame(2)
    assert parser.feed(first[:4]) == []
    events = parser.feed(first[4:] + second + b"garbage")
    assert [event.raw for event in events if event.is_frame] == [first, second]
    assert b"garbage" in b"".join(event.raw for event in events if not event.is_frame)


def test_stream_recovers_after_zero_length_bad_frame():
    parser = AFDTR1024StreamParser()
    good = protocol.build_status_query_frame(3)
    events = parser.feed(protocol.FRAME_HEADER + b"\x01\x00" + good)
    assert any(not event.is_frame and event.reason == "非法帧长度" for event in events)
    assert [event.raw for event in events if event.is_frame] == [good]


def test_simulator_multi_id_broadcast_config_and_query2_readback():
    simulator = TXSimulator("dummy", ids=[1, 2, 3])
    beam = protocol.build_tx_beam_frame(0, 40, 712, 712)
    enable = protocol.build_tx_enable_frame(0, True)
    polarization = protocol.build_tx_polarization_frame(0, protocol.POLARIZATION_RHCP)
    assert simulator.handle_frame(beam) == []
    assert simulator.handle_frame(enable) == []
    assert simulator.handle_frame(polarization) == []

    for subarray_id in (1, 2, 3):
        response = simulator.handle_frame(protocol.build_tx_beam_query_frame(subarray_id))[0]
        parsed, _ = protocol.parse_response(response)
        info, message = protocol.parse_beam_query_response(parsed["payload"], is_tx=True)
        assert message == "OK"
        assert info["freq_mhz"] == 29500
        assert info["beam_v"] == 712
        assert info["beam_h"] == 712
        assert info["en_row"] == 0xFFFF
        assert info["pol"] == 1


def test_simulator_plus_0x80_and_rx_no_pa_behavior():
    tx = TXSimulator("dummy", ids=[5])
    request = protocol.build_tx_enable_frame(0x85, True)
    assert tx.handle_frame(request) == [request]
    response = tx.handle_frame(protocol.build_status_query_frame(0x85))[0]
    parsed, _ = protocol.parse_response(response)
    assert parsed["device_id"] == 5

    rx = RXSimulator("dummy", ids=[5])
    assert rx.handle_frame(protocol.build_pa_enable_frame(5, True)) == []
    parsed, _ = protocol.parse_response(rx.build_rx_status_response(5))
    status, _ = protocol.parse_rx_status_response(parsed["payload"])
    assert "pa_en" not in status


def test_legacy_simulator_helpers_reuse_formal_protocol():
    states = {}
    record_config(states, 2, protocol.ADDR_TX_BEAM, protocol.build_tx_beam_command(40, 712, 712))
    record_config(states, 2, protocol.ADDR_TX_ENABLE, protocol.build_enable_command(True))
    response = build_beam_query_response(2, 2, states, protocol.ADDR_TX_BEAM_QUERY)
    parsed, _ = protocol.parse_response(response)
    info, _ = protocol.parse_beam_query_response(parsed["payload"], is_tx=True)
    assert (info["freq_mhz"], info["beam_v"], info["beam_h"]) == (29500, 712, 712)
    assert info["en_row"] == 0xFFFF


def test_driver_merges_query1_and_query2_by_subarray_id():
    simulator = TXSimulator(ids=[1])
    simulator.handle_frame(protocol.build_tx_beam_frame(1, 40, 712, 712))
    driver = AFDTR1024Driver("dummy", 460800, DeviceVariant.TX)
    statuses = []
    records = []
    driver.status_signal.connect(statuses.append)
    driver.frame_signal.connect(records.append)
    driver.handle_bytes(simulator.build_status_response(1))
    driver.handle_bytes(simulator.build_beam_query_response(1))
    assert statuses[-1]["device_id"] == 1
    assert statuses[-1]["sys_vcc"] == pytest.approx(11.6)
    assert statuses[-1]["beam_v"] == 712
    assert statuses[-1]["beam_h"] == 712
    assert records[-1].model == "AFDT1024"
    assert records[-1].port == "dummy/AFDT1024"


def test_driver_semantic_beam_api_queues_quantized_frame():
    driver = AFDTR1024Driver("dummy", 460800, DeviceVariant.RX)
    records = []
    driver.frame_signal.connect(records.append)
    driver.running = True
    setting = driver.set_beam(0x81, 20270, 50.2, 10.0)
    queued = driver._tx_queue.get_nowait()
    parsed, message = protocol.parse_response(queued)
    driver.running = False
    assert message == "OK"
    assert parsed["device_id"] == 0x81
    assert parsed["addr"] == protocol.ADDR_RX_BEAM
    assert setting.actual_frequency_mhz == 20250
    assert records[-1].model == "AFDR1024"
    assert records[-1].port == "dummy/AFDR1024"


def test_panel_static_multi_id_rules_and_lifecycle_contract():
    assert DeviceVariant.TX.model_name == "AFDT1024"
    assert DeviceVariant.RX.model_name == "AFDR1024"
    assert TXPanel.parse_subarray_ids("0x11, 0x01, 0x01, bad") == [1, 0x11]
    assert RXPanel.generate_subarray_ids(2, 3) == [1, 2, 3, 0x11, 0x12, 0x13]
    assert callable(getattr(TXPanel, "disconnect_device"))
    assert callable(getattr(TXPanel, "shutdown"))


_platforms = Path(QLibraryInfo.path(QLibraryInfo.PluginsPath)) / "platforms"
_has_offscreen = _platforms.is_dir() and any(_platforms.glob("*offscreen*"))


@pytest.mark.skipif(not _has_offscreen, reason="当前 Python 环境没有 Qt offscreen 平台插件")
def test_panel_can_merge_status_and_shutdown_repeatedly():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    tx_panel = TXPanel()
    rx_panel = RXPanel()
    assert tx_panel.title_label.text() == "AFDT1024"
    assert rx_panel.title_label.text() == "AFDR1024"
    tx_panel.update_status({"device_id": 1, "sys_vcc": 11.9, "sys_temp": 39, "pa_en": 1})
    tx_panel.update_status(
        {"device_id": 1, "pol": 1, "en_row": 0xFFFF, "freq_mhz": 29500, "beam_v": 712, "beam_h": 712}
    )
    row = tx_panel._status_rows[1]
    assert tx_panel.status_table.item(row, tx_panel._column_index["电压(V)"]).text() == "11.9"
    assert tx_panel.status_table.item(row, tx_panel._column_index["BeamV"]).text() == "712"
    for panel in (tx_panel, rx_panel):
        panel.disconnect_device()
        panel.disconnect_device()
        panel.shutdown()
        panel.shutdown()
        panel.deleteLater()
    app.processEvents()
