"""单客户端 AFD01 UDP 会话；Qt 事件循环收发，无额外线程或通用传输层。"""

from __future__ import annotations
import secrets
import time
from typing import Optional
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtNetwork import QUdpSocket, QHostAddress
from soft_hertz_tool.shared.observability import FrameRecord
from . import protocol as p


class Afd01Driver(QObject):
    """一次一条控制在途；查询独立、控制超时不重发。"""

    frame_signal = Signal(object)
    status_signal = Signal(dict)
    changed = Signal()
    result_signal = Signal(str)
    control_finished = Signal(object)

    def __init__(self, parent=None) -> None:
        """建立未连接会话、单条在途请求和 100 ms 非阻塞定时器。"""
        super().__init__(parent)
        self.socket: Optional[QUdpSocket] = None
        self.endpoint = ""
        self.generation = 0
        self._id = secrets.randbelow(0x7FFFFFFF) + 1
        self._query_id = 0
        self._query_deadline = 0.0
        self._query_waiting = False
        self.scan_polling = False
        self.pending: Optional[dict] = None
        self.latest: dict = {}
        self.last_response = 0.0
        self.opened = 0.0
        self._next_query = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)

    @property
    def fresh(self) -> bool:
        """最近三秒内收到匹配查询响应时为真。"""
        return bool(
            self.socket and self.latest and time.monotonic() - self.last_response < 3.0
        )

    @property
    def manual(self) -> bool:
        """当前新鲜 Tracking 状态确认手动模式时为真。"""
        return self.fresh and self.latest.get("mode") == 4

    @property
    def can_control(self) -> bool:
        """设备手动状态新鲜且没有控制在途时允许写操作。"""
        return self.manual and self.pending is None

    def connect_device(self, host: str, port: int = 4004) -> None:
        """创建新 socket 并查询能力；旧会话事件按 generation 丢弃。"""
        address = QHostAddress(host)
        if address.isNull() or not 1 <= port <= 65535:
            raise ValueError("请输入有效 IP 和端口")
        self.close()
        self.endpoint = f"{host}:{port}"
        sock = QUdpSocket(self)
        self.socket = sock
        generation = self.generation
        sock.readyRead.connect(lambda: self._receive(sock, generation))
        sock.errorOccurred.connect(lambda error: self._socket_error(sock, generation))
        sock.connectToHost(address, port)
        self.opened = time.monotonic()
        self._next_query = 0
        self.timer.start()
        self.tick()

    def close(self) -> bool:
        """停止定时器并关闭 socket；不向固件发送模式或输出修改。"""
        self.generation += 1
        self.timer.stop()
        sock, self.socket = self.socket, None
        if sock is not None:
            sock.readyRead.disconnect()
            sock.errorOccurred.disconnect()
            sock.close()
            sock.deleteLater()
        self.pending = None
        self._query_waiting = False
        self.scan_polling = False
        self.latest = {}
        self.last_response = 0
        self.changed.emit()
        return True

    def _next_id(self) -> int:
        """生成会话内递增的非零 32 位请求编号，跨连接继续递增。"""
        self._id = (self._id + 1) & 0xFFFFFFFF or 1
        return self._id

    def _record(
        self, direction: str, raw: bytes, message: str, command: str = "RF"
    ) -> None:
        """将 UDP TX/RX/DROP 转为共用 FrameRecord，交给 UI 和异步日志。"""
        self.frame_signal.emit(
            FrameRecord(
                self.latest.get("model", "AFD01"),
                self.endpoint,
                direction,
                command,
                raw,
                message,
                "WARNING" if direction == "DROP" else "INFO",
            )
        )

    def _send(
        self,
        rid: int,
        operation: int,
        target: int = 0,
        a: float = 0,
        b: float = 0,
        c: float = 0,
    ) -> None:
        """校验并发送一条请求；socket 不可用或短写抛出 OSError。"""
        raw = p.request(rid, operation, target, a, b, c)
        if self.socket is None or self.socket.write(raw) != len(raw):
            raise OSError("UDP 发送失败")
        self._record("TX", raw, "已发送 UDP 请求", p.Op(operation).name)

    def control(
        self, operation: int, target: int = 0, a: float = 0, b: float = 0, c: float = 0
    ) -> int:
        """发送一次请求并返回编号；已处于手动模式的重复切换返回0，不自动重试。"""
        if not self.fresh:
            raise ValueError("尚未收到有效测试能力，或设备状态已失效")
        if self.pending is not None:
            raise ValueError("上一条控制请求尚未结束")
        if not self.latest["capabilities"] & (1 << operation):
            raise ValueError("当前固件不支持此操作")
        if operation != p.Op.MANUAL and not self.manual:
            raise ValueError("请先切换手动模式")
        if operation == p.Op.MANUAL and self.manual:
            return 0
        rid = self._next_id()
        self._send(rid, operation, target, a, b, c)
        self.pending = dict(
            id=rid, operation=operation, deadline=time.monotonic() + 5.0
        )
        if self.scan_polling:
            self._next_query = time.monotonic()
        self.changed.emit()
        return rid

    def set_scan_polling(self, enabled: bool) -> None:
        """扫描控制在途时加快查询；停止扫描恢复普通1Hz查询，不取消在途控制。"""
        self.scan_polling = enabled
        self._next_query = time.monotonic() if enabled else time.monotonic() + 1.0

    @Slot()
    def tick(self) -> None:
        """扫描在途控制100ms查询，其他1Hz；查询最多一条在途，1秒超时后重新查询。"""
        if self.socket is None:
            return
        now = time.monotonic()
        if self.pending is not None and now >= self.pending["deadline"]:
            self._finish("控制超时，执行结果未知；未自动重发")
        if self._query_waiting and now >= self._query_deadline:
            self._query_waiting = False
        if not self._query_waiting and now >= self._next_query:
            self._next_query = now + (
                0.1 if self.scan_polling and self.pending else 1.0
            )
            self._query_waiting = True
            self._query_deadline = now + 1.0
            self._query_id = self._next_id()
            try:
                self._send(self._query_id, p.Op.QUERY)
            except OSError as exc:
                self._query_waiting = False
                self.result_signal.emit(str(exc))
        self.changed.emit()

    def _finish(self, text: str, result: Optional[int] = None) -> None:
        """结束唯一在途控制，向 UI 报告实际结果或未知结果。"""
        finished = self.pending
        self.pending = None
        self.result_signal.emit(text)
        if finished is not None:
            self.control_finished.emit(
                dict(id=finished["id"], operation=finished["operation"], result=result)
            )
        self.changed.emit()

    def _socket_error(self, sock: QUdpSocket, generation: int) -> None:
        """当前 socket 出错时令状态失效；旧代际错误不影响新连接。"""
        if sock is self.socket and generation == self.generation:
            self.last_response = 0
            self.result_signal.emit(sock.errorString())
            self.changed.emit()

    def _receive(self, sock: QUdpSocket, generation: int) -> None:
        """在 Qt 主线程读取当前 socket 数据报，交给正式 RX 校验边界。"""
        if sock is not self.socket or generation != self.generation:
            return
        while sock.hasPendingDatagrams():
            raw, _, _ = sock.readDatagram(sock.pendingDatagramSize())
            self.handle_datagram(bytes(raw), generation)

    def handle_datagram(self, raw: bytes, generation: int) -> None:
        """实际 RX 边界；旧代际、错编号和非法帧不会改变当前操作状态。"""
        if generation != self.generation or self.socket is None:
            return
        try:
            command, data = p.unpack(raw)
            if command == p.STATUS:
                snapshot = p.status(data)
                if snapshot["id"] != self._query_id:
                    return
                self._query_waiting = False
                if self.scan_polling and self.pending:
                    self._next_query = min(self._next_query, time.monotonic() + 0.1)
                self.latest = snapshot
                self.last_response = time.monotonic()
                if self.pending:
                    if (
                        self.pending["operation"] == p.Op.MANUAL
                        and snapshot["mode"] == 4
                    ):
                        self._finish("已确认 Tracking 手动模式", 1)
                    else:
                        for completion in snapshot["completions"]:
                            if (
                                completion["id"] == self.pending["id"]
                                and completion["operation"] == self.pending["operation"]
                            ):
                                self._finish(
                                    p.RESULTS.get(completion["result"], "未知执行结果"),
                                    completion["result"],
                                )
                                break
                self.status_signal.emit(snapshot)
                self.changed.emit()
            elif command == p.RESPONSE:
                response = p.response(data)
                if (
                    self.pending
                    and response["id"] == self.pending["id"]
                    and response["operation"] == self.pending["operation"]
                ):
                    if response["result"] != 0:
                        self._finish(p.RESULTS[response["result"]], response["result"])
                    else:
                        self.result_signal.emit("请求已接受，等待 owner 执行结果")
            else:
                return
            self._record("RX", raw, "有效测试响应", f"0x{command:02X}")
        except (ValueError, UnicodeError, OverflowError) as exc:
            self._record("DROP", raw, str(exc))
