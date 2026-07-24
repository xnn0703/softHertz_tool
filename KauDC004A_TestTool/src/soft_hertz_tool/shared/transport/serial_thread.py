"""由单一后台线程独占 pyserial 对象的通用串口循环。"""

from __future__ import annotations

import queue
import threading
from abc import abstractmethod

from PySide6.QtCore import QThread, Signal, Slot


class SerialThread(QThread):
    """设备 Driver 的串口基类。

    UI 线程只把待发送字节放入队列；串口的 open/read/write/close 均在 run() 所在线程执行。
    """

    log_signal = Signal(str)
    opened_signal = Signal(bool, str)
    frame_signal = Signal(object)

    def __init__(
        self,
        port_name: str,
        baudrate: int,
        timeout: float = 0.01,
        write_timeout: float = 1.0,
        idle_ms: int = 2,
        tx_queue_size: int = 1024,
        max_tx_per_cycle: int = 32,
        parent=None,
    ):
        super().__init__(parent)
        self.port_name = port_name
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.idle_ms = idle_ms
        self.max_tx_per_cycle = max_tx_per_cycle
        self.running = False
        self.serial = None
        self._stop_event = threading.Event()
        self._tx_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=tx_queue_size)

    def run(self) -> None:
        import serial

        try:
            if self._stop_event.is_set():
                return
            self.serial = serial.Serial(
                self.port_name,
                self.baudrate,
                timeout=self.timeout,
                write_timeout=self.write_timeout,
            )
            if self._stop_event.is_set():
                return
            self.running = True
            message = f"串口已打开: {self.port_name} @ {self.baudrate}"
            self.log_signal.emit(message)
            self.opened_signal.emit(True, message)
            while not self._stop_event.is_set():
                self._flush_tx()
                if not self.serial or not self.serial.is_open:
                    break
                count = self.serial.in_waiting
                if count:
                    data = self.serial.read(count)
                    if data:
                        self.handle_bytes(data)
                else:
                    QThread.msleep(self.idle_ms)
        except Exception as exc:
            message = f"串口错误: {exc}"
            self.log_signal.emit(message)
            self.opened_signal.emit(False, message)
        finally:
            self.running = False
            serial_port, self.serial = self.serial, None
            if serial_port and serial_port.is_open:
                serial_port.close()
            self.log_signal.emit("串口已关闭")

    def _flush_tx(self) -> None:
        for _ in range(self.max_tx_per_cycle):
            if self._stop_event.is_set() or not self.serial or not self.serial.is_open:
                return
            try:
                frame = self._tx_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self.serial.write(frame)
            except Exception as exc:
                self.log_signal.emit(f"发送失败: {exc}")

    @Slot(bytes)
    def send_bytes(self, frame: bytes) -> bool:
        if not self.running or self._stop_event.is_set():
            return False
        try:
            self._tx_queue.put_nowait(bytes(frame))
        except queue.Full:
            self.log_signal.emit("发送队列已满，帧未入队")
            return False
        return True

    @abstractmethod
    def handle_bytes(self, data: bytes) -> None:
        """在串口线程内接收并解析一段字节流。"""

    def stop(self, timeout_ms: int = 3000) -> bool:
        """请求线程退出并等待串口关闭；仅在真正停止后返回 ``True``。"""

        self._stop_event.set()
        self.running = False
        serial_port = self.serial
        if serial_port is not None:
            # pyserial 的 cancel_* 专门用于从另一线程中断阻塞 I/O；串口关闭仍由 run() 完成。
            for method_name in ("cancel_read", "cancel_write"):
                method = getattr(serial_port, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        pass
        if not self.isRunning():
            return True
        stopped = self.wait(timeout_ms)
        if not stopped:
            self.log_signal.emit(f"串口线程在 {timeout_ms} ms 内未停止")
        return stopped
