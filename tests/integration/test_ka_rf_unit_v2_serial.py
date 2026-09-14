"""真实 SerialThread + macOS/Linux PTY 软件闭环，不接触物理设备。"""
import binascii
import os
import select
import struct
import sys
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from soft_hertz_tool.devices.ka_rf_unit import protocol as p
from soft_hertz_tool.devices.ka_rf_unit.driver import KaRfUnitDriver
from soft_hertz_tool.devices.ka_rf_unit.simulator import KaRfUnitDeviceSimulator
from soft_hertz_tool.devices.ka_rf_unit.stream import FrameStreamParser

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="PTY 闭环只适用于 macOS/Linux")


class Receiver:
    def __init__(self, master, ota):
        self.master, self.ota = master, ota
        self.parser = FrameStreamParser()
        self.simulator = KaRfUnitDeviceSimulator(self)
        self.stage = "PSA"
        self.buffer = bytearray()
        self.received = bytearray()
        self.requests = []
        self.sequence = 1
        self.version = (0, 2, 0)
        self.errors = []
        self.closed = threading.Event()
        self.recovered = False

    def write(self, data):
        return os.write(self.master, data)

    def run(self):
        try:
            while not self.closed.is_set():
                if not select.select([self.master], [], [], 0.01)[0]:
                    continue
                chunk = os.read(self.master, 4096)
                if self.stage == "PSA":
                    for event in self.parser.feed(chunk):
                        assert event.kind == "frame", event
                        command = event.parsed["command"]
                        self.requests.append(command)
                        if command == p.CMD_OTA_STATUS and self.ota:
                            health = 1 if self.version == (0, 2, 0) or self.recovered else 0
                            self.write(p.encode_frame(p.RES_OTA_STATUS, struct.pack(
                                ">BBHHHBBBB", 0, 0, *self.version, health, 0, 0, 0)))
                            if self.version == (0, 3, 0):
                                self.recovered = True
                        elif command == p.CMD_OTA_BEGIN and self.ota:
                            assert event.parsed["payload"] == b""
                            self.stage = "HEADER"
                            self.write(p.encode_frame(p.RES_OTA_BEGIN, b"\x00") + b"C")
                        else:
                            self.simulator.process_input(event.data)
                else:
                    self.buffer.extend(chunk)
                    self.consume_raw()
        except BaseException as exc:
            self.errors.append(exc)

    def consume_raw(self):
        while self.buffer:
            if self.buffer[0] == 4:
                assert self.stage in ("DATA", "EOT2")
                del self.buffer[0]
                if self.stage == "DATA":
                    self.stage = "EOT2"
                    self.write(b"\x15")
                else:
                    self.stage = "END"
                    self.write(b"\x06C")
                continue
            assert self.buffer[0] in (1, 2), bytes(self.buffer[:6])
            size = 128 if self.buffer[0] == 1 else 1024
            if len(self.buffer) < size + 5:
                return
            packet = bytes(self.buffer[:size + 5])
            del self.buffer[:size + 5]
            assert packet[1] ^ packet[2] == 255
            assert binascii.crc_hqx(packet[3:-2], 0) == int.from_bytes(packet[-2:], "big")
            if self.stage == "HEADER":
                assert packet[1] == 0
                fields = packet[3:-2].split(b"\x00")
                assert fields[0] == b"ka_rf_unit_app_0.3.0_release.bin"
                self.size = int(fields[1])
                self.stage = "DATA"
                self.write(b"\x06C")
            elif self.stage == "DATA":
                assert packet[1] == self.sequence
                self.sequence = (self.sequence + 1) & 255
                self.received.extend(packet[3:3 + min(size, self.size - len(self.received))])
                self.write(b"\x06")
            else:
                assert self.stage == "END" and packet[1] == 0 and packet[3:-2] == bytes(128)
                self.stage = "PSA"
                self.version = (0, 3, 0)
                # 故意丢最后 ACK：上位机应恢复查询，不得重发裸末包。


def wait_for(app, predicate, timeout=6):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "等待软件串口闭环超时"


@pytest.mark.parametrize("ota", [False, True])
def test_real_serial_thread_pty_setting_query_and_auto_install(ota):
    import tty
    app = QApplication.instance() or QApplication([])
    master, slave = os.openpty()
    tty.setraw(slave)
    receiver = Receiver(master, ota)
    worker = threading.Thread(target=receiver.run)
    # macOS PTY 不支持 IOSSIOSPEED 自定义波特率；虚拟端口无物理线速。
    driver = KaRfUnitDriver(os.ttyname(slave), 38400)
    driver.set_query_hz(0)
    statuses, outcomes, records = [], [], []
    driver.status_signal.connect(statuses.append)
    driver.ota_event_signal.connect(lambda k, v: outcomes.append((k, v)))
    driver.frame_signal.connect(records.append)
    worker.start()
    driver.start()
    try:
        wait_for(app, lambda: driver.running)
        if ota:
            content = bytes(range(256)) * 5
            assert driver.start_ota(filename="ka_rf_unit_app_0.3.0_release.bin", data=content)
            wait_for(app, lambda: any(k == "state" and v == "DONE" for k, v in outcomes))
            assert receiver.received == content
            assert receiver.recovered
            assert 0x22 not in receiver.requests
            assert any(r.command == "YMODEM" for r in records)
        else:
            assert driver.set_conv_att(12.5, 4.5)
            assert driver.query_status()
            wait_for(app, lambda: bool(statuses))
            assert statuses[-1]["rx_conv_att_x10"] == 125
            assert statuses[-1]["tx_conv_att_x10"] == 45
        assert not receiver.errors
    finally:
        assert driver.stop()
        receiver.closed.set()
        worker.join(timeout=1)
        os.close(master)
        os.close(slave)
        driver.deleteLater()
        app.processEvents()
    assert not worker.is_alive()
