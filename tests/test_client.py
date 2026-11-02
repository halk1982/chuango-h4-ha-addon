"""Real loopback sockets with scripted responses; no vendor/device traffic."""
import contextlib
import io
import json
import socket
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from h4.client import MAX_LINE, NetworkError, StatusClient, Wire
from h4.protocol import AuthenticationError, PanelOfflineError, ProtocolError
from h4.__main__ import main, run


class Server:
    def __init__(self, handler):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(3)
        self.endpoint = self.listener.getsockname()
        self.handler, self.errors, self.requests = handler, [], []

    def __enter__(self):
        def serve():
            try:
                with self.listener.accept()[0] as conn:
                    conn.settimeout(3)
                    with conn.makefile("rb") as stream:
                        self.handler(conn, stream, self.requests)
            except BaseException as error:
                self.errors.append(error)
        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, kind, error, traceback):
        self.thread.join(4)
        self.listener.close()
        if self.thread.is_alive():
            raise AssertionError("Mock server did not finish")
        if self.errors:
            raise self.errors[0]


def handshake(conn, stream, requests, *, login_response=b"CGS0204555510\r\n"):
    requests.append(stream.readline())
    if requests[-1] != b"CGC0201555511000\r\n":
        raise AssertionError("Wrong handshake")
    # Fragmentation and multiple coalesced messages exercise actual framing.
    conn.sendall(b"CGS0201")
    conn.sendall(b"55551\r\n")
    requests.append(stream.readline())
    if requests[-1] != b"CGC02045555PANEL000108owner12309secret456107000110108000002en000\r\n":
        raise AssertionError("Wrong login")
    conn.sendall(login_response)


def client(**kwargs):
    return StatusClient("PANEL0001", "owner123", "secret456", allow_plaintext=True, timeout=1, **kwargs)


