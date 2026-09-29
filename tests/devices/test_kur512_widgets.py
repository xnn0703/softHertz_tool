"""KuR512B 实时曲线控件 (KUR512ChartView + ChannelBuffer) 测试。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("pyqtgraph")

import numpy as np
from PySide6.QtWidgets import QApplication

from soft_hertz_tool.devices.kur512.models import ChartWindow
from soft_hertz_tool.devices.kur512.widgets import (
    CHANNEL_BUFFER_CAPACITY,
    ChannelBuffer,
    KUR512ChartView,
)


@pytest.fixture
def app():
    instance = QApplication.instance() or QApplication([])
    return instance


# ---- ChannelBuffer ----

def test_channel_buffer_appends_in_order_and_caps_capacity():
    buf = ChannelBuffer(capacity=10)
    for i in range(5):
        buf.append(float(i), float(i * 2))
    xs, ys = buf.get_tail(10)
    assert list(xs) == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert list(ys) == [0.0, 2.0, 4.0, 6.0, 8.0]


def test_channel_buffer_ring_overflow_keeps_latest():
    buf = ChannelBuffer(capacity=4)
    for i in range(10):
        buf.append(float(i), float(i))
    xs, ys = buf.get_tail(10)
    assert list(xs) == [6.0, 7.0, 8.0, 9.0]
    assert list(ys) == [6.0, 7.0, 8.0, 9.0]


def test_channel_buffer_get_tail_returns_ndarray():
    buf = ChannelBuffer(capacity=10)
    for i in range(3):
        buf.append(float(i), float(i))
    xs, ys = buf.get_tail(2)
    assert isinstance(xs, np.ndarray)
    assert isinstance(ys, np.ndarray)
    assert xs.dtype == np.float64
    assert ys.dtype == np.float32
    assert list(xs) == [1.0, 2.0]


def test_channel_buffer_empty_returns_empty_arrays():
    buf = ChannelBuffer(capacity=5)
    xs, ys = buf.get_tail(10)
    assert xs.size == 0
    assert ys.size == 0


def test_channel_buffer_clear_resets_state():
    buf = ChannelBuffer(capacity=5)
    for i in range(3):
        buf.append(float(i), float(i))
    buf.clear()
    xs, ys = buf.get_tail(10)
    assert xs.size == 0
    assert ys.size == 0
    # 再次写入应当从头开始
    buf.append(1.0, 1.0)
    xs, ys = buf.get_tail(10)
    assert list(xs) == [1.0]
    assert list(ys) == [1.0]


# ---- KUR512ChartView ----

def test_chart_view_starts_empty_with_default_ranges(app):
    view = KUR512ChartView()
    plot = view.getPlotItem()
    # 初始无数据时 X 范围固定 0..300（5 min）
    x_min, x_max = plot.viewRange()[0]
    assert x_min == 0.0
    assert x_max == pytest.approx(300.0, abs=0.1)


def test_chart_view_append_locks_origin_and_updates_buffers(app):
    view = KUR512ChartView()
    base_ns = 1_000_000_000
    for i in range(5):
        view.append(base_ns + i * 1_000_000_000, 11.9 + i * 0.01, 30 + i)
    # 首次采样锁定原点；后续点 rel_seconds = i
    assert view._x_origin_ns == base_ns
    assert view._temp_buf._count == 5
    assert view._volt_buf._count == 5
    xs, _ = view._temp_buf.get_tail(10)
    assert list(xs) == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_chart_view_refresh_sets_curve_data_from_buffers(app):
    view = KUR512ChartView()
    base_ns = 2_000_000_000
    for i in range(10):
        view.append(base_ns + i * 1_000_000_000, 11.4, 29)
    view.refresh()
    temp_data = view._temp_curve.getData()
    volt_data = view._volt_curve.getData()
    assert temp_data[0].size == 10
    assert volt_data[1].size == 10


def test_chart_view_refresh_skips_when_no_data(app):
    view = KUR512ChartView()
    # 未 append 时 refresh 不应崩
    view.refresh()
    temp_data = view._temp_curve.getData()
    # pyqtgraph 在从未 setData 时返回 (None, None)
    assert temp_data[0] is None or temp_data[0].size == 0


def test_chart_view_reset_clears_state(app):
    view = KUR512ChartView()
    base_ns = 3_000_000_000
    for i in range(20):
        view.append(base_ns + i * 1_000_000_000, 11.0, 25)
    view.refresh()
    assert view._temp_buf._count == 20
    view.reset()
    assert view._temp_buf._count == 0
    assert view._volt_buf._count == 0
    assert view._x_origin_ns is None
    assert view._x_view_max == 0.0


def test_chart_view_set_window_rescales_x_axis(app):
    view = KUR512ChartView()
    # 设窗口 60 s
    view.set_window(ChartWindow.MIN_1)
    assert view._window_seconds == 60
    # 设窗口 900 s
    view.set_window(ChartWindow.MIN_15)
    assert view._window_seconds == 900


def test_chart_view_set_window_after_data_keeps_origin(app):
    view = KUR512ChartView()
    base_ns = 4_000_000_000
    for i in range(50):
        view.append(base_ns + i * 1_000_000_000, 11.4, 29)
    origin_before = view._x_origin_ns
    view.set_window(ChartWindow.MIN_15)
    assert view._x_origin_ns == origin_before


def test_chart_view_set_legend_label_updates_curves(app):
    view = KUR512ChartView()
    view.set_legend_label("ID=0x05")
    assert view._temp_curve.opts["name"] == "ID=0x05 温度"
    assert view._volt_curve.opts["name"] == "ID=0x05 电压"


def test_chart_view_buffer_capacity_protects_memory(app):
    """环形 buffer 在溢出时自动丢最早点。"""
    view = KUR512ChartView()
    base_ns = 5_000_000_000
    # 注入超过 buffer 容量的点数
    for i in range(CHANNEL_BUFFER_CAPACITY + 100):
        view.append(base_ns + i * 1_000_000_000, 11.4, 29)
    xs, _ = view._temp_buf.get_tail(CHANNEL_BUFFER_CAPACITY + 200)
    assert xs.size == CHANNEL_BUFFER_CAPACITY
    # 最新点的 rel_seconds 等于 CHANNEL_BUFFER_CAPACITY - 1 + 100 = CAP + 99
    assert xs[-1] == pytest.approx(float(CHANNEL_BUFFER_CAPACITY + 99))
