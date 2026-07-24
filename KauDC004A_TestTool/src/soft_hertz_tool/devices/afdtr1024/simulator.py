"""复用正式协议的 AFDT1024/AFDR1024 状态型模拟器。"""

from __future__ import annotations

import time
import argparse
import threading
from dataclasses import asdict
from typing import Iterable, Optional, Union

from soft_hertz_tool.devices.afdtr1024 import protocol
from soft_hertz_tool.devices.afdtr1024.models import DeviceVariant, SimulatorState
from soft_hertz_tool.devices.afdtr1024.stream import AFDTR1024StreamParser

# 兼容旧测试/脚本的协议常量导入；真值仍只来自 protocol.py。
FRAME_HEADER = protocol.FRAME_HEADER
ADDR_TX_BEAM = protocol.ADDR_TX_BEAM
ADDR_TX_ENABLE = protocol.ADDR_TX_ENABLE
ADDR_TX_POLARIZATION = protocol.ADDR_TX_POLARIZATION
ADDR_PA_ENABLE = protocol.ADDR_PA_ENABLE
ADDR_STATUS_QUERY = protocol.ADDR_STATUS_QUERY
ADDR_TX_BEAM_QUERY = protocol.ADDR_TX_BEAM_QUERY
ADDR_RX_BEAM = protocol.ADDR_RX_BEAM
ADDR_RX_ENABLE = protocol.ADDR_RX_ENABLE
ADDR_RX_POLARIZATION = protocol.ADDR_RX_POLARIZATION
ADDR_RX_STATUS_QUERY = protocol.ADDR_RX_STATUS_QUERY
ADDR_RX_BEAM_QUERY = protocol.ADDR_RX_BEAM_QUERY


def record_config(states: dict, sub_id: int, addr: int, payload: bytes) -> None:
    """旧模拟器辅助函数兼容层，协议字段解析复用正式模块。"""

    state = states.setdefault(
        sub_id,
        {"pol": 0, "en_row": 0, "freq_code": 0, "beam_v": 0, "beam_h": 0, "pa_en": 1},
    )
    if isinstance(state, SimulatorState):
        target = state
    else:
        target = None
    if addr in (ADDR_TX_BEAM, ADDR_RX_BEAM):
        try:
            freq_code, beam_h, beam_v = protocol.unpack_beam_payload(payload)
        except ValueError:
            return
        values = {"freq_code": freq_code, "beam_h": beam_h, "beam_v": beam_v}
    elif addr in (ADDR_TX_ENABLE, ADDR_RX_ENABLE) and len(payload) >= 2:
        values = {"en_row": (payload[0] << 8) | payload[1]}
    elif addr in (ADDR_TX_POLARIZATION, ADDR_RX_POLARIZATION) and len(payload) >= 4:
        values = {"pol": payload[3] & 0x01}
    elif addr == ADDR_PA_ENABLE and len(payload) >= 4:
        values = {"pa_en": payload[3] & 0x01}
    else:
        return
    for name, value in values.items():
        if target is not None:
            setattr(target, name, value)
        else:
            state[name] = value


def build_beam_query_response(
    device_id_byte: int,
    sub_id: int,
    states: dict,
    ret_addr: int,
) -> bytes:
    """旧查询 2 响应构造接口兼容层。"""

    state = states.get(sub_id, {})
    values = asdict(state) if isinstance(state, SimulatorState) else state
    variant = DeviceVariant.TX if ret_addr == ADDR_TX_BEAM_QUERY else DeviceVariant.RX
    return protocol.build_beam_query_response_frame(device_id_byte, variant, values)


