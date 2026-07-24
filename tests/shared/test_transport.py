"""共享串口线程的停止与阻塞写保护。"""

from __future__ import annotations

import threading
import time

import serial

from soft_hertz_tool.shared.transport import SerialThread


class NoopSerialThread(SerialThread):
    def handle_bytes(self, data: bytes) -> None:
        pass


class BlockingSerial:
    def __init__(self) -> None:
        self.is_open = True
        self.write_started = threading.Event()
        self.write_canceled = threading.Event()
        self.closed = threading.Event()
        self.write_timeout = None

    @property
    def in_waiting(self) -> int:
        return 0

    def read(self, count: int) -> bytes:
        return b""

    def write(self, data: bytes) -> int:
        self.write_started.set()
        self.write_canceled.wait(5.0)
        return len(data)

    def cancel_read(self) -> None:
        pass

    def cancel_write(self) -> None:
        self.write_canceled.set()

    def close(self) -> None:
        self.is_open = False
        self.closed.set()


def test_stop_cancels_blocking_write_and_prevents_late_open(monkeypatch) -> None:
    opened_ports = []

    def open_serial(_port, _baudrate, *, timeout, write_timeout):
        port = BlockingSerial()
        port.write_timeout = write_timeout
        opened_ports.append(port)
        return port

    monkeypatch.setattr(serial, "Serial", open_serial)
    driver = NoopSerialThread("SIM", 115200)
    driver.start()
    deadline = time.monotonic() + 1.0
    while not driver.running and time.monotonic() < deadline:
        time.sleep(0.001)
    assert driver.running
    assert driver.send_bytes(b"frame")
    assert opened_ports[0].write_started.wait(1.0)

    assert driver.stop(1000)
    assert opened_ports[0].write_canceled.is_set()
    assert opened_ports[0].closed.is_set()
    assert opened_ports[0].write_timeout == 1.0

    stopped_before_start = NoopSerialThread("SIM-LATE", 115200)
    assert stopped_before_start.stop()
    stopped_before_start.start()
    assert stopped_before_start.wait(1000)
    assert len(opened_ports) == 1
