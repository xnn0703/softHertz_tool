"""客户流量在实际写入、回复关联、周期恢复及面板入口处的回归。"""

import json

import pytest
from PySide6.QtWidgets import QApplication

from soft_hertz_tool.devices.afdtr1024 import protocol
from soft_hertz_tool.devices.afdtr1024.driver import AFDTR1024Driver
from soft_hertz_tool.devices.afdtr1024.models import DeviceVariant
from soft_hertz_tool.devices.afdtr1024.panel import RXPanel, TXPanel
from soft_hertz_tool.devices.afdtr1024.simulator import AFDTR1024Simulator
from soft_hertz_tool.devices.afdtr1024.stream import AFDTR1024StreamParser
from soft_hertz_tool.devices.afdtr1024.traffic import TrafficConfig, TrafficEngine
from soft_hertz_tool.devices.afdtr1024.traffic_recorder import TrafficRecorder

MS = 1_000_000


def make_engine(variant=DeviceVariant.RX, **kwargs):
    kwargs.setdefault("beam_mode", "broadcast")
    config = TrafficConfig(**kwargs)
    setting = protocol.make_beam_setting(27500 if variant.is_tx else 20270, 30, 10, variant)
    events = []
    engine = TrafficEngine(config, variant, protocol.build_beam_frame(0 if config.beam_mode == "broadcast" else config.target_id, setting, variant), 0, events.append)
    return engine, events, AFDTR1024Simulator(variant, [config.target_id])


def write(engine, now, returned=None):
    batch = engine.poll(now)
    assert batch is not None
    engine.written(batch, now, now if returned is None else returned, len(batch.raw))
    return batch


def reply(engine, simulator, batch, now):
    response = simulator.handle_frame(batch.frames[-1])[0]
    engine.received(response, now, now)
    return response


@pytest.mark.parametrize('variant', list(DeviceVariant))
@pytest.mark.parametrize('query_type', ['both', 'status', 'beam'])
def test_zero_gap_serializes_queries_and_matches_reply(variant, query_type):
    e, events, sim = make_engine(variant, query_type=query_type)
    b = write(e, 0)
    assert b.frames[0][3] == 0 and sim.handle_frame(b.raw) == []
    b = write(e, 1000 * MS)
    assert len(b.frames) == 2 and b.frames[0][3] == 0 and b.frames[1][3] == 1
    assert e.poll(1001 * MS) is None
    reply(e, sim, b, 1001 * MS)
    if query_type == 'both':
        assert e.poll(1002 * MS) is None
        second = write(e, 1003 * MS)
        assert len(second.frames) == 1 and not second.has_beam
        assert e.poll(1004 * MS) is None
        reply(e, sim, second, 1005 * MS)
    assert e.poll(1006 * MS) is None
    assert write(e, 1010 * MS).has_beam
    expected = 2 if query_type == 'both' else 1
    assert e.counts['matched_replies'] == expected
    assert e.counts['queries_written'] == expected
    combined = [ev for ev in events if ev['event'] == 'write' and ev['frame_count'] == 2][0]
    assert combined['host_gap_ns'] is None and combined['line_gap_ns'] is None


@pytest.mark.parametrize('mode', ['fixed', 'random'])
def test_gap_deadline_and_seed(mode):
    e, events, sim = make_engine(gap_mode=mode, gap_ms=4, random_min_ms=1, random_max_ms=5, seed=42)
    e2, events2, _ = make_engine(gap_mode=mode, gap_ms=4, random_min_ms=1, random_max_ms=5, seed=42)
    for engine in (e, e2):
        b = write(engine, 1000 * MS, 1001 * MS)
        assert len(b.frames) == 1
    assert e.gap_ns == e2.gap_ns
    assert MS <= e.gap_ns <= 5 * MS
    assert e.poll(e.due_ns - 1) is None
    due = e.due_ns
    b = write(e, due)
    assert b.query_index == 0 and not b.has_beam
    assert events[-1]['host_gap_ns'] == e.gap_ns