class AFDTR1024Simulator:
    """不依赖串口的设备内核，便于配置/回读闭环测试。"""

    def __init__(
        self,
        variant: Union[DeviceVariant, str],
        ids: Optional[Iterable[int]] = None,
    ):
        self.variant = DeviceVariant.coerce(variant)
        values = list(ids) if ids is not None else [1]
        self.ids = self._normalize_ids(values)
        self.states: dict[int, SimulatorState] = {}

    @staticmethod
    def _normalize_ids(values: Iterable[int]) -> list[int]:
        result: list[int] = []
        for value in values:
            subarray_id = int(value)
            if not 1 <= subarray_id <= 0x7F:
                raise ValueError("模拟子阵 ID 必须在 0x01~0x7F 范围内")
            if subarray_id not in result:
                result.append(subarray_id)
        if not result:
            raise ValueError("至少需要一个模拟子阵 ID")
        return result

    def state_for(self, subarray_id: int) -> SimulatorState:
        return self.states.setdefault(int(subarray_id), SimulatorState())

    def handle_frame(self, frame: bytes) -> list[bytes]:
        """处理一帧并返回零帧或一帧响应。"""

        parsed, message = protocol.parse_response(frame)
        if message != "OK" or not parsed:
            return []

        target = parsed["device_id"]
        subarray_id = target & 0x7F
        addr = parsed["addr"]
        payload = parsed["payload"]

        if target == 0:
            if addr in self._config_addresses:
                for current_id in self.ids:
                    self._record_config(current_id, addr, payload)
            return []

        if subarray_id not in self.ids:
            return []

        if addr == self._status_query_address:
            return [self.build_status_response(subarray_id)]
        if addr == self._beam_query_address:
            return [self.build_beam_query_response(subarray_id)]
        if addr in self._config_addresses:
            self._record_config(subarray_id, addr, payload)
            # 配置回显保留请求中的 ID（含可选 +0x80），与现有设备模拟行为一致。
            return [bytes(frame)]
        return []

    @property
    def _config_addresses(self) -> set[int]:
        return protocol.TX_CONFIG_ADDRS if self.variant.is_tx else protocol.RX_CONFIG_ADDRS

    @property
    def _status_query_address(self) -> int:
        return protocol.ADDR_STATUS_QUERY if self.variant.is_tx else protocol.ADDR_RX_STATUS_QUERY

    @property
    def _beam_query_address(self) -> int:
        return protocol.ADDR_TX_BEAM_QUERY if self.variant.is_tx else protocol.ADDR_RX_BEAM_QUERY

    def _record_config(self, subarray_id: int, addr: int, payload: bytes) -> None:
        state = self.state_for(subarray_id)
        if addr in (protocol.ADDR_TX_BEAM, protocol.ADDR_RX_BEAM):
            try:
                state.freq_code, state.beam_h, state.beam_v = protocol.unpack_beam_payload(payload)
            except ValueError:
                return
        elif addr in (protocol.ADDR_TX_ENABLE, protocol.ADDR_RX_ENABLE) and len(payload) >= 2:
            state.en_row = (payload[0] << 8) | payload[1]
        elif addr in (protocol.ADDR_TX_POLARIZATION, protocol.ADDR_RX_POLARIZATION) and len(payload) >= 4:
            state.pol = payload[3] & 0x01
        elif addr == protocol.ADDR_PA_ENABLE and len(payload) >= 4:
            state.pa_en = payload[3] & 0x01

    def build_status_response(self, subarray_id: int) -> bytes:
        """构造可区分多子阵的查询 1 响应。"""

        subarray_id = int(subarray_id) & 0x7F
        state = self.state_for(subarray_id)
        voltage = (115 + subarray_id) & 0xFF
        if self.variant.is_tx:
            temperature = (115 + subarray_id) & 0xFF
            return protocol.build_tx_status_response_frame(
                subarray_id,
                state=state.pa_en & 0x01,
                sys_vcc_raw=voltage,
                sys_temp_raw=temperature,
            )
        temperature = (130 + subarray_id) & 0xFF
        return protocol.build_rx_status_response_frame(
            subarray_id,
            sys_vcc_raw=voltage,
            sys_temp_raw=temperature,
        )

    def build_beam_query_response(self, subarray_id: int) -> bytes:
        state = self.state_for(subarray_id)
        return protocol.build_beam_query_response_frame(
            int(subarray_id) & 0x7F,
            self.variant,
            asdict(state),
        )


class TXSimulator(AFDTR1024Simulator):
    def __init__(self, port=None, ids: Optional[Iterable[int]] = None):
        if ids is None and port is not None and not isinstance(port, str):
            ids, port = port, None
        self.port = port
        super().__init__(DeviceVariant.TX, ids)


class RXSimulator(AFDTR1024Simulator):
    def __init__(self, port=None, ids: Optional[Iterable[int]] = None):
        if ids is None and port is not None and not isinstance(port, str):
            ids, port = port, None
        self.port = port
        super().__init__(DeviceVariant.RX, ids)

    def build_rx_status_response(self, subarray_id: int) -> bytes:
        return self.build_status_response(subarray_id)


class AFDTR1024SerialSimulator:
    """将纯模拟器内核挂接到一个实际或虚拟串口。"""

    def __init__(
        self,
        port: str,
        variant: Union[DeviceVariant, str],
        ids: Optional[Iterable[int]] = None,
        baudrate: int = 460800,
    ):
        self.port = port
        self.baudrate = int(baudrate)
        self.engine = AFDTR1024Simulator(variant, ids)
        self.stream = AFDTR1024StreamParser()
        self.running = False
        self.serial = None

    def start(self) -> None:
        import serial

        self.serial = serial.Serial(self.port, self.baudrate, timeout=0.01)
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
        self.running = False
        if self.serial and self.serial.is_open:
            self.serial.close()


SerialSimulator = AFDTR1024SerialSimulator


def main() -> None:
    parser = argparse.ArgumentParser(description="AFDT1024/AFDR1024 serial simulator")
    parser.add_argument("tx_port", nargs="?", default="COM10")
    parser.add_argument("rx_port", nargs="?", default="COM11")
    parser.add_argument("--ids", default="1,2,3", help="逗号分隔的子阵 ID，支持十进制或 0x 前缀")
    parser.add_argument("--baudrate", type=int, default=460800)
    args = parser.parse_args()
    ids = [int(item.strip(), 0) for item in args.ids.split(",") if item.strip()]

    tx = AFDTR1024SerialSimulator(args.tx_port, DeviceVariant.TX, ids, args.baudrate)
    rx = AFDTR1024SerialSimulator(args.rx_port, DeviceVariant.RX, ids, args.baudrate)
    threads = [threading.Thread(target=tx.start, daemon=True), threading.Thread(target=rx.start, daemon=True)]
    print(f"AFDT1024 simulator: {args.tx_port} @ {args.baudrate}")
    print(f"AFDR1024 simulator: {args.rx_port} @ {args.baudrate}")
    print(f"Subarray IDs: {ids}")
    try:
        for thread in threads:
            thread.start()
        while all(thread.is_alive() for thread in threads):
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        tx.stop()
        rx.stop()
        for thread in threads:
            thread.join(timeout=2.0)


if __name__ == "__main__":
    main()
