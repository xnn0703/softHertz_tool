"""KuR512B 设备模拟器：复用正式 protocol/stream 的纯内核与串口循环。"""

from __future__ import annotations

import argparse
import threading
import time
from dataclasses import asdict
from typing import Iterable, Optional

from soft_hertz_tool.devices.kur512 import protocol
from soft_hertz_tool.devices.kur512.models import SimulatorState
from soft_hertz_tool.devices.kur512.stream import KUR512StreamParser


# 兼容旧测试的协议常量再导出。
FRAME_HEADER = protocol.FRAME_HEADER
ADDR_RX_BEAM = protocol.ADDR_RX_BEAM
ADDR_RX_ENABLE = protocol.ADDR_RX_ENABLE
ADDR_RX_PHASE_CAL = protocol.ADDR_RX_PHASE_CAL
ADDR_ID_UPDATE = protocol.ADDR_ID_UPDATE
ADDR_STATUS_QUERY = protocol.ADDR_STATUS_QUERY


class KUR512Simulator:
    """不依赖串口的设备内核；可被 pytest 直接调用以验证协议实现。"""

    def __init__(self, ids: Optional[Iterable[int]] = None) -> None:
        """创建接受指定子阵 ID 的纯模拟内核。

        Args:
            ids: 模拟器响应的子阵 ID；默认 ``[0x01]``。
        """
        values = list(ids) if ids is not None else [1]
        self.ids = self._normalize_ids(values)
        self.states: dict[int, SimulatorState] = {}

    @staticmethod
    def _normalize_ids(values: Iterable[int]) -> list[int]:
        """校验、去重并保留 0x01~0x7F 的子阵 ID。"""
        result: list[int] = []
        for value in values:
            sub_id = int(value)
            if not 1 <= sub_id <= 0x7F:
                raise ValueError("模拟子阵 ID 必须在 0x01~0x7F 范围内")
            if sub_id not in result:
                result.append(sub_id)
        if not result:
            raise ValueError("至少需要一个模拟子阵 ID")
        return result

    def state_for(self, sub_id: int) -> SimulatorState:
        """获取/创建子阵状态对象。"""
        return self.states.setdefault(int(sub_id), SimulatorState())

    def handle_frame(self, frame: bytes) -> list[bytes]:
        """处理一帧并返回 0 或 1 帧响应。"""
        parsed, message = protocol.parse_response(frame)
        if message != "OK" or not parsed:
            return []

        target = parsed["device_id"]
        subarray_id = target & 0x7F
        addr = parsed["addr"]
        payload = parsed["payload"]

        if target == 0:
            if addr in protocol.CONFIG_ECHO_ADDRS:
                for current_id in self.ids:
                    self._record_config(current_id, addr, payload)
            return []

        if subarray_id not in self.ids:
            return []

        if addr == protocol.ADDR_STATUS_QUERY:
            return [self.build_status_response(subarray_id)]
        if addr in protocol.CONFIG_ECHO_ADDRS:
            self._record_config(subarray_id, addr, payload)
            return [bytes(frame)]
        return []

    def _record_config(self, sub_id: int, addr: int, payload: bytes) -> None:
        """把有效配置写入子阵状态。"""
        state = self.state_for(sub_id)
        if addr == protocol.ADDR_RX_BEAM and len(payload) >= 5:
            try:
                freq_code, pol_byte, beam_h, beam_v = protocol.unpack_beam_payload(payload)
            except ValueError:
                return
            state.freq_code = freq_code
            state.pol_byte = pol_byte
            state.beam_h = beam_h
            state.beam_v = beam_v
        elif addr == protocol.ADDR_RX_ENABLE and len(payload) >= 4:
            # 低 12 bit 强制 0xFFF；高 16 bit 为 en_row
            state.en_row = ((payload[0] & 0x0F) << 12) | (payload[1] << 4) | ((payload[2] >> 4) & 0x0F)
        elif addr == protocol.ADDR_RX_PHASE_CAL and len(payload) >= 4:
            state.ps_align = payload[3] & 0x3F

    def build_status_response(self, sub_id: int) -> bytes:
        """构造可区分多子阵的状态响应；电压与温度随子阵 ID 漂移便于观察。"""
        sub_id = int(sub_id) & 0x7F
        state = self.state_for(sub_id)
        # 电压基准 11.9V，子阵每多一个加 0.05V
        voltage_raw = int(round((11.9 + 0.05 * (sub_id - 1)) * 10))
        # 温度基准 30℃，子阵每多一个加 1℃
        temp_raw = 110 + (sub_id - 1)
        return protocol.build_status_response_frame(
            sub_id,
            rev=0,
            sys_vcc_raw=max(0, min(255, voltage_raw)),
            sys_temp_raw=max(0, min(255, temp_raw)),
            mcu_ver=state.beam_h & 0xFF,
        )