def test_timeout_skip_no_catchup_and_late_frame():
    e, events, sim = make_engine(timeout_ms=2500, query_type='status')
    b = write(e, 1000 * MS)
    response = sim.handle_frame(b.frames[-1])[0]
    e.received(response, 3500 * MS, 3500 * MS)
    assert e.counts['timeouts'] == 1 and e.counts['abnormal_replies'] == 1
    assert e.counts['matched_replies'] == 0
    assert e.next_query == 4000 * MS and e.next_beam == 3510 * MS
    assert e.poll(3500 * MS) is None
    assert write(e, 3510 * MS).has_beam
    assert e.poll(3510 * MS) is None
    assert e.counts['skipped_queries'] == 2


@pytest.mark.parametrize('kind', ['wrong_id', 'wrong_command', 'loopback', 'short', 'long', 'checksum', 'beam'])
def test_abnormal_replies_never_unlock(kind):
    e, _, sim = make_engine()
    b = write(e, 1000 * MS)
    good = sim.handle_frame(b.frames[-1])[0]
    payload = protocol.parse_response(good)[0]['payload']
    frame = {'wrong_id': protocol.build_frame(2, 0x9C, payload),
             'wrong_command': sim.build_beam_query_response(1), 'loopback': b.frames[-1],
             'short': protocol.build_frame(1, 0x9C, payload[:-1]),
             'long': protocol.build_frame(1, 0x9C, payload + b'\0'),
             'checksum': good[:-1] + bytes([good[-1] ^ 1]), 'beam': e.beam}[kind]
    e.received(frame, 1001 * MS, 1001 * MS)
    assert e.phase == 'wait' and e.counts['matched_replies'] == 0
    assert e.counts['abnormal_replies'] == 1
    e.received(good, 1002 * MS, 1002 * MS)
    assert e.counts['matched_replies'] == 1
    e.received(good, 1002 * MS, 1002 * MS)
    assert e.counts['abnormal_replies'] == 2


@pytest.mark.parametrize('variant', list(DeviceVariant))
def test_every_split_of_broadcast_query_and_fragmented_response(variant):
    e, _, sim = make_engine(variant, query_type='status')
    b = write(e, 1000 * MS)
    for split in range(len(b.raw) + 1):
        parser = AFDTR1024StreamParser()
        events = parser.feed(b.raw[:split]) + parser.feed(b.raw[split:])
        responses = [response for ev in events if ev.is_frame for response in sim.handle_frame(ev.raw)]
        assert len(responses) == 1
    parser = AFDTR1024StreamParser()
    response = sim.handle_frame(b.frames[-1])[0]
    for byte in response[:-1]:
        assert parser.feed(bytes([byte])) == []
        assert e.phase == 'wait'
    parsed = parser.feed(response[-1:])
    e.received(parsed[0].raw, 1001 * MS, 1001 * MS)
    assert e.counts['matched_replies'] == 1


@pytest.mark.parametrize('count,error', [(1, ''), (0, 'I/O failure')])
def test_failed_write_is_not_counted_or_retried(count, error):
    e, events, _ = make_engine()
    b = e.poll(1000 * MS)
    e.written(b, 1001 * MS, 1004 * MS, count, error)
    assert not e.active and e.counts['write_failures'] == 1
    assert not e.counts['beams_written'] and not e.counts['queries_written']
    assert e.poll(2000 * MS) is None
    assert events[-2]['write_start_ns'] == 1001 * MS


def test_timeout_uses_write_return_and_stop_cancels():
    e, _, sim = make_engine(query_type='status')
    b = write(e, 1000 * MS, 1050 * MS)
    assert e.poll(1100 * MS) is None
    e.stop('cancelled', 1101 * MS)
    assert e.counts['cancelled'] == 1 and not e.counts['timeouts']
    e.stop('cancelled', 1102 * MS)
    assert e.counts['cancelled'] == 1 and e.poll(2000 * MS) is None


