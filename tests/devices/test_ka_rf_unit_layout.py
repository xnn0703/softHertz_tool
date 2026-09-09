"""KA 页面高度与紧凑输入的实际 Qt 布局回归。"""
from PySide6.QtWidgets import QApplication, QTabWidget

from soft_hertz_tool.devices.ka_rf_unit.panel import KaRfUnitPanel


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
