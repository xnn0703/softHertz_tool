"""客户流量调度：单调时钟、应答等待/非等待模式和有界统计，不依赖 Qt/串口。"""

from __future__ import annotations

import math
import random
from collections import Counter, deque
from dataclasses import asdict, dataclass
from typing import Callable, Optional

from soft_hertz_tool.devices.afdtr1024 import protocol
from soft_hertz_tool.devices.afdtr1024.models import DeviceVariant


@dataclass(frozen=True)
class TrafficConfig:
    """一次运行的不可变参数；时间单位为 ms，时长为 min。"""

    beam_period_ms: float = 10
    query_period_ms: float = 1000
    query_type: str = "both"
    target_id: int = 1
    gap_mode: str = "zero"
    gap_ms: float = 1
    random_min_ms: float = 0
    random_max_ms: float = 5
    duration_min: float = 1
    timeout_ms: float = 100
    seed: int = 0
    beam_mode: str = "addressed_stream"

    def validate(self) -> None:
        """校验参数，拒绝非有限值、负时间及无效目标/枚举。"""
        for name in ("beam_period_ms", "query_period_ms", "duration_min", "timeout_ms"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0 or value > 1e7:
                raise ValueError(f"{name} 必须为有限正数且不超过 10000000")
        if self.beam_period_ms < 0.1 or self.query_period_ms < 0.1 or self.timeout_ms < 0.1:
            raise ValueError("周期和超时不能小于 0.1 ms")
        for name in ("gap_ms", "random_min_ms", "random_max_ms"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= 60000:
                raise ValueError(f"{name} 必须在 0～60000 ms")
        if self.random_max_ms < self.random_min_ms:
            raise ValueError("随机间隔上限不能小于下限")
        if not isinstance(self.target_id, int) or not 1 <= self.target_id <= 127:
            raise ValueError("查询目标 ID 必须在 1～127")
        if self.query_type not in ("both", "status", "beam") or self.gap_mode not in ("zero", "fixed", "random"):
            raise ValueError("查询类型或间隔模式无效")
        if not isinstance(self.seed, int):
            raise ValueError("随机种子必须为整数")
        if self.beam_mode not in ("addressed_stream", "addressed", "broadcast"):
            raise ValueError("波束模式无效")
        if self.beam_mode == "addressed_stream" and self.gap_mode != "zero":
            raise ValueError("客户非等待模式固定零间隙合包")


@dataclass(frozen=True)
class TrafficBatch:
    """一次 write 的完整帧及计划信息；合并写入无独立帧内时间。"""

    sequence: int
    frames: tuple[bytes, ...]
    planned_ns: int
    has_beam: bool
    query_index: Optional[int] = None
    ready_ns: int = 0

    @property
    def raw(self) -> bytes:
        """返回本批连续字节。"""
        return b"".join(self.frames)


class TrafficEngine:
    """由串口线程单独驱动的确定性状态机，时间戳由调用方提供。"""

    def __init__(self, config: TrafficConfig, variant: DeviceVariant, beam: bytes,
                 start_ns: int, record: Callable[[dict], None]):
        """冻结构帧输入，建立周期网格及记录出口。"""
        config.validate()
        self.config = config
        self.variant = variant
        self.beam = beam
        queries = protocol.build_query_frames(config.target_id, variant)
        self.queries = tuple(queries if config.query_type == "both" else [queries[0 if config.query_type == "status" else 1]])
        self.start_ns = start_ns
        self.end_ns = start_ns + int(config.duration_min * 60e9)
        self.beam_period = int(config.beam_period_ms * 1e6)
        self.query_period = int(config.query_period_ms * 1e6)
        self.next_beam = start_ns
        self.next_query = start_ns + self.query_period
        self.due_ns = start_ns
        self.phase = "beam"
        self.reason = ""
        self.stopped_ns: Optional[int] = None
        # -1 表示等待波束原帧回显，非负值表示本轮查询下标；None 表示无待应答。
        self.pending: Optional[int] = None
        self.query_return_ns = 0
        self.last_query_return_ns = 0
        self.last_beam_return_ns = 0
        self.beam_resolved_ns = 0
        self.last_beam_start_ns: Optional[int] = None
        self.paused_since_beam = False
        self.gap_ns = 0
        self.sequence = 0
        self.stream_query_index: Optional[int] = None
        self.outstanding: dict[int, deque] = {-1: deque(), **{i: deque() for i in range(len(self.queries))}}
        self.tracking_limit = 4096
        self.counts: Counter = Counter()
        self.metrics: dict[str, dict] = {}
        self.record = record
        self.random = random.Random(config.seed)
        self.record({"event": "start", "at_ns": start_ns, "config": asdict(config),
                     "beam": beam.hex(), "queries": [f.hex() for f in self.queries]})

    @property
    def active(self) -> bool:
        """是否仍允许状态机推进。"""
        return self.phase != "stopped"

    def _metric(self, name: str, value: int) -> None:
        """常量内存聚合时间差，原始值另走明细记录。"""
        m = self.metrics.setdefault(name, {"count": 0, "sum_ns": 0, "min_ns": value, "max_ns": value})
        m["count"] += 1
        m["sum_ns"] += value
        m["min_ns"] = min(m["min_ns"], value)
        m["max_ns"] = max(m["max_ns"], value)

    def snapshot(self, now: int) -> dict:
        """返回可跨线程传递的独立统计快照。"""
        return {"phase": self.phase, "reason": self.reason, "counts": dict(self.counts),
                "tracking_complete": not self.counts["tracking_overflow"],
                "outstanding_beams": len(self.outstanding[-1]),
                "outstanding_queries": sum(len(q) for i, q in self.outstanding.items() if i >= 0),
                "waiting_for": "beam" if self.pending == -1 else "query",
                "elapsed_s": ((now if self.stopped_ns is None else self.stopped_ns) - self.start_ns) / 1e9,
                "remaining_s": max(0, (self.end_ns - now) / 1e9) if self.active else 0,
                "metrics": {k: dict(v) for k, v in self.metrics.items()}}

    def stop(self, reason: str, now: int) -> None:
        """幂等终止；待应答请求记取消而不是超时。"""
        if not self.active:
            return
        if self.pending is not None:
            self.counts["beam_cancelled" if self.pending == -1 else "cancelled"] += 1
        self.pending = None
        for index, requests in self.outstanding.items():
            self.counts["beam_cancelled" if index == -1 else "cancelled"] += len(requests)
            requests.clear()
        self.phase = "stopped"
        self.reason = reason
        self.stopped_ns = now
        self.record({"event": "stop", "at_ns": now, "reason": reason})

    def _resume(self, now: int, *, skip_queries: bool = True) -> None:
        """恢复原周期网格，跳过等待阶段错过的所有时刻。"""
        for attr, period, key in (("next_beam", self.beam_period, "skipped_beams"),
                                  ("next_query", self.query_period, "skipped_queries")):
            if attr == "next_query" and not skip_queries:
                continue
            due = getattr(self, attr)
            if due <= now:
                skipped = (now - due) // period + 1
                setattr(self, attr, due + skipped * period)
                self.counts[key] += skipped
        self.phase = "beam"
        self.due_ns = self.next_beam

    def _query_done(self, now: int) -> None:
        """波束或查询等待结束，安排下一阶段或恢复周期。"""
        index = self.pending
        self.pending = None
        if index == -1:
            self.beam_resolved_ns = now
            if self.after_write == "gap":
                self.phase = "gap"
                self.due_ns = now + self.gap_ns
            else:
                self._resume(now, skip_queries=False)
        elif index is not None and index + 1 < len(self.queries):
            self.phase = "second"
            self.due_ns = max(now, self.last_query_return_ns + 3_000_000)
        else:
            self._resume(now)

    def expire(self, now: int) -> None:
        """接收处理和发送调度共用截止判断；超时后的帧不得算及时回复。"""
        if not self.active:
            return
        if now >= self.end_ns:
            self.stop("duration", now)
        elif self.config.beam_mode == "addressed_stream":
            for index, requests in self.outstanding.items():
                while requests and now >= requests[0][1]:
                    sent, deadline, batch = requests.popleft()
                    self.counts["beam_timeouts" if index == -1 else "timeouts"] += 1
                    self.record({"event": "timeout", "at_ns": now, "query_index": index,
                                 "request_kind": "beam" if index == -1 else "query",
                                 "batch": batch, "deadline_ns": deadline, "write_return_ns": sent})
        elif self.phase == "wait" and now >= self.due_ns:
            self.counts["beam_timeouts" if self.pending == -1 else "timeouts"] += 1
            self.record({"event": "timeout", "at_ns": now, "query_index": self.pending,
                         "request_kind": "beam" if self.pending == -1 else "query",
                         "deadline_ns": self.due_ns})
            self._query_done(now)

    def poll(self, now: int) -> Optional[TrafficBatch]:
        """返回至多一个写入批次；调用方必须随后报告写入结果。"""
        self.expire(now)
        if self.config.beam_mode == "addressed_stream":
            return self._poll_stream(now)
        if not self.active or self.phase in ("wait", "writing") or now < self.due_ns:
            return None
        index = None
        has_beam = False
        planned = self.due_ns
        if self.phase == "beam":
            skipped = max(0, (now - self.next_beam) // self.beam_period)
            self.counts["skipped_beams"] += skipped
            planned = self.next_beam + skipped * self.beam_period
            self.next_beam = planned + self.beam_period
            has_beam = True
            frames = (self.beam,)
            if now >= self.next_query:
                skipped_queries = (now - self.next_query) // self.query_period
                self.counts["skipped_queries"] += skipped_queries
                self.next_query += (skipped_queries + 1) * self.query_period
                self.gap_ns = int((0 if self.config.gap_mode == "zero" else self.config.gap_ms
                                   if self.config.gap_mode == "fixed" else
                                   self.random.uniform(self.config.random_min_ms, self.config.random_max_ms)) * 1e6)
                self.counts["query_rounds"] += 1
                self.record({"event": "query_gap", "at_ns": now, "requested_ns": self.gap_ns,
                             "mode": self.config.gap_mode})
                if self.config.gap_mode == "zero" and self.config.beam_mode == "broadcast":
                    frames = (self.beam, self.queries[0])
                    index = 0
                else:
                    self.phase = "gap_beam"
        else:
            index = 0 if self.phase == "gap" else 1
            frames = (self.queries[index],)
        self.sequence += 1
        batch = TrafficBatch(self.sequence, frames, planned, has_beam, index, now)
        self.after_write = "gap" if self.phase == "gap_beam" else "beam"
        self.phase = "writing"
        return batch

    def _poll_stream(self, now: int) -> Optional[TrafficBatch]:
        """客户模式按周期直接发出两帧包，完全不以回复作为发送门槛。"""
        if not self.active or self.phase == "writing" or now < self.next_beam:
            return None
        skipped = (now - self.next_beam) // self.beam_period
        self.counts["skipped_beams"] += skipped
        planned = self.next_beam + skipped * self.beam_period
        self.next_beam = planned + self.beam_period
        if self.stream_query_index is None and now >= self.next_query:
            missed = (now - self.next_query) // self.query_period
            self.counts["skipped_queries"] += missed
            self.next_query += (missed + 1) * self.query_period
            self.counts["query_rounds"] += 1
            self.stream_query_index = 0
        index = self.stream_query_index
        frames = (self.beam,) if index is None else (self.beam, self.queries[index])
        if index is not None:
            self.stream_query_index = index + 1 if index + 1 < len(self.queries) else None
        self.sequence += 1
        self.after_write = "beam"
        self.phase = "writing"
        return TrafficBatch(self.sequence, frames, planned, True, index, now)

    def _track_stream_write(self, batch: TrafficBatch, returned: int) -> None:
        """独立跟踪已写出请求；容量受限，不能静默丢弃应答统计。"""
        indices = [-1] + ([] if batch.query_index is None else [batch.query_index])
        if batch.query_index is not None:
            self.counts["queries_written"] += 1
        for index in indices:
            requests = self.outstanding[index]
            if len(requests) >= self.tracking_limit:
                self.counts["tracking_overflow"] += 1
                self.stop("tracking_capacity", returned)
                return
            requests.append((returned, returned + int(self.config.timeout_ms * 1e6), batch.sequence))
        if self.next_beam <= returned:
            skipped = (returned - self.next_beam) // self.beam_period + 1
            self.counts["skipped_beams"] += skipped
            self.next_beam += skipped * self.beam_period
        self.phase = "beam"
        self.due_ns = self.next_beam

    def written(self, batch: TrafficBatch, started: int, returned: int, count: int, error: str = "") -> None:
        """记录真实 write 结果；仅完整写入计成功，短写/异常立即停止。"""
        success = not error and count == len(batch.raw)
        event = {"event": "write", "batch": batch.sequence, "planned_ns": batch.planned_ns,
                 "ready_ns": batch.ready_ns, "queue_ns": None,
                 "write_start_ns": started, "write_return_ns": returned, "requested_bytes": len(batch.raw),
                 "written_bytes": count, "success": success, "error": error,
                 "frame_count": len(batch.frames), "query_index": batch.query_index,
                 "line_gap_ns": None}
        if batch.query_index is not None and self.config.beam_mode == "addressed_stream":
            event.update(requested_gap_ns=0, host_gap_ns=None)
        if batch.query_index == 0:
            event["requested_gap_ns"] = self.gap_ns
            event["host_gap_ns"] = None if batch.has_beam else started - self.last_beam_return_ns
            if self.config.beam_mode == "addressed":
                event["post_beam_response_gap_ns"] = started - self.beam_resolved_ns
            if not batch.has_beam and success:
                self._metric("query_host_gap", started - self.last_beam_return_ns)
        if batch.has_beam:
            event["period_deviation_ns"] = started - batch.planned_ns
            event["beam_interval_ns"] = None if self.last_beam_start_ns is None else started - self.last_beam_start_ns
            event["query_pause"] = self.paused_since_beam
        self.record(event)
        if not success:
            self.counts["write_failures"] += 1
            self.stop("write_failure", returned)
            return
        if batch.has_beam:
            self.counts["beams_written"] += 1
            self._metric("paused_period_deviation" if self.paused_since_beam else "period_deviation",
                         started - batch.planned_ns)
            if self.last_beam_start_ns is not None:
                self._metric("paused_beam_interval" if self.paused_since_beam else "normal_beam_interval",
                             started - self.last_beam_start_ns)
            self.last_beam_start_ns = started
            self.last_beam_return_ns = returned
            self.paused_since_beam = batch.query_index is not None or self.after_write == "gap"
        if self.config.beam_mode == "addressed_stream":
            self.paused_since_beam = False
            self._track_stream_write(batch, returned)
        elif batch.has_beam and self.config.beam_mode == "addressed":
            self.pending = -1
            self.phase = "wait"
            self.due_ns = returned + int(self.config.timeout_ms * 1e6)
        elif batch.query_index is not None:
            self.counts["queries_written"] += 1
            self.pending = batch.query_index
            self.query_return_ns = self.last_query_return_ns = returned
            self.phase = "wait"
            self.due_ns = returned + int(self.config.timeout_ms * 1e6)
        elif self.after_write == "gap":
            self.phase = "gap"
            self.due_ns = returned + self.gap_ns
        else:
            self.phase = "beam"
            # 慢写跨过的周期也作废，不能紧接着补发已经迟到的波束。
            if self.next_beam <= returned:
                skipped = (returned - self.next_beam) // self.beam_period + 1
                self.next_beam += skipped * self.beam_period
                self.counts["skipped_beams"] += skipped
            self.due_ns = self.next_beam
        self.expire(returned)

    def received(self, frame: bytes, read_ns: int, parsed_ns: int) -> None:
        """识别合法匹配回复；无事务号协议无法排除同指令旧回复。"""
        self.expire(parsed_ns)
        parsed, message = protocol.parse_response(frame)
        self.counts["rx_frames_total"] += 1
        if parsed:
            addr = parsed["addr"]
            if addr == self.beam[-2]:
                self.counts["beam_reply_frames"] += 1
            elif addr in protocol.STATUS_RETURN_ADDRS:
                self.counts["status_reply_frames"] += 1
            elif addr in protocol.BEAM_QUERY_RETURN_ADDRS:
                self.counts["beam_query_reply_frames"] += 1
        if self.config.beam_mode == "addressed_stream":
            self._receive_stream(frame, parsed, read_ns, parsed_ns)
            return
        valid = False
        if parsed:
            message = "无待应答请求或迟到/重复回复"
        if parsed and parsed["device_id"] == self.config.target_id and self.pending is not None:
            addr = self.beam[-2] if self.pending == -1 else self.queries[self.pending][-2]
            message = "回复指令不匹配"
            if parsed["addr"] == addr:
                payload = parsed["payload"]
                if self.pending == -1:
                    valid = frame == self.beam
                    message = "OK" if valid else "波束回显内容不匹配"
                elif addr in protocol.STATUS_RETURN_ADDRS:
                    parser = protocol.parse_status_response if self.variant.is_tx else protocol.parse_rx_status_response
                    _, message = parser(payload)
                    valid = len(payload) == (6 if self.variant.is_tx else 5) and message == "OK"
                else:
                    _, message = protocol.parse_beam_query_response(payload, is_tx=self.variant.is_tx)
                    valid = (len(payload) == 16 and message == "OK"
                             and payload[10:12] == b"\xff\xff" and payload[12] <= 70)
                if not valid:
                    message = "回复载荷长度或字段非法"
        elif parsed and parsed["device_id"] != self.config.target_id:
            message = "回复目标 ID 不匹配"
        matched = self.phase == "wait" and valid
        beam_reply = self.pending == -1
        key = "beam_matched_replies" if beam_reply else "matched_replies"
        self.counts[key if matched else "abnormal_replies"] += 1
        event = {"event": "reply", "read_ns": read_ns, "parsed_ns": parsed_ns,
                 "request_kind": "beam" if beam_reply else "query",
                 "matched": matched, "addr": parsed.get("addr") if parsed else None,
                 "query_index": self.pending, "message": message}
        if matched:
            delay = parsed_ns - (self.last_beam_return_ns if beam_reply else self.query_return_ns)
            event["latency_ns"] = delay
            self._metric("beam_reply_latency" if beam_reply else "reply_latency", delay)
        self.record(event)
        if matched:
            self._query_done(parsed_ns)

    def _receive_stream(self, frame: bytes, parsed: Optional[dict], read_ns: int, now: int) -> None:
        """对非等待模式的回复按类型分别计数，并与未超时同类请求 FIFO 关联。"""
        index = None
        valid = False
        if parsed and parsed["device_id"] == self.config.target_id:
            addr, payload = parsed["addr"], parsed["payload"]
            if addr == self.beam[-2]:
                index, valid = -1, frame == self.beam
            else:
                for i, query in enumerate(self.queries):
                    if query[-2] != addr:
                        continue
                    index = i
                    if addr in protocol.STATUS_RETURN_ADDRS:
                        parser = protocol.parse_status_response if self.variant.is_tx else protocol.parse_rx_status_response
                        _, message = parser(payload)
                        valid = len(payload) == (6 if self.variant.is_tx else 5) and message == "OK"
                    else:
                        _, message = protocol.parse_beam_query_response(payload, is_tx=self.variant.is_tx)
                        valid = (len(payload) == 16 and message == "OK"
                                 and payload[10:12] == b"\xff\xff" and payload[12] <= 70)
                    break
        requests = self.outstanding.get(index)
        matched = self.active and valid and bool(requests)
        event = {"event": "reply", "read_ns": read_ns, "parsed_ns": now, "matched": matched,
                 "query_index": index, "addr": parsed.get("addr") if parsed else None,
                 "request_kind": "beam" if index == -1 else "query",
                 "association": "oldest_unexpired_same_kind" if matched else "unmatched"}
        if matched:
            sent, _, batch = requests.popleft()
            delay = now - sent
            event.update(batch=batch, latency_ns=delay)
            self.counts["beam_matched_replies" if index == -1 else "matched_replies"] += 1
            self._metric("beam_reply_latency" if index == -1 else "reply_latency", delay)
        else:
            self.counts["abnormal_replies"] += 1
        self.record(event)

    def dropped(self, reason: str, now: int) -> None:
        """记录拆帧丢弃；错误字节不能结束查询等待。"""
        self.counts["drops"] += 1
        self.record({"event": "drop", "at_ns": now, "reason": reason})
