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
        """保存串口参数并创建有界发送队列。

        Args:
            port_name: pyserial 可打开的端口名。
            baudrate: 串口波特率。
            timeout: 单次读取的最长阻塞秒数。
            write_timeout: 单次写入的最长阻塞秒数。
            idle_ms: 当前无接收数据时的线程让步毫秒数。
            tx_queue_size: 待发送完整帧的最大队列长度。
            max_tx_per_cycle: 每轮读取前最多写出的帧数，用于避免 TX 挤占 RX。
            parent: 可选 Qt 父对象。
        """

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
        """在线程内完成串口打开、收发循环和关闭。

        Returns:
            无返回值。打开成功/失败通过 ``opened_signal``，运行错误通过
            ``log_signal`` 报告；无论如何都在退出前清除 ``serial`` 引用。

        Notes:
            本方法由 :class:`QThread` 调用，禁止在 UI 线程直接执行。
        """

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
                # 每轮只发送有限帧，再检查接收缓冲，避免高密度配置命令饿死 RX。
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
        """在串口线程中写出本轮允许的待发送帧。

        Returns:
            无返回值。队列为空、停止请求或串口失效时提前结束；单帧写入失败
            通过日志信号报告，不跨线程抛出。
        """

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
        """从调用线程把一个完整帧非阻塞地提交到发送队列。

        Args:
            frame: 待发送的完整字节帧；入队前复制为不可变 ``bytes``。

        Returns:
            成功入队返回 ``True``；线程未运行、正在停止或队列已满时返回
            ``False``。返回成功不代表设备已经收到或回复。
        """

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
        """在串口线程内接收并解析一段字节流。

        Args:
            data: pyserial 本轮读取到的非空字节。

        Returns:
            无返回值；子类应通过 Qt 信号发布解析结果。
        """

    def stop(self, timeout_ms: int = 3000) -> bool:
        """请求线程退出并等待串口关闭。

        Args:
            timeout_ms: 等待线程结束的最长毫秒数。

        Returns:
            线程已经停止或在期限内停止时返回 ``True``；超时返回 ``False``。
            只有 ``True`` 才表示调用方可以安全销毁 Driver。
        """

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
