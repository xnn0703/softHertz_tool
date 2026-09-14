"""AFD01 协议与实际 UDP/UI 边界回归。"""

import socket
import struct
import time
import pytest
from PySide6.QtWidgets import QApplication
from soft_hertz_tool.devices.afd01 import protocol as p
from soft_hertz_tool.devices.afd01.driver import Afd01Driver
from soft_hertz_tool.devices.afd01.panel import Afd01Panel
from soft_hertz_tool.app.registry import WORKSPACE_SPECS


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def snapshot(rid, mode=4, completion=None):
    data = struct.pack("<BI16sBI", 1, rid, b"AFD01C", mode, (1 << 14) - 1)
    data += struct.pack("<IIIIffHh", 28050, 29500, 18250, 19500, 1.5, 2.0, 0x0FFF, 30)
    data += struct.pack("<IBBfffB", *(completion or (0, 0, 0, 0, 0, 0, 0)))
    data += struct.pack("<IBBfffB", 0, 0, 0, 0, 0, 0, 0)
    for frequency in (29500, 19500):
        data += struct.pack("<IffffHBBh", frequency, 0, 0, 1, 2, 0x37, 0, 16, 35)
    return p.frame(p.STATUS, data)


def test_golden_and_crc():
    raw = p.request(0x12345678, p.Op.IF, 1, 1)
    command, data = p.unpack(raw)
    assert command == p.REQUEST
    assert data.hex() == "017856341204010000803f0000000000000000"
    assert raw.hex() == "aa550d301300017856341204010000803f00000000000000004f9cee"
    for invalid in (raw[:-1], raw + b"x", raw[:9] + bytes([raw[9] ^ 1]) + raw[10:]):
        with pytest.raises(ValueError):
            p.unpack(invalid)


@pytest.mark.parametrize(
    "op,target,a,b",
    [
        (p.Op.CONV_FREQ, 1, 28050, 29500),
        (p.Op.SIZE, 0, 9, 0),
        (p.Op.CONV_ATT, 0, 1.2, 0),
        (p.Op.REFERENCE, 0, 101, 0),
        (p.Op.PA, 1, 1, 0),
        (p.Op.BEAM, 0, 90.1, 0),
        (p.Op.IF, 0, float("nan"), 0),
    ],
)
def test_invalid(op, target, a, b):
    with pytest.raises(ValueError):
        p.request(1, op, target, a, b)


def test_status_decode():
    s = p.status(p.unpack(snapshot(9))[1])
    assert s["id"] == 9 and s["model"] == "AFD01C" and s["converter"]["rx_rf"] == 19500
    assert s["arrays"][1]["temperature"] == 35
    with pytest.raises(ValueError):
        p.status(b"")
    with pytest.raises(ValueError):
        p.response(struct.pack("<BIBB", 2, 1, 1, 0))


def test_driver_correlation_timeout_and_generation(app):
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    d = Afd01Driver()
    d.connect_device("127.0.0.1", port)
    d.timer.stop()
    d.handle_datagram(snapshot(d._query_id), d.generation)
    assert d.can_control
    d.control(p.Op.IF, 0, 1)
    rid = d.pending["id"]
    d.handle_datagram(
        p.frame(p.RESPONSE, struct.pack("<BIBB", 1, rid + 1, p.Op.IF, 6)), d.generation
    )
    assert d.pending
    d.handle_datagram(
        p.frame(p.RESPONSE, struct.pack("<BIBB", 1, rid, p.Op.IF, 0)), d.generation
    )
    assert d.pending
    d.handle_datagram(
        snapshot(d._query_id, completion=(rid, p.Op.IF, 0, 1, 0, 0, 1)), d.generation
    )
    assert d.pending is None
    sent = []
    d.frame_signal.connect(sent.append)
    d.control(p.Op.IF, 0, 0)
    d.pending["deadline"] = 0
    d._next_query = time.monotonic() + 100
    d.tick()
    assert d.pending is None and len([f for f in sent if f.direction == "TX"]) == 1
    old = d.generation
    d.close()
    d.connect_device("127.0.0.1", port)
    d.timer.stop()
    d.handle_datagram(snapshot(d._query_id), old)
    assert not d.fresh
    d.close()
    server.close()
    assert not d.timer.isActive()


