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
        if not self._closed:
            self._queue.put(record.to_line() + "\n")

    def close(self, timeout: float = 3.0) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put(None)
        self._thread.join(timeout)

    def _next_path(self, index: int) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{index:03d}" if index else ""
        return self.log_dir / f"frames_{stamp}{suffix}.log"

    def _run(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        index = 0
        stream = self._next_path(index).open("a", encoding="utf-8", buffering=1)
        try:
            while True:
                line = self._queue.get()
                if line is None:
                    break
                encoded_size = len(line.encode("utf-8"))
                if stream.tell() > 0 and stream.tell() + encoded_size > self.max_bytes:
                    stream.close()
                    index += 1
                    stream = self._next_path(index).open("a", encoding="utf-8", buffering=1)
                stream.write(line)
        finally:
            stream.close()
