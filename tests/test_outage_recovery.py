"""Long-outage policies with synthetic failures and no real wait/cloud traffic."""
import threading
import unittest
from unittest.mock import Mock, patch

from h4.bridge import run_bridge
from h4.client import NetworkError, NetworkTimeoutError
from h4.protocol import (
    AccountRemovedError, AuthenticationError, PanelOfflineError, ProtocolError,
    SessionReplacedError, Status,
)
from test_rejections import rejection


HOME = Status("armed_home", "2", ())
DISARMED = Status("disarmed", "1", ())


class OutageRecoveryTests(unittest.TestCase):
    options = {"device_id": "PANEL0001", "username": "owner123", "password": "secret456",
               "allow_plaintext": True, "mqtt_host": "localhost", "enable_controls": True}

    def worker(self, c, broker, stop, **options):
        run_bridge(dict(self.options, **options), stop=stop,
                   client_factory=lambda *a, **k: c, broker_factory=lambda *a, **k: broker)

    def test_default_recovers_after_more_failures_than_the_initial_budget(self):
        c, broker, stop = Mock(), Mock(), threading.Event()
        c.connect.side_effect = [NetworkError("DNS lookup failed")] * 6 + [None]
        c.status.return_value = DISARMED
        broker.take_command.return_value = None
        broker.report.side_effect = lambda status: stop.set()
        with patch.object(stop, "wait", return_value=False) as wait, \
                self.assertLogs("h4.bridge", level="WARNING") as logs:
            self.worker(c, broker, stop)
        self.assertEqual([call.args[0] for call in wait.call_args_list],
                         [30, 60, 120, 300, 300, 300])
        self.assertEqual(c.connect.call_count, 7)
        self.assertEqual(broker.offline.call_count, 6)
        broker.report.assert_called_once_with(DISARMED)
        c.change_mode.assert_not_called()
        broker.close.assert_called_once()
        self.assertIn("bridge remains offline; retry in 300 seconds", "\n".join(logs.output))

    def test_explicit_panel_offline_notifications_also_use_cooldown(self):
        c, broker, stop = Mock(), Mock(), threading.Event()
        c.status.side_effect = [PanelOfflineError("Server reports the panel offline")] * 5 + [DISARMED]
        broker.take_command.return_value = None
        broker.report.side_effect = lambda status: stop.set()
        with patch.object(stop, "wait", return_value=False) as wait:
            self.worker(c, broker, stop)
        self.assertEqual([call.args[0] for call in wait.call_args_list], [30, 60, 120, 300, 300])
        self.assertEqual(c.connect.call_count, 6)
        broker.report.assert_called_once_with(DISARMED)
        c.change_mode.assert_not_called()

    def test_long_outage_never_restarts_fast_retry_bursts(self):
        c, broker, stop = Mock(), Mock(), Mock()
        c.connect.side_effect = NetworkError("connection timed out")
        stop.is_set.return_value = False
        stop.wait.side_effect = [False] * 22 + [True]
        with self.assertLogs("h4.bridge", level="WARNING"):
            self.worker(c, broker, stop)
        waits = [call.args[0] for call in stop.wait.call_args_list]
        self.assertEqual(waits, [30, 60, 120] + [300] * 20)
        self.assertEqual(c.connect.call_count, 23)
        broker.report.assert_not_called()
        c.change_mode.assert_not_called()

    def test_shutdown_interrupts_cooldown_without_another_connection(self):
        c, broker, stop = Mock(), Mock(), Mock()
        c.connect.side_effect = NetworkError("connection reset by peer")
        stop.is_set.return_value = False
        stop.wait.side_effect = [False, False, False, True]
        self.worker(c, broker, stop)
        self.assertEqual(c.connect.call_count, 4)
        self.assertEqual([call.args[0] for call in stop.wait.call_args_list], [30, 60, 120, 300])
        broker.close.assert_called_once()
        broker.report.assert_not_called()

    def test_zero_retries_disables_cooldown_even_when_enabled(self):
        for error in (NetworkError("connection timed out"), PanelOfflineError("panel offline")):
            with self.subTest(error=type(error).__name__):
                c, broker, stop = Mock(), Mock(), Mock()
                c.connect.side_effect = error
                stop.is_set.return_value = False
                with self.assertRaises(type(error)):
                    self.worker(c, broker, stop, reconnect_attempts=0, recover_after_outage=True)
                c.connect.assert_called_once()
                stop.wait.assert_not_called()
                broker.close.assert_called_once()

    def test_login_session_account_protocol_and_server_rejections_still_stop(self):
        terminal_errors = [AuthenticationError("Login rejected"),
                           SessionReplacedError("session replaced"),
                           AccountRemovedError("account removed"),
                           ProtocolError("Unrecognized response header"),
                           rejection(), rejection("handshake", "01")]
        for error in terminal_errors:
            with self.subTest(error=str(error)):
                c, broker, stop = Mock(), Mock(), Mock()
                c.connect.side_effect = [NetworkError("connection timed out")] * 4 + [error]
                stop.is_set.return_value = False
                stop.wait.return_value = False
                with self.assertRaises(type(error)):
                    self.worker(c, broker, stop)
                self.assertEqual(c.connect.call_count, 5)
                self.assertEqual([call.args[0] for call in stop.wait.call_args_list],
                                 [30, 60, 120, 300])
                broker.report.assert_not_called()
                c.change_mode.assert_not_called()

    def test_an_uncertain_disarm_is_never_replayed_after_a_long_outage(self):
        c, broker, stop = Mock(), Mock(), threading.Event()
        c.connect.side_effect = [None] + [NetworkError("connection timed out")] * 3 + [None]
        c.status.side_effect = [HOME, DISARMED]
        c.change_mode.side_effect = NetworkTimeoutError("mode command: timed out")
        broker.take_command.side_effect = [(0, "DISARM"), None]
        broker.command_valid.return_value = True
        def report(status):
            if status.mode == "disarmed":
                stop.set()
        broker.report.side_effect = report
        with patch.object(stop, "wait", return_value=False) as wait:
            self.worker(c, broker, stop)
        self.assertEqual([call.args[0] for call in wait.call_args_list], [30, 60, 120, 300])
        c.change_mode.assert_called_once_with("1")
        self.assertEqual([call.args[0] for call in broker.report.call_args_list], [HOME, DISARMED])
        results = [call.args[0] for call in broker.result.call_args_list]
        self.assertIn("unconfirmed", results)
        self.assertNotIn("confirmed", results)

    def test_three_stable_reads_restore_budget_but_two_do_not(self):
        for reads in (2, 3):
            with self.subTest(reads=reads):
                c, broker, stop = Mock(), Mock(), threading.Event()
                c.connect.side_effect = [NetworkError("connection timed out")] * 4 + [None, None]
                c.status.side_effect = [HOME] * reads + [NetworkError("status query: timed out"), DISARMED]
                def report(status):
                    if status.mode == "disarmed":
                        stop.set()
                broker.report.side_effect = report
                with patch("h4.bridge.time.monotonic", return_value=0) as clock:
                    def take_command(timeout):
                        clock.return_value += 10
                        return None
                    broker.take_command.side_effect = take_command
                    with patch.object(stop, "wait", return_value=False) as wait, \
                            self.assertLogs("h4.bridge", level="INFO") as logs:
                        self.worker(c, broker, stop)
                expected_last = 30 if reads == 3 else 300
                self.assertEqual([call.args[0] for call in wait.call_args_list],
                                 [30, 60, 120, 300, expected_last])
                restored = "Alarm connection stable after outage; normal retry budget restored"
                self.assertEqual(any(restored in line for line in logs.output), reads == 3)
                self.assertEqual(c.connect.call_count, 6)

    def test_outage_flag_requires_a_boolean_before_creating_any_connection(self):
        for value in (None, "true", 0, 1):
            with self.subTest(value=value):
                factory = Mock()
                with self.assertRaisesRegex(ValueError, "Invalid outage recovery flag"):
                    run_bridge(dict(self.options, recover_after_outage=value),
                               stop=threading.Event(), client_factory=factory, broker_factory=factory)
                factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