def test_udp_loopback_actual_socket(app):
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server.settimeout(1)
    d = Afd01Driver()
    try:
        d.connect_device("127.0.0.1", server.getsockname()[1])
        raw, peer = server.recvfrom(512)
        cmd, data = p.unpack(raw)
        assert cmd == p.REQUEST and data[5] == p.Op.QUERY
        rid = struct.unpack_from("<I", data, 1)[0]
        server.sendto(snapshot(rid), peer)
        until = time.monotonic() + 1
        while not d.fresh and time.monotonic() < until:
            app.processEvents()
            time.sleep(0.005)
        assert d.manual and d.latest["model"] == "AFD01C"
        d.control(p.Op.ARRAY_ATT, 1, 2, 3)
        raw, _ = server.recvfrom(512)
        _, data = p.unpack(raw)
        assert struct.unpack("<BIBBfff", data)[2:] == (p.Op.ARRAY_ATT, 1, 2, 3, 0)
    finally:
        d.close()
        server.close()


def test_panel_semantic_gate_and_lifecycle(app):
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    panel = Afd01Panel()
    panel.host.setText("127.0.0.1")
    panel.port.setValue(server.getsockname()[1])
    assert [s.title for s in WORKSPACE_SPECS if s.key == "AFD01"] == ["AFD01"]
    assert all(not b.isEnabled() for _, b in panel.controls)
    panel._connect()
    panel.driver.timer.stop()
    panel.driver.handle_datagram(
        snapshot(panel.driver._query_id, 0), panel.driver.generation
    )
    assert panel.driver.pending["operation"] == p.Op.MANUAL
    assert not panel.manual_button.isEnabled() and not panel.controls[0][1].isEnabled()
    panel.driver.handle_datagram(
        snapshot(panel.driver._query_id, 4), panel.driver.generation
    )
    calls = []
    panel.driver.control = lambda *args: calls.append(args)
    fields = panel.inputs[(p.Op.CONV_FREQ, 1)]
    fields[0].setValue(18250)
    fields[1].setValue(19500)
    # Actual signal/slot path from the RX frequency button to the semantic driver call.
    panel.controls[1][1].click()
    assert calls == [(p.Op.CONV_FREQ, 1, 18250, 19500, 0)]
    old = panel.driver.generation
    assert panel.deactivate() and panel.driver.socket is None
    panel.activate()
    panel.driver.timer.stop()
    assert (
        panel.driver.socket is not None
        and panel.driver.generation > old
        and not panel.driver.fresh
    )
    assert panel.shutdown() and panel.shutdown()
    server.close()


@pytest.mark.parametrize("case", ["absent", "unsupported", "automatic", "stale"])
def test_controls_require_fresh_supported_manual_device(app, case):
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    d = Afd01Driver()
    try:
        d.connect_device("127.0.0.1", server.getsockname()[1])
        d.timer.stop()
        if case != "absent":
            d.handle_datagram(
                snapshot(d._query_id, 0 if case == "automatic" else 4), d.generation
            )
        if case == "unsupported":
            d.latest["capabilities"] &= ~(1 << p.Op.IF)
        if case == "stale":
            d.last_response = time.monotonic() - 4
        frames = []
        d.frame_signal.connect(frames.append)
        with pytest.raises(ValueError):
            d.control(p.Op.IF, 0, 1)
        assert frames == [] and d.pending is None
    finally:
        d.close()
        server.close()


def test_busy_and_error_response_finish_exact_request(app):
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    d = Afd01Driver()
    try:
        d.connect_device("127.0.0.1", server.getsockname()[1])
        d.timer.stop()
        d.handle_datagram(snapshot(d._query_id), d.generation)
        d.control(p.Op.IF, 1, 0)
        rid = d.pending["id"]
        with pytest.raises(ValueError):
            d.control(p.Op.IF, 0, 0)
        d.handle_datagram(
            p.frame(p.RESPONSE, struct.pack("<BIBB", 1, rid, p.Op.IF, 3)), d.generation
        )
        assert d.pending is None
    finally:
        d.close()
        server.close()


@pytest.mark.parametrize("angle", [-90, -70, 70, 90])
def test_beam_debug_angle_bounds(angle):
    """Debug 波束命令接受正负 90 度边界。"""
    raw = p.request(1, p.Op.BEAM, 0, angle, 0)
    assert p.unpack(raw)[0] == p.REQUEST


@pytest.mark.parametrize("manual", [False, True])
def test_connect_manual_once(app, manual):
    """首次响应按模式切换一次，后续状态或失败不会重新切换。"""
    panel = Afd01Panel()
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    try:
        assert panel.host.text() == "192.168.1.12"
        assert panel.snapshot.rowCount() == 8
        panel.host.setText("127.0.0.1")
        panel.port.setValue(server.getsockname()[1])
        panel._connect()
        d = panel.driver
        d.timer.stop()
        calls = []
        d.control = lambda *args: calls.append(args)
        for mode in (4 if manual else 0, 0, 0):
            d.handle_datagram(snapshot(d._query_id, mode), d.generation)
        assert calls == ([] if manual else [(p.Op.MANUAL, 0, 0, 0, 0)])
    finally:
        panel.shutdown()
        server.close()
