"""KuR512B 模拟器纯内核回归测试。"""

from __future__ import annotations

import pytest

from soft_hertz_tool.devices.kur512 import protocol
from soft_hertz_tool.devices.kur512.models import Polarity, SimulatorState
from soft_hertz_tool.devices.kur512.simulator import KUR512Simulator


def test_simulator_normalizes_and_validates_ids():
    sim = KUR512Simulator([1, 2, 3])
    assert sim.ids == [1, 2, 3]
    with pytest.raises(ValueError):
        KUR512Simulator([0])
    with pytest.raises(ValueError):
        KUR512Simulator([0x80])
    with pytest.raises(ValueError):
        KUR512Simulator([])


def test_simulator_set_beam_then_query_status_round_trip():
    sim = KUR512Simulator([0x01])
    setting = protocol.make_beam_setting(11700, 30, 45, Polarity.LINEAR, 0)
    beam_frame = protocol.build_beam_frame(0x01, setting)
    responses = sim.handle_frame(beam_frame)
    assert len(responses) == 1
    assert responses[0] == beam_frame  # 原帧回显

    status_query = protocol.build_status_query_frame(0x01)
    responses = sim.handle_frame(status_query)
    assert len(responses) == 1
    parsed, message = protocol.parse_response(responses[0])
    assert message == "OK"
    assert parsed["device_id"] == 0x01
    assert parsed["addr"] == protocol.ADDR_STATUS_QUERY
    info, _ = protocol.parse_status_response(parsed["payload"])
    assert info["sys_vcc"] == pytest.approx(11.9)
    assert info["sys_temp"] == 30


def test_simulator_multi_subarray_isolation():
    sim = KUR512Simulator([0x01, 0x02])
    setting1 = protocol.make_beam_setting(11700, 30, 0, Polarity.LINEAR, 0)
    sim.handle_frame(protocol.build_beam_frame(0x01, setting1))
    setting2 = protocol.make_beam_setting(12700, 10, 10, Polarity.RHCP, 0)
    sim.handle_frame(protocol.build_beam_frame(0x02, setting2))
    s1 = sim.state_for(0x01)
    s2 = sim.state_for(0x02)
    assert s1.freq_code == 20
    assert s2.freq_code == 40
    assert s1.pol_byte == 0
    assert s2.pol_byte == protocol.POL_RHCP


def test_simulator_broadcast_records_but_does_not_reply():
    sim = KUR512Simulator([0x01, 0x02])
    setting = protocol.make_beam_setting(11700, 30, 0, Polarity.LINEAR, 0)
    responses = sim.handle_frame(protocol.build_beam_frame(0x00, setting))
    assert responses == []
    assert sim.state_for(0x01).freq_code == 20
    assert sim.state_for(0x02).freq_code == 20


def test_simulator_unknown_id_returns_no_response():
    sim = KUR512Simulator([0x01])
    response = sim.handle_frame(protocol.build_status_query_frame(0x05))
    assert response == []


def test_simulator_enable_and_phase_cal_round_trip():
    sim = KUR512Simulator([0x01])
    sim.handle_frame(protocol.build_enable_frame(0x01, True))
    sim.handle_frame(protocol.build_phase_cal_frame(0x01, 20))
    state = sim.state_for(0x01)
    assert state.en_row == 0xFFFF
    assert state.ps_align == 20


def test_simulator_status_response_differentiates_subarrays():
    sim = KUR512Simulator([0x01, 0x02, 0x03])
    for sub_id in (0x01, 0x02, 0x03):
        response = sim.handle_frame(protocol.build_status_query_frame(sub_id))
        parsed, _ = protocol.parse_response(response[0])
        info, _ = protocol.parse_status_response(parsed["payload"])
        # 电压按 (sub_id-1)*0.05 漂移
        expected_vcc = 11.9 + 0.05 * (sub_id - 1)
        assert info["sys_vcc"] == pytest.approx(round(expected_vcc, 1), abs=0.06)
        # 温度按 (sub_id-1) 漂移
        assert info["sys_temp"] == 30 + (sub_id - 1)
