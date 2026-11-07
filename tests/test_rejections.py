"""Synthetic rejection/recovery cases. No vendor account or physical alarm."""
import contextlib
import io
import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from h4.__main__ import main
from h4.bridge import run_bridge
from h4.client import NetworkError
from h4.protocol import (
    AuthenticationError, Frame, ProtocolError, ServerRejectedError, Status,
    require_success,
)
from test_client import Server, client, handshake


def rejection(phase="status query", command="10", code="08"):
    error = ServerRejectedError(command, code)
    error.set_phase(phase)
    return error


class RejectionTests(unittest.TestCase):
    def test_only_exact_negative_envelopes_are_classified(self):
        with self.assertRaises(ServerRejectedError) as caught:
            require_success(Frame("10", "008"))
        self.assertEqual((caught.exception.command, caught.exception.code), ("10", "08"))
        for body in ("x08", "008private-payload", "08", "0ab", "0０８", "0"):
            with self.subTest(body=body), self.assertRaises(ProtocolError) as caught:
                require_success(Frame("10", body))
            self.assertNotIsInstance(caught.exception, ServerRejectedError)
            self.assertNotIn("private-payload", str(caught.exception))
        with self.assertRaises(AuthenticationError):
            require_success(Frame("04", "008"))

    def test_rejection_metadata_cannot_echo_unvalidated_values(self):
        error = ServerRejectedError("private-command", "private-code")
        error.set_phase("private-phase")
        self.assertEqual(str(error), "Server rejected request (phase=unknown; "
                         "server_command=unknown; code=unknown)")
        self.assertNotIn("private", repr(error))

    def test_real_socket_rejections_identify_the_failing_phase_without_resending(self):
        for phase, command in (("handshake", "01"), ("status query", "10"),
                               ("mode command", "10")):
            with self.subTest(phase=phase):
                def session(conn, stream, requests):
                    if phase == "handshake":
                        requests.append(stream.readline())
                    else:
                        handshake(conn, stream, requests)
                        requests.append(stream.readline())
                    conn.sendall(f"CGS02{command}5555008\r\n".encode())
                    self.assertEqual(stream.readline(), b"")

                with Server(session) as server:
                    c = client(endpoint=server.endpoint, event_diagnostics=True)
                    try:
                        with self.assertRaises(ServerRejectedError) as caught:
                            c.connect()
                            if phase == "status query":
                                c.status(datetime(2026, 11, 7))
                            elif phase == "mode command":
                                c.change_mode("1")
                        error = caught.exception
                        self.assertEqual((error.phase, error.command, error.code),
                                         (phase, command, "08"))
                        for secret in ("owner123", "secret456", "PANEL0001"):
                            self.assertNotIn(secret, str(error))
                    finally:
                        c.close()
                    self.assertEqual(len(server.requests), 1 if phase == "handshake" else 3)

    def test_code_08_login_rejection_still_stops_without_a_status_query(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests, login_response=b"CGS02045555008\r\n")
            self.assertEqual(stream.readline(), b"")
        with Server(session) as server:
            c = client(endpoint=server.endpoint)
            with self.assertRaises(AuthenticationError):
                c.connect()
            self.assertIsNone(c.wire)
            self.assertEqual(len(server.requests), 2)

    def test_cli_reports_a_server_rejection_separately_without_private_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "options.json"
            path.write_text(json.dumps({"run_mode": "mqtt", "password": "private-password"}))
            with patch("h4.bridge.run_bridge", side_effect=rejection("handshake", "01")), \
                    self.assertLogs(level="ERROR") as logs, \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--options", str(path)]), 1)
            message = "\n".join(logs.output)
            self.assertIn("Alarm server rejection", message)
            self.assertIn("phase=handshake; server_command=01; code=08", message)
            self.assertNotIn("compatibility check failed", message)
            self.assertNotIn("private-password", message)


