"""AFD01_QS 运行期轻量模型。"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Optional


class ReportRateMeter:
    """根据接收时间戳计算 A0 滑动上报频率。"""

    def __init__(self, window_seconds: float = 2.0):
        """创建滑动窗口统计器。

        Args:
            window_seconds: 统计窗口长度，单位为秒，必须大于零。

        Raises:
            ValueError: 统计窗口不为正数。
        """
        if window_seconds <= 0:
            raise ValueError("统计窗口必须大于 0")
        self.window_seconds = window_seconds
        self.timestamps: Deque[float] = deque()

    def add(self, timestamp: Optional[float] = None) -> float:
        """记录一条 A0 到达时间并返回窗口平均频率。

        Args:
            timestamp: 单调时钟时间戳，单位为秒；省略时读取当前单调时钟。

        Returns:
            窗口内相邻上报的平均频率，单位 Hz；样本不足时为 0.0。
        """
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
        """清空全部时间戳，使下一次统计从零开始。"""
        self.timestamps.clear()
