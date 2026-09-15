"""AFD01 点位与真实 Driver RX → 扫描推进边界。"""

import socket
import struct
import time
import pytest
from PySide6.QtWidgets import QApplication
from soft_hertz_tool.devices.afd01 import protocol as p
from soft_hertz_tool.devices.afd01.panel import Afd01Panel
from soft_hertz_tool.devices.afd01.scan import ScanAxis, ScanGrid


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def report(driver, rid=0, result=1, mode=4):
    data = struct.pack("<BI16sBI", 1, driver._query_id, b"AFD01C", mode, (1 << 14) - 1)
    data += struct.pack("<IIIIffHh", 28050, 29500, 18250, 19500, 0, 0, 63, 30)
    data += struct.pack("<IBBfffB", 0, 0, 0, 0, 0, 0, 0)
    data += struct.pack("<IBBfffB", rid, p.Op.BEAM, 0, 0, 0, 0, result)
    for freq in (29500, 19500):
        data += struct.pack("<IffffHBBh", freq, 0, 0, 0, 0, 3, 0, 16, 0)
    driver.handle_datagram(p.frame(p.STATUS, data), driver.generation)


@pytest.fixture
def panel(app, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    widget = Afd01Panel()
    widget.host.setText("127.0.0.1")
    widget.port.setValue(server.getsockname()[1])
    widget._connect()
    widget.driver.timer.stop()
    report(widget.driver)
    for widgets, values in zip(widget.scan_axes, ((0, 1, 1), (0, 0, 1))):
        for w, v in zip(widgets, values):
            w.setValue(v)
    frames = []
    widget.driver.frame_signal.connect(frames.append)
    yield widget, clock, frames
    widget.shutdown()
    widget.deleteLater()
    app.processEvents()
    server.close()


def beams(frames):
    return [
        struct.unpack("<BIBBfff", p.unpack(f.raw)[1])
        for f in frames
        if f.direction == "TX" and p.unpack(f.raw)[1][5] == p.Op.BEAM
    ]


@pytest.mark.parametrize(
    "start,end,step,expected",
    [
        (0, 1, 0.3, [0, 0.3, 0.6, 0.9, 1]),
        (1, 0, 0.3, [1, 0.7, 0.4, 0.1, 0]),
        (2, 2, 0.1, [2]),
        (-70, 70, 140, [-70, 70]),
    ],
)
def test_axis_endpoints(start, end, step, expected):
    a = ScanAxis.degrees(start, end, step, 70)
    assert [a.point(i) for i in range(a.count)] == expected


@pytest.mark.parametrize(
    "args",
    [
        (0, 1, 0, 70),
        (0, 1, 0.01, 70),
        (0, 71, 1, 70),
        (0, 1, float("nan"), 70),
        (0, 0.11, 0.1, 70),
    ],
)
def test_axis_invalid(args):
    with pytest.raises(ValueError):
        ScanAxis.degrees(*args)


def test_grid_order_and_boundaries():
    g = ScanGrid(ScanAxis.degrees(1, 0, 1, 70), ScanAxis.degrees(-360, 360, 360, 360))
    assert [g.point(i) for i in range(g.count)] == [
        (1, -360),
        (1, 0),
        (1, 360),
        (0, -360),
        (0, 0),
        (0, 360),
    ]
    with pytest.raises(IndexError):
        g.point(g.count)


def test_both_waits_for_each_success_then_dwell(panel):
    w, t, frames = panel
    w.scan_target.setCurrentIndex(2)
    w.scan_start.click()
    w._scan_timer.stop()
    rid = w._scan_request
    assert len(beams(frames)) == 1 and beams(frames)[0][3] == 0
    w.driver.handle_datagram(
        p.frame(p.RESPONSE, struct.pack("<BIBB", 1, rid, p.Op.BEAM, 0)),
        w.driver.generation,
    )
    w._scan_tick()
    assert len(beams(frames)) == 1
    report(w.driver, rid + 123)
    w._scan_tick()
    assert len(beams(frames)) == 1
    report(w.driver, rid)
    w._scan_tick()
    assert [b[3] for b in beams(frames)] == [0, 1]
    report(w.driver, w._scan_request)
    assert w._scan_index == 1
    t[0] += 0.19
    w._scan_tick()
    assert len(beams(frames)) == 2
    t[0] += 0.02
    w._scan_tick()
    assert len(beams(frames)) == 3
    assert beams(frames)[-1][4:6] == (1, 0)
    assert all(not button.isEnabled() for _, button in w.controls)


def test_pause_between_targets_and_stop_inflight(panel):
    w, t, frames = panel
    w.scan_target.setCurrentIndex(2)
    w._start_scan()
    w._scan_timer.stop()
    rid = w._scan_request
    w.scan_pause.click()
    report(w.driver, rid)
    t[0] += 1
    w._scan_tick()
    assert len(beams(frames)) == 1
    w.scan_pause.click()
    w._scan_tick()
    assert len(beams(frames)) == 2
    rid = w._scan_request
    w.scan_stop.click()
    assert w.driver.pending and w._scan_grid is None
    report(w.driver, rid)
    t[0] += 5
    w._scan_tick()
    assert len(beams(frames)) == 2 and w.driver.pending is None


@pytest.mark.parametrize("reason", ["mode", "disconnect", "tab"])
def test_abort_never_sends_next_point(panel, reason):
    w, t, frames = panel
    w._start_scan()
    w._scan_timer.stop()
    rid = w._scan_request
    if reason == "mode":
        report(w.driver, rid, 1, 0)
    elif reason == "disconnect":
        w.driver.close()
    elif reason == "tab":
        w.deactivate()
    assert w._scan_grid is None and not w._scan_timer.isActive()
    t[0] += 10
    w._scan_tick()
    assert len(beams(frames)) == 1


def test_rx_single_point_finishes_after_dwell(panel):
    w, t, frames = panel
    w.scan_target.setCurrentIndex(1)
    w.scan_axes[0][1].setValue(0)
    w._start_scan()
    w._scan_timer.stop()
    assert beams(frames)[0][3] == 1
    report(w.driver, w._scan_request)
    w._scan_tick()
    assert w._scan_grid
    t[0] += 0.201
    w._scan_tick()
    assert w._scan_grid is None and len(beams(frames)) == 1


def test_fast_query_keeps_delayed_id(panel):
    w, t, frames = panel
    w._start_scan()
    w._scan_timer.stop()
    d = w.driver
    d.tick()
    qid = d._query_id
    assert d._query_waiting
    t[0] += 0.25
    d.tick()
    assert d._query_id == qid
    report(d)
    t[0] += 0.11
    d.tick()
    assert d._query_id != qid
    qid = d._query_id
    t[0] += 1.01
    d.tick()
    assert d._query_id != qid
    w._scan_stop_clicked()
    report(d, w.driver.pending["id"])
    t[0] += 0.11
    qid = d._query_id
    d.tick()
    assert d._query_id == qid


@pytest.mark.parametrize("result", [None, 3, 6, 7])
def test_retry_current_point_and_ignore_old_result(panel, result):
    """可恢复失败保持点位，新请求成功才推进，迟到旧结果不推进。"""
    w, t, frames = panel
    w._start_scan()
    w._scan_timer.stop()
    first = w._scan_request
    if result is None:
        w.driver.pending["deadline"] = 0
        w.driver.tick()
    else:
        report(w.driver, first, result)
    assert w._scan_grid is not None and w._scan_index == 0
    t[0] += 0.99
    w._scan_tick()
    assert len(beams(frames)) == 1
    t[0] += 0.02
    report(w.driver)
    w._scan_tick()
    second = w._scan_request
    assert second != first and second is not None
    assert beams(frames)[0][3:] == beams(frames)[1][3:]
    report(w.driver, first)
    assert w._scan_index == 0 and w._scan_request == second
    report(w.driver, second)
    assert w._scan_index == 1


@pytest.mark.parametrize("condition", ["stale", "offline", "frequency"])
def test_transient_status_recovers(panel, condition):
    """临时状态异常保留进度，频率变化继续使用设备当前频率。"""
    w, t, frames = panel
    w._start_scan()
    w._scan_timer.stop()
    report(w.driver, w._scan_request)
    t[0] += 0.3
    if condition == "stale":
        t[0] += 3
    elif condition == "offline":
        w.driver.latest["arrays"][0]["flags"] = 1
    else:
        w.driver.latest["arrays"][0]["frequency"] = 30000
    w._scan_tick()
    assert w._scan_grid is not None
    if condition != "frequency":
        assert len(beams(frames)) == 1
        report(w.driver)
        w._scan_tick()
    assert len(beams(frames)) == 2


@pytest.mark.parametrize("result", [2, 4, 5])
def test_permanent_result_stops(panel, result):
    """参数、不支持和非手动错误终止重试。"""
    w, t, frames = panel
    w._start_scan()
    report(w.driver, w._scan_request, result)
    t[0] += 2
    w._scan_tick()
    assert w._scan_grid is None and len(beams(frames)) == 1


def test_pause_and_stop_cancel_retries(panel):
    """暂停期间不重发，恢复后重试当前点，停止后不再发送。"""
    w, t, frames = panel
    w._start_scan()
    w._scan_timer.stop()
    report(w.driver, w._scan_request, 3)
    w._pause_scan()
    t[0] += 2
    report(w.driver)
    w._scan_tick()
    assert len(beams(frames)) == 1
    w._pause_scan()
    w._scan_tick()
    assert len(beams(frames)) == 2
    report(w.driver, w._scan_request, 6)
    w._scan_stop_clicked()
    t[0] += 2
    w._scan_tick()
    assert len(beams(frames)) == 2


def test_dual_target_retry_only_failed_rx(panel):
    """TX 成功后 RX 失败只重发 RX，整点成功才计数。"""
    w, t, frames = panel
    w.scan_target.setCurrentIndex(2)
    w._start_scan()
    w._scan_timer.stop()
    report(w.driver, w._scan_request)
    w._scan_tick()
    report(w.driver, w._scan_request, 6)
    assert w._scan_index == 0
    t[0] += 1.01
    w._scan_tick()
    assert [f[3] for f in beams(frames)] == [0, 1, 1]
    report(w.driver, w._scan_request)
    assert w._scan_index == 1
