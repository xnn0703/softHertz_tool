"""KuR512B 设备 Driver：传输、协议分派、主动查询循环与 CSV 落盘。"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from PySide6.QtCore import Signal, Slot

from soft_hertz_tool.devices.kur512 import protocol
from soft_hertz_tool.devices.kur512.models import BeamSetting, SubarrayStatus
from soft_hertz_tool.devices.kur512.recorder import StatusRecorder
from soft_hertz_tool.devices.kur512.stream import KUR512StreamParser
from soft_hertz_tool.shared.observability import FrameRecord
from soft_hertz_tool.shared.transport import SerialThread


MIN_QUERY_HZ = 0
MAX_QUERY_HZ = 100
DEFAULT_QUERY_HZ = 1
MIN_FRAME_GAP_SECONDS = 0.003  # 受控原件建议 ≥3 ms
ACTIVE_WINDOW_SECONDS = 10.0  # 实际达成频率的滑动窗口长度


class KUR512Driver(SerialThread):
    """KuR512B 串口 Driver；管理主动查询循环与每个子阵的 CSV 记录线程。"""

    status_signal = Signal(dict)

    def __init__(
        self,
        port_name: str,
        baudrate: int,
        log_root: Optional[Path] = None,
        parent=None,
    ):
        """初始化串口参数和主动查询状态机。

        Args:
            port_name: pyserial 可打开的端口名。
            baudrate: 串口波特率（默认 460800）。
            log_root: 状态 CSV 根目录；为 ``None`` 时由 Panel 提供。
            parent: 可选 Qt 父对象。
        """
        super().__init__(port_name, baudrate, timeout=0.005, idle_ms=2, parent=parent)
        self.stream = KUR512StreamParser()
        self._status_by_id: dict[int, SubarrayStatus] = {}
        self._session_lock = threading.RLock()

        self._query_hz: int = 0
        self._query_interval: float = 0.0
        self._next_query_ns: int = 0
        self._last_query_ns: int = 0
        self._round_index: int = 0
        self._round_ids: List[int] = []
        self._last_emit_ns: int = 0

        self._achieved_window_start_ns: int = 0
        self._achieved_window_count: int = 0
        self._achieved_hz: float = 0.0

        self._log_root: Optional[Path] = log_root
        self._recorders: dict[int, StatusRecorder] = {}

    @property
    def endpoint(self) -> str:
        """返回监视器使用的端口/型号端点名。"""
        return f"{self.port_name}/KuR512"

    @property
    def achieved_hz(self) -> float:
        """最近 10 s 滑动窗口的实际达成查询频率（Hz）。"""
        with self._session_lock:
            return self._achieved_hz

    def set_log_root(self, root: Optional[Path]) -> None:
        """更新落盘根目录；下次 start_polling 时按新目录创建子目录。"""
        with self._session_lock:
            self._log_root = root

    def set_round_ids(self, device_ids: Iterable[int]) -> None:
        """更新轮询的子阵 ID 列表；按去重 + 排序后的顺序循环。"""
        ids: List[int] = []
        for value in device_ids:
            sub_id = int(value)
            if not 1 <= sub_id <= 0x7F:
                raise ValueError("子阵 ID 必须在 0x01~0x7F 范围内")
            if sub_id not in ids:
                ids.append(sub_id)
        ids.sort()
        with self._session_lock:
            self._round_ids = ids
            self._round_index = 0

    def set_query_hz(self, rate_hz: int) -> bool:
        """设置主动查询频率；``0`` 表示停止。

        Args:
            rate_hz: 0..100 Hz；越界抛 ``ValueError``。

        Returns:
            状态是否变化（True 表示从停止改为运行或频率改变）。
        """
        rate_hz = int(rate_hz)
        if not MIN_QUERY_HZ <= rate_hz <= MAX_QUERY_HZ:
            raise ValueError(f"查询频率必须在 {MIN_QUERY_HZ}~{MAX_QUERY_HZ} Hz 范围内")
        with self._session_lock:
            changed = (rate_hz != self._query_hz)
            self._query_hz = rate_hz
            self._query_interval = (1.0 / rate_hz) if rate_hz > 0 else 0.0
            self._next_query_ns = time.monotonic_ns() if rate_hz > 0 else 0
            self._round_index = 0
            self._achieved_window_start_ns = 0
            self._achieved_window_count = 0
            self._achieved_hz = 0.0
            return changed

    def active_ids(self) -> List[int]:
        """返回当前轮询列表的快照，便于面板显示。"""
        with self._session_lock:
            return list(self._round_ids)

    def _ensure_recorder(self, device_id: int) -> Optional[StatusRecorder]:
        """懒创建对应 device_id 的 CSV 落盘线程。"""
        with self._session_lock:
            if self._log_root is None:
                return None
            recorder = self._recorders.get(device_id)
            if recorder is not None:
                return recorder
            recorder = StatusRecorder(self._log_root, device_id)
            self._recorders[device_id] = recorder
            return recorder

    def start_polling(self, device_ids: Iterable[int], freq_hz: int) -> None:
        """启动主动轮询；建立轮询列表、创建所有 recorders、设置频率。"""
        self.set_round_ids(device_ids)
        ids = self.active_ids()
        with self._session_lock:
            if self._log_root is not None:
                for sub_id in ids:
                    self._ensure_recorder(sub_id)
            self.set_query_hz(freq_hz)

    def stop_polling(self, timeout: float = 1.0) -> None:
        """停止主动轮询并有界等待所有 recorders 收尾。"""
        with self._session_lock:
            self._query_hz = 0
            self._query_interval = 0.0
            self._next_query_ns = 0
            self._round_index = 0
            recorders = list(self._recorders.values())
            self._recorders.clear()
        for recorder in recorders:
            recorder.close(timeout=timeout)

    def _next_due_device_id(self) -> Optional[int]:
        """根据 ``_query_interval`` 和上次发送时间决定是否本轮需要查询。"""
        if self._query_interval <= 0:
            return None
        if not self._round_ids:
            return None
        now = time.monotonic_ns()
        if now < self._next_query_ns:
            return None
        if self._last_query_ns and (now - self._last_query_ns) < MIN_FRAME_GAP_SECONDS * 1e9:
            return None
        sub_id = self._round_ids[self._round_index % len(self._round_ids)]
        self._round_index += 1
        self._last_query_ns = now
        return sub_id

    def _flush_tx(self) -> None:
        """串口线程：优先写普通业务帧；空闲时按主动查询节奏发送 0x9C。"""
        # 主动查询：业务队列为空 + 到下一拍截止时主动入队 0x9C
        with self._session_lock:
            if self._query_interval > 0 and self._round_ids and self._tx_queue.empty():
                target = self._next_due_device_id()
                if target is not None:
                    frame = protocol.build_status_query_frame(target)
                    self._next_query_ns = time.monotonic_ns() + int(
                        self._query_interval / len(self._round_ids) * 1e9
                    )
                    self.frame_signal.emit(
                        FrameRecord(
                            "KuR512",
                            self.endpoint,
                            "TX",
                            protocol.command_name(protocol.ADDR_STATUS_QUERY),
                            frame,
                            f"主动查询 sub_id=0x{target:02X}",
                        )
                    )
                    self._tx_queue.put_nowait(frame)
        super()._flush_tx()

    def _record_achieved(self) -> None:
        """更新 10 s 滑动窗口的实际达成频率。"""
        now = time.monotonic_ns()
        with self._session_lock:
            if self._achieved_window_start_ns == 0 or (now - self._achieved_window_start_ns) >= ACTIVE_WINDOW_SECONDS * 1e9:
                if self._achieved_window_start_ns:
                    elapsed = (now - self._achieved_window_start_ns) / 1e9
                    self._achieved_hz = self._achieved_window_count / max(elapsed, 1e-6)
                self._achieved_window_start_ns = now
                self._achieved_window_count = 0

    @Slot(bytes)
    def handle_bytes(self, data: bytes) -> None:
        """解析输入字节，发布 status_signal 并异步落盘 CSV。"""
        for event in self.stream.feed(data):
            if not event.is_frame:
                self.frame_signal.emit(
                    FrameRecord(
                        "KuR512",
                        self.endpoint,
                        "DROP",
                        "KuR512",
                        event.raw,
                        event.reason,
                        "ERROR",
                    )
                )
                self.log_signal.emit(f"✗ {event.reason}: {event.raw.hex().upper()}")
                continue
            self._process_frame(event.raw)

    def _process_frame(self, frame: bytes) -> None:
        """解析一帧协议数据；按地址分派到状态查询或配置回显。

        设备实测：状态响应可能是 4 字节载荷（无尾部 0x9C）；受控原件 V3.1 PDF
        写的是 5 字节（含尾部 0x9C）。两种格式都按状态查询处理。
        """
        parsed, message = protocol.parse_response(frame)
        addr = parsed.get("addr") if parsed else None
        command = protocol.command_name(addr) if addr is not None else "KuR512"
        self.frame_signal.emit(
            FrameRecord(
                "KuR512",
                self.endpoint,
                "RX",
                command,
                frame,
                message if not parsed else f"OK device=0x{parsed['device_id']:02X}",
                "INFO" if parsed else "ERROR",
            )
        )
        if not parsed:
            self.log_signal.emit(f"✗ 解析失败: {message}")
            return

        if addr == protocol.ADDR_STATUS_QUERY:
            info, status_message = protocol.parse_status_response(parsed["payload"])
            if status_message != "OK" or info is None:
                self.log_signal.emit(f"✗ 状态解析失败: {status_message}")
                return
            self._handle_status_response(parsed["device_id"], info, frame)
            return

        # 实测兼容：状态响应可能不带尾部 0x9C，载荷 4 字节且未被识别为配置回显时尝试状态解析
        raw_data = frame[5:-1]
        if (
            len(raw_data) == 4
            and addr not in protocol.CONFIG_ECHO_ADDRS
            and addr != protocol.ADDR_ID_UPDATE
        ):
            info, status_message = protocol.parse_status_response(raw_data)
            if status_message == "OK" and info is not None:
                self._handle_status_response(parsed["device_id"], info, frame)
                return

        if addr in protocol.CONFIG_ECHO_ADDRS:
            self.log_signal.emit(f"<<< 收到: {frame.hex().upper()}")
            self.log_signal.emit(f"✓ {protocol.command_name(addr)}配置成功")

    def _handle_status_response(self, device_id: int, info: dict, raw: bytes) -> None:
        """聚合状态：状态信号 ≤10 Hz + 异步落盘 + 速率统计。"""
        now_ns = time.monotonic_ns()
        subarray_id = device_id & 0x7F
        info_with_meta = {
            **info,
            "last_ts_ns": now_ns,
            "last_raw_hex": raw.hex().upper(),
            "device_id": subarray_id,
        }

        status = self._status_by_id.setdefault(subarray_id, SubarrayStatus(device_id=subarray_id))
        status.update(info_with_meta)
        self._status_by_id[subarray_id] = status

        recorder = self._ensure_recorder(subarray_id)
        if recorder is not None:
            recorder.append(
                subarray_id,
                info,
                raw.hex().upper(),
                ts=datetime.now().astimezone(),
            )

        with self._session_lock:
            if (now_ns - self._last_emit_ns) >= 100_000_000:
                self._last_emit_ns = now_ns
                should_emit = True
            else:
                should_emit = False
        if should_emit:
            self.status_signal.emit(status.as_dict())

        self._achieved_window_count += 1
        self._record_achieved()

    def status_snapshot(self) -> dict[int, dict]:
        """返回按子阵 ID 索引的最新状态字典副本。"""
        with self._session_lock:
            return {
                sub_id: status.as_dict()
                for sub_id, status in self._status_by_id.items()
            }

    def _require_open(self) -> None:
        """确认串口线程已运行；否则抛出 ``ConnectionError``。"""
        if not self.running:
            raise ConnectionError("KuR512 串口未连接")

    def _send_required(self, frame: bytes) -> None:
        """发送必须成功的完整帧；未连接或入队失败时抛出。"""
        self._require_open()
        addr = frame[-2] if len(frame) >= 2 else 0
        self.log_signal.emit(f">>> 发送: {frame.hex().upper()}")
        self.frame_signal.emit(
            FrameRecord(
                "KuR512",
                self.endpoint,
                "TX",
                protocol.command_name(addr),
                frame,
                "已加入发送队列",
            )
        )
        if not self.send_bytes(frame):
            raise ConnectionError("KuR512 帧发送失败")

    # 业务接口
    def set_beam(self, device_id: int, setting: BeamSetting) -> None:
        """下发 KuR512B 波束（含 POL）配置。"""
        self._send_required(protocol.build_beam_frame(device_id, setting))

    def set_array_enabled(self, device_id: int, enabled: bool) -> None:
        """下发阵列使能命令。"""
        self._send_required(protocol.build_enable_frame(device_id, enabled))

    def set_phase_calibration(self, device_id: int, phase_offset: int) -> None:
        """下发整板相位校准；相位值限制为 0..63。"""
        self._send_required(protocol.build_phase_cal_frame(device_id, phase_offset))

    def update_device_id(self, new_id: int) -> None:
        """按公共 ID 0x00 下发 ID 更新命令。"""
        if not 1 <= int(new_id) <= 0x7F:
            raise ValueError("新子阵 ID 必须在 0x01~0x7F 范围内")
        self._send_required(protocol.build_id_update_frame(0, int(new_id)))

    def query_status(self, device_ids: Iterable[int]) -> int:
        """非主动轮询路径：按列表发送一次 0x9C，返回实际发送的 ID 数。"""
        self._require_open()
        ids: List[int] = []
        for value in device_ids:
            sub_id = int(value)
            if not 1 <= sub_id <= 0x7F:
                raise ValueError("查询子阵 ID 必须在 0x01~0x7F 范围内")
            if sub_id not in ids:
                ids.append(sub_id)
        if not ids:
            raise ValueError("查询子阵 ID 列表不能为空")
        for sub_id in ids:
            self._send_required(protocol.build_status_query_frame(sub_id))
        return len(ids)

    def on_loop_stopped(self) -> None:
        """串口循环退出时收尾 recorders。"""
        self.stop_polling(timeout=0.5)

    def stop(self, timeout_ms: int = 3000) -> bool:
        """请求串口线程退出并等待 recorders 关闭。"""
        stopped = super().stop(timeout_ms)
        with self._session_lock:
            recorders = list(self._recorders.values())
            self._recorders.clear()
        for recorder in recorders:
            recorder.close(0.5)
        return stopped


__all__ = [
    "ACTIVE_WINDOW_SECONDS",
    "DEFAULT_QUERY_HZ",
    "KUR512Driver",
    "MAX_QUERY_HZ",
    "MIN_FRAME_GAP_SECONDS",
    "MIN_QUERY_HZ",
]
