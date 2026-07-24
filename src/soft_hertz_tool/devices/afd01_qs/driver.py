"""AFD01_QS 设备串口 Driver。"""

from __future__ import annotations

import time

from PySide6.QtCore import Signal, Slot

from soft_hertz_tool.devices.afd01_qs.models import ReportRateMeter
from soft_hertz_tool.devices.afd01_qs.protocol import (
    build_angle_command,
    build_array_query,
    build_array_set,
    build_beam_angle,
    build_beam_config,
    build_snr_report,
    build_tle,
    build_u8_command,
    describe,
)
from soft_hertz_tool.devices.afd01_qs.stream import FrameStreamParser
from soft_hertz_tool.shared.observability import FrameRecord
from soft_hertz_tool.shared.transport import SerialThread


class Afd01QsDriver(SerialThread):
    """QS 串口会话，负责分帧、语义分派和低频统计信号。"""

    telemetry_signal = Signal(dict)
    report_rate_signal = Signal(float)
    array_status_signal = Signal(dict)

    def __init__(self, port_name: str, baudrate: int, parent=None):
        super().__init__(port_name, baudrate, timeout=0.01, idle_ms=2, parent=parent)
        self.parser = FrameStreamParser()
        self.report_rate = ReportRateMeter()
        self._last_rate_emit = 0.0

    def handle_bytes(self, data: bytes) -> None:
        for event in self.parser.feed(data):
            if event.kind != "frame":
                command = f"0x{event.data[1]:02X}" if len(event.data) > 1 else "RAW"
                self.frame_signal.emit(
                    FrameRecord(
                        "AFD01_QS",
                        f"{self.port_name}/QS",
                        "DROP",
                        command,
                        event.data,
                        event.message,
                        "ERROR",
                    )
                )
                continue

            parsed = event.parsed or {}
            command = f"0x{parsed['command']:02X} {parsed['name']}"
            summary = describe(parsed, event.message)
            self.frame_signal.emit(
                FrameRecord("AFD01_QS", f"{self.port_name}/QS", "RX", command, event.data, summary)
            )

            if parsed["command"] == 0xA0:
                now = time.monotonic()
                rate = self.report_rate.add(now)
                # A0 按 100 Hz 接收，频率指示最多 2 Hz 刷新，避免信号淹没 UI 线程。
                if now - self._last_rate_emit >= 0.5:
                    self._last_rate_emit = now
                    self.report_rate_signal.emit(rate)
                self.telemetry_signal.emit(parsed["decoded"])
            elif parsed["command"] == 0xA1:
                self.array_status_signal.emit(parsed["decoded"])

    @Slot(bytes)
    def send_frame(self, frame: bytes) -> bool:
        """将帧放入串口线程发送队列。"""
        accepted = self.send_bytes(frame)
        if accepted:
            command = frame[1] if len(frame) > 1 else 0
            self.frame_signal.emit(
                FrameRecord(
                    "AFD01_QS",
                    f"{self.port_name}/QS",
                    "TX",
                    f"0x{command:02X}",
                    bytes(frame),
                    "已进入发送队列",
                )
            )
        return accepted

    def report_snr(self, snr: float, indicator: int, power: int, reboot: int) -> bool:
        """上报信噪比及电源/重启控制参数。"""
        return self.send_frame(build_snr_report(snr, indicator, power, reboot))

    def configure_beam(
        self,
        longitude_deg: float,
        polarization: int,
        rx_frequency_mhz: float,
        tx_frequency_mhz: float,
    ) -> bool:
        """设置卫星经度、极化及收发频率。"""
        return self.send_frame(
            build_beam_config(
                longitude_deg,
                polarization,
                rx_frequency_mhz,
                tx_frequency_mhz,
            )
        )

    def set_transmit_enabled(self, enabled: int) -> bool:
        return self.send_frame(build_u8_command(0x03, enabled))

    def set_heading_scan_angle(self, angle_deg: float) -> bool:
        return self.send_frame(build_angle_command(0x04, angle_deg))

    def set_track_mode(self, mode: int) -> bool:
        return self.send_frame(build_u8_command(0x05, mode))

    def set_heading_align_angle(self, angle_deg: float) -> bool:
        return self.send_frame(build_angle_command(0x06, angle_deg))

    def configure_tle(self, line1: str, line2: str) -> bool:
        return self.send_frame(build_tle(line1, line2))

    def set_beam_angle(self, target: int, theta_deg: float, phi_deg: float) -> bool:
        """设置 TX(0x07)、RX(0x09) 或共同(0x0A)波束角。"""
        return self.send_frame(build_beam_angle(target, theta_deg, phi_deg))

    def query_array(self) -> bool:
        return self.send_frame(build_array_query())

    def set_array_size(self, tx_size: int, rx_size: int) -> bool:
        return self.send_frame(build_array_set(tx_size, rx_size))


# 过渡期兼容旧页面中的类名，新代码优先使用 Afd01QsDriver。
QSSerialWorker = Afd01QsDriver
