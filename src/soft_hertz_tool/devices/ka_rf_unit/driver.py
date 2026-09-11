"""KA_RF_UNIT 串口 Driver。"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from PySide6.QtCore import Signal, Slot

from soft_hertz_tool.devices.ka_rf_unit import protocol
from soft_hertz_tool.devices.ka_rf_unit.stream import FrameStreamParser
from soft_hertz_tool.shared.observability import FrameRecord
from soft_hertz_tool.shared.transport import SerialThread


MODEL_NAME = "KA_RF_UNIT"
PORT_SUFFIX = "KaRF"


class KaRfUnitDriver(SerialThread):
    """独占串口并把原始帧转换为 KA_RF_UNIT 语义状态。"""

    status_signal = Signal(dict)
    internal_status_signal = Signal(dict)
    array_attenuation_signal = Signal(dict)
    result_signal = Signal(int, str)  # command, result_name
    report_rate_signal = Signal(float)

    def __init__(self, port_name: str, baudrate: int, parent=None) -> None:
        """创建绑定单个串口的 KA_RF_UNIT Driver。

        Args:
            port_name: pyserial 使用的串口名。
            baudrate: 串口波特率，默认 460800。
            parent: 可选 Qt 父对象。
        """
        super().__init__(port_name, baudrate, timeout=0.01, idle_ms=2, parent=parent)
        self.stream = FrameStreamParser()
        self._last_rate_emit = 0.0
        self._status_count = 0
        self._status_window_start = time.monotonic()
        self._last_status_time = 0.0

    @property
    def monitor_port(self) -> str:
        """返回报文监视器使用的 ``port`` 可读值。"""
        return f"{self.port_name}/{PORT_SUFFIX}"

    @Slot(bytes)
    def handle_bytes(self, data: bytes) -> None:
        """在串口线程中解析字节块并分派 KA_RF_UNIT 语义事件。

        Args:
            data: 本次从串口读出的原始字节块，可含分包、粘包或异常字节。

        线程：仅由 :class:`SerialThread` 所属后台串口线程调用。
        """
        for event in self.stream.feed(data):
            if event.kind != "frame":
                self.frame_signal.emit(
                    FrameRecord(
                        MODEL_NAME,
                        self.monitor_port,
                        "DROP",
                        "KA_RF_UNIT",
                        event.data,
                        event.message,
                        "ERROR",
                    )
                )
                continue
            parsed = event.parsed or {}
            command = parsed["command"]
            decoded = parsed["decoded"]
            self.frame_signal.emit(
                FrameRecord(
                    MODEL_NAME,
                    self.monitor_port,
                    "RX",
                    f"0x{command:02X} {parsed['name']}",
                    event.data,
                    protocol.describe(parsed, event.message),
                )
            )
            if command == protocol.CMD_STATUS_REPORT:
                self._emit_status(decoded)
            elif command == protocol.RES_INTERNAL_STATUS and "snapshot_version" in decoded:
                self.internal_status_signal.emit(decoded)
            elif command == protocol.RES_ARRAY_ATT and "snapshot_version" in decoded:
                self.array_attenuation_signal.emit(decoded)
            elif "result" in decoded:
                self.result_signal.emit(command, decoded["name"])

    def _emit_status(self, decoded: Dict[str, Any]) -> None:
        """更新 0x30 上报频率统计并发布结构化状态。

        Args:
            decoded: :func:`protocol.parse_response` 生成的 STATUS_REPORT 字段。
        """
        now = time.monotonic()
        self._status_count += 1
        elapsed = now - self._status_window_start
        if elapsed >= 1.0:
            rate = self._status_count / elapsed
            self._status_window_start = now
            self._status_count = 0
            if now - self._last_rate_emit >= 0.5:
                self._last_rate_emit = now
                self.report_rate_signal.emit(rate)
        self._last_status_time = now
        self.status_signal.emit(decoded)

    def _queue_frame(self, frame: bytes) -> bool:
        """将完整协议帧送入所属串口线程的发送队列。

        Args:
            frame: 已由协议层构建并完成校验的完整帧。

        Returns:
            已接受并记录 TX ``FrameRecord`` 时为 ``True``；串口未运行或队列拒绝时为 ``False``。
        """
        accepted = self.send_bytes(frame)
        if not accepted:
            self.log_signal.emit("发送失败，串口尚未打开")
            return False
        parsed, message = protocol.parse_response(frame)
        command = frame[4] if len(frame) > 4 else 0
        name = parsed["name"] if parsed is not None else f"UNKNOWN_0x{command:02X}"
        summary = protocol.describe(parsed, message)
        self.frame_signal.emit(
            FrameRecord(MODEL_NAME, self.monitor_port, "TX", f"0x{command:02X} {name}", frame, summary)
        )
        return True

    def set_conv_freq(
        self,
        rx_rf_mhz: int,
        rx_lo_mhz: int,
        tx_rf_mhz: int,
        tx_lo_mhz: int,
        rx_polar: int,
        tx_polar: int,
    ) -> bool:
        """发送 0x10 频点与极化配置。

        Args:
            rx_rf_mhz / rx_lo_mhz: 接收 RF/LO 频率，LO 必须匹配 RF 分段。
            tx_rf_mhz / tx_lo_mhz: 发射 RF/LO 频率，LO 必须匹配 RF 分段。
            rx_polar / tx_polar: 极化，0=左旋、1=右旋。

        Returns:
            帧是否成功进入发送队列。

        Raises:
            ValueError: 任一字段越界时由构帧器抛出。
        """
        return self._queue_frame(
            protocol.build_set_conv_freq(
                rx_rf_mhz,
                rx_lo_mhz,
                tx_rf_mhz,
                tx_lo_mhz,
                rx_polar,
                tx_polar,
            )
        )

    def set_conv_freq_free(
        self, rx_rf_mhz: int, rx_lo_mhz: int, tx_rf_mhz: int, tx_lo_mhz: int,
        rx_polar: int, tx_polar: int,
    ) -> bool:
        """发送 0x16 自由配置；LO=0 为 AUTO，非法参数抛出 ValueError，返回是否成功入队。"""
        return self._queue_frame(protocol.build_set_conv_freq_free(
            rx_rf_mhz, rx_lo_mhz, tx_rf_mhz, tx_lo_mhz, rx_polar, tx_polar))

    def set_conv_att(self, rx_att_db: float, tx_att_db: float) -> bool:
        """发送 0x11 变频衰减。

        Args:
            rx_att_db / tx_att_db: 衰减值，单位 dB，0.5 步进。

        Returns:
            帧是否成功进入发送队列。

        Raises:
            ValueError: 衰减越界时由构帧器抛出。
        """
        return self._queue_frame(protocol.build_set_conv_att(rx_att_db, tx_att_db))

    def set_tx_enabled(self, enabled: bool) -> bool:
        """发送 0x12 TX 阵列使能。"""
        return self._queue_frame(protocol.build_set_tx_en(enabled))

    def set_rx_enabled(self, enabled: bool) -> bool:
        """发送 0x13 RX 阵列使能。"""
        return self._queue_frame(protocol.build_set_rx_en(enabled))

    def set_beam(
        self,
        target_mask: int,
        tx_beam_h: int,
        tx_beam_v: int,
        rx_beam_h: int,
        rx_beam_v: int,
    ) -> bool:
        """发送 0x14 波束配置。

        Args:
            target_mask: bit0=TX、bit1=RX，至少 1 位。
            tx_beam_h / tx_beam_v / rx_beam_h / rx_beam_v: 原始波束码 0~4095。

        Returns:
            帧是否成功进入发送队列。

        Raises:
            ValueError: target_mask 或波束码越界时由构帧器抛出。
        """
        return self._queue_frame(
            protocol.build_set_beam(
                target_mask,
                tx_beam_h,
                tx_beam_v,
                rx_beam_h,
                rx_beam_v,
            )
        )

    def set_ext_ref(self, ref_mhz: int) -> bool:
        """发送 0x15 外参时钟配置。"""
        return self._queue_frame(protocol.build_set_ext_ref(ref_mhz))

    def set_report_hz(self, rate_hz: int) -> bool:
        """发送 0x20 主动上报频率配置。"""
        return self._queue_frame(protocol.build_set_report_hz(rate_hz))

    def stop(self, timeout_ms: int = 3000) -> bool:
        """停止串口线程，并在确认退出后丢弃未完成半帧。"""
        stopped = super().stop(timeout_ms)
        if stopped:
            self.stream.reset()
            self._status_count = 0
            self._last_status_time = 0.0
        return stopped

    def set_pa_enabled(self, enabled: bool) -> bool:
        """独立控制 TX 阵列推动 PA，返回入队结果。"""
        return self._queue_frame(protocol.build_internal_switch(protocol.CMD_SET_PA, enabled))

    def set_tx_if_enabled(self, enabled: bool) -> bool:
        """独立控制变频 TX IF，返回入队结果。"""
        return self._queue_frame(protocol.build_internal_switch(protocol.CMD_SET_TX_IF, enabled))

    def set_rx_if_enabled(self, enabled: bool) -> bool:
        """独立控制变频 RX IF，返回入队结果。"""
        return self._queue_frame(protocol.build_internal_switch(protocol.CMD_SET_RX_IF, enabled))

    def set_array_mask(self, target: int, tx_rows: int, tx_cols: int, rx_rows: int, rx_cols: int) -> bool:
        """发送独立芯片行列 mask，返回入队结果。"""
        return self._queue_frame(protocol.build_array_mask(target, tx_rows, tx_cols, rx_rows, rx_cols))

    def set_beam_angles(self, target: int, tx_theta: float, tx_phi: float, rx_theta: float, rx_phi: float) -> bool:
        """发送度值，由主控换算；不使用本机 raw 波束转换。"""
        return self._queue_frame(protocol.build_beam_angles(target, tx_theta, tx_phi, rx_theta, rx_phi))

    def query_internal_status(self) -> bool:
        """查询内部控制快照，不代表硬件回读。"""
        return self._queue_frame(protocol.build_internal_status_query())

    def set_array_attenuation(self, target: int, tx_common: float, tx_branch: float,
                              rx_common: float, rx_branch: float) -> bool:
        """设置阵列 TA/RA 干路和支路衰减，输入单位 dB。"""
        return self._queue_frame(protocol.build_array_attenuation(target, tx_common, tx_branch, rx_common, rx_branch))

    def set_conv_att_persist(self, rx_att_db: float, tx_att_db: float) -> bool:
        """提交0x48保存并应用双侧变频衰减；返回是否入队，不表示设备已保存。"""
        return self._queue_frame(protocol.build_set_conv_att_persist(rx_att_db, tx_att_db))

    def query_array_attenuation(self) -> bool:
        """查询阵列 BF 类型及最近衰减发送记录。"""
        return self._queue_frame(protocol.build_array_attenuation_query())


# 与目录名及其他设备 Driver 命名保持一致的简写。
DeviceDriver = KaRfUnitDriver
