"""正式模块入口的离屏启动冒烟。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from soft_hertz_tool import __main__ as entrypoint


def test_smoke_mode_creates_and_closes_main_window(monkeypatch):
    monkeypatch.setattr(entrypoint, "SMOKE_CLOSE_DELAY_MS", 0)

    assert entrypoint.main(["--smoke"]) == 0
