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
    parse_frame,
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
        """创建 QS 串口会话和 A0 上报速率统计器。

        Args:
            port_name: 要打开的串口名称。
            baudrate: 串口波特率，QS 通常使用 921600。
            parent: Qt 父对象。
        """
        super().__init__(port_name, baudrate, timeout=0.01, idle_ms=2, parent=parent)
        self.parser = FrameStreamParser()
        self.report_rate = ReportRateMeter()
        self._last_rate_emit = 0.0

    def handle_bytes(self, data: bytes) -> None:
        """在串口线程中拆分接收字节并分派 A0/A1 语义事件。

        Args:
            data: 本次从串口读出的原始字节块，可包含分包、粘包或异常字节。

        线程：由 :class:`SerialThread` 所属后台串口线程调用；只通过 Qt 信号通知 UI。
        """
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
        """将完整 QS 帧放入串口线程发送队列并记录 TX 事件。

        Args:
            frame: 已完成协议编码的完整 QS 帧。

        Returns:
            串口线程正在运行且发送队列接受该帧时为 ``True``。

        线程：调用方不直接访问 pyserial；实际写入由后台串口线程完成。
        """
        accepted = self.send_bytes(frame)
        if accepted:
            parsed, message = parse_frame(frame)
            command_value = frame[1] if len(frame) > 1 else 0
            command = (
                f"0x{parsed['command']:02X} {parsed['name']}"
                if parsed is not None
                else f"0x{command_value:02X}"
            )
            summary = describe(parsed, message)
            self.frame_signal.emit(
                FrameRecord(
                    "AFD01_QS",
                    f"{self.port_name}/QS",
                    "TX",
                    command,
                    bytes(frame),
                    summary,
                )
            )
        return accepted

    def report_snr(self, snr: float, indicator: int, power: int, reboot: int) -> bool:
        """构建并发送 0x01 信噪比及电源/重启控制参数。

        Args:
            snr: 信噪比浮点值。
            indicator: uint8 指示值。
            power: uint8 电源状态。
            reboot: uint8 重启状态。

        Returns:
            帧是否成功进入发送队列。
        """
        return self.send_frame(build_snr_report(snr, indicator, power, reboot))

    def configure_beam(
        self,
        longitude_deg: float,
        polarization: int,
        rx_frequency_mhz: float,
        tx_frequency_mhz: float,
    ) -> bool:
        """构建并发送 0x02 卫星经度、极化及收发频率配置。

        Args:
            longitude_deg: 卫星经度，单位为度。
            polarization: uint8 极化值。
            rx_frequency_mhz: 接收频率，单位 MHz。
            tx_frequency_mhz: 发射频率，单位 MHz。

        Returns:
            帧是否成功进入发送队列。

        Raises:
            ValueError: 经度超出协议范围时由构帧器抛出。
        """
        return self.send_frame(
            build_beam_config(
                longitude_deg,
                polarization,
                rx_frequency_mhz,
                tx_frequency_mhz,
            )
        )

    def set_transmit_enabled(self, enabled: int) -> bool:
        """发送 0x03 发射开关命令。

        Args:
            enabled: uint8 开关值，通常为 0（关闭）或 1（开启）。

        Returns:
            帧是否成功进入发送队列。
        """
        return self.send_frame(build_u8_command(0x03, enabled))

    def set_heading_scan_angle(self, angle_deg: float) -> bool:
        """发送 0x04 航向扫描角命令。

        Args:
            angle_deg: 扫描角，单位为度，范围由协议构帧器校验。

        Returns:
            帧是否成功进入发送队列。
        """
        return self.send_frame(build_angle_command(0x04, angle_deg))

    def set_track_mode(self, mode: int) -> bool:
        """发送 0x05 跟踪模式命令。

        Args:
            mode: uint8 跟踪模式值。

        Returns:
            帧是否成功进入发送队列。
        """
        return self.send_frame(build_u8_command(0x05, mode))

    def set_heading_align_angle(self, angle_deg: float) -> bool:
        """发送 0x06 航向对准角命令。

        Args:
            angle_deg: 对准角，单位为度，范围由协议构帧器校验。

        Returns:
            帧是否成功进入发送队列。
        """
        return self.send_frame(build_angle_command(0x06, angle_deg))

    def configure_tle(self, line1: str, line2: str) -> bool:
        """发送 0x08 双行 TLE 配置。

        Args:
            line1: 第一行 ASCII TLE，最长 69 字节。
            line2: 第二行 ASCII TLE，最长 69 字节。

        Returns:
            帧是否成功进入发送队列。

        Raises:
            UnicodeEncodeError: TLE 含非 ASCII 字符时由构帧器抛出。
            ValueError: TLE 单行超过协议长度时由构帧器抛出。
        """
        return self.send_frame(build_tle(line1, line2))

    def set_beam_angle(self, target: int, theta_deg: float, phi_deg: float) -> bool:
        """设置 TX(0x07)、RX(0x09) 或共同(0x0A)波束角。

        Args:
            target: 波束目标命令号。
            theta_deg: 俯仰角，单位为度。
            phi_deg: 方位角，单位为度。

        Returns:
            帧是否成功进入发送队列。

        Raises:
            ValueError: 命令号或角度不符合协议范围时由构帧器抛出。
        """
        return self.send_frame(build_beam_angle(target, theta_deg, phi_deg))

    def query_array(self) -> bool:
        """发送 0x0B 有效子阵档位查询。

        Returns:
            帧是否成功进入发送队列；A1 回读由 ``array_status_signal`` 发布。
        """
        return self.send_frame(build_array_query())

    def set_array_level(self, tx_level: int, rx_level: int) -> bool:
        """发送 0x0B TX/RX 有效子阵档位设置。

        Args:
            tx_level: TX 客户档位，仅支持 1 至 5。
            rx_level: RX 客户档位，仅支持 1 至 5。

        Returns:
            帧是否成功进入发送队列。

        Raises:
            ValueError: 阵列档位不受协议支持时由构帧器抛出。
        """
        return self.send_frame(build_array_set(tx_level, rx_level))


# 过渡期兼容旧页面中的类名，新代码优先使用 Afd01QsDriver。
QSSerialWorker = Afd01QsDriver
