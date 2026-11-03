"""Idle observation uses local sockets; diagnostic bodies must never be logged."""
import time
import select
import threading
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock

from h4.client import Wire
from h4.protocol import ProtocolError, SessionReplacedError
from test_client import Server, client, handshake


def forwarded(payload):
    return f"CGS021055551{len(payload):04}{payload}\r\n".encode()


class EventDiagnosticTests(unittest.TestCase):
    def test_idle_poll_preserves_partial_and_coalesced_frames_for_rpc_reads(self):
        partial_sent = threading.Event()
        finish = threading.Event()

        def session(conn, stream, requests):
            conn.sendall(b"first\r\nsecond\r\npar")
            partial_sent.set()
            self.assertTrue(finish.wait(2))
            conn.sendall(b"tial\r\nthird\r\n")
            self.assertEqual(stream.readline(), b"")

        with Server(session) as server:
            wire = Wire(server.endpoint, 1)
            try:
                self.assertTrue(partial_sent.wait(2))
                self.assertTrue(select.select([wire.socket],[],[],1)[0])
                self.assertEqual(wire.poll(), "first")
                self.assertEqual(wire.poll(), "second")
                self.assertIsNone(wire.poll())
                self.assertIsNone(wire.poll()) # empty polling must not poison the stream
                finish.set()
                self.assertEqual(wire.read(time.monotonic()+1), "partial")
                self.assertEqual(wire.read(time.monotonic()+1), "third")
            finally:
                finish.set()
                wire.close()

    def test_idle_metadata_is_private_and_does_not_replace_next_polled_status(self):
        emit = threading.Event()
        idle_sent = threading.Event()
        private_body = "27owner123-secret456-PANEL0001-private-sensor-data"

        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.sendall(forwarded("20100"))
            self.assertTrue(emit.wait(2))
            conn.sendall(forwarded("20200") + forwarded(private_body))
            idle_sent.set()
            requests.append(stream.readline())
            # This notification is encountered while awaiting the next query.
            conn.sendall(forwarded(private_body) + forwarded("20100"))
            self.assertEqual(stream.readline(), b"")

        with Server(session) as server, self.assertLogs("h4.client", level="INFO") as logs:
            c = client(endpoint=server.endpoint, event_diagnostics=True)
            try:
                c.connect()
                self.assertEqual(c.status(datetime(2026,11,3)).mode,"disarmed")
                emit.set()
                self.assertTrue(idle_sent.wait(2))
                # sendall() completing at the peer does not prove arrival at
                # this socket (e.g. Nagle/delayed ACK). Simulate repeated idle
                # turns until both messages have actually been observed.
                deadline = time.monotonic()+1
                while time.monotonic() < deadline:
                    c.observe_events()
                    if sum("phase=idle" in r.getMessage() for r in logs.records) >= 2:
                        break
                    threading.Event().wait(.01)
                self.assertGreaterEqual(sum("phase=idle" in r.getMessage() for r in logs.records),2)
                # The idle home-mode payload is diagnostic only. It must not be
                # returned as the next request's disarmed response.
                self.assertEqual(c.status(datetime(2026,11,3)).mode,"disarmed")
            finally:
                emit.set()
                c.close()
            self.assertEqual(len(server.requests),4) # only handshake/login/two queries
        text = "\n".join(logs.output)
        self.assertIn("phase=idle server_command=10 device_command=20",text)
        self.assertIn("phase=idle server_command=10 device_command=27",text)
        self.assertIn("phase=status query server_command=10 device_command=27",text)
        self.assertIn("since_status_request_s=",text)
        for private in (private_body,"owner123","secret456","PANEL0001","private-sensor-data","CGS021055551"):
            self.assertNotIn(private,text)

    def test_idle_logout_is_respected_without_a_new_query_or_relogin(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests,
                      login_response=b"CGS0204555510\r\nCGS0251\r\n")
            self.assertEqual(stream.readline(),b"")

        with Server(session) as server:
            c = client(endpoint=server.endpoint,event_diagnostics=True)
            try:
                c.connect()
                with self.assertRaises(SessionReplacedError):c.observe_events()
            finally:c.close()
            self.assertEqual(len(server.requests),2)

    def test_unsupported_envelope_logs_only_a_safe_identifier_before_stopping(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests,
                      login_response=b"CGS0204555510\r\nCGS0253private-secret-body\r\n")
            self.assertEqual(stream.readline(),b"")
        with Server(session) as server, self.assertLogs("h4.client",level="INFO") as logs:
            c = client(endpoint=server.endpoint,event_diagnostics=True)
            try:
                c.connect()
                with self.assertRaises(ProtocolError):c.observe_events()
            finally:c.close()
        text = "\n".join(logs.output)
        self.assertIn("phase=idle server_command=53",text)
        self.assertIn("envelope=unsupported",text)
        self.assertNotIn("private-secret-body",text)

    def test_mqtt_worker_observes_idle_frames_but_publishes_only_polled_modes(self):
        from h4.bridge import connected_loop
        stop = threading.Event()
        reported = []

        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            # Coalesced data can remain buffered after the requested reply.
            conn.sendall(forwarded("20100") + forwarded("20200"))
            requests.append(stream.readline())
            conn.sendall(forwarded("20100"))
            self.assertEqual(stream.readline(),b"")

        class Broker:
            def report(self,status):
                reported.append(status.mode)
                if len(reported) == 2:stop.set()
            def take_command(self,timeout):
                stop.wait(timeout)
                return None

        with Server(session) as server, self.assertLogs("h4.client",level="INFO") as logs:
            c = client(endpoint=server.endpoint,event_diagnostics=True)
            try:
                c.connect()
                connected_loop(c,Broker(),stop,interval=.1,zone=ZoneInfo("UTC"),
                               confirmation_timeout=30,event_diagnostics=True)
            finally:c.close()
            self.assertEqual(len(server.requests),4)
        self.assertEqual(reported,["disarmed","disarmed"])
        self.assertTrue(any("phase=idle server_command=10 device_command=20" in s for s in logs.output))

    def test_diagnostics_are_off_by_default_and_log_volume_is_bounded(self):
        c = client()
        c.wire = Mock()
        c.observe_events()
        c.wire.poll.assert_not_called()
        c.event_diagnostics = True
        c.wire.poll.side_effect = ["CGS020255551"]*520 + [None]
        with self.assertLogs("h4.client",level="INFO") as logs:
            for _ in range(33):c.observe_events()
        self.assertEqual(sum("H4 RX phase=" in line for line in logs.output),500)
        self.assertEqual(sum("diagnostic log limit" in line for line in logs.output),1)


if __name__ == "__main__":unittest.main()
