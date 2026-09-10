"""POSIX 真实伪终端闭环；可用环境变量把短回归延长至 60 秒。"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from soft_hertz_tool.devices.afdtr1024.driver import AFDTR1024Driver
from soft_hertz_tool.devices.afdtr1024.models import DeviceVariant
from soft_hertz_tool.devices.afdtr1024.simulator import AFDTR1024Simulator
from soft_hertz_tool.devices.afdtr1024.stream import AFDTR1024StreamParser
from soft_hertz_tool.devices.afdtr1024.traffic import TrafficConfig


@pytest.mark.parametrize('beam_mode', ['broadcast', 'addressed', 'addressed_stream'])
@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX PTY 不代表 Windows 串口验收')
def test_both_variants_real_pty_with_fragmented_replies(tmp_path, beam_mode):
    import pty
    import select
    import tty

    app = QApplication.instance() or QApplication([])
    seconds = float(os.environ.get('SOFTHERTZ_TRAFFIC_PTY_SECONDS', '2.2'))
    assert seconds >= 2.2
    stop = threading.Event()
    jobs = []
    errors = []

    def serve(master, simulator):
        parser = AFDTR1024StreamParser()
        try:
            while not stop.is_set():
                if not select.select([master], [], [], 0.05)[0]:
                    continue
                for event in parser.feed(os.read(master, 65536)):
                    assert event.is_frame, event.reason
                    for response in simulator.handle_frame(event.raw):
                        os.write(master, response[:4])
                        time.sleep(0.001)
                        os.write(master, response[4:])
        except Exception as exc:
            errors.append(repr(exc))

    try:
        for variant in DeviceVariant:
            master, slave = pty.openpty()
            tty.setraw(slave)
            worker = threading.Thread(target=serve, args=(master, AFDTR1024Simulator(variant, [1])), daemon=True)
            # macOS PTY 不支持 460800 自定义波特率 ioctl；PTY 的 115200 不是线路速率证据。
            driver = AFDTR1024Driver(os.ttyname(slave), 115200, variant)
            jobs.append((driver, worker, master, slave))
            worker.start()
            driver.start()
            deadline = time.monotonic() + 3
            while not driver.running and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.002)
            assert driver.running
            driver.start_traffic(TrafficConfig(duration_min=seconds / 60, beam_mode=beam_mode),
                                 27500 if variant.is_tx else 20270, 0, 0, directory=tmp_path)
        deadline = time.monotonic() + seconds + 5
        while any(driver._traffic_owned for driver, *_ in jobs) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        for driver, *_ in jobs:
            assert not driver._traffic_owned
            assert driver.stop()
            summary = json.loads((driver._traffic_recorder.directory / 'summary.json').read_text())
            counts = summary['counts']
            assert summary['reason'] == 'duration'
            assert counts['queries_written'] == counts['matched_replies'] >= 4
            assert counts['beams_written'] > 100
            if beam_mode != 'broadcast':
                assert counts['beams_written'] == counts['beam_matched_replies'] + counts.get('beam_cancelled', 0)
                assert not counts.get('beam_timeouts', 0)
            assert not counts.get('timeouts', 0) and not counts.get('abnormal_replies', 0)
            assert summary['evidence_complete'] and summary['recording_finished']
        assert not errors
    finally:
        stop.set()
        for driver, worker, master, slave in jobs:
            driver.stop()
            if worker.ident is not None:
                worker.join(1)
            os.close(master)
            os.close(slave)
            assert not worker.is_alive()
        app.processEvents()
