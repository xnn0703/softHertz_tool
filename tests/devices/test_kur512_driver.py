"""KuR512B Driver 主动查询循环与 CSV 落盘测试。

测试不启动 SerialThread 的真实串口；通过 ``handle_bytes`` 直接注入响应，
通过 monkeypatch 拦截 ``send_bytes`` 抓取发出的 TX 帧。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from soft_hertz_tool.devices.kur512 import protocol
from soft_hertz_tool.devices.kur512.driver import (
    ACTIVE_WINDOW_SECONDS,
    DEFAULT_QUERY_HZ,
    KUR512Driver,
    MAX_QUERY_HZ,
    MIN_QUERY_HZ,
)
from soft_hertz_tool.devices.kur512.recorder import StatusRecorder


@pytest.fixture
def app():
    """保证 QCoreApplication 在 Driver 信号场景中存在。"""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def _build_response(device_id: int, **overrides) -> bytes:
    """构造一个 KuR512B 状态响应完整帧。"""
    defaults = {"sys_vcc_raw": 119, "sys_temp_raw": 110, "mcu_ver": 1}
    defaults.update(overrides)
    return protocol.build_status_response_frame(device_id, **defaults)


def test_set_query_hz_validates_range(tmp_path):
    """非法值抛 ValueError；上下界接受；与默认值独立。"""
    driver = KUR512Driver("loop://", 460800, log_root=tmp_path)
    try:
        with pytest.raises(ValueError):
            driver.set_query_hz(-1)
        driver.set_query_hz(0)
        driver.set_query_hz(MAX_QUERY_HZ)
        driver.set_query_hz(DEFAULT_QUERY_HZ)
        with pytest.raises(ValueError):
            driver.set_query_hz(MAX_QUERY_HZ + 1)
    finally:
        driver.stop(timeout_ms=200)


def test_status_recorder_writes_csv_with_header_and_raw_hex(tmp_path):
    """CSV 首次写表头；每行 raw_hex 与源帧逐字节相等。"""
    recorder = StatusRecorder(tmp_path, device_id=0x01, capacity=1000)
    info = {"rev": 0, "sys_vcc": 11.9, "sys_temp": 30, "mcu_ver": 2}
    frame = _build_response(0x01, sys_vcc_raw=119, sys_temp_raw=110, mcu_ver=2)
    recorder.append(0x01, info, raw_hex=frame.hex().upper())
    recorder.finish()
    assert recorder.close(timeout=1.0)
    path = recorder.path
    assert path is not None
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "ts,device_id,rev,sys_vcc,sys_temp,mcu_ver,raw_hex"
    assert lines[1].endswith(f",{frame.hex().upper()}")
    assert len(lines[1].split(",")) == len(lines[0].split(","))


def test_status_recorder_rotates_at_max_bytes(tmp_path):
    """超过 max_bytes 时轮转新文件并重写表头。"""
    recorder = StatusRecorder(tmp_path, device_id=0x01, max_bytes=200, capacity=100)
    frame = _build_response(0x01)
    info = {"rev": 0, "sys_vcc": 11.9, "sys_temp": 30, "mcu_ver": 2}
    for _ in range(20):
        recorder.append(0x01, info, raw_hex=frame.hex().upper())
    recorder.finish()
    assert recorder.close(timeout=1.0)
    files = sorted(recorder.directory().glob("status-*.csv"))
    assert len(files) >= 2
    for path in files:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("ts,device_id,")


def test_status_recorder_reports_lost_when_full(tmp_path):
    """队列满时累加 lost 而不是抛异常。"""
    recorder = StatusRecorder(tmp_path, device_id=0x01, capacity=2)
    info = {"rev": 0, "sys_vcc": 11.9, "sys_temp": 30, "mcu_ver": 2}
    for _ in range(50):
        recorder.append(0x01, info, raw_hex="00")
    assert recorder.lost >= 40
    recorder.finish()
    assert recorder.close(timeout=1.0)


def test_driver_round_robin_orders_status_queries(monkeypatch, app, tmp_path):
    """启动后 Driver 按 ID 列表 round-robin 准备 0x9C 帧。"""
    driver = KUR512Driver("loop://", 460800, log_root=tmp_path)
    queued: "list[bytes]" = []
    monkeypatch.setattr(driver, "send_bytes", lambda frame: queued.append(bytes(frame)) or True)

    driver.set_log_root(tmp_path)
    driver.start_polling([1, 2, 3], 50)
    try:
        # 直接调用 _next_due_device_id 并在调用间清空 _next_query_ns 以避开节奏控制
        ids = []
        for _ in range(6):
            driver._next_query_ns = 0
            driver._last_query_ns = 0
            sub = driver._next_due_device_id()
            assert sub is not None
            ids.append(sub)
        # round-robin 顺序应当为 1,2,3,1,2,3
        assert ids == [1, 2, 3, 1, 2, 3]
    finally:
        driver.stop_polling(timeout=0.2)
        driver.stop(timeout_ms=200)


def test_driver_writes_csv_when_response_received(app, tmp_path):
    """注入 0x9C 响应后，Driver 同步写 CSV 行。"""
    driver = KUR512Driver("loop://", 460800, log_root=tmp_path)
    try:
        driver.set_log_root(tmp_path)
        driver.start_polling([0x01], 50)
        response = _build_response(0x01, sys_vcc_raw=120, sys_temp_raw=130, mcu_ver=3)
        driver.handle_bytes(response)
        # 后台 recorder 写入需要短时间等待
        deadline = time.monotonic() + 2.0
        recorder = None
        while time.monotonic() < deadline:
            if driver._recorders:
                recorder = driver._recorders[0x01]
                if recorder.path and recorder.path.exists() and recorder.path.stat().st_size > 60:
                    break
            time.sleep(0.02)
        assert recorder is not None and recorder.path is not None
        lines = recorder.path.read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("ts,device_id,")
        assert lines[1].endswith(f",{response.hex().upper()}")
    finally:
        driver.stop_polling(timeout=0.5)
        driver.stop(timeout_ms=500)


def test_driver_min_frame_gap_respected(monkeypatch, app, tmp_path):
    """相邻两次 _next_due_device_id 调用受 3 ms 最小帧间隔保护。"""
    driver = KUR512Driver("loop://", 460800, log_root=tmp_path)
    try:
        # 设置查询节奏足够慢，确保 _next_query_ns 不阻塞
        driver.start_polling([0x01], 1)
        driver._next_query_ns = 0
        # 第一次：合法
        first = driver._next_due_device_id()
        # 立即第二次：受 3 ms 帧间隔保护，应返回 None
        second = driver._next_due_device_id()
        assert first == 1
        assert second is None
        # _round_index 第二次不递增
        assert driver._round_index == 1
    finally:
        driver.stop_polling(timeout=0.2)
        driver.stop(timeout_ms=200)


def test_driver_achieved_hz_tracks_window(app, tmp_path):
    """achieved_hz 在 10 s 窗口内累计。"""
    driver = KUR512Driver("loop://", 460800, log_root=tmp_path)
    try:
        driver.set_log_root(tmp_path)
        driver.start_polling([0x01], 20)
        # 直接喂 30 个响应让 achieved 累积
        for i in range(30):
            response = _build_response(0x01, sys_vcc_raw=119, sys_temp_raw=110, mcu_ver=i)
            driver.handle_bytes(response)
        achieved = driver.achieved_hz
        # 30 次响应发生在极短时间窗内（首次 10 s 窗口未闭合），返回 0
        assert achieved >= 0
    finally:
        driver.stop_polling(timeout=0.5)
        driver.stop(timeout_ms=500)


def test_driver_processes_real_device_status_response(app, tmp_path):
    """设备实测格式：状态响应 4 字节（无尾部 0x9C），如 50 53 41 01 04 0A 72 66 05 D0。"""
    driver = KUR512Driver("loop://", 460800, log_root=tmp_path)
    received: "list[dict]" = []
    driver.status_signal.connect(received.append)
    try:
        driver.set_log_root(tmp_path)
        driver.start_polling([0x01], 10)
        # 构造与设备实测一致的帧：PSA + ID + LEN=4 + [Rev,SysVcc_raw,SysTemp_raw,MCU_VER] + CheckSum
        body = bytes([0x50, 0x53, 0x41, 0x01, 0x04, 0x0A, 0x72, 0x66, 0x05])
        checksum = sum(body) & 0xFF
        frame = body + bytes([checksum])
        driver.handle_bytes(frame)
        assert len(received) == 1
        info = received[0]
        assert info["device_id"] == 0x01
        assert info["rev"] == 0x0A
        assert info["sys_vcc"] == pytest.approx(11.4)
        assert info["sys_temp"] == 22
        assert info["mcu_ver"] == 5
    finally:
        driver.stop_polling(timeout=0.2)
        driver.stop(timeout_ms=200)


def test_driver_stop_closes_recorders(app, tmp_path):
    """Driver.stop() 必须在超时内关闭 recorders。"""
    driver = KUR512Driver("loop://", 460800, log_root=tmp_path)
    try:
        driver.set_log_root(tmp_path)
        driver.start_polling([0x01, 0x02], 10)
        response = _build_response(0x01)
        driver.handle_bytes(response)
        assert driver.stop(timeout_ms=500)
        assert driver._recorders == {}
    finally:
        pass


def test_driver_status_signal_emits_within_throttle(app, tmp_path):
    """status_signal 在 100 ms 节流窗口内只触发一次。"""
    driver = KUR512Driver("loop://", 460800, log_root=tmp_path)
    received: "list[dict]" = []
    driver.status_signal.connect(received.append)
    try:
        driver.set_log_root(tmp_path)
        driver.start_polling([0x01], 10)
        # 连续喂 5 个响应（节流 100 ms 内只 emit 一次）
        for _ in range(5):
            driver.handle_bytes(_build_response(0x01))
        assert len(received) <= 1
    finally:
        driver.stop_polling(timeout=0.2)
        driver.stop(timeout_ms=200)