@pytest.mark.parametrize('phase', ['beam', 'gap', 'wait', 'writing'])
def test_duration_stops_every_stage(phase):
    e, _, _ = make_engine(duration_min=0.02, gap_mode='fixed' if phase == 'gap' else 'zero', gap_ms=500)
    if phase == 'writing':
        e.poll(1000 * MS)
    elif phase != 'beam':
        write(e, 1000 * MS)
    e.poll(1200 * MS)
    assert not e.active and e.reason == 'duration'


@pytest.mark.parametrize('kwargs', [{'beam_period_ms': 0}, {'timeout_ms': float('nan')}, {'target_id': 0},
                                   {'query_type': 'bad'}, {'random_min_ms': 6}, {'duration_min': -1}])
def test_invalid_config(kwargs):
    with pytest.raises(ValueError):
        TrafficConfig(**kwargs).validate()


class FakeSerial:
    is_open = True

    def __init__(self):
        self.writes = []

    def write(self, raw):
        self.writes.append(raw)
        return len(raw)


def test_driver_real_write_boundary_excludes_manual_and_updates_reply(tmp_path):
    driver = AFDTR1024Driver('FAKE', 460800, DeviceVariant.RX)
    driver.running = True
    driver.serial = FakeSerial()
    run_id = driver.start_traffic(TrafficConfig(query_period_ms=0.1, beam_mode="broadcast"), 20270, 0, 0, directory=tmp_path)
    assert not driver.send_bytes(b'ordinary')
    with pytest.raises(ConnectionError):
        driver.set_array_enabled(1, True)
    driver._flush_tx()
    engine = driver._traffic_engine
    engine.next_query = engine.next_beam = engine.due_ns = 0
    driver._flush_tx()
    assert len(driver.serial.writes[-1]) == 18
    sim = AFDTR1024Simulator(DeviceVariant.RX, [1])
    response = sim.build_status_response(1)
    driver.handle_bytes(b'junk' + response[:4])
    assert engine.phase == 'wait'
    driver.handle_bytes(response[4:])
    assert engine.counts['matched_replies'] == 1 and engine.counts['drops'] > 0
    driver.stop_traffic()
    driver._flush_tx()
    driver.on_loop_stopped()
    assert driver._traffic_recorder.close()
    summary = json.loads((tmp_path / run_id / 'summary.json').read_text(encoding="utf-8"))
    assert summary['counts']['matched_replies'] == 1
    events = [json.loads(l) for l in (tmp_path / run_id / 'events.jsonl').read_text(encoding="utf-8").splitlines()]
    actual = [ev for ev in events if ev['event'] == 'write']
    assert len(actual) == len(driver.serial.writes)
    assert all(ev['write_return_ns'] >= ev['write_start_ns'] for ev in actual)
    assert driver.stop()


def test_start_refuses_old_queue_and_old_scheduled_callback(tmp_path):
    d = AFDTR1024Driver('FAKE', 460800, DeviceVariant.TX)
    d.running = True
    d.send_bytes(b'old')
    with pytest.raises(ConnectionError):
        d.start_traffic(TrafficConfig(), 27500, 0, 0, directory=tmp_path)
    d._tx_queue.get_nowait()
    generation = d._schedule_generation
    d.start_traffic(TrafficConfig(), 27500, 0, 0, directory=tmp_path)
    d._send_scheduled(b'late', generation)
    assert d._tx_queue.empty()
    d.on_loop_stopped()
    assert d.stop()


@pytest.mark.parametrize('panel_class,frequency,addresses', [(TXPanel, 27500, '0x5C'), (RXPanel, 20270, '0x9C')])
def test_panel_button_semantic_boundary_and_freeze(panel_class, frequency, addresses):
    app = QApplication.instance() or QApplication([])
    p = panel_class()
    calls = []

    class Driver:
        running = True

        def start_traffic(self, config, freq, theta, phi):
            calls.append((config, freq, theta, phi))
            return 'test-run'

        def stop(self):
            return True

        def deleteLater(self):
            pass

    p.driver = Driver()
    p.traffic.start_button.click()
    assert len(calls) == 1
    assert calls[0][1:] == (frequency, 0, 0)
    assert calls[0][0].target_id == 1 and calls[0][0].query_type == 'both'
    assert calls[0][0].beam_mode == 'addressed_stream'
    assert addresses in p.traffic.query_type.currentText()
    assert not p.frequency_edit.isEnabled() and not p.traffic.start_button.isEnabled()
    assert p.traffic.stop_button.isEnabled()
    assert p.shutdown()
    p.close()
    p.deleteLater()
    app.processEvents()


