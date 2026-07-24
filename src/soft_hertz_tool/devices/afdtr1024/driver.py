"""AFDT1024/AFDR1024 共用 Driver：传输、协议分派和语义化设备命令。"""

from __future__ import annotations

from functools import partial
from typing import Iterable, Optional, Union

from PySide6.QtCore import QTimer, Signal, Slot

from soft_hertz_tool.devices.afdtr1024 import protocol
from soft_hertz_tool.devices.afdtr1024.models import BeamSetting, DeviceVariant, SubarrayStatus
from soft_hertz_tool.devices.afdtr1024.stream import AFDTR1024StreamParser
from soft_hertz_tool.shared.observability import FrameRecord
from soft_hertz_tool.shared.transport import SerialThread


class AFDTR1024Driver(SerialThread):
    """一个串口总线上的 AFDT1024 或 AFDR1024 驱动。"""

    status_signal = Signal(dict)
    config_success_signal = Signal(str)

    def __init__(
        self,
        port_name: str,
        baudrate: int,
        variant: Union[DeviceVariant, str],
        parent=None,
    ):
        """初始化指定串口和 AFDT1024/AFDR1024 变体的驱动实例。"""
        super().__init__(port_name, baudrate, timeout=0.01, idle_ms=5, parent=parent)
        self.variant = DeviceVariant.coerce(variant)
        self.device_type = self.variant.value
        self.stream = AFDTR1024StreamParser()
        self._status_by_id: dict[int, SubarrayStatus] = {}
        self._schedule_generation = 0

    @property
    def endpoint(self) -> str:
        """返回用于日志和帧监视器的“串口/硬件型号”端点名称。"""
        return f"{self.port_name}/{self.variant.model_name}"

    def handle_bytes(self, data: bytes) -> None:
        """在串口线程拆分输入字节，并发布有效帧或丢弃诊断记录。"""
        for event in self.stream.feed(data):
            if event.is_frame:
                self._process_frame(event.raw)
                continue
            self.frame_signal.emit(
                FrameRecord(
                    self.variant.model_name,
                    self.endpoint,
                    "DROP",
                    self.variant.value,
                    event.raw,
                    event.reason,
                    "ERROR",
                )
            )
            self.log_signal.emit(f"✗ {event.reason}: {event.raw.hex().upper()}")

    def _process_frame(self, frame: bytes) -> None:
        """解析一帧协议数据，分派状态回读、波束回读或配置回显。"""
        parsed, message = protocol.parse_response(frame)
        addr = parsed.get("addr") if parsed else None
        command = protocol.command_name(addr) if addr is not None else self.variant.value
        self.frame_signal.emit(
            FrameRecord(
                self.variant.model_name,
                self.endpoint,
                "RX",
                command,
                frame,
                message if not parsed else f"OK device=0x{parsed['device_id']:02X}",
                "INFO" if parsed else "ERROR",
            )
        )
        frame_hex = frame.hex().upper()
        if not parsed:
            self.log_signal.emit(f"<<< 收到: {frame_hex}")
            self.log_signal.emit(f"✗ 解析失败: {message}")
            return

        addr = parsed["addr"]
        if addr in protocol.STATUS_RETURN_ADDRS:
            parser = (
                protocol.parse_status_response
                if addr == protocol.ADDR_STATUS_QUERY
                else protocol.parse_rx_status_response
            )
            info, status_message = parser(parsed["payload"])
            self._publish_status(parsed["device_id"], info, status_message, "状态")
            return

        if addr in protocol.BEAM_QUERY_RETURN_ADDRS:
            response_is_tx = addr == protocol.ADDR_TX_BEAM_QUERY
            info, status_message = protocol.parse_beam_query_response(
                parsed["payload"],
                is_tx=response_is_tx,
            )
            self._publish_status(parsed["device_id"], info, status_message, "波束参数")
            return

        self.log_signal.emit(f"<<< 收到: {frame_hex}")
        if addr in protocol.CONFIG_ECHO_ADDRS:
            name = protocol.command_name(addr)
            self.log_signal.emit(f"✓ {name}配置成功")
            self.config_success_signal.emit(name)

    def _publish_status(
        self,
        device_id: int,
        info: Optional[dict],
        message: str,
        label: str,
    ) -> None:
        """合并单个子阵的查询结果并发出面向 UI 的状态快照。"""
        if message != "OK" or not info:
            self.log_signal.emit(f"✗ {label}解析失败: {message}")
            return

        subarray_id = device_id & 0x7F
        status = self._status_by_id.setdefault(subarray_id, SubarrayStatus(device_id=device_id))
        status.device_id = device_id
        status.update(info)
        merged = status.as_dict()
        self.status_signal.emit(merged)

        detail = f"[ID=0x{subarray_id:02X}]"
        if "sys_vcc" in info:
            detail += f" 电压:{info['sys_vcc']:.1f}V 温度:{info['sys_temp']}°C"
        if "beam_v" in info:
            detail += (
                f" 极化:{'RHCP' if info['pol'] else 'LHCP'}"
                f" 使能:{'ON' if info['en_row'] else 'OFF'}"
                f" 频率:{info['freq_mhz']}MHz"
                f" BeamV:{info['beam_v']} BeamH:{info['beam_h']}"
            )
        self.log_signal.emit(detail)

    @Slot(bytes)
    def send_frame(self, frame: bytes) -> bool:
        """把完整帧加入共享串口线程的发送队列。"""

        frame = bytes(frame)
        queued = super().send_bytes(frame)
        if not queued:
            return False
        addr = frame[-2] if len(frame) >= 2 else 0
        self.log_signal.emit(f">>> 发送: {frame.hex().upper()}")
        self.frame_signal.emit(
            FrameRecord(
                self.variant.model_name,
                self.endpoint,
                "TX",
                protocol.command_name(addr),
                frame,
                "已加入发送队列",
            )
        )
        return True

    def _require_open(self) -> None:
        """确认串口线程已运行，否则抛出 ``ConnectionError``。"""
        if not self.running:
            raise ConnectionError(f"{self.variant.model_name} 串口未连接")

    def _send_required(self, frame: bytes) -> None:
        """发送必须成功的完整帧；未连接或入队失败时抛出 ``ConnectionError``。"""
        self._require_open()
        if not self.send_frame(frame):
            raise ConnectionError(f"{self.variant.model_name} 帧发送失败")

    def set_beam(
        self,
        device_id: int,
        frequency_mhz: float,
        theta: float,
        phi: float,
    ) -> BeamSetting:
        """设置目标子阵波束。

        Args:
            device_id: 目标 ID，可为广播 ID ``0``。
            frequency_mhz: 请求频率，单位 MHz。
            theta: 俯仰角，单位度。
            phi: 方位角，单位度。

        Returns:
            经协议频率网格量化后的实际设置。

        Raises:
            ValueError: 频率或角度参数不满足协议约束。
            ConnectionError: 串口未连接或帧未能入队。
        """
        setting = protocol.make_beam_setting(frequency_mhz, theta, phi, self.variant)
        self._send_required(protocol.build_beam_frame(device_id, setting, self.variant))
        return setting

    def set_array_enabled(self, device_id: int, enabled: bool) -> None:
        """设置 AFDT1024 或 AFDR1024 的目标阵列使能状态。"""
        self._send_required(protocol.build_enable_frame(device_id, enabled, self.variant))

    def set_polarization(self, device_id: int, polarization: int) -> None:
        """设置目标子阵极化；``0`` 为 LHCP，``1`` 为 RHCP。"""
        self._send_required(protocol.build_polarization_frame(device_id, polarization, self.variant))

    def set_pa_enabled(self, device_id: int, enabled: bool) -> None:
        """设置 AFDT1024 推动 PA；AFDR1024 调用时抛出 ``ValueError``。"""
        if not self.variant.is_tx:
            raise ValueError("AFDR1024 不支持 PA 使能")
        self._send_required(protocol.build_pa_enable_frame(device_id, enabled))

    def set_phase_calibration(self, device_id: int, phase_offset: int) -> None:
        """按当前硬件变体发送相位校准值，协议值被限制为 0~63。"""
        if self.variant.is_tx:
            frame = protocol.build_phase_cal_frame(device_id, phase_offset)
        else:
            frame = protocol.build_rx_phase_cal_frame(device_id, phase_offset)
        self._send_required(frame)

    def update_device_id(self, new_id: int) -> None:
        """ID 更新按受控协议使用公共 ID=0x00 发送。"""

        if not 1 <= int(new_id) <= 0x7F:
            raise ValueError("新子阵 ID 必须在 0x01~0x7F 范围内")
        self._send_required(protocol.build_id_update_frame(0, int(new_id)))

    def query_status(
        self,
        device_ids: Iterable[int],
        *,
        plus_0x80: bool = False,
        interval_ms: int = 50,
    ) -> int:
        """逐个 ID 发送查询 1/2；定时投递，避免阻塞 UI 线程。"""

        self._require_open()
        ids: list[int] = []
        for value in device_ids:
            subarray_id = int(value)
            if not 1 <= subarray_id <= 0x7F:
                raise ValueError("查询子阵 ID 必须在 0x01~0x7F 范围内")
            if subarray_id not in ids:
                ids.append(subarray_id)
        if not ids:
            raise ValueError("查询子阵 ID 列表不能为空")
        if interval_ms < 0:
            raise ValueError("查询间隔不能为负数")

        frames: list[bytes] = []
        for subarray_id in ids:
            # +0x80 是“仅本子阵”寻址位；状态缓存仍以低 7 位子阵号归并。
            device_id = (subarray_id + 0x80) & 0xFF if plus_0x80 else subarray_id
            frames.extend(protocol.build_query_frames(device_id, self.variant))

        generation = self._schedule_generation
        for index, frame in enumerate(frames):
            if index == 0:
                if not self.send_frame(frame):
                    raise ConnectionError(f"{self.variant.model_name} 查询发送失败")
                continue
            # 首帧即时验证发送链路，其余帧错开投递，避免 UI 调用一次性占满发送队列。
            QTimer.singleShot(
                index * interval_ms,
                partial(self._send_scheduled, frame, generation),
            )
        return len(ids)

    def _send_scheduled(self, frame: bytes, generation: int) -> None:
        """在代际仍有效且串口运行时发送延迟查询帧。"""

        # stop() 递增代际，使已登记的 QTimer 回调不会向已关闭串口发送数据。
        if generation == self._schedule_generation and self.running:
            self.send_frame(frame)

    def status_snapshot(self) -> dict[int, dict]:
        """返回按低 7 位子阵 ID 索引的状态副本，不暴露内部模型。"""
        return {subarray_id: status.as_dict() for subarray_id, status in self._status_by_id.items()}

    def stop(self, timeout_ms: int = 3000) -> bool:
        """取消待调度查询后停止串口线程，超时时返回 ``False``。"""
        self._schedule_generation += 1
        return super().stop(timeout_ms)


# 简短别名供 workspace 组装。
Driver = AFDTR1024Driver
