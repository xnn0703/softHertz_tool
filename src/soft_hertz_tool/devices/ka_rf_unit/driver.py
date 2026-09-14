"""KA_RF_UNIT 串口 Driver。"""

from __future__ import annotations

import time
import queue
import threading
from typing import Any, Dict, Optional

from PySide6.QtCore import Signal, Slot

from soft_hertz_tool.devices.ka_rf_unit import protocol
from soft_hertz_tool.devices.ka_rf_unit.ota_traffic import OtaConfig, OtaTrafficEngine
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
    # OTA 客户控制器专用信号（V0.3.0）。
    ota_busy_signal = Signal(bool)
    ota_status_signal = Signal(dict)
    ota_event_signal = Signal(str, object)
    ota_progress_signal = Signal(int, int)

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
        # OTA 状态（与 start_traffic 所有权转交模式对称）。
        self._ota_engine: Optional[OtaTrafficEngine] = None
        self._session_lock = threading.RLock()
        self._ota_config: Optional[OtaConfig] = None
        self._ota_reserved = False
        self._ota_cancel = threading.Event()
        self._pending_command: Optional[int] = None
        self._pending_deadline = 0.0
        self._query_interval = 1.0
        self._next_query = 0.0
        self._last_was_query = False

    @property
    def monitor_port(self) -> str:
        """返回报文监视器使用的 ``port`` 可读值。"""
        return f"{self.port_name}/{PORT_SUFFIX}"

    @Slot(bytes)
    def handle_bytes(self, data: bytes) -> None:
        """串口线程逐字节切换 PSA/原始模式，正确处理 A1 与 C 粘包。"""
        for value in data:
            if self._ota_engine and self._ota_engine.raw_mode:
                self.frame_signal.emit(FrameRecord(
                    MODEL_NAME, self.monitor_port, "RX", "YMODEM", bytes((value,)), "OTA 原始接收"))
                self._ota_engine.on_raw(bytes((value,)))
                self.stream.reset()
                continue
            for event in self.stream.feed(bytes((value,))):
                if event.kind != "frame":
                    self.frame_signal.emit(FrameRecord(
                        MODEL_NAME, self.monitor_port, "DROP", "KA_RF_UNIT",
                        event.data, event.message, "ERROR"))
                    continue
                parsed = event.parsed
                command, decoded = parsed["command"], parsed["decoded"]
                self.frame_signal.emit(FrameRecord(
                    MODEL_NAME, self.monitor_port, "RX", f"0x{command:02X} {parsed['name']}",
                    event.data, protocol.describe(parsed, event.message)))
                with self._session_lock:
                    if command == self._pending_command:
                        self._pending_command = None
                if command == protocol.RES_STATUS and "uptime_ms" in decoded:
                    self._emit_status(decoded)
                elif command == protocol.RES_INTERNAL_STATUS and "snapshot_version" in decoded:
                    self.internal_status_signal.emit(decoded)
                elif command == protocol.RES_ARRAY_ATT and "snapshot_version" in decoded:
                    self.array_attenuation_signal.emit(decoded)
                elif command == protocol.RES_OTA_STATUS and not self.ota_active:
                    self.ota_status_signal.emit(decoded)
                elif "result" in decoded:
                    self.result_signal.emit(command, decoded["name"])
                if self._ota_engine and self.ota_active:
                    self._ota_engine.on_response(parsed, event.data)
        self._release_ota_if_done()

    def _emit_status(self, decoded: Dict[str, Any]) -> None:
        """更新 0xA0 上报频率统计并发布结构化状态。

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
        """提交普通请求；OTA 独占、队列满或串口不可用时明确拒绝。"""
        return self.send_bytes(frame)

    @Slot(bytes)
    def send_bytes(self, frame: bytes) -> bool:
        """所有普通入口共享 OTA 互斥；此处仅入队，不把入队当实际发送。"""
        with self._session_lock:
            if self._ota_reserved:
                self.log_signal.emit("OTA 占用串口，普通命令未入队")
                return False
            if len(frame) < 8 or not frame.startswith(protocol.FRAME_MAGIC):
                self.log_signal.emit("拒绝非 PSA 普通请求")
                return False
            if frame[4] == protocol.CMD_SET_BEAM and (self._pending_command is not None or not self._tx_queue.empty()):
                # 扫描点不积压成迟到轨迹；本拍失败由 Panel 计为跳过。
                return False
            accepted = super().send_bytes(frame)
            if not accepted:
                self.log_signal.emit("发送未入队：串口未就绪或队列已满")
            return accepted

    def _write_frame(self, data: bytes) -> None:
        """串口线程实际写入并记录字节数；短写和失败抛给状态机处理。"""
        _, _, count, error = self.write_observed(data)
        is_frame = data.startswith(protocol.FRAME_MAGIC)
        label = f"0x{data[4]:02X}" if is_frame else "YMODEM"
        self.frame_signal.emit(FrameRecord(
            MODEL_NAME, self.monitor_port, "TX" if not error else "DROP", label,
            data, error or f"串口写入 {count} 字节（不代表设备接受）", "ERROR" if error else "INFO"))
        if error:
            self.log_signal.emit(error)
            raise IOError(error)

    def _flush_tx(self) -> None:
        """串口线程调度；锁只保护预约，不跨串口 I/O 持锁阻塞 UI。"""
        with self._session_lock:
            now = time.monotonic()
            cfg, self._ota_config = self._ota_config, None
            ota = self._ota_reserved
            if not ota:
                if self._pending_command is not None:
                    if now < self._pending_deadline:
                        return
                    self.log_signal.emit(f"请求 0x{self._pending_command & 0x7F:02X} 响应超时")
                    self._pending_command = None
                if (self._query_interval and now >= self._next_query and
                        (self._tx_queue.empty() or not self._last_was_query)):
                    frame = protocol.build_status_query()
                    self._next_query = now + self._query_interval
                else:
                    try:
                        frame = self._tx_queue.get_nowait()
                    except queue.Empty:
                        return
                self._pending_command = frame[4] | 0x80
                self._pending_deadline = now + 2.0
                self._last_was_query = frame[4] == protocol.CMD_STATUS_QUERY
        # 此后的写入与引擎推进只在串口线程，不持有 UI 预约锁。
        if ota:
            if cfg is not None:
                self.stream.reset()
                self._ota_engine = OtaTrafficEngine(cfg)
                self._ota_engine.start()
            if self._ota_cancel.is_set():
                self._ota_cancel.clear()
                self._ota_engine.cancel()
            self._ota_engine.poll(time.monotonic())
            self._release_ota_if_done()
            return
        try:
            self._write_frame(frame)
        except IOError:
            # 短写后仍留出请求超时窗口，不立即穿插下一条。
            pass
        self._pending_deadline = time.monotonic() + 2.0

    def set_query_hz(self, rate_hz: int) -> bool:
        """仅改变主站查询频率（0=关），不发送旧的 SET_REPORT_HZ。"""
        if not 0 <= rate_hz <= 10:
            raise ValueError("本地查询频率必须为 0..10 Hz")
        with self._session_lock:
            self._query_interval = 1 / rate_hz if rate_hz else 0
            self._next_query = time.monotonic()
        return True

    def query_status(self) -> bool:
        """发送 V2 空载荷状态查询。"""
        return self._queue_frame(protocol.build_status_query())

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

    def ota_status(self) -> bool:
        """普通协议模式查询 OTA 快照。"""
        return self._queue_frame(protocol.build_ota_status())

    def ota_abort(self) -> bool:
        """普通协议模式清理候选；原始模式禁止发送 ABORT 帧。"""
        return self._queue_frame(protocol.build_ota_abort())

    def start_ota(self, *, filename: str, data: bytes) -> bool:
        """校验输入并预约串口线程上传，已有普通请求时拒绝而不抢占。"""
        cfg = OtaConfig(filename, bytes(data), self._write_frame, self._ota_dispatch_event)
        with self._session_lock:
            if (not self.running or self._stop_event.is_set() or self._ota_reserved or
                    self._pending_command is not None or not self._tx_queue.empty()):
                self.log_signal.emit("OTA 未启动：串口未就绪或仍有在途/排队请求，请稍后重试")
                return False
            self._ota_config = cfg
            self._ota_reserved = True
            self._ota_cancel.clear()
            self.ota_busy_signal.emit(True)
            return True

    def stop_ota(self) -> bool:
        """请求串口线程取消；返回 True 仅表示当前已不占用，不提前释放设备会话。"""
        with self._session_lock:
            if self._ota_reserved:
                self._ota_cancel.set()
                return False
            return True

    @property
    def ota_active(self) -> bool:
        """上传/恢复已预约或正在占用串口。"""
        with self._session_lock:
            return self._ota_reserved

    def _release_ota_if_done(self) -> None:
        """终态后释放主站占用；已有新预约时不被上一会话终态清掉。"""
        with self._session_lock:
            if (self._ota_reserved and self._ota_config is None and
                    self._ota_engine and not self._ota_engine.active):
                self._ota_reserved = False
                self._next_query = time.monotonic() + self._query_interval
                self.stream.reset()
                self.ota_busy_signal.emit(False)

    def on_loop_stopped(self) -> None:
        """串口线程关闭时保留明确的未确认结论，不把断开视为安装成功。"""
        with self._session_lock:
            if self._ota_reserved:
                self.ota_event_signal.emit("outcome", "串口已断开，上传/安装结果未确认；重新连接后查询")
            self._ota_reserved = False
            self._ota_config = None
            self._ota_engine = None
            self._pending_command = None
            self.ota_busy_signal.emit(False)

    def _ota_dispatch_event(self, kind: str, payload: Any) -> None:
        """串口线程通过 Qt 信号交付事件，UI 不直接读写状态机。"""
        if kind == "status_received":
            self.ota_status_signal.emit(payload)
        elif kind == "progress":
            self.ota_progress_signal.emit(payload["sent"], payload["total"])
        else:
            self.ota_event_signal.emit(kind, payload)
        if kind in {"outcome", "send_failed", "timeout", "status_error", "notice"}:
            self.log_signal.emit(f"OTA {kind}: {payload}")


DeviceDriver = KaRfUnitDriver
