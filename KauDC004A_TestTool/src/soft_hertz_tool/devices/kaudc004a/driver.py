"""KaUDC004A 串口 Driver。"""

from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import Signal, Slot

from soft_hertz_tool.shared.observability.frame_record import FrameRecord
from soft_hertz_tool.shared.transport.serial_thread import SerialThread

from . import protocol
from .stream import KaUDCStreamParser


MODEL_NAME = "KaUDC004A"
PORT_SUFFIX = "KaUDC"


class KaUDCDriver(SerialThread):
    """独占串口并把原始帧转换为 KaUDC004A 语义状态。"""

    status_signal = Signal(dict)
    response_signal = Signal(str, str)

    def __init__(self, port_name: str, baudrate: int, parent=None) -> None:
        super().__init__(port_name, baudrate, timeout=0.01, idle_ms=5, parent=parent)
        self.stream = KaUDCStreamParser()

    @property
    def monitor_port(self) -> str:
        return f"{self.port_name}/{PORT_SUFFIX}"

    @Slot(bytes)
    def handle_bytes(self, data: bytes) -> None:
        for event in self.stream.feed(data):
            if not event.is_frame:
                self.frame_signal.emit(
                    FrameRecord(
                        MODEL_NAME,
                        self.monitor_port,
                        "DROP",
                        "KaUDC",
                        event.raw,
                        event.reason,
                        "ERROR",
                    )
                )
                continue
            self._process_frame(event.raw)

    def _process_frame(self, frame: bytes) -> None:
        payload, message = protocol.parse_response(frame)
        command = protocol.command_name(payload[0]) if payload else "KaUDC"
        self.frame_signal.emit(
            FrameRecord(
                MODEL_NAME,
                self.monitor_port,
                "RX",
                command,
                frame,
                message,
                "INFO" if payload else "ERROR",
            )
        )
        if payload is None:
            self.log_signal.emit(f"<<< 收到: {frame.hex().upper()}")
            self.log_signal.emit(f"✗ 解析失败: {message}")
            return

        try:
            status = protocol.parse_response_data(payload)
        except ValueError as exc:
            self.log_signal.emit(f"✗ 字段解析失败: {exc}")
            return

        self.log_signal.emit(f"<<< 收到: {frame.hex().upper()}")
        self.status_signal.emit(status)
        self._emit_legacy_response(status)

    def _emit_legacy_response(self, status: Dict[str, Any]) -> None:
        """保留旧页面的响应信号文本，供过渡期外部调用者使用。"""
        command = status["cmd"]
        if command == protocol.CMD_RESET:
            text = "复位完成" if status.get("status") == "reset_complete" else "复位失败"
            self.response_signal.emit("复位", text)
        elif command == protocol.CMD_VERSION:
            self.response_signal.emit("版本回读", f"0x{status['version']:02X}")
        elif command == protocol.CMD_LO_QUERY:
            self.response_signal.emit(
                "本振查询",
                f"TxLO={status['tx_lo']}, RxLO={status['rx_lo']}, LOCK={status['lock_status']:08b}",
            )
        elif command == protocol.CMD_ATT_QUERY:
            self.response_signal.emit(
                "衰减查询",
                (
                    f"TxAtt={status['tx_att']}({status['tx_att_db']:.1f}dB), "
                    f"RxAtt={status['rx_att']}({status['rx_att_db']:.1f}dB)"
                ),
            )

    def _queue_frame(self, frame: bytes) -> bool:
        accepted = self.send_bytes(frame)
        command = protocol.command_name(frame[4]) if len(frame) > 4 else "KaUDC"
        if not accepted:
            self.log_signal.emit(f"发送失败，串口尚未打开: {command}")
            return False

        self.log_signal.emit(f">>> 发送: {frame.hex().upper()}")
        self.frame_signal.emit(
            FrameRecord(MODEL_NAME, self.monitor_port, "TX", command, frame, "已排队")
        )
        return True

    def send_reset(self) -> bool:
        return self._queue_frame(protocol.build_reset_frame())

    def query_version(self) -> bool:
        return self._queue_frame(protocol.build_version_query_frame())

    def query_temperature(self) -> bool:
        return self._queue_frame(protocol.build_temp_query_frame())

    def set_rx_lo(self, freq_mhz: int) -> bool:
        return self._queue_frame(protocol.build_rx_lo_frame(freq_mhz))

    def set_tx_lo(self, freq_mhz: int) -> bool:
        return self._queue_frame(protocol.build_tx_lo_frame(freq_mhz))

    def query_lo(self) -> bool:
        return self._queue_frame(protocol.build_lo_query_frame())

    def set_tx_attenuation(self, value: int) -> bool:
        return self._queue_frame(protocol.build_tx_att_frame(value))

    def set_rx_attenuation(self, value: int) -> bool:
        return self._queue_frame(protocol.build_rx_att_frame(value))

    def query_attenuation(self) -> bool:
        return self._queue_frame(protocol.build_att_query_frame())

    def stop(self, timeout_ms: int = 3000) -> bool:
        stopped = super().stop(timeout_ms)
        if stopped:
            self.stream.reset()
        return stopped


# 与目录名及其他设备 Driver 命名保持一致的简写。
DeviceDriver = KaUDCDriver
