"""Bounded status-only sessions. No live endpoints are contacted on import."""
import socket
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime

from .protocol import (
    ProtocolError, forwarded_payload, directory_request, handshake_request,
    heartbeat_request, login_request, parse_directory, parse_frame, parse_status,
    require_success, status_request,
    mode_request, require_mode_ack,
)

DIRECTORY = ("www.4g-alarm.com", 30010)
MAX_LINE = 65536


class NetworkError(Exception):
    """Safe transport diagnostics: no endpoints, credentials or response bodies."""


class Wire:
    def __init__(self, endpoint, timeout):
        self.socket = socket.create_connection(endpoint, timeout=timeout)
        self.reader = self.socket.makefile("rb")

    def close(self):
        try:
            self.reader.close()
        finally:
            self.socket.close()

    def write(self, packet):
        self.socket.sendall(packet)

    def read(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Response deadline exceeded")
        self.socket.settimeout(remaining)
        line = self.reader.readline(MAX_LINE + 1)
        if not line:
            raise ConnectionError("Server closed the connection")
        if len(line) > MAX_LINE or not line.endswith(b"\n"):
            raise ProtocolError("Oversized or unterminated response")
        try:
            return line.rstrip(b"\r\n").decode("ascii")
        except UnicodeDecodeError:
            raise ProtocolError("Non-ASCII response; unsupported protocol variant") from None


class StatusClient:
    def __init__(self, device_id, username, password, *, allow_plaintext=False,
                 directory=DIRECTORY, endpoint=None, timeout=15):
        if not allow_plaintext:
            raise ValueError("The traced app uses plaintext TCP. Explicit opt-in is required.")
        if not 0 < timeout <= 120:
            raise ValueError("Timeout must be between 0 and 120 seconds")
        # Validate credentials before initiating any connection.
        self._login = login_request(device_id, username, password)
        self._lookup = directory_request(device_id)
        self.directory, self.endpoint, self.timeout = directory, endpoint, timeout
        self.wire = None
        self._reply_counts = Counter()

    @contextmanager
    def _transport(self, phase):
        self._reply_counts.clear()
        try:
            yield
        except OSError as error:
            if isinstance(error, TimeoutError):
                reason = "timed out"
            elif isinstance(error, ConnectionResetError):
                reason = "connection reset by peer"
            elif isinstance(error, BrokenPipeError):
                reason = "connection no longer accepts writes"
            elif isinstance(error, ConnectionRefusedError):
                reason = "connection refused"
            elif isinstance(error, socket.gaierror):
                reason = "DNS lookup failed"
            elif isinstance(error, ConnectionError):
                reason = "connection closed by peer"
            else:
                reason = "socket error"
                if isinstance(error.errno, int):
                    reason += f" (errno {error.errno})"
            summary = ", ".join(f"{code} x{count}" for code, count in self._reply_counts.most_common(5))
            replies = f"; reply codes seen: {summary}" if summary else "; no reply decoded during this step"
            raise NetworkError(f"{phase}: {reason}{replies}") from None

    def _read_frame(self, deadline):
        frame = parse_frame(self.wire.read(deadline))
        self._reply_counts["CGS02" + frame.command] += 1
        return frame

    def close(self):
        if self.wire is not None:
            self.wire.close()
            self.wire = None

    def _expect(self, command):
        deadline = time.monotonic() + self.timeout
        while True:
            frame = self._read_frame(deadline)
            if frame.command == command:
                return frame
            # Heartbeats and unsolicited notifications must not satisfy a
            # different request or get mistaken for a confirmed mode.

    def connect(self):
        self.close()
        endpoint = self.endpoint
        if endpoint is None:
            with self._transport("directory connection"):
                directory = Wire(self.directory, self.timeout)
            try:
                with self._transport("directory lookup"):
                    directory.write(self._lookup)
                    endpoint = parse_directory(directory.read(time.monotonic() + self.timeout))
            finally:
                directory.close()
        with self._transport("alarm server connection"):
            self.wire = Wire(endpoint, self.timeout)
        try:
            with self._transport("handshake"):
                self.wire.write(handshake_request())
                handshake = self._expect("01")
                if require_success(handshake):
                    raise ProtocolError("Unexpected handshake response length")
            with self._transport("login response"):
                self.wire.write(self._login)
                require_success(self._expect("04"))
        except BaseException:
            self.close()
            raise

    def status(self, now: datetime):
        if self.wire is None:
            raise RuntimeError("Client is not connected")
        with self._transport("status query"):
            self.wire.write(status_request(now))
            deadline = time.monotonic() + self.timeout
            while True:
                frame = self._read_frame(deadline)
                if frame.command == "10":
                    payload = forwarded_payload(frame)
                    if len(payload) >= 2 and payload[:2].isascii() and payload[:2].isdecimal():
                        self._reply_counts["device " + payload[:2]] += 1
                    if payload.startswith("20"):
                        return parse_status(payload)

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(min(10, remaining))
            self.heartbeat()

    def heartbeat(self):
        with self._transport("heartbeat write"):
            self.wire.write(heartbeat_request())

    def change_mode(self, mode_code):
        """Send once, require the app's 09 acknowledgement; caller must read state."""
        packet = mode_request(mode_code)
        with self._transport("mode command"):
            self.wire.write(packet)
            deadline = time.monotonic() + self.timeout
            while True:
                frame = self._read_frame(deadline)
                if frame.command == "10":
                    payload = forwarded_payload(frame)
                    if payload.startswith("09"):
                        require_mode_ack(payload)
                        return