def test_recorder_integrity_and_finish(tmp_path):
    r = TrafficRecorder(tmp_path / 'run', {'run_id': 'run'}, capacity=2)
    for i in range(10000):
        r.record({'event': 'item', 'number': i})
    r.finish({'reason': 'test'})
    assert r.close()
    summary = json.loads((tmp_path / 'run' / 'summary.json').read_text(encoding="utf-8"))
    assert summary['records_lost'] > 0 and not summary['evidence_complete']
    assert summary['recording_finished']
    lines = (tmp_path / 'run' / 'events.jsonl').read_text(encoding="utf-8").splitlines()
    assert len(lines) - 1 + summary['records_lost'] == 10000


def test_slow_beam_write_skips_elapsed_slots():
    e, _, _ = make_engine()
    write(e, 0, 35 * MS)
    assert e.next_beam == 40 * MS
    assert e.poll(35 * MS) is None and e.counts['skipped_beams'] == 3
    assert write(e, 40 * MS).has_beam


def test_recorder_rotates_without_losing_details(tmp_path):
    r = TrafficRecorder(tmp_path / 'rotate', {'run_id': 'rotate'}, max_bytes=80)
    for i in range(30):
        r.record({'event': 'example', 'number': i})
    r.finish({'reason': 'test'})
    assert r.close()
    summary = json.loads((tmp_path / 'rotate' / 'summary.json').read_text(encoding="utf-8"))
    assert len(summary['detail_files']) > 1
    events = [json.loads(l) for name in summary['detail_files']
              for l in (tmp_path / 'rotate' / name).read_text(encoding="utf-8").splitlines()]
    assert len(events) == 31 and summary['evidence_complete']


def test_old_connection_snapshot_cannot_unlock_new_run():
    app = QApplication.instance() or QApplication([])
    p = RXPanel()
    p.traffic.run_id = 'new'
    p._set_traffic_active(True)
    p._on_traffic_snapshot(object(), -1, {'run_id': 'old'})
    assert not p.traffic.start_button.isEnabled()
    assert p.shutdown()
    p.deleteLater()
    app.processEvents()


def test_cancel_before_first_write(tmp_path):
    d = AFDTR1024Driver('FAKE', 460800, DeviceVariant.RX)
    d.running = True
    d.serial = FakeSerial()
    d.start_traffic(TrafficConfig(), 20270, 0, 0, directory=tmp_path)
    d.stop_traffic()
    d._flush_tx()
    assert not d.serial.writes
    d.on_loop_stopped()
    assert d.stop()


def test_restart_does_not_release_new_owner_during_recorder_setup(tmp_path, monkeypatch):
    from soft_hertz_tool.devices.afdtr1024 import driver as module
    d = AFDTR1024Driver('FAKE', 460800, DeviceVariant.RX)
    d.running = True
    d.serial = FakeSerial()
    d.start_traffic(TrafficConfig(), 20270, 0, 0, directory=tmp_path)
    d._flush_tx()
    d.stop_traffic()
    d._flush_tx()
    d.on_loop_stopped()
    assert not d._traffic_owned
    recorder_type = module.TrafficRecorder

    def interleaved(directory, metadata):
        d._flush_tx()
        assert d._traffic_owned and not d.send_bytes(b'forbidden')
        return recorder_type(directory, metadata)

    monkeypatch.setattr(module, 'TrafficRecorder', interleaved)
    d.start_traffic(TrafficConfig(), 20270, 0, 0, directory=tmp_path)
    d._flush_tx()
    assert d._traffic_engine.counts['beams_written'] == 1
    d.on_loop_stopped()
    assert d.stop()