class RecoveryTests(unittest.TestCase):
    options = {"device_id": "PANEL0001", "username": "owner123", "password": "secret456",
               "allow_plaintext": True, "mqtt_host": "localhost", "enable_controls": True}

    def run_worker(self, c, broker, stop, **options):
        run_bridge(dict(self.options, **options), stop=stop,
                   client_factory=lambda *a, **k: c, broker_factory=lambda *a, **k: broker)

    def test_status_08_and_network_failures_share_budget_and_restore_only_fresh_state(self):
        stop = threading.Event()
        c, broker = Mock(), Mock()
        broker.take_command.return_value = None
        responses = [NetworkError("status query: timed out"), rejection(), Status("disarmed", "1", ())]
        def status(now):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            stop.set()
            return response
        c.status.side_effect = status
        with patch.object(stop, "wait", return_value=False) as wait:
            self.run_worker(c, broker, stop)
        self.assertEqual([call.args[0] for call in wait.call_args_list], [30, 60])
        self.assertEqual(c.connect.call_count, 3)
        self.assertEqual(broker.offline.call_count, 2)
        broker.report.assert_called_once_with(Status("disarmed", "1", ()))
        names = [call[0] for call in broker.mock_calls]
        self.assertGreater(names.index("report"), max(i for i, name in enumerate(names) if name == "offline"))
        c.change_mode.assert_not_called()

    def test_repeated_status_08_is_bounded_including_zero_retry_setting(self):
        for limit in (0, 2):
            with self.subTest(limit=limit):
                c, broker, stop = Mock(), Mock(), Mock()
                c.status.side_effect = rejection()
                stop.is_set.return_value = False
                stop.wait.return_value = False
                with self.assertRaises(ServerRejectedError):
                    self.run_worker(c, broker, stop, reconnect_attempts=limit)
                self.assertEqual(c.connect.call_count, limit + 1)
                self.assertEqual([call.args[0] for call in stop.wait.call_args_list], [30, 60][:limit])
                broker.report.assert_not_called()
                broker.close.assert_called_once()
                c.change_mode.assert_not_called()

    def test_real_status_rejection_reconnects_and_requires_a_fresh_panel_reply(self):
        stop = threading.Event()
        def rejected_session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.sendall(b"CGS02105555008\r\n")
            self.assertEqual(stream.readline(), b"")
        def recovered_session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.sendall(b"CGS021055551000520100\r\n")
            self.assertEqual(stream.readline(), b"")
        with Server(rejected_session) as first, Server(recovered_session) as second:
            c = client(endpoint=first.endpoint, event_diagnostics=True)
            endpoints = iter((first.endpoint, second.endpoint))
            connect = c.connect
            def next_connection():
                c.endpoint = next(endpoints)
                connect()
            broker = Mock()
            broker.report.side_effect = lambda status: stop.set()
            broker.take_command.return_value = None
            with patch.object(c, "connect", side_effect=next_connection) as connects, \
                    patch.object(stop, "wait", return_value=False) as wait:
                self.run_worker(c, broker, stop)
            self.assertEqual(connects.call_count, 2)
            wait.assert_called_once_with(30)
            broker.offline.assert_called_once()
            broker.report.assert_called_once_with(Status("disarmed", "1", ()))
            self.assertEqual(len(first.requests), 3)
            self.assertEqual(len(second.requests), 3)

    def test_other_rejections_do_not_enter_recovery(self):
        cases = [("handshake", "01", "08"), ("mode command", "10", "08"),
                 ("idle", "10", "08"), ("unknown", "10", "08"),
                 ("status query", "10", "07"), ("status query", "01", "08")]
        for phase, command, code in cases:
            with self.subTest(phase=phase, command=command, code=code):
                c, broker, stop = Mock(), Mock(), Mock()
                stop.is_set.return_value = False
                error = rejection(phase, command, code)
                if phase == "handshake":
                    c.connect.side_effect = error
                else:
                    c.status.side_effect = error
                with self.assertRaises(ServerRejectedError):
                    self.run_worker(c, broker, stop)
                c.connect.assert_called_once()
                stop.wait.assert_not_called()
                broker.report.assert_not_called()
                broker.close.assert_called_once()

    def test_status_recovery_after_ack_never_replays_or_confirms_the_command(self):
        stop = threading.Event()
        c, broker = Mock(), Mock()
        broker.take_command.side_effect = [(0, "DISARM"), None]
        broker.command_valid.return_value = True
        responses = [Status("armed_away", "0", ()), rejection(), Status("armed_away", "0", ())]
        def status(now):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            if not responses:
                stop.set()
            return response
        c.status.side_effect = status
        with patch.object(stop, "wait", return_value=False):
            self.run_worker(c, broker, stop)
        self.assertEqual(c.connect.call_count, 2)
        c.change_mode.assert_called_once_with("1")
        self.assertEqual([call.args[0].mode for call in broker.report.call_args_list],
                         ["armed_away", "armed_away"])
        results = [call.args[0] for call in broker.result.call_args_list]
        self.assertIn("unconfirmed", results)
        self.assertNotIn("confirmed", results)

    def test_real_rejected_mode_command_stops_without_reconnect_or_replay(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.sendall(b"CGS021055551000520000\r\n")
            requests.append(stream.readline())
            self.assertEqual(requests[-1], b"CGC021055550003091\r\n")
            conn.sendall(b"CGS02105555008\r\n")
            self.assertEqual(stream.readline(), b"")
        with Server(session) as server:
            c = client(endpoint=server.endpoint)
            broker, stop = Mock(), Mock()
            stop.is_set.return_value = False
            broker.take_command.return_value = (0, "DISARM")
            broker.command_valid.return_value = True
            with self.assertRaises(ServerRejectedError) as caught:
                self.run_worker(c, broker, stop)
            self.assertEqual(caught.exception.phase, "mode command")
            stop.wait.assert_not_called()
            self.assertEqual(len(server.requests), 4)


if __name__ == "__main__":
    unittest.main()
