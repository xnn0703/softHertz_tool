#!/usr/bin/env python3
"""AFD01_QS V1.7 串口模拟器：100 Hz A0 + 0x0B/A1 档位查询与设置。"""

from __future__ import annotations

import argparse
import struct
import time

from soft_hertz_tool.devices.afd01_qs.protocol import ARRAY_LEVEL_PROFILES, build_frame
from soft_hertz_tool.devices.afd01_qs.stream import FrameStreamParser


class QSDeviceSimulator:
    """通过串口模拟周期 A0 上报和 0x0B/A1 档位交互的状态内核。"""
    PERIOD_S = 0.01
    MIN_INTERVAL_S = 0.005

    def __init__(self, serial_port):
        """创建使用给定串口对象的 QS 模拟器。

        Args:
            serial_port: 提供 ``read``、``write`` 和 ``in_waiting`` 的串口对象。
        """
        self.serial = serial_port
        self.parser = FrameStreamParser()
        self.tx_level = 5
        self.rx_level = 5
        self.started = time.monotonic()
        self.running = False

    def _a0_frame(self) -> bytes:
        """构建一帧包含固定示例遥测与运行时间的 A0 上报。

        Returns:
            完整 QS A0 帧；运行时间字段单位为秒。
        """
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

    def _a1_frame(self) -> bytes:
        """构建当前 TX/RX 有效子阵档位的 A1 回读帧。

        Returns:
            载荷只含 TX/RX 当前档位的完整 QS A1 帧。
        """
        return build_frame(0xA1, bytes([self.tx_level, self.rx_level]))

    def process_input(self, data: bytes) -> None:
        """解析输入并对有效 0x0B 查询或设置返回 A1。

        Args:
            data: 串口输入字节，可含分包、粘包或非阵列命令。
        """
        for event in self.parser.feed(data):
            if event.kind != "frame" or not event.parsed:
                continue
            parsed = event.parsed
            if parsed["command"] != 0x0B:
                continue

            payload = parsed["payload"]
            operation, tx_level, rx_level = payload
            set_ok = (
                operation == 1
                and (tx_level in ARRAY_LEVEL_PROFILES or tx_level == 0xFF)
                and (rx_level in ARRAY_LEVEL_PROFILES or rx_level == 0xFF)
            )
            if set_ok:
                if tx_level != 0xFF:
                    self.tx_level = tx_level
                if rx_level != 0xFF:
                    self.rx_level = rx_level
            # A1 没有结果位：非法请求保持当前档位不变，仍只回读当前 TX/RX 档位。
            self.serial.write(self._a1_frame())

    def run(self, duration: float = 0.0) -> None:
        """运行串口循环并以目标 100 Hz 发送 A0。

        Args:
            duration: 运行时长，单位为秒；零表示持续运行至 ``stop``。
        """
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
        """请求 ``run`` 循环在下一次条件检查时退出。"""
        self.running = False


def main() -> None:
    """解析命令行串口参数并启动 QS 模拟器。

    Raises:
        serial.SerialException: 串口无法打开时由 pyserial 抛出。
    """
    import serial

    parser = argparse.ArgumentParser(description="AFD01_QS V1.7 serial simulator")
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
