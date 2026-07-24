"""AFD01_QS 运行期轻量模型。"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Optional


class ReportRateMeter:
    """根据接收时间戳计算 A0 滑动上报频率。"""

    def __init__(self, window_seconds: float = 2.0):
        if window_seconds <= 0:
            raise ValueError("统计窗口必须大于 0")
        self.window_seconds = window_seconds
        self.timestamps: Deque[float] = deque()

    def add(self, timestamp: Optional[float] = None) -> float:
        now = time.monotonic() if timestamp is None else timestamp
        self.timestamps.append(now)
        cutoff = now - self.window_seconds
        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.popleft()
        if len(self.timestamps) < 2:
            return 0.0
        elapsed = self.timestamps[-1] - self.timestamps[0]
        return (len(self.timestamps) - 1) / elapsed if elapsed > 0 else 0.0

    def reset(self) -> None:
        self.timestamps.clear()
