"""KuR512B 主动读取实时曲线控件（pyqtgraph 版本）。

设计要点（参考 satellite_debug_tool GroupedChartWidget）：

- **稳定相对时间原点**：首次采样确定 ``_x_origin_ns``，后续 ``(t - origin) / 1e9`` 算 X 秒数
- **ChannelBuffer 环形 ndarray**：每通道预分配 ndarray（默认 5 min × 100 Hz = 30000 点），append O(1)
- **refresh pull 模型**：定时器调用 ``refresh()``，从 buffer 拉 ``get_tail(n)`` ndarray 整批 ``setData``，
  避免 Python 循环逐点 append
- **peak 降采样**：min+max 配对，保留尖峰（不是 stride 抽样）
- **pyqtgraph 内置 ``setDownsampling(mode="peak", auto=True)`` + ``setClipToView(True)``**
- **antialias=False**：长路径关抗锯齿，性能提升数倍
- **扩窗节流**：X 范围只在数据超出右边界 1 s 才 ``setXRange``
- **Y 范围自动**：缓冲为空时占位；数据平直时强制 ``center ± 1`` 留呼吸空间
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Dict, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget

from soft_hertz_tool.devices.kur512.models import ChartWindow


# 5 min × 100 Hz ≈ 30000 点；溢出丢最早点
CHANNEL_BUFFER_CAPACITY = 30000

# 至少扩 1 s 才调用 setXRange，避免每帧滚动触发重绘
_X_SCROLL_STEP_SEC = 1.0

# Y 轴自动范围：数据平直时强制 ±2℃ / ±0.5V 缓冲
_TEMP_PAD_C = 2.0
_VOLT_PAD_V = 0.5
_FLAT_TEMP_RANGE = (20.0, 40.0)
_FLAT_VOLT_RANGE = (10.0, 13.0)


_DISTINCT_COLORS = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)


class ChannelBuffer:
    """单通道环形 ndarray 缓冲。

    - 预分配 ``capacity`` 大小的 ndarray，append O(1)
    - ``get_tail(n)`` 取最近 n 个点，仅复制视窗内数据（避免每次 ``setData`` 拷贝全量）
    """

    __slots__ = ("_times", "_values", "_head", "_count", "_capacity")

    def __init__(self, capacity: int = CHANNEL_BUFFER_CAPACITY) -> None:
        """创建容量为 ``capacity`` 的环形缓冲；容量不足 2 时强制为 2。"""
        capacity = max(int(capacity), 2)
        self._times = np.zeros(capacity, dtype=np.float64)
        self._values = np.zeros(capacity, dtype=np.float32)
        self._head = 0
        self._count = 0
        self._capacity = capacity

    def append(self, timestamp: float, value: float) -> None:
        """追加一个采样点；溢出丢最早点。"""
        cap = self._capacity
        self._times[self._head] = float(timestamp)
        self._values[self._head] = float(value)
        self._head = (self._head + 1) % cap
        if self._count < cap:
            self._count += 1

    def clear(self) -> None:
        """清空缓冲（保留 ndarray 容量）。"""
        self._head = 0
        self._count = 0
        self._times.fill(0)
        self._values.fill(0)

    def __len__(self) -> int:
        """返回当前已存储的采样点数（不超过 capacity）。"""
        return self._count

    def get_tail(self, n: int) -> Tuple[np.ndarray, np.ndarray]:
        """返回最近 ``n`` 个采样点的 ``(times, values)`` ndarray 副本。

        当 ``n >= count`` 时返回全部；时间未对齐（最新在尾部）。
        """
        if n <= 0 or self._count == 0:
            empty64 = np.empty(0, dtype=np.float64)
            empty32 = np.empty(0, dtype=np.float32)
            return empty64, empty32
        cap = self._capacity
        n = min(n, self._count)
        if self._count < cap:
            start = self._count - n
            return (
                self._times[start : self._count].copy(),
                self._values[start : self._count].copy(),
            )
        # 已满：最新 n 个起点 = (_head - n) mod cap
        start = (self._head - n) % cap
        end = start + n
        if end <= cap:
            return (
                self._times[start:end].copy(),
                self._values[start:end].copy(),
            )
        first_n = cap - start
        wrap_n = n - first_n
        return (
            np.concatenate([self._times[start:], self._times[:wrap_n]]),
            np.concatenate([self._values[start:], self._values[:wrap_n]]),
        )


class KUR512ChartView(pg.PlotWidget):
    """KuR512B 温度/电压实时曲线视图：每子阵两条曲线（温度 + 电压）。

    使用 ``PlotWidget``（单图多系列），双 Y 轴由温度（左）和电压（右）共享 X 秒数。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """创建空图、X/Y 轴、可见曲线占位（按需创建）。"""
        pg.setConfigOptions(antialias=True)
        super().__init__(parent)
        self.setMouseEnabled(x=True, y=True)
        self.setMenuEnabled(False)
        self.hideButtons()
        self.showGrid(x=True, y=True, alpha=0.25)
        self.getAxis("bottom").enableAutoSIPrefix(False)
        self.setDownsampling(mode="peak", auto=True)
        self.setClipToView(True)

        self._temp_curve: Optional[pg.PlotDataItem] = None
        self._volt_curve: Optional[pg.PlotDataItem] = None
        self._temp_buf = ChannelBuffer()
        self._volt_buf = ChannelBuffer()
        self._legend_label: str = ""
        self._x_origin_ns: Optional[int] = None
        self._x_view_max: float = 0.0
        self._window_seconds: int = int(ChartWindow.MIN_5.value)

        plot_item = self.getPlotItem()
        plot_item.setLabel("left", "温度(℃)")
        plot_item.setLabel("bottom", "相对时间", units="s")
        plot_item.setTitle(f"最近 {self._window_seconds // 60} min")
        # 第二 Y 轴（右）放电压：共享 X 轴，独立范围
        self._volt_viewbox = pg.ViewBox()
        plot_item.showAxis("right")
        plot_item.scene().addItem(self._volt_viewbox)
        plot_item.getAxis("right").linkToView(self._volt_viewbox)
        plot_item.getAxis("right").setLabel("电压(V)")
        self._volt_viewbox.setXLink(plot_item)
        plot_item.vb.sigResized.connect(self._update_volt_viewbox_geometry)

        # 初始占位 X 范围：0..window；后续 refresh 内按需扩窗
        plot_item.setXRange(0.0, float(self._window_seconds), padding=0)
        plot_item.setYRange(*_FLAT_TEMP_RANGE, padding=0)
        self._volt_viewbox.setYRange(*_FLAT_VOLT_RANGE, padding=0)

        self._build_curves(legend_label="ID=0x01")

    # ---------- 公开 API ----------

    def set_window(self, window: ChartWindow) -> None:
        """切换显示窗口（秒）；缓冲保留，X 轴右边界立即缩到新窗口。"""
        seconds = int(window.value)
        if seconds == self._window_seconds:
            return
        self._window_seconds = seconds
        self.getPlotItem().setTitle(f"最近 {seconds // 60} min")
        # 立即按新窗口宽度重设 X；refresh 会再微调
        plot_item = self.getPlotItem()
        if self._x_origin_ns is None:
            plot_item.setXRange(0.0, float(seconds), padding=0)
            return
        # 取当前最新时间为右边界，左边界 = 右边界 - window
        latest_rel = max(
            0.0,
            (self._latest_ts_ns() - self._x_origin_ns) / 1e9,
        )
        plot_item.setXRange(
            max(0.0, latest_rel - seconds),
            max(latest_rel, float(seconds)),
            padding=0,
        )
        self._x_view_max = max(latest_rel, self._x_view_max)

    def append(self, t_ns: int, sys_vcc: float, sys_temp: int) -> None:
        """由 Driver 状态信号调用：把一个采样点写入两个环形缓冲。"""
        # 首次接收时锁定相对时间原点
        if self._x_origin_ns is None:
            self._x_origin_ns = int(t_ns)
        rel_seconds = (int(t_ns) - self._x_origin_ns) / 1e9
        self._temp_buf.append(rel_seconds, float(sys_temp))
        self._volt_buf.append(rel_seconds, float(sys_vcc))

    def refresh(self) -> None:
        """由 Panel 定时器调用：拉 buffer → ndarray → 整批 setData → 节流扩窗。

        设计参考 satellite_debug_tool.GroupedChartWidget.refresh。
        """
        if self._temp_curve is None or self._volt_curve is None:
            return

        temp_xs, temp_ys = self._temp_buf.get_tail(CHANNEL_BUFFER_CAPACITY)
        volt_xs, volt_ys = self._volt_buf.get_tail(CHANNEL_BUFFER_CAPACITY)

        if temp_xs.size > 0:
            self._temp_curve.setData(temp_xs, temp_ys)
            self._volt_curve.setData(volt_xs, volt_ys)
            self._update_ranges(temp_xs, temp_ys, volt_xs, volt_ys)

    def set_legend_label(self, text: str) -> None:
        """更新图例文本（如 "ID=0x01 温度/电压"）。"""
        self._legend_label = text
        if self._temp_curve is not None:
            self._temp_curve.opts["name"] = f"{text} 温度"
            self._volt_curve.opts["name"] = f"{text} 电压"

    def reset(self) -> None:
        """清空缓冲与曲线；保留系列对象（panel 复用）。

        命名避开 ``pg.PlotWidget.clear()``（Qt 原生 slot，会拦截 Python 重写）。
        """
        self._temp_buf.clear()
        self._volt_buf.clear()
        if self._temp_curve is not None:
            self._temp_curve.clear()
        if self._volt_curve is not None:
            self._volt_curve.clear()
        self._x_origin_ns = None
        self._x_view_max = 0.0
        plot_item = self.getPlotItem()
        plot_item.setXRange(0.0, float(self._window_seconds), padding=0)
        plot_item.setYRange(*_FLAT_TEMP_RANGE, padding=0)
        self._volt_viewbox.setYRange(*_FLAT_VOLT_RANGE, padding=0)

    # ---------- 内部 ----------

    def _build_curves(self, legend_label: str) -> None:
        """创建两条曲线（首次构建）；颜色按 _DISTINCT_COLORS 循环。"""
        plot_item = self.getPlotItem()
        # 温度（左 Y）：实线蓝
        self._temp_curve = plot_item.plot(
            [],
            [],
            pen=pg.mkPen(color=_DISTINCT_COLORS[0], width=1.5),
            name=f"{legend_label} 温度",
            antialias=False,
        )
        # 电压（右 Y）：虚线橙
        self._volt_curve = pg.PlotDataItem(
            [],
            [],
            pen=pg.mkPen(color=_DISTINCT_COLORS[1], width=1.5, style=Qt.DashLine),
            name=f"{legend_label} 电压",
            antialias=False,
        )
        self._volt_viewbox.addItem(self._volt_curve)

    def _latest_ts_ns(self) -> int:
        """当前 buffer 中最新时间对应的绝对纳秒（用于 X 窗口右边界）。"""
        # ChannelBuffer 不直接暴露绝对时间；从最后写入的元素推断
        # 直接读 _values 头部位置的前一个元素
        cap = self._temp_buf._capacity
        head = self._temp_buf._head
        if self._temp_buf._count == 0:
            return 0
        idx = (head - 1) % cap
        rel_seconds = float(self._temp_buf._times[idx])
        # rel 是相对原点秒；绝对 = origin + rel*1e9
        if self._x_origin_ns is None:
            return 0
        return self._x_origin_ns + int(rel_seconds * 1e9)

    def _update_ranges(
        self,
        temp_xs: np.ndarray,
        temp_ys: np.ndarray,
        volt_xs: np.ndarray,
        volt_ys: np.ndarray,
    ) -> None:
        """根据当前 buffer 更新 X / 左 Y / 右 Y 范围。"""
        plot_item = self.getPlotItem()
        latest_x = float(temp_xs[-1])
        # X 扩窗：仅在最新数据超出当前右边界至少 1 s 时调用 setXRange
        if latest_x > self._x_view_max + _X_SCROLL_STEP_SEC:
            new_xmax = latest_x + _X_SCROLL_STEP_SEC
            new_xmin = max(0.0, new_xmax - self._window_seconds)
            self._x_view_max = new_xmax
            plot_item.setXRange(new_xmin, new_xmax, padding=0)

        # 左 Y：温度
        finite = temp_ys[np.isfinite(temp_ys)]
        if finite.size:
            minimum = float(finite.min())
            maximum = float(finite.max())
            spread = maximum - minimum
            if spread < 1e-3:
                # 数据平直（如所有点都在 29℃），强制 ±2℃ 留呼吸空间
                center = (minimum + maximum) / 2.0
                plot_item.setYRange(center - _TEMP_PAD_C, center + _TEMP_PAD_C, padding=0)
            else:
                pad = max(_TEMP_PAD_C * 0.5, spread * 0.1)
                plot_item.setYRange(minimum - pad, maximum + pad, padding=0)

        # 右 Y：电压
        finite_v = volt_ys[np.isfinite(volt_ys)]
        if finite_v.size:
            minimum = float(finite_v.min())
            maximum = float(finite_v.max())
            spread = maximum - minimum
            if spread < 1e-3:
                center = (minimum + maximum) / 2.0
                self._volt_viewbox.setYRange(center - _VOLT_PAD_V, center + _VOLT_PAD_V, padding=0)
            else:
                pad = max(_VOLT_PAD_V * 0.5, spread * 0.1)
                self._volt_viewbox.setYRange(minimum - pad, maximum + pad, padding=0)

    def _update_volt_viewbox_geometry(self) -> None:
        """右侧 Y 轴的 ViewBox 跟随主视图几何同步。"""
        if not hasattr(self, "_volt_viewbox"):
            return
        self._volt_viewbox.setGeometry(self.getPlotItem().vb.sceneBoundingRect())
        self._volt_viewbox.linkedViewChanged(self.getPlotItem().vb, self._volt_viewbox.XAxis)


__all__ = [
    "CHANNEL_BUFFER_CAPACITY",
    "ChannelBuffer",
    "KUR512ChartView",
]