def test_invalid_beam_payload_does_not_complete_query():
    e, _, sim = make_engine(query_type='beam')
    b = write(e, 1000 * MS)
    good = sim.handle_frame(b.frames[-1])[0]
    payload = bytearray(protocol.parse_response(good)[0]['payload'])
    payload[12] = 255
    e.received(protocol.build_frame(1, 0x9F, payload), 1001 * MS, 1001 * MS)
    assert e.phase == 'wait' and not e.counts['matched_replies']


def test_driver_pending_normal_write_refuses_start(tmp_path):
    d = AFDTR1024Driver('FAKE', 460800, DeviceVariant.RX)
    d.running = True
    d._normal_writing = True
    with pytest.raises(ConnectionError):
        d.start_traffic(TrafficConfig(), 20270, 0, 0, directory=tmp_path)
    assert not d._traffic_owned
    assert d.stop()


def test_disconnect_retains_final_export(panel_class=RXPanel):
    app = QApplication.instance() or QApplication([])
    p = panel_class()
    p.traffic.run_id = 'finished'
    snapshot = {'run_id': 'finished', 'active': False, 'directory': '/tmp', 'recording_finished': True,
                'counts': {}, 'phase': 'stopped', 'remaining_s': 0, 'records_lost': 0,
                'record_error': '', 'reason': 'disconnected'}

    class Driver:
        def stop(self):
            return True

        def traffic_snapshot(self):
            return snapshot

        def deleteLater(self):
            pass

    p.driver = Driver()
    assert p.disconnect_device()
    assert p.traffic.export_button.isEnabled() and p.traffic.start_button.isEnabled()
    p.shutdown()
    p.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('variant', list(DeviceVariant))
@pytest.mark.parametrize('gap_mode', ['zero', 'fixed', 'random'])
def test_addressed_beam_echo_gates_queries_and_extra_gap(variant, gap_mode):
    e, events, sim = make_engine(variant, beam_mode='addressed', target_id=7, gap_mode=gap_mode,
                                gap_ms=2, random_min_ms=1, random_max_ms=3, seed=5)
    b = write(e, 0)
    assert len(b.frames) == 1 and b.frames[0][3] == 7
    assert e.pending == -1 and e.poll(5 * MS) is None
    reply(e, sim, b, 5 * MS)
    assert e.counts['beam_matched_replies'] == 1 and not e.counts['matched_replies']
    assert e.poll(6 * MS) is None
    b = write(e, 1000 * MS)
    assert len(b.frames) == 1 and e.phase == 'wait'
    assert e.poll(1001 * MS) is None
    reply(e, sim, b, 1002 * MS)
    due = 1002 * MS + e.gap_ns
    assert e.due_ns == due and e.poll(due - 1) is None
    query = write(e, due)
    assert len(query.frames) == 1 and not query.has_beam and query.query_index == 0
    assert events[-1]['post_beam_response_gap_ns'] == e.gap_ns
    assert e.poll(due + MS) is None
    reply(e, sim, query, due + MS)
    second = write(e, due + 3 * MS)
    reply(e, sim, second, due + 4 * MS)
    assert e.counts['matched_replies'] == 2
    assert e.metrics['beam_reply_latency']['count'] == 2


