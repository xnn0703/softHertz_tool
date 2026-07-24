#!/usr/bin/env python3
"""AFD01_QS V1.6 串口模拟器：100 Hz A0 + 0x0B/A1 阵列查询与设置。"""

from __future__ import annotations

import argparse
import struct
import time

from soft_hertz_tool.devices.afd01_qs.protocol import build_frame
from soft_hertz_tool.devices.afd01_qs.stream import FrameStreamParser


class QSDeviceSimulator:
    PERIOD_S = 0.01
    MIN_INTERVAL_S = 0.005

    def __init__(self, serial_port):
        self.serial = serial_port
        self.parser = FrameStreamParser()
        self.tx_size = 8
        self.rx_size = 8
        self.power_flags = 0x03
        self.apply_flags = 0x03
        self.started = time.monotonic()
        self.running = False

    def _a0_frame(self) -> bytes:
        uptime = int(time.monotonic() - self.started)
        payload = struct.pack(
            ">BhhHffffBBhhhhhBBBI",
            1,
            12500,
            3000,
            100,
            19798.0,
            29797.5,
            19250.0,
            29050.0,
            1,
            0,
            0,
            0,
            0,
            1200,
            3400,
            0,
            0,
            1 << 5,
            uptime,
        )
        return build_frame(0xA0, payload)

    def _a1_frame(self, result: int = 0) -> bytes:
        return build_frame(
            0xA1,
            bytes([result, self.tx_size, self.rx_size, self.power_flags, self.apply_flags]),
        )

    def process_input(self, data: bytes) -> None:
        for event in self.parser.feed(data):
            if event.kind != "frame" or not event.parsed:
                continue
            parsed = event.parsed
            if parsed["command"] != 0x0B:
                continue

            payload = parsed["payload"]
            result = 0
            if len(payload) != 3:
                result |= 0x01
            else:
                operation, tx_size, rx_size = payload
                query_ok = operation == 0 and tx_size == 0 and rx_size == 0
                set_ok = (
                    operation == 1
                    and tx_size in (4, 5, 6, 7, 8, 0xFF)
                    and rx_size in (4, 5, 6, 7, 8, 0xFF)
                )
                if not query_ok and not set_ok:
                    result |= 0x01
                elif operation == 1:
                    if tx_size != 0xFF:
                        self.tx_size = tx_size
                    if rx_size != 0xFF:
                        self.rx_size = rx_size
            self.serial.write(self._a1_frame(result))

    def run(self, duration: float = 0.0) -> None:
        self.running = True
        deadline = time.monotonic()
        end = deadline + duration if duration > 0 else None
        while self.running and (end is None or time.monotonic() < end):
            count = self.serial.in_waiting
            if count:
                self.process_input(self.serial.read(count))
            now = time.monotonic()
            if now >= deadline:
                self.serial.write(self._a0_frame())
                sent_at = time.monotonic()
                deadline += self.PERIOD_S
                if deadline <= sent_at:
                    # 阻塞后跳过已错过的截止时间，不突发补帧。
                    missed = int((sent_at - deadline) / self.PERIOD_S) + 1
                    deadline += missed * self.PERIOD_S
                # 晚唤醒但尚未跨过完整周期时也不做紧邻追赶。
                deadline = max(deadline, sent_at + self.MIN_INTERVAL_S)
            time.sleep(min(0.001, max(0.0, deadline - time.monotonic())))

    def stop(self) -> None:
        self.running = False


def main() -> None:
    import serial

    parser = argparse.ArgumentParser(description="AFD01_QS V1.6 serial simulator")
    parser.add_argument("port", help="串口或 PTY 路径")
    parser.add_argument("--baudrate", type=int, default=921600)
    args = parser.parse_args()
    with serial.Serial(args.port, args.baudrate, timeout=0) as port:
        print(f"QS simulator: {args.port} @ {args.baudrate}")
        try:
            QSDeviceSimulator(port).run()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
