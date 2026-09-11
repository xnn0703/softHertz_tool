"""客户流量明细的有界异步 JSONL 记录与运行汇总。"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Optional


class TrafficRecorder:
    """单写线程，非阻塞提交；溢出和磁盘错误使证据显式不完整。"""

    def __init__(self, directory: Path, metadata: dict, capacity: int = 4096,
                 max_bytes: int = 50 * 1024 * 1024):
        """先同步创建文件以尽早报告权限错误，再启动有界后台记录。"""
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.metadata = metadata
        self.path = self.directory / "events.jsonl"
        self.path.touch(exist_ok=False)
        self._queue: queue.Queue = queue.Queue(maxsize=capacity)
        self._closing = threading.Event()
        self._lock = threading.Lock()
        self._summary: dict = {}
        self.lost = 0
        self.error = ""
        self.max_bytes = max_bytes
        self.part = 0
        self._thread = threading.Thread(target=self._run, name="traffic-recorder", daemon=True)
        self._thread.start()

    def record(self, event: dict) -> None:
        """提交不可再修改的事件副本，不在串口线程进行磁盘写入。"""
        with self._lock:
            if self._closing.is_set() or self.error:
                self.lost += 1
                return
            try:
                self._queue.put_nowait(dict(event))
            except queue.Full:
                self.lost += 1

    def finish(self, summary: dict) -> None:
        """幂等请求关闭；写线程排空既有事件后输出汇总。"""
        with self._lock:
            if not self._closing.is_set():
                self._summary = summary
                self._closing.set()

    def close(self, timeout: float = 3.0) -> bool:
        """有界等待写线程退出；调用方需检查结果。"""
        self.finish(self._summary)
        self._thread.join(timeout)
        return not self._thread.is_alive()

    @property
    def finished(self) -> bool:
        """明细与汇总是否已完成收尾。"""
        return not self._thread.is_alive()

    def evidence(self) -> dict:
        """返回记录完整性及可导出的目录。"""
        with self._lock:
            return {"directory": str(self.directory), "records_lost": self.lost,
                    "record_error": self.error, "evidence_complete": not self.lost and not self.error,
                    "detail_files": ["events.jsonl"] + [f"events_{i:03d}.jsonl" for i in range(1, self.part + 1)],
                    "recording_finished": self.finished}

    def _run(self) -> None:
        """顺序写入，磁盘异常后排空队列并尽力留下失败汇总。"""
        stream: Optional[object] = None
        try:
            stream = self.path.open("a", encoding="utf-8")
            stream.write(json.dumps({"event": "metadata", **self.metadata}, ensure_ascii=False) + "\n")
            while not self._closing.is_set() or not self._queue.empty():
                try:
                    event = self._queue.get(timeout=0.05)
                except queue.Empty:
                    if stream:
                        stream.flush()
                    continue
                try:
                    if stream:
                        if stream.tell() >= self.max_bytes:
                            stream.close()
                            self.part += 1
                            stream = (self.directory / f"events_{self.part:03d}.jsonl").open("w", encoding="utf-8")
                        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                    else:
                        with self._lock:
                            self.lost += 1
                except Exception as exc:
                    with self._lock:
                        self.error = str(exc)
                        self.lost += 1
                    try:
                        stream.close()
                    except Exception:
                        pass
                    stream = None
        except Exception as exc:
            with self._lock:
                self.error = str(exc)
                self.lost += self._queue.qsize()
        finally:
            if stream:
                try:
                    stream.close()
                except Exception as exc:
                    self.error = str(exc)
            # 失败必须可观察；不把打不开汇总文件当作成功。
            try:
                summary = {**self.metadata, **self._summary, **self.evidence()}
                summary["recording_finished"] = True
                (self.directory / "summary.json").write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                self.error = str(exc)
