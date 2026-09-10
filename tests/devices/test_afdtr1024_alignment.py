"""RX 校准查询在协议、流式接收和按钮到 Driver 边界的回归。"""

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from soft_hertz_tool.devices.afdtr1024 import protocol
from soft_hertz_tool.devices.afdtr1024.driver import AFDTR1024Driver
from soft_hertz_tool.devices.afdtr1024.panel import RXPanel, TXPanel
from soft_hertz_tool.devices.afdtr1024.simulator import AFDTR1024Simulator
from soft_hertz_tool.devices.afdtr1024.stream import AFDTR1024StreamParser


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_query_wire_vector():
    assert protocol.build_rx_alignment_query_frame(1) == bytes.fromhex("50 53 41 01 01 9E 84")
    assert protocol.build_rx_alignment_query_frame(0x81) == bytes.fromhex("50 53 41 81 01 9E 04")


@pytest.mark.parametrize("raw,expected", [(0, -80), (79, -1), (80, 0), (81, 1), (255, 175)])
def test_payload_fields(raw, expected):
    info, message = protocol.parse_rx_alignment_response(bytes([3, raw, 7, 1, 11, 12, 13, 14, 21, 22]))
    assert message == "OK"
    assert info == dict(align_link_id=3, align_temp_offset=expected, align_init_att=7,
                        align_zcal_en=1, align_ofst_vl=11, align_ofst_hl=12, align_ofst_vr=13,
                        align_ofst_hr=14, align_att_l=21, align_att_r=22)


@pytest.mark.parametrize("size", [0, 9, 11])
def test_bad_payload_does_not_publish(app, size):
    driver = AFDTR1024Driver("unused", 115200, "RX")
    published = []
    driver.status_signal.connect(published.append)
    driver._process_frame(protocol.build_frame(1, 0x9E, bytes(size)))
    assert published == []


def test_split_join_checksum_and_merge(app):
    driver = AFDTR1024Driver("unused", 115200, "RX")
    published, records = [], []
    driver.status_signal.connect(published.append)
    driver.frame_signal.connect(records.append)
    # 独立固定向量，LINK_ID=3 与外层地址不同，不能覆盖行归属。
    frame = bytes.fromhex("50 53 41 81 0B 03 4F 07 01 0B 0C 0D 0E 15 16 9E C5")
    assert sum(frame[:-1]) & 0xFF == frame[-1]
    status = protocol.build_rx_status_response_frame(1)
    parser = AFDTR1024StreamParser()
    assert parser.feed(frame[:8]) == []
    events = parser.feed(frame[8:] + status)
    for event in events:
        assert event.is_frame
        driver._process_frame(event.raw)
    assert len(published) == 2
    assert published[-1]["align_link_id"] == 3
    assert published[-1]["align_temp_offset"] == -1
    assert published[-1]["device_id"] == 1
    assert "sys_vcc" in published[-1]
    driver._process_frame(frame[:-1] + bytes([frame[-1] ^ 1]))
    assert len(published) == 2
    assert records[-1].level == "ERROR"


@pytest.mark.parametrize("panel_type,variant,commands", [(RXPanel, "RX", [0x9C, 0x9F, 0x9E]),
                                                       (TXPanel, "TX", [0x5C, 0x5F])])
def test_button_query_sequence_and_results(app, monkeypatch, panel_type, variant, commands):
    panel = panel_type()
    driver = AFDTR1024Driver("unused", 115200, variant)
    sent, scheduled = [], []
    monkeypatch.setattr(panel, "_active_driver", lambda: driver)
    monkeypatch.setattr(driver, "_require_open", lambda: None)
    monkeypatch.setattr(driver, "send_frame", lambda frame: sent.append(frame) or True)
    monkeypatch.setattr(driver, "_send_scheduled", lambda frame, generation: sent.append(frame))
    monkeypatch.setattr("soft_hertz_tool.devices.afdtr1024.driver.QTimer.singleShot",
                        lambda delay, callback: scheduled.append((delay, callback)))
    driver.status_signal.connect(panel.update_status)
    panel.id_list_edit.setText("1,2")
    panel._rebuild_status_table()
    panel.plus_0x80_check.setChecked(True)
    try:
        button = next(b for b in panel.findChildren(QPushButton) if b.text() == "查询全部状态")
        button.click()
        assert [delay for delay, _ in scheduled] == list(range(50, 50 * len(commands) * 2, 50))
        for _, callback in scheduled:
            callback()
        assert [frame[-2] for frame in sent] == commands * 2
        assert [frame[3] for frame in sent] == [0x81] * len(commands) + [0x82] * len(commands)
        sim = AFDTR1024Simulator(variant, [1, 2])
        for frame in sent:
            for response in sim.handle_frame(frame):
                driver._process_frame(response)
        if variant == "RX":
            assert panel.alignment_table.item(0, 1).text() == "1"
            assert panel.alignment_table.item(1, 1).text() == "2"
            assert panel.alignment_table.item(1, 3).text() == "7"
            panel.alignment_toggle.click()
            assert not panel.alignment_table.isHidden()
            panel.id_list_edit.setText("3")
            panel._rebuild_status_table()
            assert panel.alignment_table.item(0, 1).text() == "N/A"
        else:
            assert not hasattr(panel, "alignment_table")
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_simulator_address_and_variant_scope():
    rx = AFDTR1024Simulator("RX", [1])
    tx = AFDTR1024Simulator("TX", [1])
    for target in (0, 2):
        assert rx.handle_frame(protocol.build_rx_alignment_query_frame(target)) == []
    request = protocol.build_rx_alignment_query_frame(0x81)
    assert tx.handle_frame(request) == []
    reply = rx.handle_frame(request)[0]
    assert len(reply) == 17 and reply[3] == 0x81
