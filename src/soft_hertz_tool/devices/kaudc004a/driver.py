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
        """创建绑定单个串口的 KaUDC004A Driver。

        Args:
            port_name: pyserial 使用的串口名。
            baudrate: 串口波特率。
            parent: 可选 Qt 父对象。
        """
        super().__init__(port_name, baudrate, timeout=0.01, idle_ms=5, parent=parent)
        self.stream = KaUDCStreamParser()

    @property
    def monitor_port(self) -> str:
        """返回报文监视器使用的 ``port`` 可读值。

        Returns:
            ``串口名/KaUDC`` 连接标签；公开硬件型号仍由
            ``FrameRecord.model=KaUDC004A`` 单独提供。
        """
        return f"{self.port_name}/{PORT_SUFFIX}"

    @Slot(bytes)
    def handle_bytes(self, data: bytes) -> None:
        """接收串口线程字节并转换为 RX 或 DROP 事件。

        Args:
            data: 任意长度的串口读取块。

        状态:
            半帧保留在流解析器；异常字节产生 ``DROP``，完整候选帧继续交给协议校验。
        """
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
        """校验并解码一个完整候选帧，再发布监视和状态信号。

        Args:
            frame: 流解析器给出的 12 字节候选帧。

        状态:
            CRC、帧头或字段解析失败仍发布带诊断信息的 RX 记录；成功时发布结构化状态。
        """
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
        """将完整协议帧送入所属串口线程的发送队列。

        Args:
            frame: 已由协议层构建并完成校验的完整帧。

        Returns:
            已接受并记录 TX ``FrameRecord`` 时为 ``True``；串口未运行或队列拒绝时为 ``False``。
        """
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
        """发送复位命令。

        Returns:
            帧进入发送队列时为 ``True``，否则为 ``False``。
        """
        return self._queue_frame(protocol.build_reset_frame())

    def query_version(self) -> bool:
        """发送版本查询命令。

        Returns:
            帧进入发送队列时为 ``True``，否则为 ``False``。
        """
        return self._queue_frame(protocol.build_version_query_frame())

    def query_temperature(self) -> bool:
        """发送温度原始值查询命令。

        Returns:
            帧进入发送队列时为 ``True``，否则为 ``False``。
        """
        return self._queue_frame(protocol.build_temp_query_frame())

    def set_rx_lo(self, freq_mhz: int) -> bool:
        """设置接收本振频率。

        Args:
            freq_mhz: 接收本振频率，单位 MHz。

        Returns:
            帧进入发送队列时为 ``True``，否则为 ``False``。

        Raises:
            ValueError: 频率无法编码为协议无符号 16 位字段。
        """
        return self._queue_frame(protocol.build_rx_lo_frame(freq_mhz))

    def set_tx_lo(self, freq_mhz: int) -> bool:
        """设置发射本振频率。

        Args:
            freq_mhz: 发射本振频率，单位 MHz。

        Returns:
            帧进入发送队列时为 ``True``，否则为 ``False``。

        Raises:
            ValueError: 频率无法编码为协议无符号 16 位字段。
        """
        return self._queue_frame(protocol.build_tx_lo_frame(freq_mhz))

    def query_lo(self) -> bool:
        """发送收发本振与锁定状态查询命令。

        Returns:
            帧进入发送队列时为 ``True``，否则为 ``False``。
        """
        return self._queue_frame(protocol.build_lo_query_frame())

    def set_tx_attenuation(self, value: int) -> bool:
        """设置发射衰减。

        Args:
            value: 0 到 300 的协议整数，实际值为 ``value / 10`` dB。

        Returns:
            帧进入发送队列时为 ``True``，否则为 ``False``。

        Raises:
            ValueError: 衰减不在协议允许的 ``0.0..30.0 dB`` 范围。
        """
        return self._queue_frame(protocol.build_tx_att_frame(value))

    def set_rx_attenuation(self, value: int) -> bool:
        """设置接收衰减。

        Args:
            value: 0 到 300 的协议整数，实际值为 ``value / 10`` dB。

        Returns:
            帧进入发送队列时为 ``True``，否则为 ``False``。

        Raises:
            ValueError: 衰减不在协议允许的 ``0.0..30.0 dB`` 范围。
        """
        return self._queue_frame(protocol.build_rx_att_frame(value))

    def query_attenuation(self) -> bool:
        """发送收发衰减查询命令。

        Returns:
            帧进入发送队列时为 ``True``，否则为 ``False``。
        """
        return self._queue_frame(protocol.build_att_query_frame())

    def stop(self, timeout_ms: int = 3000) -> bool:
        """停止串口线程，并在确认退出后丢弃未完成半帧。

        Args:
            timeout_ms: 等待串口线程退出的最长时间，单位毫秒。

        Returns:
            串口线程已停止时为 ``True``；超时时为 ``False``，此时保留流状态供后续停止重试。
        """
        stopped = super().stop(timeout_ms)
        if stopped:
            self.stream.reset()
        return stopped


# 与目录名及其他设备 Driver 命名保持一致的简写。
DeviceDriver = KaUDCDriver
