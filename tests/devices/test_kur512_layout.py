"""KuR512B 面板布局与控件存在性回归。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from soft_hertz_tool.devices.kur512 import KUR512Panel
from soft_hertz_tool.devices.kur512.driver import MAX_QUERY_HZ
from soft_hertz_tool.devices.kur512.widgets import KUR512ChartView


@pytest.fixture
def app():
    instance = QApplication.instance() or QApplication([])
    return instance


def test_panel_has_required_widgets(app):
    panel = KUR512Panel()
    try:
        # POL 三选一
        assert panel.polarity_linear_radio.isChecked()
        assert not panel.polarity_lhcp_radio.isChecked()
        assert not panel.polarity_rhcp_radio.isChecked()
        # 不再有"目标工作频率"输入框
        assert not hasattr(panel, "target_freq_edit")
        # 查询频率上限 = 100
        assert panel.query_hz_spin.maximum() == MAX_QUERY_HZ
        assert MAX_QUERY_HZ == 100
        # 启动/停止按钮初始状态
        assert panel.start_button.isEnabled()
        assert not panel.stop_button.isEnabled()
        # 实时曲线窗口下拉默认 5 min
        assert panel.window_combo.currentData() == 300
        # 最近一行预览存在
        assert panel.last_line_edit.isReadOnly()
        # 打开日志目录按钮存在
        assert panel.open_log_button.text() == "打开日志目录"
        # 状态表列头不含"最近频率(MHz)"
        headers = [
            panel.status_table.horizontalHeaderItem(i).text()
            for i in range(panel.status_table.columnCount())
        ]
        assert "最近频率(MHz)" not in headers
        # 曲线控件为 pyqtgraph PlotWidget 子类
        assert isinstance(panel.chart_view, KUR512ChartView)
    finally:
        panel.shutdown()
        panel.close()


def test_panel_polarity_change_disables_angle_input(app):
    panel = KUR512Panel()
    try:
        # 默认线极化，角度输入可用
        assert panel.pol_value_edit.isEnabled()
        panel.polarity_lhcp_radio.setChecked(True)
        assert not panel.pol_value_edit.isEnabled()
        panel.polarity_rhcp_radio.setChecked(True)
        assert not panel.pol_value_edit.isEnabled()
        panel.polarity_linear_radio.setChecked(True)
        assert panel.pol_value_edit.isEnabled()
    finally:
        panel.shutdown()
        panel.close()


def test_panel_subarray_helpers():
    assert KUR512Panel.generate_subarray_ids(1, 3) == [0x01, 0x02, 0x03]
    assert KUR512Panel.generate_subarray_ids(2, 2) == [0x01, 0x02, 0x11, 0x12]
    with pytest.raises(ValueError):
        KUR512Panel.generate_subarray_ids(3, 1)
    with pytest.raises(ValueError):
        KUR512Panel.generate_subarray_ids(1, 16)
    assert KUR512Panel.parse_subarray_ids("0x01, 0x02, 0x11") == [0x01, 0x02, 0x11]
    assert KUR512Panel.parse_subarray_ids("0x80") == []  # 0x80 越界 0x7F


def test_panel_polling_group_has_no_overlapping_buttons(app):
    """停止和打开日志目录不应放在 grid 同一格；show 后 geometry 应不重叠。"""
    panel = KUR512Panel()
    panel.resize(1200, 800)
    panel.show()
    app.processEvents()
    try:
        start_geo = panel.start_button.geometry()
        stop_geo = panel.stop_button.geometry()
        log_geo = panel.open_log_button.geometry()
        # 三个按钮的 geometry 都应该是非空矩形
        assert start_geo.width() > 0 and start_geo.height() > 0
        assert stop_geo.width() > 0 and stop_geo.height() > 0
        assert log_geo.width() > 0 and log_geo.height() > 0
        # 停止按钮和打开日志目录按钮不重叠
        assert not stop_geo.intersects(log_geo), (
            f"stop={stop_geo.getRect()}, log={log_geo.getRect()}"
        )
    finally:
        panel.shutdown()
        panel.close()