@pytest.mark.parametrize('kind', ['id', 'command', 'payload', 'checksum', 'partial'])
def test_addressed_beam_requires_exact_complete_echo(kind):
    e, _, sim = make_engine(beam_mode='addressed')
    b = write(e, 0)
    p = protocol.parse_response(b.raw)[0]
    if kind == 'id':
        bad = protocol.build_frame(2, p['addr'], p['payload'])
    elif kind == 'command':
        bad = sim.build_status_response(1)
    elif kind == 'payload':
        bad = protocol.build_frame(1, p['addr'], p['payload'][:-1] + bytes([p['payload'][-1] ^ 1]))
    elif kind == 'checksum':
        bad = b.raw[:-1] + bytes([b.raw[-1] ^ 1])
    else:
        parser = AFDTR1024StreamParser()
        assert not parser.feed(b.raw[:4])
        assert e.poll(MS) is None
        good = parser.feed(b.raw[4:])[0].raw
        e.received(good, 2 * MS, 2 * MS)
        assert e.counts['beam_matched_replies'] == 1
        return
    e.received(bad, MS, MS)
    assert e.pending == -1 and e.poll(2 * MS) is None
    assert not e.counts['beam_matched_replies']
    reply(e, sim, b, 3 * MS)
    assert e.counts['beam_matched_replies'] == 1


def test_beam_timeout_skip_and_stop_are_separate_from_query_stats():
    e, events, _ = make_engine(beam_mode='addressed', timeout_ms=35)
    write(e, 0)
    assert e.poll(35 * MS) is None
    assert e.next_beam == 40 * MS and e.counts['skipped_beams'] == 3
    assert e.counts['beam_timeouts'] == 1 and not e.counts['timeouts']
    write(e, 40 * MS)
    e.stop('cancelled', 41 * MS)
    assert e.counts['beam_cancelled'] == 1 and not e.counts['cancelled']
    assert e.poll(50 * MS) is None


def test_beam_timeout_before_due_query_does_not_skip_query_round():
    e, _, _ = make_engine(beam_mode='addressed', timeout_ms=25, query_period_ms=10)
    write(e, 0)
    assert e.poll(25 * MS) is None
    b = write(e, 30 * MS)
    assert len(b.frames) == 1 and e.counts['query_rounds'] == 1
    q = write(e, 55 * MS)
    assert not q.has_beam and q.query_index == 0
    assert e.counts['beam_timeouts'] == 2 and e.counts['queries_written'] == 1


def test_default_driver_uses_target_beam_and_waits(tmp_path):
    d = AFDTR1024Driver('FAKE', 460800, DeviceVariant.RX)
    d.running = True
    d.serial = FakeSerial()
    d.start_traffic(TrafficConfig(target_id=7, beam_mode="addressed"), 20270, 0, 0, directory=tmp_path)
    d._flush_tx()
    assert d.serial.writes[0][3] == 7
    d._flush_tx()
    assert len(d.serial.writes) == 1
    d.handle_bytes(d.serial.writes[0])
    assert d._traffic_engine.counts['beam_matched_replies'] == 1
    d.on_loop_stopped()
    assert d.stop()


@pytest.mark.parametrize('variant', list(DeviceVariant))
def test_customer_stream_sends_without_any_reply_and_pairs_each_query(variant):
    e, events, _ = make_engine(variant, beam_mode='addressed_stream', query_period_ms=20, timeout_ms=100)
    batches = [write(e, t * MS) for t in (0, 10, 20, 30, 40)]
    assert [len(b.frames) for b in batches] == [1, 1, 2, 2, 2]
    assert all(b.frames[0][3] == 1 for b in batches)
    assert [b.query_index for b in batches] == [None, None, 0, 1, 0]
    assert e.pending is None and e.counts['beams_written'] == 5
    assert e.counts['queries_written'] == 3 and e.phase == 'beam'
    assert e.poll(40 * MS) is None
    writes = [ev for ev in events if ev['event'] == 'write']
    assert len(writes) == 5 and writes[2]['frame_count'] == 2
    assert writes[2]['host_gap_ns'] is None and writes[2]['line_gap_ns'] is None


