"""共享帧事件、日志与监视器测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from soft_hertz_tool.shared.observability import AsyncFrameLogger, FrameRecord
from soft_hertz_tool.shared.ui.frame_monitor import FrameMonitorWidget


def test_async_logger_rotates_without_deleting_history(tmp_path: Path):
    logger = AsyncFrameLogger(tmp_path, max_bytes=260)
    for index in range(20):
        logger.write(FrameRecord("AFD01_QS", "COM1", "RX", "0xA0", bytes(range(20)), f"line {index}"))
    logger.close()
    files = sorted(tmp_path.glob("frames_*.log"))
    assert len(files) >= 2
    content = "".join(path.read_text(encoding="utf-8") for path in files)
    assert "line 0" in content and "line 19" in content


def test_monitor_discovers_models_and_keeps_line_limit(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    monitor = FrameMonitorWidget(logger=AsyncFrameLogger(tmp_path), max_lines=5)
    models = ("AFDT1024", "AFDR1024", "AFD01_QS")
    for index in range(8):
        model = models[index % len(models)]
        monitor.add_record(FrameRecord(model, "SIM", "RX", "STATUS", b"\x55", f"line {index}"))
    monitor._flush_pending()
    assert monitor.model_filter.findText("AFDT1024") >= 0
    assert monitor.model_filter.findText("AFDR1024") >= 0
    assert monitor.model_filter.findText("AFD01_QS") >= 0
    assert len(monitor.records) == 5
    assert monitor.text.document().blockCount() <= 5
    assert "line 7" in monitor.text.toPlainText()
    monitor.close_logger()
    monitor.deleteLater()
    app.processEvents()
