"""Post-ACK timeout cases using synthetic clients and loopback servers only."""
import threading
import unittest
from unittest.mock import Mock, patch

from h4.bridge import ConfirmationReadTimeout, run_bridge
from h4.client import NetworkError, NetworkTimeoutError, StatusClient
from h4.protocol import AuthenticationError, Status
from test_client import Server, handshake


HOME = Status("armed_home", "2", ())
DISARMED = Status("disarmed", "1", ())


class ConfirmationRecoveryTests(unittest.TestCase):
    options = {"device_id": "PANEL0001", "username": "owner123", "password": "secret456",
               "allow_plaintext": True, "mqtt_host": "localhost", "enable_controls": True}

    def worker(self, c, broker, stop, **options):
        run_bridge(dict(self.options, **options), stop=stop,
                   client_factory=lambda *a, **k: c, broker_factory=lambda *a, **k: broker)

    def scenario(self, responses, *, command=True, mode_error=None, connect_errors=None,
                 retries=3, expired=False):
        c, broker, stop = Mock(), Mock(), threading.Event()
        results, reports, trace = [], [], []
        responses = iter(responses)
        broker.take_command.side_effect = [(0, "DISARM"), None] if command else [None]
        broker.command_valid.return_value = True
        broker.result.side_effect = lambda value: results.append(value)
        broker.report.side_effect = lambda status: reports.append(status)
        broker.offline.side_effect = lambda: trace.append("offline")
        if mode_error:
            c.change_mode.side_effect = mode_error
        if connect_errors:
            failures = iter(connect_errors)
            def connect():
                error = next(failures)
                trace.append("connect")
                if error:
                    raise error
            c.connect.side_effect = connect
        else:
            c.connect.side_effect = lambda: trace.append("connect")
        with patch("h4.bridge.time.monotonic", return_value=0) as clock:
            def status(now):
                response = next(responses)
                if isinstance(response, Exception):
                    if expired:
                        clock.return_value = 16
                    raise response
                if response is DISARMED:
                    trace.append("fresh status")
                    stop.set()
                return response
            c.status.side_effect = status
            with patch.object(stop, "wait", return_value=False) as waits:
                self.worker(c, broker, stop, reconnect_attempts=retries,
                            confirmation_timeout=15 if expired else 120)
        return c, broker, results, reports, trace, [call.args[0] for call in waits.call_args_list]

    def test_ack_followed_by_timeout_spends_one_retry_without_waiting_or_replaying(self):
        c, broker, results, reports, trace, waits = self.scenario([
            HOME, NetworkTimeoutError("status query: timed out"), DISARMED,
        ])
        self.assertEqual(waits, [0])
        self.assertEqual(c.connect.call_count, 2)
        c.change_mode.assert_called_once_with("1")
        self.assertEqual(reports, [HOME, DISARMED])
        self.assertEqual(trace, ["connect", "offline", "connect", "fresh status"])
        self.assertIn("unconfirmed", results)
        self.assertNotIn("confirmed", results)

    def test_following_status_timeouts_return_to_backoff_without_another_fast_retry(self):
        c, broker, results, reports, trace, waits = self.scenario([
            HOME, NetworkTimeoutError("status query: timed out"),
            NetworkTimeoutError("status query: timed out"), DISARMED,
        ])
        self.assertEqual(waits, [0, 60])
        self.assertEqual(c.connect.call_count, 3)
        c.change_mode.assert_called_once_with("1")
        self.assertEqual(reports, [HOME, DISARMED])

    def test_failed_fast_connection_returns_to_backoff(self):
        c, broker, results, reports, trace, waits = self.scenario([
            HOME, NetworkTimeoutError("status query: timed out"), DISARMED,
        ], connect_errors=[None, NetworkError("alarm server connection: connection refused"), None])
        self.assertEqual(waits, [0, 60])
        self.assertEqual(c.connect.call_count, 3)
        c.change_mode.assert_called_once_with("1")

    def test_routine_poll_timeout_keeps_the_normal_delay(self):
        c, broker, results, reports, trace, waits = self.scenario([
            NetworkTimeoutError("status query: timed out"), DISARMED,
        ], command=False)
        self.assertEqual(waits, [30])
        c.change_mode.assert_not_called()
        self.assertEqual(reports, [DISARMED])

    def test_missing_command_ack_keeps_the_normal_delay_and_never_replays(self):
        c, broker, results, reports, trace, waits = self.scenario([
            HOME, DISARMED,
        ], mode_error=NetworkTimeoutError("mode command: timed out"))
        self.assertEqual(waits, [30])
        c.change_mode.assert_called_once_with("1")
        self.assertNotIn("confirmed", results)

    def test_non_timeout_after_ack_keeps_the_normal_delay(self):
        c, broker, results, reports, trace, waits = self.scenario([
            HOME, NetworkError("status query: connection reset by peer"), DISARMED,
        ])
        self.assertEqual(waits, [30])
        c.change_mode.assert_called_once_with("1")

    def test_expired_confirmation_does_not_get_a_fast_retry(self):
        c, broker, results, reports, trace, waits = self.scenario([
            HOME, NetworkTimeoutError("status query: timed out"), DISARMED,
        ], expired=True)
        self.assertEqual(waits, [30])
        c.change_mode.assert_called_once_with("1")

    def test_zero_budget_disables_the_fast_retry(self):
        stop = threading.Event()
        c, broker = Mock(), Mock()
        c.status.side_effect = [HOME, NetworkTimeoutError("status query: timed out")]
        broker.take_command.return_value = (0, "DISARM")
        broker.command_valid.return_value = True
        with patch.object(stop, "wait", return_value=False) as wait:
            with self.assertRaises(ConfirmationReadTimeout):
                self.worker(c, broker, stop, reconnect_attempts=0)
        wait.assert_not_called()
        c.connect.assert_called_once()
        c.change_mode.assert_called_once_with("1")
        broker.report.assert_called_once_with(HOME)
        broker.close.assert_called_once()

    def test_fast_retry_does_not_bypass_an_authentication_rejection(self):
        c, broker, stop = Mock(), Mock(), threading.Event()
        c.connect.side_effect = [None, AuthenticationError("session ended")]
        c.status.side_effect = [HOME, NetworkTimeoutError("status query: timed out")]
        broker.take_command.return_value = (0, "DISARM")
        broker.command_valid.return_value = True
        with patch.object(stop, "wait", return_value=False) as wait:
            with self.assertRaises(AuthenticationError):
                self.worker(c, broker, stop)
        wait.assert_called_once_with(0)
        self.assertEqual(c.connect.call_count, 2)
        c.change_mode.assert_called_once_with("1")
        broker.report.assert_called_once_with(HOME)

    def test_real_ack_then_silent_status_reconnects_for_fresh_state_without_resending(self):
        stop = threading.Event()
        def first_session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.sendall(b"CGS021055551000520200\r\n")
            requests.append(stream.readline())
            self.assertEqual(requests[-1], b"CGC021055550003091\r\n")
            conn.sendall(b"CGS0210555510003091\r\n")
            requests.append(stream.readline())
            self.assertTrue(requests[-1].startswith(b"CGC02105555001720"))
            # Withhold the read reply until the real client times out/closes.
            self.assertEqual(stream.readline(), b"")
        def second_session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            self.assertTrue(requests[-1].startswith(b"CGC02105555001720"))
            conn.sendall(b"CGS021055551000520100\r\n")
            self.assertEqual(stream.readline(), b"")
        with Server(first_session) as first, Server(second_session) as second:
            c = StatusClient("PANEL0001", "owner123", "secret456", allow_plaintext=True,
                             endpoint=first.endpoint, timeout=.1)
            endpoints, original_connect = iter((first.endpoint, second.endpoint)), c.connect
            def connect():
                c.endpoint = next(endpoints)
                original_connect()
            broker = Mock()
            reports = []
            def report(status):
                reports.append(status)
                if status.mode == "disarmed":
                    stop.set()
            broker.report.side_effect = report
            broker.take_command.side_effect = [(0, "DISARM"), None]
            broker.command_valid.return_value = True
            with patch.object(c, "connect", side_effect=connect), \
                    patch.object(c, "change_mode", wraps=c.change_mode) as change, \
                    patch.object(stop, "wait", return_value=False) as wait, \
                    self.assertLogs("h4.bridge", level="WARNING") as logs:
                self.worker(c, broker, stop)
            change.assert_called_once_with("1")
            wait.assert_called_once_with(0)
            self.assertEqual(reports, [HOME, DISARMED])
            self.assertEqual(len(first.requests), 5)
            self.assertEqual(len(second.requests), 3)
            self.assertIn("after command acknowledgement; retry 1/3 in 0 seconds", logs.output[0])
            for secret in ("PANEL0001", "owner123", "secret456"):
                self.assertNotIn(secret, "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
