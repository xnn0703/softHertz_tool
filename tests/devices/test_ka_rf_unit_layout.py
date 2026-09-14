"""KA 页面高度与紧凑输入的实际 Qt 布局回归。"""
import pytest
from PySide6.QtWidgets import QApplication, QTabWidget

from soft_hertz_tool.devices.ka_rf_unit.panel import KaRfUnitPanel


@pytest.mark.parametrize("width", [1180, 1280, 1450])
def test_scan_status_is_below_controls_and_fits_wrapped_text(width):
    """运行中长状态不能与按钮抢宽，也不能在换行后被命令页裁掉。"""
    app = QApplication.instance() or QApplication([])
    panel = KaRfUnitPanel()
    panel.resize(width, 1000)
    panel.show()
    try:
        panel._scan_index = 999999
        panel._scan_total = 1000000
        panel._scan_skipped = 999999
        panel._scan_current_theta = 90.0
        panel._scan_current_phi = 360.0
        panel._scan_state = "RUNNING"
        panel._scan_update_status_label()
        for _ in range(3):
            app.processEvents()
        label = panel.scan_status_label
        button = panel.scan_stop_btn
        assert label.mapTo(panel, label.rect().topLeft()).y() > button.mapTo(panel, button.rect().bottomLeft()).y()
        assert label.wordWrap()
        assert label.height() >= label.heightForWidth(label.width())
        page = panel.command_tabs.currentWidget()
        assert label.mapTo(page, label.rect().bottomRight()).y() < page.height()
        assert "1000000" in label.text() and "RUNNING" in label.text()
    finally:
        panel.shutdown()
        panel.close()


def test_command_page_uses_active_height_and_compact_inputs():
    app = QApplication.instance() or QApplication([])
    panel = KaRfUnitPanel()
    panel.resize(1450, 1000)
    panel.show()
    tabs = panel.findChild(QTabWidget)
    try:
        for index in (0, 1, 0):
            tabs.setCurrentIndex(index)
            app.processEvents()
            page = tabs.currentWidget()
            assert tabs.height() <= page.sizeHint().height() + tabs.tabBar().height() + 12
            assert page.height() >= page.minimumSizeHint().height()
        tabs.setCurrentIndex(1)
        app.processEvents()
        for spin in panel.internal_angles + panel.array_att_inputs:
            assert spin.sizeHint().width() <= spin.width() <= 125
        for key in ("TX 行", "TX 列"):
            tx = panel.internal_masks[key][0]
            rx = panel.internal_masks[key.replace("TX", "RX")][0]
            assert tx.mapTo(panel, tx.rect().topLeft()).y() == rx.mapTo(panel, rx.rect().topLeft()).y()
    finally:
        panel.shutdown()
        panel.close()