class ClientTests(unittest.TestCase):
    def test_complete_directory_login_status_and_mode_transition(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            for mode in ("1", "0", "2"):
                requests.append(stream.readline())
                self.assertEqual(requests[-1], b"CGC02105555001720202611022000001\r\n")
                conn.sendall(b"CGS020255551\r\n" + f"CGS021055551000520{mode}00\r\n".encode())
        with Server(session) as panel:
            def directory(conn, stream, requests):
                requests.append(stream.readline())
                self.assertEqual(requests[-1], b"CGCPANEL0001\r\n")
                host, port = panel.endpoint
                conn.sendall(f"CGS109{host}{len(str(port)):02}{port}\r\n".encode())
            with Server(directory) as lookup:
                c = client(directory=lookup.endpoint)
                try:
                    c.connect()
                    actual = [c.status(datetime(2026,11,2,20)).mode for _ in range(3)]
                    self.assertEqual(actual, ["disarmed", "armed_away", "armed_home"])
                finally:
                    c.close()
            # Login, handshake and status are the only packets sent.
            self.assertEqual(len(panel.requests), 5)

    def test_failed_login_is_not_retried_or_followed_by_query(self):
        def reject(conn, stream, requests):
            handshake(conn, stream, requests, login_response=b"CGS02045555003\r\n")
            self.assertEqual(stream.readline(), b"")
        with Server(reject) as server:
            c = client(endpoint=server.endpoint)
            with self.assertRaises(AuthenticationError):
                c.connect()
            self.assertIsNone(c.wire)
            self.assertEqual(len(server.requests), 2)

    def test_offline_response_never_returns_cached_status(self):
        def offline(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.sendall(b"CGS01\r\n")
        with Server(offline) as server:
            c = client(endpoint=server.endpoint)
            try:
                c.connect()
                with self.assertRaises(PanelOfflineError):
                    c.status(datetime(2026,11,2))
            finally:
                c.close()

    def test_transport_bounds_and_eof(self):
        for response, error in ((b"", ConnectionError), (b"x"*(MAX_LINE+1)+b"\n", ProtocolError),
                                (b"bad\xff\n", ProtocolError), (b"unterminated", ProtocolError)):
            with self.subTest(error=error.__name__):
                with Server(lambda conn, stream, requests: conn.sendall(response)) as server:
                    wire = Wire(server.endpoint,1)
                    try:
                        with self.assertRaises(error):
                            wire.read(__import__('time').monotonic()+1)
                    finally:
                        wire.close()

    def test_plaintext_requires_opt_in_before_connect(self):
        with patch("socket.create_connection") as connect:
            with self.assertRaises(ValueError):
                StatusClient("PANEL0001", "owner123", "secret456")
            connect.assert_not_called()

    def test_cli_outputs_confirmed_modes_without_credentials(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.sendall(b"CGS021055551000520100\r\n")
        with Server(session) as server:
            output, errors = io.StringIO(), io.StringIO()
            def factory(*args, **kwargs):
                return StatusClient(*args, endpoint=server.endpoint, **kwargs)
            with patch("h4.__main__.StatusClient", side_effect=factory), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                run({"device_id":"PANEL0001", "username":"owner123", "password":"secret456",
                     "allow_plaintext":True, "samples":1})
            self.assertEqual(json.loads(output.getvalue())["mode"], "disarmed")
            for secret in ("PANEL0001", "owner123", "secret456"):
                self.assertNotIn(secret, output.getvalue()+errors.getvalue())

    def test_logout_after_successful_status_is_reported_without_relogin(self):
        for code, expected in (("51", "Session ended:"), ("52", "Account notification:")):
            with self.subTest(notification=code):
                def session(conn, stream, requests):
                    handshake(conn, stream, requests)
                    requests.append(stream.readline())
                    conn.sendall(b"CGS021055551000520200\r\n")
                    requests.append(stream.readline())
                    conn.sendall(f"CGS02{code}\r\n".encode())
                    # The client must close, not try another login or query.
                    self.assertEqual(stream.readline(), b"")
                with Server(session) as server, tempfile.TemporaryDirectory() as tmp:
                    options = Path(tmp)/"options.json"
                    options.write_text(json.dumps({
                        "device_id":"PANEL0001", "username":"owner123", "password":"secret456",
                        "allow_plaintext":True, "samples":3, "interval":10,
                    }))
                    output, errors = io.StringIO(), io.StringIO()
                    def factory(*args, **kwargs):
                        return StatusClient(*args, endpoint=server.endpoint, **kwargs)
                    with patch("h4.__main__.StatusClient", side_effect=factory), \
                            patch.object(StatusClient, "wait"), \
                            contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                        result = main(["--options", str(options)])
                    self.assertEqual(result, 1)
                    self.assertEqual(len(output.getvalue().splitlines()), 1)
                    self.assertEqual(json.loads(output.getvalue())["mode"], "armed_home")
                    self.assertIn(expected, errors.getvalue())
                    self.assertIn("CGS02"+code, errors.getvalue())
                    self.assertIn("no automatic login retries", errors.getvalue())
                    self.assertNotIn("Authentication failed", errors.getvalue())
                    for secret in ("PANEL0001", "owner123", "secret456"):
                        self.assertNotIn(secret, output.getvalue()+errors.getvalue())
                    self.assertEqual(len(server.requests), 4)

    def test_timeout_reports_phase_and_safe_reply_codes_without_retry(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.sendall(b"CGS020255551\r\n")
            # A heartbeat is not a fresh panel status. Wait for client timeout
            # and close, rather than accepting another login/query.
            self.assertEqual(stream.readline(), b"")
        with Server(session) as server:
            c = StatusClient("PANEL0001", "owner123", "secret456", allow_plaintext=True,
                             endpoint=server.endpoint, timeout=0.2)
            try:
                c.connect()
                with self.assertRaises(NetworkError) as caught:
                    c.status(datetime(2026,11,2))
                message = str(caught.exception)
                self.assertIn("status query: timed out", message)
                self.assertIn("CGS0202 x1", message)
                for secret in ("PANEL0001", "owner123", "secret456"):
                    self.assertNotIn(secret, message)
            finally:
                c.close()
            self.assertEqual(len(server.requests), 3)

    def test_remote_close_is_not_reported_as_a_timeout_or_logout(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.shutdown(socket.SHUT_WR)
            self.assertEqual(stream.readline(), b"")
        with Server(session) as server:
            c = client(endpoint=server.endpoint)
            try:
                c.connect()
                with self.assertRaisesRegex(NetworkError, "status query: connection closed by peer"):
                    c.status(datetime(2026,11,2))
            finally:
                c.close()

    def test_cli_compact_output_tracks_received_mode_changes(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            for mode in ("1", "2", "2"):
                requests.append(stream.readline())
                conn.sendall(f"CGS021055551000520{mode}00\r\n".encode())
        with Server(session) as server:
            output, errors = io.StringIO(), io.StringIO()
            def factory(*args, **kwargs):
                return StatusClient(*args, endpoint=server.endpoint, **kwargs)
            with patch("h4.__main__.StatusClient", side_effect=factory), \
                    patch.object(StatusClient, "wait"), \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                run({"device_id":"PANEL0001", "username":"owner123", "password":"secret456",
                     "allow_plaintext":True, "samples":3})
            rows = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual([r['mode'] for r in rows], ['disarmed','armed_home','armed_home'])
            self.assertEqual([r['mode_changed'] for r in rows], [None,True,False])
            self.assertTrue(all(r['accessory_count'] == 0 and 'accessories' not in r for r in rows))
            self.assertIn("Probe completed normally after 3 samples", errors.getvalue())

    def test_cli_accessory_details_are_opt_in(self):
        def session(conn, stream, requests):
            handshake(conn, stream, requests)
            requests.append(stream.readline())
            conn.sendall(b"CGS021055551000520100\r\n")
        with Server(session) as server:
            output = io.StringIO()
            def factory(*args, **kwargs):
                return StatusClient(*args, endpoint=server.endpoint, **kwargs)
            with patch("h4.__main__.StatusClient", side_effect=factory), \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                run({"device_id":"PANEL0001", "username":"owner123", "password":"secret456",
                     "allow_plaintext":True, "samples":1, "include_accessories":True})
            self.assertEqual(json.loads(output.getvalue())['accessories'], [])

    def test_mode_command_is_sent_once_and_followed_by_actual_status(self):
        def session(conn,stream,requests):
            handshake(conn,stream,requests)
            requests.append(stream.readline())
            self.assertEqual(requests[-1],b'CGC021055550003092\r\n')
            conn.sendall(b'CGS0210555510003091\r\n')
            requests.append(stream.readline())
            conn.sendall(b'CGS021055551000520100\r\n')
        with Server(session) as server:
            c=client(endpoint=server.endpoint)
            try:
                c.connect();c.change_mode('2')
                # Even an accepted home command cannot override a disarmed reply.
                self.assertEqual(c.status(datetime(2026,11,2)).mode,'disarmed')
            finally:c.close()
            self.assertEqual(len(server.requests),4)


if __name__ == "__main__":
    unittest.main()
