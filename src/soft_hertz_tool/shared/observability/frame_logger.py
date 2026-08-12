"""异步帧日志和定长轮转。"""

from __future__ import annotations

import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QStandardPaths

from soft_hertz_tool.identity import default_log_directory
from soft_hertz_tool.shared.observability.frame_record import FrameRecord


class AsyncFrameLogger:
    """单写线程日志；达到上限后新建文件，不自动删除历史。"""

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        max_bytes: int = 50 * 1024 * 1024,
        documents_dir: Optional[Path] = None,
    ):
        """创建日志目录配置并立即启动唯一写线程。

        Args:
            log_dir: 显式日志目录；为 ``None`` 时使用产品默认文档目录。
            max_bytes: 单个日志文件的近似最大字节数。
            documents_dir: 测试或定制默认路径时使用的文档根目录。
        """

        if log_dir is None:
            if documents_dir is None:
                docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
                documents_dir = Path(docs or str(Path.home() / "Documents"))
            log_dir = default_log_directory(documents_dir)
        self.log_dir = Path(log_dir)
        self.max_bytes = max_bytes
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._closed = False
        self._close_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="frame-log-writer", daemon=True)
        self._thread.start()

    def write(self, record: FrameRecord) -> None:
        """异步提交一条帧记录。

        Args:
            record: 待序列化并落盘的设备帧事件。

        Returns:
            无返回值。日志器关闭后的记录会被忽略，调用线程不会执行磁盘 I/O。
        """

        if not self._closed:
            self._queue.put(record.to_line() + "\n")

    def close(self, timeout: float = 3.0) -> None:
        """幂等地停止接收新记录并等待队列写线程退出。

        Args:
            timeout: 等待写线程结束的最长秒数。

        Returns:
            无返回值。超时只结束等待，不强制终止守护线程。
        """

        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            # sentinel 排在既有记录之后，保证正常关闭时先刷完队列再退出。
            self._queue.put(None)
        # 不在锁内 join，避免未来写线程收尾路径与关闭锁形成互等。
        self._thread.join(timeout)

    def _next_path(self, index: int) -> Path:
        """生成本次进程内指定轮转序号的日志路径。

        Args:
            index: 从 0 开始的轮转序号。

        Returns:
            带当前时间戳和可选三位序号的 ``.log`` 路径。
        """

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{index:03d}" if index else ""
        return self.log_dir / f"frames_{stamp}{suffix}.log"

    def _run(self) -> None:
        """在专用线程中顺序写入并按单文件大小轮转。

        Returns:
            无返回值；收到 sentinel 后关闭当前文件。轮转只创建新文件，不删除
            任何历史日志。
        """

        self.log_dir.mkdir(parents=True, exist_ok=True)
        index = 0
        stream = self._next_path(index).open("a", encoding="utf-8", buffering=1)
        try:
            while True:
                line = self._queue.get()
                if line is None:
                    break
                encoded_size = len(line.encode("utf-8"))
                # 空文件必须先容纳至少一条记录，避免单条超限记录触发空文件循环。
                if stream.tell() > 0 and stream.tell() + encoded_size > self.max_bytes:
                    stream.close()
                    index += 1
                    stream = self._next_path(index).open("a", encoding="utf-8", buffering=1)
                stream.write(line)
        finally:
            stream.close()