class KUR512SerialSimulator:
    """将纯模拟内核挂接到一个实际或虚拟串口。"""

    def __init__(
        self,
        port: str,
        ids: Optional[Iterable[int]] = None,
        baudrate: int = 460800,
    ) -> None:
        """创建串口模拟器。

        Args:
            port: 实体或虚拟串口名。
            ids: 可响应的子阵 ID。
            baudrate: 串口波特率。
        """
        self.port = port
        self.baudrate = int(baudrate)
        self.engine = KUR512Simulator(ids)
        self.stream = KUR512StreamParser()
        self.running = False
        self.serial = None

    def start(self) -> None:
        """阻塞运行串口收发循环；``stop`` 或串口关闭后退出。"""
        import serial

        self.serial = serial.Serial(self.port, self.baudrate, timeout=0.005)
        self.running = True
        try:
            while self.running and self.serial.is_open:
                count = self.serial.in_waiting
                if not count:
                    time.sleep(0.0001)
                    continue
                data = self.serial.read(count)
                for event in self.stream.feed(data):
                    if not event.is_frame:
                        continue
                    for response in self.engine.handle_frame(event.raw):
                        self.serial.write(response)
        finally:
            self.running = False
            if self.serial and self.serial.is_open:
                self.serial.close()

    def stop(self) -> None:
        """请求停止模拟器并关闭串口。"""
        self.running = False
        if self.serial and self.serial.is_open:
            self.serial.close()


SerialSimulator = KUR512SerialSimulator


def main() -> None:
    """启动 KuR512B 串口模拟器；通过 ``run.sh kur512-sim`` 或 ``run.bat`` 间接调用。"""
    parser = argparse.ArgumentParser(description="KuR512B serial simulator")
    parser.add_argument("port", nargs="?", default="COM14")
    parser.add_argument("--ids", default="1,2,3", help="逗号分隔的子阵 ID，支持十进制或 0x 前缀")
    parser.add_argument("--baudrate", type=int, default=460800)
    args = parser.parse_args()
    ids = [int(item.strip(), 0) for item in args.ids.split(",") if item.strip()]

    simulator = KUR512SerialSimulator(args.port, ids, args.baudrate)
    thread = threading.Thread(target=simulator.start, daemon=True)
    print(f"KuR512B simulator: {args.port} @ {args.baudrate}")
    print(f"Subarray IDs: {ids}")
    try:
        thread.start()
        while thread.is_alive():
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        simulator.stop()
        thread.join(timeout=2.0)


if __name__ == "__main__":
    main()


__all__ = [
    "ADDR_ID_UPDATE",
    "ADDR_RX_BEAM",
    "ADDR_RX_ENABLE",
    "ADDR_RX_PHASE_CAL",
    "ADDR_STATUS_QUERY",
    "FRAME_HEADER",
    "KUR512SerialSimulator",
    "KUR512Simulator",
    "SerialSimulator",
]