@pytest.mark.parametrize('variant', list(DeviceVariant))
def test_customer_stream_counts_reverse_order_sticky_replies(variant):
    e, _, sim = make_engine(variant, beam_mode='addressed_stream', query_type='status', query_period_ms=10)
    b = write(e, 10 * MS)
    query_reply = sim.handle_frame(b.frames[1])[0]
    beam_reply = sim.handle_frame(b.frames[0])[0]
    parser = AFDTR1024StreamParser()
    assert not parser.feed(query_reply[:3])
    frames = parser.feed(query_reply[3:] + beam_reply)
    for event in frames:
        assert event.is_frame
        e.received(event.raw, 11 * MS, 11 * MS)
    assert e.counts['rx_frames_total'] == 2
    assert e.counts['status_reply_frames'] == e.counts['beam_reply_frames'] == 1
    assert e.counts['matched_replies'] == e.counts['beam_matched_replies'] == 1
    e.received(query_reply, 12 * MS, 12 * MS)
    assert e.counts['status_reply_frames'] == 2
    assert e.counts['matched_replies'] == 1 and e.counts['abnormal_replies'] == 1
    assert write(e, 20 * MS).has_beam


def test_customer_stream_timeouts_only_affect_stats_and_late_replies_count():
    e, _, sim = make_engine(beam_mode='addressed_stream', query_type='status', query_period_ms=10, timeout_ms=5)
    b = write(e, 10 * MS)
    e.expire(15 * MS)
    assert e.counts['beam_timeouts'] == e.counts['timeouts'] == 1
    for frame in (b.frames[0], sim.handle_frame(b.frames[1])[0]):
        e.received(frame, 16 * MS, 16 * MS)
    assert e.counts['rx_frames_total'] == 2 and e.counts['abnormal_replies'] == 2
    assert not e.counts['beam_matched_replies'] and not e.counts['matched_replies']
    assert len(write(e, 20 * MS).frames) == 2
    e.stop('cancelled', 21 * MS)
    assert e.counts['beam_cancelled'] == e.counts['cancelled'] == 1
    assert not any(e.outstanding.values())


def test_customer_stream_wrong_id_payload_do_not_consume_pending_reply():
    e, _, sim = make_engine(beam_mode='addressed_stream', query_type='status', query_period_ms=10)
    b = write(e, 10 * MS)
    response = sim.handle_frame(b.frames[1])[0]
    parsed = protocol.parse_response(response)[0]
    wrong = protocol.build_frame(2, parsed['addr'], parsed['payload'])
    e.received(wrong, 11 * MS, 11 * MS)
    e.received(b.frames[1], 11 * MS, 11 * MS)
    assert len(e.outstanding[0]) == 1 and e.counts['abnormal_replies'] == 2
    e.received(response, 12 * MS, 12 * MS)
    assert e.counts['matched_replies'] == 1


def test_customer_stream_capacity_and_stop_keep_bounded_tracking():
    e, _, _ = make_engine(beam_mode='addressed_stream', timeout_ms=1000)
    e.tracking_limit = 2
    write(e, 0)
    write(e, 10 * MS)
    write(e, 20 * MS)
    assert not e.active and e.reason == 'tracking_capacity'
    assert not e.snapshot(20 * MS)['tracking_complete']
    assert e.counts['tracking_overflow'] == 1 and e.counts['beam_cancelled'] == 2
    assert not any(e.outstanding.values())


def test_customer_stream_ui_locks_zero_gap_and_driver_uses_one_write(tmp_path):
    app = QApplication.instance() or QApplication([])
    p = RXPanel()
    assert p.traffic.config().beam_mode == 'addressed_stream'
    assert not p.traffic.gap_mode.isEnabled()
    d = AFDTR1024Driver('FAKE', 460800, DeviceVariant.RX)
    d.running = True
    d.serial = FakeSerial()
    d.start_traffic(p.traffic.config(), 20270, 0, 0, directory=tmp_path)
    d._flush_tx()
    e = d._traffic_engine
    e.next_beam = e.due_ns = e.next_query = 0
    before = len(d.serial.writes)
    d._flush_tx()
    assert len(d.serial.writes) == before + 1
    parser = AFDTR1024StreamParser()
    frames = parser.feed(d.serial.writes[-1])
    assert len(frames) == 2
    assert all(ev.is_frame and ev.raw[3] == 1 for ev in frames)
    assert e.pending is None
    d.on_loop_stopped()
    assert d.stop()
    p.shutdown();p.deleteLater();app.processEvents()
