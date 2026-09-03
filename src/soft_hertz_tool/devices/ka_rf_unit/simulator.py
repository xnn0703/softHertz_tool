#!/usr/bin/env python3
"""KA_RF_UNIT 串口模拟器。

仅供无硬件联调：复用正式 :mod:`soft_hertz_tool.devices.ka_rf_unit.protocol`
编解码，按 ``report_hz`` 主动发送 ``0x30 STATUS_REPORT``，并按协议结果码
应答 7 个控制命令。
"""

from __future__ import annotations

import argparse
import time

from soft_hertz_tool.devices.ka_rf_unit import protocol
from soft_hertz_tool.devices.ka_rf_unit.stream import FrameStreamParser


DEFAULT_REPORT_HZ = 50
MIN_PERIOD_S = 0.005


class KaRfUnitDeviceSimulator:
    """维护 RF 状态并通过同一串口接收控制与发送状态上报。"""

    def __init__(self, serial_port) -> None:
        """创建使用给定串口对象的 KA_RF_UNIT 模拟器。

        Args:
            serial_port: 提供 ``read``、``write`` 和 ``in_waiting`` 的串口对象。
        """
        self.serial = serial_port
        self.parser = FrameStreamParser()
        self.started = time.monotonic()
        self.report_hz = DEFAULT_REPORT_HZ
        self.tx_enabled = False
        self.rx_enabled = False
        self.pa_enabled = False
        self.rx_rf_mhz = 19966
        self.rx_lo_mhz = 19250
        self.tx_rf_mhz = 29500
        self.tx_lo_mhz = 28050
        self.rx_att_x10 = 0
        self.tx_att_x10 = 0
        self.ext_ref_mhz = 100
        self.rx_polar = protocol.POLAR_RIGHT_CIRCLE
        self.tx_polar = protocol.POLAR_LEFT_CIRCLE
        self.tx_beam_h = 0
        self.tx_beam_v = 0
        self.rx_beam_h = 0
        self.rx_beam_v = 0
        self.unit_sw = 0x0100
        self.running = False

    def _status_payload(self) -> bytes:
        """按当前状态生成 43 B STATUS_REPORT payload。

        Returns:
            解码校验通过的完整 STATUS_REPAY payload 字节。
        """
        uptime_ms = int((time.monotonic() - self.started) * 1000) & 0xFFFFFFFF
        lock_mask = 0x0007 if self.ext_ref_mhz else 0x0001
        payload = protocol.build_status_report(
            uptime_ms=uptime_ms,
            conv_lock_mask=lock_mask,
            pa_enable=self.pa_enabled,
            tx_enable=self.tx_enabled,
            rx_enable=self.rx_enabled,
            status_report_rate_hz=self.report_hz,
            unit_sw=self.unit_sw,
            rx_rf_mhz=self.rx_rf_mhz,
            rx_lo_mhz=self.rx_lo_mhz,
            tx_rf_mhz=self.tx_rf_mhz,
            tx_lo_mhz=self.tx_lo_mhz,
            rx_conv_att_x10=self.rx_att_x10,
            tx_conv_att_x10=self.tx_att_x10,
            ext_ref_mhz=self.ext_ref_mhz,
            conv_temp_x10=350,
            tx_array_temp_x10=410,
            rx_array_temp_x10=405,
            tx_beam_h=self.tx_beam_h,
            tx_beam_v=self.tx_beam_v,
            rx_beam_h=self.rx_beam_h,
            rx_beam_v=self.rx_beam_v,
            rx_polar=self.rx_polar,
            tx_polar=self.tx_polar,
        )
        # 提取 payload 部分。
        length = payload[5]
        return payload[protocol.FRAME_HEADER_SIZE:protocol.FRAME_HEADER_SIZE + length]

    def _write_status_frame(self) -> None:
        """写入完整 ``0x30 STATUS_REPORT`` 帧。"""
        self.serial.write(protocol.encode_frame(protocol.CMD_STATUS_REPORT, self._status_payload()))

    def _write_response(self, command: int, result: int) -> None:
        """发送 ``0x90..0xA0`` 响应帧。"""
        response_cmd = command | 0x80
        self.serial.write(protocol.encode_frame(response_cmd, bytes([result])))

    def _apply_set_conv_freq(self, payload: bytes) -> int:
        """处理 ``0x10 SET_CONV_FREQ`` 载荷并返回结果码。"""
        if len(payload) != 10:
            return protocol.RESULT_BAD_LENGTH
        rx_rf = protocol.be16_read(payload, 0)
        rx_lo = protocol.be16_read(payload, 2)
        tx_rf = protocol.be16_read(payload, 4)
        tx_lo = protocol.be16_read(payload, 6)
        rx_polar = payload[8]
        tx_polar = payload[9]
        if not protocol.rx_rf_valid(rx_rf) or not protocol.tx_rf_valid(tx_rf):
            return protocol.RESULT_OUT_OF_RANGE
        if not protocol.rx_lo_valid(rx_lo) or not protocol.tx_lo_valid(tx_lo):
            return protocol.RESULT_OUT_OF_RANGE
        if rx_polar not in (protocol.POLAR_LEFT_CIRCLE, protocol.POLAR_RIGHT_CIRCLE):
            return protocol.RESULT_OUT_OF_RANGE
        if tx_polar not in (protocol.POLAR_LEFT_CIRCLE, protocol.POLAR_RIGHT_CIRCLE):
            return protocol.RESULT_OUT_OF_RANGE
        self.rx_rf_mhz = rx_rf
        self.rx_lo_mhz = rx_lo
        self.tx_rf_mhz = tx_rf
        self.tx_lo_mhz = tx_lo
        self.rx_polar = rx_polar
        self.tx_polar = tx_polar
        return protocol.RESULT_OK

    def _apply_set_conv_att(self, payload: bytes) -> int:
        """处理 ``0x11 SET_CONV_ATT`` 载荷并返回结果码。"""
        if len(payload) != 4:
            return protocol.RESULT_BAD_LENGTH
        rx_att = protocol.be16_read(payload, 0)
        tx_att = protocol.be16_read(payload, 2)
        if not protocol.conv_att_valid(rx_att) or not protocol.conv_att_valid(tx_att):
            return protocol.RESULT_OUT_OF_RANGE
        self.rx_att_x10 = rx_att
        self.tx_att_x10 = tx_att
        return protocol.RESULT_OK

    def _apply_set_tx_en(self, payload: bytes) -> int:
        """处理 ``0x12 SET_TX_EN`` 载荷并返回结果码。"""
        if len(payload) != 1:
            return protocol.RESULT_BAD_LENGTH
        self.tx_enabled = bool(payload[0])
        # 按硬件合同：TX 阵列开启后才允许 PA；关闭 TX 时关闭 PA。
        if self.tx_enabled:
            self.pa_enabled = True
        else:
            self.pa_enabled = False
        return protocol.RESULT_OK

    def _apply_set_rx_en(self, payload: bytes) -> int:
        """处理 ``0x13 SET_RX_EN`` 载荷并返回结果码。"""
        if len(payload) != 1:
            return protocol.RESULT_BAD_LENGTH
        self.rx_enabled = bool(payload[0])
        return protocol.RESULT_OK

    def _apply_set_beam(self, payload: bytes) -> int:
        """处理 ``0x14 SET_BEAM`` 载荷并返回结果码。"""
        if len(payload) != 9:
            return protocol.RESULT_BAD_LENGTH
        target = payload[0]
        if target & ~protocol.BEAM_TARGET_ALL or target == 0:
            return protocol.RESULT_OUT_OF_RANGE
        beams = (
            protocol.be16_read(payload, 1),
            protocol.be16_read(payload, 3),
            protocol.be16_read(payload, 5),
            protocol.be16_read(payload, 7),
        )
        if any(b > protocol.BEAM_CODE_MAX for b in beams):
            return protocol.RESULT_OUT_OF_RANGE
        self.tx_beam_h, self.tx_beam_v, self.rx_beam_h, self.rx_beam_v = beams
        return protocol.RESULT_OK

    def _apply_set_ext_ref(self, payload: bytes) -> int:
        """处理 ``0x15 SET_EXT_REF`` 载荷并返回结果码。"""
        if len(payload) != 2:
            return protocol.RESULT_BAD_LENGTH
        ref = protocol.be16_read(payload, 0)
        if not protocol.ext_ref_valid(ref):
            return protocol.RESULT_OUT_OF_RANGE
        self.ext_ref_mhz = ref
        return protocol.RESULT_OK

    def _apply_set_report_hz(self, payload: bytes) -> int:
        """处理 ``0x20 SET_REPORT_HZ`` 载荷并返回结果码。"""
        if len(payload) != 2:
            return protocol.RESULT_BAD_LENGTH
        rate = protocol.be16_read(payload, 0)
        if rate > 200:
            return protocol.RESULT_OUT_OF_RANGE
        self.report_hz = rate
        return protocol.RESULT_OK

    def process_input(self, data: bytes) -> None:
        """解析串口输入并对每个有效控制命令返回响应。"""
        for event in self.parser.feed(data):
            if event.kind != "frame" or not event.parsed:
                continue
            command = event.parsed["command"]
            payload = event.parsed["payload"]
            if command == protocol.CMD_SET_CONV_FREQ:
                result = self._apply_set_conv_freq(payload)
            elif command == protocol.CMD_SET_CONV_ATT:
                result = self._apply_set_conv_att(payload)
            elif command == protocol.CMD_SET_TX_EN:
                result = self._apply_set_tx_en(payload)
            elif command == protocol.CMD_SET_RX_EN:
                result = self._apply_set_rx_en(payload)
            elif command == protocol.CMD_SET_BEAM:
                result = self._apply_set_beam(payload)
            elif command == protocol.CMD_SET_EXT_REF:
                result = self._apply_set_ext_ref(payload)
            elif command == protocol.CMD_SET_REPORT_HZ:
                result = self._apply_set_report_hz(payload)
            else:
                # 0x30 等其它命令不响应。
                continue
            self._write_response(command, result)

    def run(self, duration: float = 0.0) -> None:
        """以目标 ``report_hz`` 发送 0x30 并处理控制命令。

        Args:
            duration: 运行时长，单位为秒；零表示持续运行至 ``stop``。
        """
        self.running = True
        end = time.monotonic() + duration if duration > 0 else None
        if self.report_hz <= 0:
            period = None
        else:
            period = 1.0 / self.report_hz
        deadline = time.monotonic() + period if period is not None else None

        while self.running and (end is None or time.monotonic() < end):
            count = self.serial.in_waiting
            if count:
                self.process_input(self.serial.read(count))
            if deadline is None:
                time.sleep(0.001)
                continue
            now = time.monotonic()
            if now >= deadline:
                self._write_status_frame()
                sent_at = time.monotonic()
                deadline += period
                if deadline <= sent_at:
                    missed = int((sent_at - deadline) / period) + 1
                    deadline += missed * period
                deadline = max(deadline, sent_at + MIN_PERIOD_S)
            time.sleep(min(0.001, max(0.0, deadline - time.monotonic())))

    def stop(self) -> None:
        """请求 ``run`` 循环在下一次条件检查时退出。"""
        self.running = False


def main() -> None:
    """解析命令行串口参数并启动 KA_RF_UNIT 模拟器。"""
    import serial

    parser = argparse.ArgumentParser(description="KA_RF_UNIT V1 serial simulator")
    parser.add_argument("port", help="串口或 PTY 路径")
    parser.add_argument("--baudrate", type=int, default=460800)
    parser.add_argument("--report-hz", type=int, default=DEFAULT_REPORT_HZ,
                        help="STATUS_REPORT 主动上报频率，0 表示关闭")
    args = parser.parse_args()
    with serial.Serial(args.port, args.baudrate, timeout=0) as port:
        print(f"KA_RF_UNIT simulator: {args.port} @ {args.baudrate}, report={args.report_hz} Hz")
        sim = KaRfUnitDeviceSimulator(port)
        sim.report_hz = args.report_hz
        try:
            sim.run()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()