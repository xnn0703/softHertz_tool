"""KuR512B 状态查询的 CSV 异步落盘线程。"""

from __future__ import annotations

import csv
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


CSV_FIELDS = ("ts", "device_id", "rev", "sys_vcc", "sys_temp", "mcu_ver", "raw_hex")


class StatusRecorder:
    """单写线程 + 有界队列；轮转新文件后重新写 CSV 表头。"""

    def __init__(
        self,
        root: Path,
        device_id: int,
        capacity: int = 10000,
        max_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        """创建目录与文件，启动后台写线程。

        Args:
            root: 状态日志根目录（如 ``logs/kur512/``）。
            device_id: 子阵 ID；按 ID 分子目录。
            capacity: 有界队列大小。
            max_bytes: 单文件字节上限。
        """
        self.root = Path(root)
        self.device_id = int(device_id)
        self._queue: "queue.Queue[dict]" = queue.Queue(maxsize=capacity)
        self._closing = threading.Event()
        self._lock = threading.Lock()
        self._path: Optional[Path] = None
        self._stream = None
        self._writer = None
        self._part = 0
        self.max_bytes = max_bytes
        self.lost = 0
        self.error = ""
        self._open_file_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run, name=f"kur512-recorder-{self.device_id}", daemon=True,
        )
        self._thread.start()

    @property
    def path(self) -> Optional[Path]:
        """当前正在写入的 CSV 路径。"""
        with self._open_file_lock:
            return self._path

    def append(
        self,
        device_id: int,
        info: dict,
        raw_hex: str,
        ts: Optional[datetime] = None,
    ) -> None:
        """非阻塞入队；写入失败或队列满时累加 ``lost``。"""
        ts = ts or datetime.now().astimezone()
        record = {
            "ts": ts.isoformat(timespec="milliseconds"),
            "device_id": f"0x{int(device_id) & 0xFF:02X}",
            "rev": info.get("rev"),
            "sys_vcc": info.get("sys_vcc"),
            "sys_temp": info.get("sys_temp"),
            "mcu_ver": info.get("mcu_ver"),
            "raw_hex": raw_hex,
        }
        with self._lock:
            if self._closing.is_set() or self.error:
                self.lost += 1
                return
            try:
                self._queue.put_nowait(record)
            except queue.Full:
                self.lost += 1

    def finish(self) -> None:
        """幂等请求关闭；写线程排空既有事件后退出。"""
        with self._lock:
            self._closing.set()

    def close(self, timeout: float = 1.0) -> bool:
        """有界等待写线程退出。"""
        self.finish()
        self._thread.join(timeout)
        return not self._thread.is_alive()

    @property
    def finished(self) -> bool:
        """写线程是否已结束。"""
        return not self._thread.is_alive()

    def directory(self) -> Path:
        """返回此子阵的状态日志目录（不保证已创建）。"""
        return self.root / f"0x{self.device_id:02X}"

    def _run(self) -> None:
        """顺序写盘：满 50 MiB 轮转；磁盘错误时记录并退出。"""
        try:
            self._ensure_open()
            while not self._closing.is_set() or not self._queue.empty():
                try:
                    record = self._queue.get(timeout=0.05)
                except queue.Empty:
                    if self._stream:
                        self._stream.flush()
                    continue
                try:
                    self._maybe_rollover(len(record["raw_hex"]) + 64)
                    if self._writer is None:
                        self.lost += 1
                        continue
                    self._writer.writerow(record)
                    self._stream.flush()
                except Exception as exc:
                    with self._lock:
                        self.error = str(exc)
                        self.lost += 1
                    self._close_stream()
        except Exception as exc:
            with self._lock:
                self.error = str(exc)
                self.lost += self._queue.qsize()
        finally:
            self._close_stream()

    def _ensure_open(self) -> None:
        """创建目录与新文件；首次写表头。"""
        with self._open_file_lock:
            directory = self.directory()
            directory.mkdir(parents=True, exist_ok=True)
            date_tag = datetime.now().astimezone().strftime("%Y-%m-%d")
            self._path = directory / f"status-{date_tag}.csv"
            self._stream = self._path.open("a", encoding="utf-8", newline="")
            self._writer = csv.DictWriter(self._stream, fieldnames=CSV_FIELDS)
            if self._path.stat().st_size == 0:
                self._writer.writeheader()
                self._stream.flush()

    def _maybe_rollover(self, incoming_size: int) -> None:
        """文件大小超过 max_bytes 时关闭并创建新文件（同名 + part 后缀）。"""
        with self._open_file_lock:
            if self._stream is None:
                return
            size = self._stream.tell() + incoming_size
            if size < self.max_bytes:
                return
            self._close_stream_locked()
            self._part += 1
            directory = self.directory()
            date_tag = datetime.now().astimezone().strftime("%Y-%m-%d")
            self._path = directory / f"status-{date_tag}_{self._part:03d}.csv"
            self._stream = self._path.open("w", encoding="utf-8", newline="")
            self._writer = csv.DictWriter(self._stream, fieldnames=CSV_FIELDS)
            self._writer.writeheader()
            self._stream.flush()

    def _close_stream(self) -> None:
        """获取文件锁后委托给内部实现。"""
        with self._open_file_lock:
            self._close_stream_locked()

    def _close_stream_locked(self) -> None:
        """关闭当前 CSV 文件并清空 writer；调用方必须持有 ``_open_file_lock``。"""
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception as exc:
                with self._lock:
                    self.error = str(exc)
        self._stream = None
        self._writer = None


__all__ = ["CSV_FIELDS", "StatusRecorder"]
