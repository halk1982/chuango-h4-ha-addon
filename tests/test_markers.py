"""Response correlation tests use synthetic frames and loopback servers only."""
import time
import unittest
from datetime import datetime

from h4.client import NetworkError, StatusClient
from h4.protocol import ProtocolError, SessionReplacedError, UnmatchedResponseMarker
from test_client import Server, client, handshake


def response(payload, marker="5555"):
    return f"CGS0210{marker}1{len(payload):04}{payload}\r\n".encode()


class MarkerTests(unittest.TestCase):
    def test_other_marker_cannot_override_matching_status(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.sendall(response("20200", "1234") + response("20100"))
            self.assertEqual(stream.readline(), b"")

        with Server(session) as server, self.assertLogs("h4.client", level="WARNING") as logs:
            c = client(endpoint=server.endpoint)
            try:
                c.connect()
                self.assertEqual(c.status(datetime(2026, 11, 6)).mode, "disarmed")
            finally:
                c.close()
            self.assertEqual(len(server.requests), 3)
        self.assertIn("phase=status query server_command=10", "\n".join(logs.output))

    def test_other_marker_rejection_cannot_reject_a_matching_acknowledgement(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            self.assertEqual(requests[-1], b"CGC021055550003091\r\n")
            conn.sendall(response("090", "1234") + response("091"))
            requests.append(stream.readline())
            # An accepted disarm command still cannot turn an armed status
            # into a confirmed disarmed assertion.
            conn.sendall(response("20200"))
            self.assertEqual(stream.readline(), b"")

        with Server(session) as server, self.assertLogs("h4.client", level="WARNING"):
            c = client(endpoint=server.endpoint)
            try:
                c.connect()
                c.change_mode("1")
                self.assertEqual(c.status(datetime(2026, 11, 6)).mode, "armed_home")
            finally:
                c.close()
            self.assertEqual(len(server.requests), 4)

    def test_only_other_marker_replies_timeout_without_resending(self):
        for operation, payload in (("status", "20100"), ("command", "091")):
            with self.subTest(operation=operation):
                def session(conn, stream, requests):
                    handshake(conn, stream, requests)
                    requests.append(stream.readline())
                    conn.sendall(response(payload, "1234"))
                    self.assertEqual(stream.readline(), b"")

                with Server(session) as server, self.assertLogs("h4.client", level="WARNING"):
                    c = StatusClient("PANEL0001", "owner123", "secret456", allow_plaintext=True,
                                     endpoint=server.endpoint, timeout=.15)
                    try:
                        c.connect()
                        with self.assertRaises(NetworkError) as caught:
                            if operation == "status":
                                c.status(datetime(2026, 11, 6))
                            else:
                                c.change_mode("1")
                        self.assertIn("timed out", str(caught.exception))
                        self.assertIn("unmatched CGS0210 x1", str(caught.exception))
                    finally:
                        c.close()
                    self.assertEqual(len(server.requests), 3)

    def test_unmatched_stream_keeps_deadline_and_bounds_private_logs(self):
        private = "owner123-secret456-PANEL0001-private-sensor-data"

        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            for _ in range(200):
                try:
                    conn.sendall(response(private, "1234"))
                except OSError:
                    break
                time.sleep(.005)

        with Server(session) as server, self.assertLogs("h4.client", level="WARNING") as logs:
            c = StatusClient("PANEL0001", "owner123", "secret456", allow_plaintext=True,
                             endpoint=server.endpoint, timeout=.15)
            try:
                c.connect()
                started = time.monotonic()
                with self.assertRaises(NetworkError):
                    c.status(datetime(2026, 11, 6))
                self.assertLess(time.monotonic() - started, .8)
            finally:
                c.close()
        text = "\n".join(logs.output)
        self.assertEqual(text.count("Ignored mismatched response marker"), 5)
        self.assertEqual(text.count("warnings suppressed"), 1)
        for value in (private, "owner123", "secret456", "PANEL0001", "1234"):
            self.assertNotIn(value, text)

    def test_nondecimal_marker_is_still_a_fatal_protocol_error(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.sendall(response("private-sensor-data", "abcd"))
            self.assertEqual(stream.readline(), b"")

        with Server(session) as server:
            c = client(endpoint=server.endpoint)
            try:
                c.connect()
                with self.assertRaisesRegex(ProtocolError, "marker_format=nondecimal") as caught:
                    c.status(datetime(2026, 11, 6))
                self.assertNotIn("abcd", str(caught.exception))
                self.assertNotIn("private-sensor-data", str(caught.exception))
            finally:
                c.close()

    def test_handshake_and_login_require_matching_markers_without_relogin(self):
        for phase in ("handshake", "login"):
            with self.subTest(phase=phase):
                def session(conn, stream, requests):
                    if phase == "handshake":
                        requests.append(stream.readline())
                        conn.sendall(b"CGS020112341\r\n")
                    else:
                        handshake(conn, stream, requests, login_response=b"CGS0204123410\r\n")
                    self.assertEqual(stream.readline(), b"")

                with Server(session) as server:
                    c = client(endpoint=server.endpoint)
                    with self.assertRaises(UnmatchedResponseMarker):
                        c.connect()
                    self.assertIsNone(c.wire)
                    self.assertEqual(len(server.requests), 1 if phase == "handshake" else 2)

    def test_idle_other_marker_is_diagnostic_only_and_does_not_poison_status(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests,
                      login_response=b"CGS0204555510\r\n" + response("20200", "1234"))
            requests.append(stream.readline())
            conn.sendall(response("20100"))
            self.assertEqual(stream.readline(), b"")

        with Server(session) as server, self.assertLogs("h4.client", level="WARNING") as logs:
            c = client(endpoint=server.endpoint, event_diagnostics=True)
            try:
                c.connect()
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    c.observe_events()
                    if any("phase=idle" in entry.getMessage() for entry in logs.records):
                        break
                    time.sleep(.01)
                self.assertTrue(any("phase=idle" in entry.getMessage() for entry in logs.records))
                self.assertEqual(c.status(datetime(2026, 11, 6)).mode, "disarmed")
            finally:
                c.close()
            self.assertEqual(len(server.requests), 3)

    def test_session_replacement_after_other_marker_still_stops(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.sendall(response("20200", "1234") + b"CGS0251\r\n")
            self.assertEqual(stream.readline(), b"")

        with Server(session) as server, self.assertLogs("h4.client", level="WARNING"):
            c = client(endpoint=server.endpoint)
            try:
                c.connect()
                with self.assertRaises(SessionReplacedError):
                    c.status(datetime(2026, 11, 6))
            finally:
                c.close()
            self.assertEqual(len(server.requests), 3)


if __name__ == "__main__":
    unittest.main()
