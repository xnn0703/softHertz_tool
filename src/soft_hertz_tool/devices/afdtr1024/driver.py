"""AFDT1024/AFDR1024 共用 Driver：传输、协议分派和语义化设备命令。"""

from __future__ import annotations

from functools import partial
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import threading
import math
import time
import uuid
from typing import Iterable, Optional, Union

from PySide6.QtCore import QStandardPaths, QTimer, Signal, Slot

from soft_hertz_tool.devices.afdtr1024 import protocol
from soft_hertz_tool.devices.afdtr1024.models import BeamSetting, DeviceVariant, SubarrayStatus
from soft_hertz_tool.devices.afdtr1024.stream import AFDTR1024StreamParser
from soft_hertz_tool.shared.observability import FrameRecord
from soft_hertz_tool.shared.transport import SerialThread
from soft_hertz_tool.identity import default_log_directory
from soft_hertz_tool.devices.afdtr1024.traffic import TrafficConfig, TrafficEngine
from soft_hertz_tool.devices.afdtr1024.traffic_recorder import TrafficRecorder


class AFDTR1024Driver(SerialThread):
    """一个串口总线上的 AFDT1024 或 AFDR1024 驱动。"""

    status_signal = Signal(dict)
    config_success_signal = Signal(str)
    traffic_signal = Signal(dict)

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
        self._traffic_lock = threading.RLock()
        self._traffic_owned = False
        self._normal_writing = False
        self._traffic_request = None
        self._traffic_cancel = threading.Event()
        self._traffic_engine = None
        self._traffic_recorder = None
        self._traffic_last_emit_ns = 0
        self._traffic_run_id = ""
        self._traffic_read_ns = 0
        self._traffic_snapshot: dict = {}

    def traffic_snapshot(self) -> dict:
        """返回最近一次不可变发布快照，供确认断开后保留导出入口。"""
        with self._traffic_lock:
            return dict(self._traffic_snapshot)

    def start_traffic(self, config: TrafficConfig, frequency_mhz: float, theta: float,
                      phi: float, *, directory: Optional[Path] = None) -> str:
        """非阻塞取得空闲发送队列所有权，冻结配置；返回本次运行 ID。"""
        config.validate()
        if not all(math.isfinite(v) for v in (frequency_mhz, theta, phi)):
            raise ValueError("波束参数必须为有限数值")
        setting = protocol.make_beam_setting(frequency_mhz, theta, phi, self.variant)
        beam_id = 0 if config.beam_mode == "broadcast" else config.target_id
        beam = protocol.build_beam_frame(beam_id, setting, self.variant)
        with self._traffic_lock:
            self._require_open()
            if self._traffic_owned or self._normal_writing or not self._tx_queue.empty():
                raise ConnectionError("串口发送尚未空闲或客户流量正在运行，请稍后重试")
            self._traffic_owned = True
            self._schedule_generation += 1
            self._traffic_cancel.clear()
            # 新运行尚在准备记录目录时，串口线程不得看到上轮已停止的状态机并误释放所有权。
            self._traffic_engine = None
            self._traffic_recorder = None
            self._traffic_request = None
        run_id = uuid.uuid4().hex
        recorder = None
        try:
            if directory is None:
                docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
                directory = default_log_directory(Path(docs or str(Path.home() / "Documents"))) / "traffic"
            metadata = {"run_id": run_id, "generation": self._schedule_generation,
                        "model": self.variant.model_name, "port": self.port_name, "baudrate": self.baudrate,
                        "serial_format": "8N1", "wall_time": datetime.now().astimezone().isoformat(),
                        "clock_origin_ns": time.monotonic_ns(), "config": asdict(config),
                        "timing_contract": "write 起止为主机调用时间；线路间隔未测；回复延迟为完整解析减 write 返回",
                        "association_limit": "协议无事务号，无法严格区分同指令旧回复；原帧回显也无法排除本地回环"}
            recorder = TrafficRecorder(Path(directory) / run_id, metadata)
            with self._traffic_lock:
                if not self.running or self._stop_event.is_set():
                    raise ConnectionError("串口已停止，客户流量未开始")
                self._traffic_run_id = run_id
                self._traffic_recorder = recorder
                self._traffic_engine = None
                self._traffic_request = (config, beam)
                self._traffic_last_emit_ns = 0
                self._traffic_snapshot = {}
            return run_id
        except Exception:
            if recorder is not None:
                recorder.finish({"reason": "start_failed"})
                recorder.close(0.1)
            with self._traffic_lock:
                self._traffic_owned = False
            raise

    def stop_traffic(self) -> None:
        """请求所属线程停止，不在 UI 线程修改状态机或关闭串口。"""
        self._traffic_cancel.set()

    @Slot(bytes)
    def send_bytes(self, frame: bytes) -> bool:
        """运行期间从 Driver 边界拒绝所有普通业务发送。"""
        with self._traffic_lock:
            if self._traffic_owned:
                self.log_signal.emit("客户流量模拟独占串口，普通命令未发送")
                return False
            return super().send_bytes(frame)

    def _flush_tx(self) -> None:
        """串口线程执行独占调度，每轮最多一次 write，然后返回接收循环。"""
        with self._traffic_lock:
            owned = self._traffic_owned
            if not owned:
                self._normal_writing = True
            request, self._traffic_request = self._traffic_request, None
        if not owned:
            try:
                super()._flush_tx()
            finally:
                with self._traffic_lock:
                    self._normal_writing = False
            return
        recorder = self._traffic_recorder
        if recorder is None:
            return
        now = time.monotonic_ns()
        if request is not None:
            config, beam = request
            self._traffic_engine = TrafficEngine(config, self.variant, beam, now, recorder.record)
        engine = self._traffic_engine
        if engine is None:
            return
        if self._traffic_cancel.is_set() or self._stop_event.is_set():
            engine.stop("cancelled", now)
        if recorder.error:
            engine.stop("record_failure", now)
        batch = engine.poll(now)
        if batch is not None:
            # 停止可在 poll 后到达；未进入 write 的批次不再投递。
            if self._traffic_cancel.is_set() or self._stop_event.is_set():
                engine.stop("cancelled", time.monotonic_ns())
            else:
                result = self.write_observed(batch.raw)
                engine.written(batch, *result)
                for frame in batch.frames:
                    self.frame_signal.emit(FrameRecord(
                        self.variant.model_name, self.endpoint, "TX", protocol.command_name(frame[-2]), frame,
                        f"run={self._traffic_run_id} batch={batch.sequence} write={result[2]}/{len(batch.raw)} "
                        f"start_ns={result[0]} return_ns={result[1]} {result[3]}",
                        "ERROR" if result[3] else "INFO"))
        self._publish_traffic(time.monotonic_ns())

    def _publish_traffic(self, now: int) -> None:
        """最多 10 Hz 发布快照；后台记录关闭后释放发送所有权。"""
        engine, recorder = self._traffic_engine, self._traffic_recorder
        if engine is None or recorder is None:
            return
        if not engine.active:
            recorder.finish(engine.snapshot(now))
        finished = not engine.active and recorder.finished
        if finished or now - self._traffic_last_emit_ns >= 100_000_000:
            self._traffic_last_emit_ns = now
            snapshot = {**engine.snapshot(now), **recorder.evidence(),
                        "run_id": self._traffic_run_id, "active": not finished}
            with self._traffic_lock:
                self._traffic_snapshot = snapshot
            self.traffic_signal.emit(snapshot)
        if finished:
            with self._traffic_lock:
                self._traffic_owned = False

    def idle_wait_seconds(self) -> float:
        """按最近截止时刻缩短空闲等待，不使用 UI 定时器发送。"""
        engine = self._traffic_engine
        if self._traffic_owned and engine is not None and engine.active:
            due = min(engine.due_ns, engine.end_ns)
            return min(0.001, max(0.0001, (due - time.monotonic_ns()) / 1e9))
        return super().idle_wait_seconds()

    def on_loop_stopped(self) -> None:
        """断连也取消运行并有界等待记录线程收尾。"""
        engine, recorder = self._traffic_engine, self._traffic_recorder
        now = time.monotonic_ns()
        if engine is not None:
            engine.stop("disconnected", now)
        if recorder is not None:
            recorder.finish(engine.snapshot(now) if engine else {"reason": "cancelled_before_start"})
            if not recorder.close(1.0):
                self.log_signal.emit("客户流量记录仍在收尾，记录未完成")
        self._publish_traffic(now)

    @property
    def endpoint(self) -> str:
        """返回用于日志和帧监视器的“串口/硬件型号”端点名称。"""
        return f"{self.port_name}/{self.variant.model_name}"

    def handle_bytes(self, data: bytes) -> None:
        """在串口线程拆分输入字节，并发布有效帧或丢弃诊断记录。"""
        self._traffic_read_ns = time.monotonic_ns()
        if self._traffic_owned and self._traffic_engine is not None and self._traffic_engine.active:
            self._traffic_engine.record({"event": "read", "read_ns": self._traffic_read_ns, "bytes": len(data)})
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
            if self._traffic_owned and self._traffic_engine is not None and self._traffic_engine.active:
                self._traffic_engine.dropped(event.reason, time.monotonic_ns())
            self.log_signal.emit(f"✗ {event.reason}: {event.raw.hex().upper()}")

    def _process_frame(self, frame: bytes) -> None:
        """解析一帧协议数据，分派状态回读、波束回读或配置回显。"""
        parsed, message = protocol.parse_response(frame)
        if self._traffic_owned and self._traffic_engine is not None and self._traffic_engine.active:
            self._traffic_engine.received(frame, self._traffic_read_ns, time.monotonic_ns())
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
        if addr == protocol.ADDR_RX_ALIGNMENT_QUERY and not self.variant.is_tx:
            info, status_message = protocol.parse_rx_alignment_response(parsed["payload"])
            self._publish_status(parsed["device_id"], info, status_message, "校准结果")
            return
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

        if self._traffic_owned:
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
        if "align_link_id" in info:
            detail += " 校准结果 " + " ".join(f"{key[6:]}={value}" for key, value in info.items())
        self.log_signal.emit(detail)

    @Slot(bytes)
    def send_frame(self, frame: bytes) -> bool:
        """把完整帧加入共享串口线程的发送队列。"""

        frame = bytes(frame)
        queued = self.send_bytes(frame)
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
        """逐个 ID 查询状态、波束及 RX 校准结果；定时投递避免阻塞 UI。"""

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
            if not self.variant.is_tx:
                frames.append(protocol.build_rx_alignment_query_frame(device_id))

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
        with self._traffic_lock:
            if generation == self._schedule_generation and self.running:
                self.send_frame(frame)

    def status_snapshot(self) -> dict[int, dict]:
        """返回按低 7 位子阵 ID 索引的状态副本，不暴露内部模型。"""
        return {subarray_id: status.as_dict() for subarray_id, status in self._status_by_id.items()}

    def stop(self, timeout_ms: int = 3000) -> bool:
        """取消待调度查询后停止串口线程，超时时返回 ``False``。"""
        self._schedule_generation += 1
        self.stop_traffic()
        stopped = super().stop(timeout_ms)
        recorder = self._traffic_recorder
        if recorder is not None and not recorder.finished:
            recorder.finish({"reason": "disconnected"})
            return stopped and recorder.close(0.1)
        return stopped


# 简短别名供 workspace 组装。
Driver = AFDTR1024Driver
