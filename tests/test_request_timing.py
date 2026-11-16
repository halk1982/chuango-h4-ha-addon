"""Send diagnostics use fake clocks/sockets and loopback, never a real alarm."""
import contextlib
import io
import threading
import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from h4.__main__ import main, run
from h4.bridge import connected_loop, run_bridge
from h4.client import NetworkError, NetworkTimeoutError, Wire
from h4.protocol import Status, heartbeat_request, status_request
from test_client import Server, client, handshake
from test_events import forwarded


NOW = datetime(2026, 11, 16)


class Clock:
    def __init__(self, now=100):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class RequestTimingTests(unittest.TestCase):
    def test_default_off_has_no_timing_logs_or_extra_clock_reads(self):
        c = client()
        c.wire = Mock()
        c.wire.read.return_value = forwarded('20100').decode().strip()
        with self.assertNoLogs('h4.client', level='INFO'), \
                patch('h4.client.time.monotonic', side_effect=[10, 11]) as clock:
            c.status(NOW)
            c.heartbeat()
            c.observe_events()
        self.assertFalse(c.request_timing)
        self.assertEqual(clock.call_count, 2)  # original status timestamp and deadline
        self.assertEqual(c._last_status_request, 10)
        c.wire.read.assert_called_once_with(11+c.timeout)
        c.wire.poll.assert_not_called()
        self.assertEqual([call.args[0] for call in c.wire.write.call_args_list],
                         [status_request(NOW), heartbeat_request()])

    def test_flags_are_independent_and_timing_does_not_poll(self):
        for receive, timing in ((False, True), (True, False), (True, True)):
            with self.subTest(receive=receive, timing=timing):
                c = client(event_diagnostics=receive, request_timing=timing)
                c.wire = Mock()
                c.wire.read.return_value = forwarded('20100').decode().strip()
                c.wire.poll.return_value = None
                with self.assertLogs('h4.client', level='INFO') as logs:
                    c.status(NOW)
                    c.observe_events()
                text = '\n'.join(logs.output)
                self.assertEqual('H4 TX' in text, timing)
                self.assertEqual('H4 RX' in text, receive)
                self.assertEqual(c.wire.poll.called, receive)

    def test_success_records_due_start_and_write_duration_excluding_logger(self):
        c = client(request_timing=True)
        c.wire = Mock()
        c.wire.read.return_value = forwarded('20100').decode().strip()
        # The first timestamp is still taken before packet construction/write.
        # Simulate 0.2s in the start logger, 0.5s in the actual write.
        with patch('h4.client.time.monotonic', side_effect=[100, 101, 101.2, 101.7, 102]), \
                self.assertLogs('h4.client', level='INFO') as logs:
            c.status(NOW, scheduled_due=98, schedule='poll')
        self.assertEqual(len(logs.records), 2)
        start, complete = [record.getMessage() for record in logs.records]
        self.assertIn('event=write_start', start)
        self.assertIn('event=write_complete', complete)
        for text in (start, complete):
            self.assertIn('operation=status server_command=10 device_command=20 marker=5555', text)
            self.assertIn(f'intended_bytes={len(status_request(NOW))}', text)
            self.assertIn('schedule=poll due_mono_s=98.000000', text)
        self.assertIn('observed_mono_s=101.000000', start)
        self.assertIn('start_mono_s=101.200000 lateness_s=3.200000', complete)
        self.assertIn('end_mono_s=101.700000 write_duration_s=0.500000', complete)
        self.assertIn('result=local_stack_accepted', complete)
        self.assertTrue(all(record.created > 0 for record in logs.records))
        self.assertEqual(c._last_status_request, 100)
        c.wire.read.assert_called_once_with(102+c.timeout)  # deadline still after write

    def test_failed_sendall_has_unknown_progress_safe_category_and_no_read_or_retry(self):
        for error, category, wrapped in (
            (TimeoutError('secret-token endpoint.example payload'), 'timeout', NetworkTimeoutError),
            (ConnectionResetError('secret-token endpoint.example payload'), 'reset', NetworkError),
            (BrokenPipeError('secret-token endpoint.example payload'), 'write-error', NetworkError),
            (OSError('secret-token endpoint.example payload'), 'write-error', NetworkError),
        ):
            for operation in ('status', 'heartbeat'):
                with self.subTest(error=type(error), operation=operation):
                    c = client(request_timing=True)
                    c.wire = Wire.__new__(Wire)
                    c.wire.socket = Mock()
                    accepted_prefix = []

                    def partial_then_fail(packet):
                        accepted_prefix.append(packet[:4])
                        raise error

                    c.wire.socket.sendall.side_effect = partial_then_fail
                    c.wire.read = Mock()
                    times = [100, 101, 101.1, 101.6] if operation == 'status' else [101, 101.1, 101.6]
                    with patch('h4.client.time.monotonic', side_effect=times), \
                            self.assertLogs('h4.client', level='INFO') as logs, \
                            self.assertRaises(wrapped) as caught:
                        c.status(NOW) if operation == 'status' else c.heartbeat()
                    self.assertEqual(accepted_prefix, [b'CGC0'])
                    c.wire.socket.sendall.assert_called_once()
                    c.wire.read.assert_not_called()
                    self.assertEqual(len(logs.records), 2)
                    text = '\n'.join(logs.output)
                    self.assertIn('event=write_start', text)
                    self.assertIn('event=write_failed', text)
                    self.assertIn(f'failure={category} progress=unknown', text)
                    self.assertIn('write_duration_s=0.500000', text)
                    for private in ('secret-token', 'endpoint.example', 'payload', 'sent_bytes=',
                                    'event=write_complete', 'local_stack_accepted', 'Traceback'):
                        self.assertNotIn(private, text)
                    self.assertNotIn('secret-token', str(caught.exception))

    def test_heartbeat_never_changes_since_status_request_semantics(self):
        c = client(request_timing=True, event_diagnostics=True)
        c.wire = Mock()
        c.wire.read.side_effect = ['CGS020255551', forwarded('20100').decode().strip()]
        clock = Clock()
        with patch('h4.client.time.monotonic', clock), self.assertLogs('h4.client', level='INFO') as logs:
            c.heartbeat()
            self.assertIsNone(c._last_status_request)
            c.status(NOW)
            clock.now = 107
            c.heartbeat()
            c._parse_received('CGS020255551')
        text = '\n'.join(logs.output)
        self.assertEqual(c._last_status_request, 100)
        self.assertIn('server_command=02 device_command=none marker=5555', text)
        self.assertIn('since_status_request_s=0.000', text)
        self.assertIn('since_status_request_s=7.000', text)

    def test_receive_age_still_includes_packet_construction_and_write(self):
        c = client(request_timing=True, event_diagnostics=True)
        c.wire = Mock()
        c.wire.read.return_value = forwarded('20100').decode().strip()
        with patch('h4.client.time.monotonic', side_effect=[100, 101, 101.1, 101.6, 102, 104]), \
                self.assertLogs('h4.client', level='INFO') as logs:
            c.status(NOW)
        self.assertIn('since_status_request_s=4.000', '\n'.join(logs.output))

    def test_only_status_and_heartbeat_are_timed_on_loopback(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())  # mode write must not be instrumented
            conn.sendall(forwarded('091'))
            requests.append(stream.readline())
            conn.sendall(forwarded('20100'))
            requests.append(stream.readline())
            self.assertEqual(stream.readline(), b'')

        with Server(session) as server, self.assertLogs('h4.client', level='INFO') as logs:
            c = client(endpoint=server.endpoint, request_timing=True)
            try:
                c.connect()
                c.change_mode('1')
                c.status(NOW)
                c.heartbeat()
            finally:
                c.close()
        self.assertEqual(len(server.requests), 5)  # Server context joins the receiver first.
        text = '\n'.join(logs.output)
        self.assertEqual(text.count('event=write_start'), 2)
        self.assertEqual(text.count('event=write_complete'), 2)
        for private in ('PANEL0001', 'owner123', 'secret456', '127.0.0.1', 'CGC02',
                        NOW.strftime('%Y%m%d'), 'operation=login', 'operation=mode'):
            self.assertNotIn(private, text)

    def test_unvalidated_identifiers_and_schedule_cannot_leak(self):
        c = client(request_timing=True)
        c.wire = Mock()
        with self.assertLogs('h4.client', level='INFO') as logs:
            c._write_request(b'CGC02xxLEAKprivate-payload', 'status', None, 'private-schedule')
        text = '\n'.join(logs.output)
        self.assertIn('server_command=unavailable', text)
        self.assertIn('marker=unavailable', text)
        self.assertIn('schedule=direct due_mono_s=none', text)
        for private in ('LEAK', 'private', 'payload', 'xx'):
            self.assertNotIn(private, text)

    def test_completed_local_write_without_reply_keeps_recovery_and_no_replay(self):
        for command in (False, True):
            with self.subTest(command=command):
                def first_session(conn, stream, requests):
                    handshake(conn, stream, requests)
                    if command:
                        requests.append(stream.readline())
                        conn.sendall(forwarded('20200'))
                        requests.append(stream.readline())
                        conn.sendall(forwarded('091'))
                    requests.append(stream.readline())  # status write completes, but no reply
                    # Worker must close the timed-out connection, not query it again.
                    self.assertEqual(stream.readline(), b'')

                def recovered_session(conn, stream, requests):
                    handshake(conn, stream, requests)
                    requests.append(stream.readline())
                    conn.sendall(forwarded('20100'))
                    self.assertEqual(stream.readline(), b'')

                stop = threading.Event()
                broker = Mock()
                broker.take_command.side_effect = [(0, 'DISARM'), None] if command else [None]
                broker.command_valid.return_value = True
                trace = []
                broker.offline.side_effect = lambda: trace.append('offline')

                def report(status):
                    trace.append(status.mode)
                    if status.mode == 'disarmed':
                        stop.set()

                broker.report.side_effect = report
                with Server(first_session) as first, Server(recovered_session) as second:
                    c = client(request_timing=True)
                    c.timeout = .1
                    endpoints = iter((first.endpoint, second.endpoint))
                    connect = c.connect

                    def connect_next():
                        c.endpoint = next(endpoints)
                        connect()

                    with patch.object(c, 'connect', side_effect=connect_next) as connects, \
                            patch.object(stop, 'wait', return_value=False) as wait, \
                            self.assertLogs('h4.client', level='INFO') as logs:
                        run_bridge({'device_id': 'PANEL0001', 'mqtt_host': 'localhost',
                                    'request_timing': True}, stop=stop,
                                   client_factory=lambda *a, **k: c,
                                   broker_factory=lambda *a, **k: broker)
                    self.assertEqual(connects.call_count, 2)
                    wait.assert_called_once_with(0 if command else 30)
                    self.assertEqual(len(first.requests), 5 if command else 3)
                    self.assertEqual(len(second.requests), 3)
                self.assertEqual(trace, ['armed_home', 'offline', 'disarmed'] if command else ['offline', 'disarmed'])
                text = '\n'.join(logs.output)
                self.assertEqual(text.count('event=write_complete'), 3 if command else 2)
                self.assertNotIn('event=write_failed', text)  # read timeout, not a write failure
                self.assertNotIn(('confirmed',), [call.args for call in broker.result.call_args_list])
                self.assertIsNone(c.wire)

    def test_worker_labels_immediate_reads_and_reports_poll_and_heartbeat_lateness(self):
        clock = Clock()
        stop = threading.Event()
        c = client(request_timing=True)
        c.timeout = 15
        c.wire = Mock()
        writes, deadlines = [], []

        def write(packet):
            writes.append(packet)
            clock.now += .25

        def read(deadline):
            deadlines.append(deadline)
            if len(deadlines) == 1:
                clock.now = 112  # status wait delays the first heartbeat
            elif len(deadlines) == 2:
                clock.now = 126
            elif len(deadlines) == 3:
                return forwarded('091').decode().strip()
            return forwarded('20100').decode().strip()

        c.wire.write.side_effect = write
        c.wire.read.side_effect = read
        broker = Mock()
        reports = []

        def report(status):
            reports.append(status.mode)
            if len(reports) == 3:
                stop.set()

        def command(timeout):
            if len(reports) == 1:
                clock.now = 125  # scheduled poll at 122 starts three seconds late
            if len(reports) == 2:
                return 0, 'ARM_HOME'

        broker.report.side_effect = report
        broker.take_command.side_effect = command
        with patch('h4.client.time.monotonic', clock), self.assertLogs('h4.client', level='INFO') as logs:
            connected_loop(c, broker, stop, interval=10, zone=ZoneInfo('UTC'),
                           confirmation_timeout=120, request_timing=True)
        completed = [record.getMessage() for record in logs.records if 'event=write_complete' in record.getMessage()]
        self.assertEqual(len(completed), 5)  # three statuses, two heartbeats; no mode write
        self.assertIn('schedule=initial due_mono_s=none', completed[0])
        self.assertIn('due_mono_s=110.000000 event=write_complete start_mono_s=112.000000 lateness_s=2.000000', completed[1])
        self.assertIn('schedule=poll due_mono_s=122.000000 event=write_complete start_mono_s=125.000000 lateness_s=3.000000', completed[2])
        self.assertIn('due_mono_s=122.250000 event=write_complete start_mono_s=126.000000 lateness_s=3.750000', completed[3])
        self.assertIn('schedule=post_command due_mono_s=none', completed[4])
        self.assertIn('lateness_s=none', completed[4])
        self.assertEqual(reports, ['disarmed']*3)  # ACK never asserts armed_home
        self.assertNotIn(('confirmed',), [call.args for call in broker.result.call_args_list])
        self.assertEqual(len(writes), 6)
        self.assertEqual(deadlines, [115.25, 140.25, 141.5, 141.75])
        c.wire.poll.assert_not_called()

    def test_probe_wait_keeps_schedule_and_does_not_enable_idle_draining(self):
        for receive in (False, True):
            for timing in (False, True):
                with self.subTest(receive=receive, timing=timing):
                    clock = Clock()
                    c = client(request_timing=timing, event_diagnostics=receive)
                    c.wire = Mock()
                    c.wire.poll.return_value = None
                    with patch('h4.client.time.monotonic', clock), patch('h4.client.time.sleep', clock.sleep), \
                            patch('h4.client.LOG.info') as log:
                        due = c.wait(25)
                    self.assertEqual(due, 125)
                    self.assertEqual(clock.now, 125)
                    self.assertEqual(c.wire.write.call_count, 3)  # 10, 20, end-of-wait at 25s
                    self.assertEqual(c.wire.poll.called, receive)
                    self.assertEqual(log.call_count, 6 if timing else 0)
                    if timing:
                        self.assertEqual([call.args[7] for call in log.call_args_list[::2]],
                                         ['110.000000', '120.000000', '125.000000'])
                        self.assertEqual(log.call_args_list[-2].args[6], 'probe_wait_end')

    def test_probe_options_and_cli_wire_timing_without_receive_diagnostics(self):
        c = Mock()
        c.status.return_value = Status('disarmed', '1', ())
        c.wait.return_value = 125
        with patch('h4.__main__.StatusClient', return_value=c) as factory, \
                patch('h4.__main__.logging.basicConfig') as logging_config, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            run({'allow_plaintext': True, 'samples': 2, 'request_timing': True})
        self.assertTrue(factory.call_args.kwargs['request_timing'])
        self.assertFalse(factory.call_args.kwargs['event_diagnostics'])
        self.assertEqual(c.status.call_args_list[0].kwargs, {'scheduled_due': None, 'schedule': 'initial'})
        self.assertEqual(c.status.call_args_list[1].kwargs, {'scheduled_due': 125, 'schedule': 'poll'})
        logging_config.assert_called_once()
        with patch('builtins.input', return_value='unused'), patch('getpass.getpass', return_value='unused'), \
                patch('h4.__main__.run') as probe:
            self.assertEqual(main(['--allow-plaintext', '--request-timing']), 0)
        self.assertTrue(probe.call_args.args[0]['request_timing'])
        self.assertFalse(probe.call_args.args[0]['event_diagnostics'])

    def test_bridge_passes_validated_option_and_defaults_off(self):
        options = {'device_id': 'PANEL0001', 'allow_plaintext': True, 'mqtt_host': 'localhost'}
        for timing in (None, True):
            c, broker, stop = Mock(), Mock(), threading.Event()
            stop.set()
            factory = Mock(return_value=c)
            run_bridge(options if timing is None else dict(options, request_timing=timing),
                       stop=stop, client_factory=factory, broker_factory=lambda *a, **k: broker)
            self.assertEqual(factory.call_args.kwargs['request_timing'], timing is True)
            self.assertFalse(factory.call_args.kwargs['event_diagnostics'])

    def test_non_boolean_options_are_rejected_before_any_network(self):
        for value in (1, 'false', None, []):
            with self.subTest(value=value), patch('h4.client.Wire') as wire:
                with self.assertRaises(ValueError):
                    client(request_timing=value)
                with self.assertRaises(ValueError):
                    run({'request_timing': value})
                with self.assertRaises(ValueError):
                    run_bridge({'request_timing': value})
                wire.assert_not_called()


if __name__ == '__main__':
    unittest.main()
