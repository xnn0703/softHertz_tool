"""KA_RF_UNIT V2 自动安装 OTA；纯状态机，所有入口由 Driver 串口线程串行调用。

on_send 必须完成写入或抛出异常；ACK 不等于安装成功。时间来自可注入单调时钟。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

from . import protocol as p

SOH, STX, EOT, ACK, NAK, CAN, CRC_CHAR = 1, 2, 4, 6, 21, 24, 67
RAW_STATES = {"WAIT_C", "HEADER", "HEADER_C", "DATA", "EOT1", "EOT2", "END_C", "END_ACK"}


def image_version(filename: str) -> tuple:
    """验证本 target 的版本化 App BIN basename，返回三个 u16 版本号。"""
    p._validate_ota_filename(filename)
    match = re.fullmatch(r"ka_rf_unit_app_(\d+)\.(\d+)\.(\d+)_(release|beta)\.bin", filename)
    if not match:
        raise ValueError("请选择 ka_rf_unit_app_<版本>_release.bin 或 beta.bin，不能是 FACTORY/OLD")
    version = tuple(int(match[i]) for i in (1, 2, 3))
    if any(v > 65535 for v in version):
        raise ValueError("版本号各段必须为 0..65535")
    return version


@dataclass
class OtaConfig:
    """不可跨线程修改的上传输入；恢复期限包含设备健康观察时间。"""
    filename: str
    data: bytes
    on_send: Callable[[bytes], None]
    on_event: Callable[[str, object], None]
    clock: Callable[[], float] = time.monotonic
    recovery_timeout: float = 180.0

    def __post_init__(self) -> None:
        """进入串口前完成便宜的名称/大小检查。"""
        image_version(self.filename)
        self.data = bytes(self.data)
        if not 1 <= len(self.data) <= p.OTA_APP_MAX_SIZE:
            raise ValueError("固件大小必须为 1..786432 字节")
        if self.recovery_timeout < 100:
            raise ValueError("恢复期限至少 100 秒，以容纳启动健康观察")


class OtaTrafficEngine:
    """停等 YMODEM-1K 发送及自动安装恢复查询，不创建线程或操作 UI。"""

    def __init__(self, config: OtaConfig) -> None:
        """建立待启动会话，不在构造期间发送任何字节。"""
        self.cfg = config
        self.state = "IDLE"
        self.now = config.clock()
        self.target = image_version(config.filename)
        self.before: Optional[tuple] = None
        self.pending: Optional[int] = None
        self.deadline = 0.0
        self.next_query = 0.0
        self.recovery_end = 0.0
        self.raw_started = self.now
        self.progress_at = self.now
        self.last_packet = b""
        self.offset = 0
        self.chunk_size = 0
        self.sequence = 1
        self.retries = 0
        self.authorized_finish = False
        self.cancelled = False
        self.header_ack_seen = False

    @property
    def active(self) -> bool:
        """是否仍占用本串口，终态不表示真实安装得到证明。"""
        return self.state not in {"IDLE", "DONE", "FAILED", "UNCONFIRMED", "CANCELLED"}

    @property
    def raw_mode(self) -> bool:
        """静默恢复窗口仍丢弃迟到原始字节，不混入 PSA 解析器。"""
        return self.state in RAW_STATES or self.state == "QUIET"

    def _enter(self, state: str) -> None:
        """改变内部阶段并通过事件报告。"""
        self.state = state
        self.cfg.on_event("state", state)

    def _send(self, data: bytes) -> bool:
        """提交串口写入；失败时保留占用并进入有界恢复。"""
        try:
            self.cfg.on_send(data)
            return True
        except Exception as exc:
            self.cfg.on_event("send_failed", str(exc))
            # 写出部分字节时设备状态未知；保留独占并等原始接收窗口退出。
            self.now = self.cfg.clock()
            self._recover(10.0)
            return False

    def _request(self, command: int) -> None:
        """发送空载荷请求并设置唯一的在途响应。"""
        self.pending = command | 0x80
        self.deadline = self.now + 2.0
        if not self._send(p.encode_frame(command, b"")):
            self.pending = None
        else:
            self.deadline = self.cfg.clock() + 2.0

    def start(self) -> None:
        """先探测普通 V2 状态，再探测 OTA；探测失败绝不发 BEGIN。"""
        if self.state != "IDLE":
            return
        self.now = self.cfg.clock()
        self._enter("PROBE_STATUS")
        self._request(p.CMD_STATUS_QUERY)

    def _finish(self, state: str, message: str) -> None:
        """设置终态并给出不超出证据的结论。"""
        self.pending = None
        self._enter(state)
        self.cfg.on_event("outcome", message)

    def on_response(self, parsed: dict, raw: bytes = b"") -> None:
        """仅接受当前等待的响应；错误响应不能推进传输。"""
        self.now = self.cfg.clock()
        if parsed["command"] != self.pending:
            return
        self.pending = None
        d = parsed["decoded"]
        result = d.get("result", p.RESULT_BAD_LENGTH)
        if parsed["command"] == p.RES_OTA_STATUS:
            self.cfg.on_event("status_received", d)
        if self.state == "RECOVERY":
            self.next_query = self.now + 1
            if result != p.RESULT_OK:
                self.cfg.on_event("status_error", d)
                return
            if d["last_result"]:
                self._finish("FAILED", "设备自动安装失败：" + p.result_text(d["last_result"]))
                return
            version = tuple(d[k] for k in ("fw_major", "fw_minor", "fw_revision"))
            if self.cancelled and d["phase"] == p.OTA_PHASE_IDLE and not d["update_requested"]:
                self._finish("CANCELLED", "上传已停止；候选如仍存在，可在普通模式清理")
            elif not self.authorized_finish and d["phase"] == p.OTA_PHASE_IDLE and not d["update_requested"]:
                self._finish("FAILED", "未完成上传，设备已恢复普通模式；检查候选后重试")
            elif (self.authorized_finish and version == self.target and
                  d["app_boot_state"] == p.OTA_BOOT_STABLE and
                  d["phase"] == p.OTA_PHASE_IDLE and not d["update_requested"]):
                if self.before == self.target:
                    self._finish("UNCONFIRMED", "目标版本健康运行；同版本重装无法证明本次安装完成")
                else:
                    self._finish("DONE", "目标版本已运行且健康状态为 STABLE")
            return
        if result != p.RESULT_OK:
            self._finish("FAILED", "设备拒绝：" + p.result_text(result))
        elif self.state == "PROBE_STATUS":
            self._enter("PROBE_OTA")
            self._request(p.CMD_OTA_STATUS)
        elif self.state == "PROBE_OTA":
            self.before = tuple(d[k] for k in ("fw_major", "fw_minor", "fw_revision"))
            if (d["phase"] != p.OTA_PHASE_IDLE or d["candidate_present"] or
                    d["update_requested"] or d["app_boot_state"] != p.OTA_BOOT_STABLE):
                self._finish("FAILED", "设备未就绪、存在候选或尚未稳定；请查询并处理后重试")
                return
            self._enter("BEGIN")
            self._request(p.CMD_OTA_BEGIN)
        elif self.state == "BEGIN":
            self.raw_started = self.progress_at = self.now
            self.deadline = self.now + 10
            self._enter("WAIT_C")

    def _packet(self, sequence: int, data: bytes, size: int) -> bytes:
        """编码 SOH/STX 数据包，CRC16/XMODEM 大端，填充不计有效文件长度。"""
        payload = data.ljust(size, b"\x00")
        return (bytes((SOH if size == 128 else STX, sequence, sequence ^ 255)) +
                payload + p.crc16_ccitt_ymodem(payload).to_bytes(2, "big"))

    def _transmit(self, state: str, packet: bytes, timeout: float = 2) -> None:
        """进入下一停等阶段，保存原包供同序号重传。"""
        self._enter(state)
        self.last_packet = packet
        self.retries = 0
        self.deadline = self.now + timeout
        if self._send(packet):
            self.deadline = self.cfg.clock() + timeout

    def _data_or_eot(self) -> None:
        """发送下一数据块；有效文件字节全部被 ACK 后发送 EOT。"""
        if self.offset >= len(self.cfg.data):
            self._transmit("EOT1", bytes((EOT,)))
        else:
            size = 1024 if len(self.cfg.data) - self.offset > 128 else 128
            self.chunk_size = min(size, len(self.cfg.data) - self.offset)
            self._transmit("DATA", self._packet(
                self.sequence, self.cfg.data[self.offset:self.offset + self.chunk_size], size))

    def _retry(self) -> None:
        """重传同一包，不刷新有效进展截止时间。"""
        if self.now - self.progress_at >= 10 or self.retries >= p.YMODEM_MAX_RETRANSMIT:
            self.cfg.on_event("timeout", "YMODEM 无有效进展或重试耗尽")
            self._cancel_raw()
            return
        self.retries += 1
        timeout = 10 if self.state == "HEADER" else 2
        if self._send(self.last_packet):
            self.deadline = self.cfg.clock() + timeout

    def on_raw(self, data: bytes) -> None:
        """解析分片或合并控制字符；只有真正推进状态才刷新进展时间。"""
        self.now = self.cfg.clock()
        if self.state in RAW_STATES:
            # 迟到控制字节不得在接收期限外授权发送最后空包。
            if self.now - self.raw_started >= 120 or self.now - self.progress_at >= 10:
                if self.authorized_finish:
                    self._recover(0.2)
                else:
                    self._cancel_raw()
                return
        for value in data:
            if self.state not in RAW_STATES:
                return
            if value == CAN:
                self.cfg.on_event("ymodem_cancelled", "设备取消传输")
                self.cancelled = not self.authorized_finish
                self._recover(10)
                return
            previous = self.state
            duplicate_header_ack = self.state == "HEADER" and value == ACK and self.header_ack_seen
            if self.state == "WAIT_C" and value == CRC_CHAR:
                metadata = self.cfg.filename.encode("ascii") + b"\x00" + str(len(self.cfg.data)).encode() + b"\x00"
                self._transmit("HEADER", self._packet(0, metadata, 128), 10)
            elif self.state == "HEADER" and value == ACK:
                self.header_ack_seen = True
                self._enter("HEADER_C")
                self.deadline = self.now + 2
            elif self.state == "HEADER_C" and value == CRC_CHAR:
                self._data_or_eot()
            elif self.state == "DATA" and value == ACK:
                self.offset += self.chunk_size
                self.sequence = (self.sequence + 1) & 255
                self.cfg.on_event("progress", {"sent": self.offset, "total": len(self.cfg.data)})
                self._data_or_eot()
                self.progress_at = self.now  # DATA -> DATA 也是有效推进。
            elif self.state == "EOT1" and value == NAK:
                self._transmit("EOT2", bytes((EOT,)))
            elif self.state == "EOT2" and value == ACK:
                self._enter("END_C")
                self.deadline = self.now + 2
            elif self.state in {"END_C", "EOT2"} and value == CRC_CHAR:
                # 第二个 EOT 的 ACK 丢失时，接收端已进入等待末包并周期发 C。
                # 此包一旦完整到达就已授权自动安装，ACK 丢失也不能重发。
                self.authorized_finish = True
                self._transmit("END_ACK", self._packet(0, b"", 128))
            elif self.state == "END_ACK" and value == ACK:
                self._recover(0.2)
            elif value == NAK and self.state in {"HEADER", "DATA", "EOT2"}:
                self._retry()
            if previous != self.state and self.state != "QUIET" and not duplicate_header_ack:
                self.progress_at = self.now

    def _recover(self, quiet: float) -> None:
        """静默期间丢弃裸字节，之后才恢复 PSA 查询。"""
        self.pending = None
        self._enter("QUIET")
        self.deadline = self.now + quiet
        if not self.recovery_end:
            self.recovery_end = self.deadline + self.cfg.recovery_timeout

    def _cancel_raw(self) -> None:
        """发送 CAN 请求接收端退出，仍等待接收超时窗口。"""
        self.cancelled = True
        self._send(bytes((CAN, CAN)))
        self._recover(10)

    def cancel(self) -> None:
        """仅原始接收阶段可发 CAN；末包后自动安装不可撤销。"""
        self.now = self.cfg.clock()
        if self.state in RAW_STATES and not self.authorized_finish:
            self._cancel_raw()
        elif self.state == "BEGIN":
            self.cancelled = True
            self._recover(10)
        elif self.state in {"PROBE_STATUS", "PROBE_OTA"}:
            # 已在途的查询仍须等待响应/超时，不提前释放串口。
            self.cancelled = True
            self._recover(2)
        else:
            self.cfg.on_event("notice", "正在恢复查询；完整上传后的自动安装不能撤销")

    def poll(self, now: Optional[float] = None) -> None:
        """串口循环驱动截止时间，恢复查询始终最多一个在途。"""
        self.now = self.cfg.clock() if now is None else now
        if not self.active:
            return
        if self.state == "QUIET":
            if self.now >= self.deadline:
                self._enter("RECOVERY")
                self.next_query = self.now
            else:
                return
        if self.state == "RECOVERY":
            if self.now >= self.recovery_end:
                self._finish("UNCONFIRMED", "恢复等待到期，安装结果未确认；请检查连接后查询")
            elif self.pending is not None:
                if self.now >= self.deadline:
                    self.pending = None
                    self.next_query = self.now + 1
            elif self.now >= self.next_query:
                self._request(p.CMD_OTA_STATUS)
            return
        if self.state in RAW_STATES:
            if self.state == "END_ACK" and self.now >= self.deadline:
                self._recover(0.2)
            elif self.now - self.raw_started >= 120 or self.now - self.progress_at >= 10:
                self.cfg.on_event("timeout", "YMODEM 接收窗口到期")
                self._cancel_raw()
            elif self.now >= self.deadline:
                if self.state == "WAIT_C":
                    self._cancel_raw()
                elif self.state == "HEADER_C":
                    self._enter("HEADER")
                    self._retry()
                elif self.state == "END_C":
                    # 已收到第二个 EOT 的 ACK，不能向等待 block0 的设备再发 EOT。
                    self.deadline = self.now + 2
                else:
                    self._retry()
        elif self.pending is not None and self.now >= self.deadline:
            if self.state == "BEGIN":
                self.cfg.on_event("timeout", "BEGIN 响应丢失；不发送文件，等待接收窗口退出")
                self._recover(10)
            else:
                self._finish("FAILED", "V2 服务探测超时；未发送文件")
