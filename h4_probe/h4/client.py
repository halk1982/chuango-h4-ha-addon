"""Bounded status-only sessions. No live endpoints are contacted on import."""
import socket
import select
import logging
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime

from .protocol import (
    ProtocolError, ServerRejectedError, UnmatchedResponseMarker, forwarded_payload, directory_request, handshake_request,
    heartbeat_request, login_request, parse_directory, parse_frame, parse_status,
    require_success, status_request,
    mode_request, require_mode_ack,
)

DIRECTORY = ("www.4g-alarm.com", 30010)
MAX_LINE = 65536
LOG = logging.getLogger(__name__)


class NetworkError(Exception):
    """Safe transport diagnostics: no endpoints, credentials or response bodies."""


class NetworkTimeoutError(NetworkError):
    """A transport deadline expired; distinct from disconnect/reset/DNS errors."""


class Wire:
    def __init__(self, endpoint, timeout):
        self.socket = socket.create_connection(endpoint, timeout=timeout)
        self._buffer = bytearray()

    def close(self):
        self.socket.close()

    def write(self, packet):
        self.socket.sendall(packet)

    def _line(self):
        end = self._buffer.find(b"\n")
        if end < 0:
            if len(self._buffer) > MAX_LINE:
                raise ProtocolError("Oversized or unterminated response")
            return None
        if end + 1 > MAX_LINE:
            raise ProtocolError("Oversized or unterminated response")
        line = bytes(self._buffer[:end+1])
        del self._buffer[:end+1]
        try:
            return line.rstrip(b"\r\n").decode("ascii")
        except UnicodeDecodeError:
            raise ProtocolError("Non-ASCII response; unsupported protocol variant") from None

    def _receive(self):
        data = self.socket.recv(MAX_LINE + 1 - len(self._buffer))
        if not data:
            if self._buffer:
                raise ProtocolError("Oversized or unterminated response")
            raise ConnectionError("Server closed the connection")
        self._buffer.extend(data)

    def read(self, deadline):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Response deadline exceeded")
            line = self._line()
            if line is not None:
                return line
            if not select.select([self.socket], [], [], remaining)[0]:
                raise TimeoutError("Response deadline exceeded")
            self.socket.settimeout(remaining)
            self._receive()

    def poll(self):
        """Return one complete available line without blocking on a partial one.

        The same buffer serves RPC reads and idle observation. A buffered file
        reader plus select() would miss data already buffered outside the socket,
        and socket-file timeouts can poison subsequent reads.
        """
        while True:
            line = self._line()
            if line is not None:
                return line
            if not select.select([self.socket], [], [], 0)[0]:
                return None
            self._receive()


class StatusClient:
    def __init__(self, device_id, username, password, *, allow_plaintext=False,
                 directory=DIRECTORY, endpoint=None, timeout=15, event_diagnostics=False,
                 request_timing=False):
        if not allow_plaintext:
            raise ValueError("The traced app uses plaintext TCP. Explicit opt-in is required.")
        if not 0 < timeout <= 120:
            raise ValueError("Timeout must be between 0 and 120 seconds")
        if type(event_diagnostics) is not bool:
            raise ValueError("event_diagnostics must be a boolean")
        if type(request_timing) is not bool:
            raise ValueError("request_timing must be a boolean")
        # Validate credentials before initiating any connection.
        self._login = login_request(device_id, username, password)
        self._lookup = directory_request(device_id)
        self.directory, self.endpoint, self.timeout = directory, endpoint, timeout
        self.wire = None
        self._reply_counts = Counter()
        self.event_diagnostics = event_diagnostics
        self.request_timing = request_timing
        self._phase = "idle"
        self._last_status_request = None
        self._diagnostic_lines = 0
        self._marker_warnings = 0

    @contextmanager
    def _transport(self, phase):
        self._reply_counts.clear()
        previous_phase, self._phase = self._phase, phase
        try:
            yield
        except ServerRejectedError as error:
            error.set_phase(phase)
            raise
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
            failure = NetworkTimeoutError if isinstance(error, TimeoutError) else NetworkError
            raise failure(f"{phase}: {reason}{replies}") from None
        finally:
            self._phase = previous_phase

    def _diagnostic_rx(self, frame, line):
        if not self.event_diagnostics or self._diagnostic_lines >= 500:
            return
        server_command = "unrecognized"
        if len(line) >= 7 and line.startswith("CGS02") and line[5:7].isascii() and line[5:7].isdecimal():
            server_command = line[5:7]
        envelope = "recognized" if frame is not None else "unsupported"
        if line == "CGS01" or line.startswith(("CGS0251","CGS0252")):
            envelope = "notification"
        device_command = "unavailable" if frame is None else "none"
        if frame is not None and frame.command == "10":
            try:
                payload = forwarded_payload(frame)
                if len(payload) >= 2 and payload[:2].isascii() and payload[:2].isdecimal():
                    device_command = payload[:2]
            except ProtocolError:
                device_command = "unavailable"
        age = ("none" if self._last_status_request is None else
               f"{time.monotonic()-self._last_status_request:.3f}")
        # All fields are local constants/numbers or validated two-digit IDs.
        # Never log the response body, status values, account or endpoint.
        LOG.info("H4 RX phase=%s server_command=%s device_command=%s frame_bytes=%d since_status_request_s=%s envelope=%s",
                 self._phase, server_command, device_command, len(line), age, envelope)
        self._diagnostic_lines += 1
        if self._diagnostic_lines == 500:
            LOG.info("H4 RX diagnostic log limit reached for this session")

    def _parse_received(self, line):
        try:
            frame = parse_frame(line)
        except UnmatchedResponseMarker as error:
            self._diagnostic_rx(None, line)
            # Never treat another marker as a reply to our request. Established
            # sessions may receive other traffic; ignore it within the existing
            # read deadline, without accepting its payload or replaying actions.
            # Handshake/login still require the exact expected marker.
            if self._phase not in ("idle", "status query", "mode command"):
                raise
            self._reply_counts["unmatched CGS02" + error.command] += 1
            if self._marker_warnings < 5:
                LOG.warning(
                    "Ignored mismatched response marker; phase=%s server_command=%s frame_bytes=%d",
                    self._phase, error.command, len(line),
                )
                self._marker_warnings += 1
                if self._marker_warnings == 5:
                    LOG.warning("Further mismatched-marker warnings suppressed for this connection")
            return None
        except ProtocolError:
            self._diagnostic_rx(None, line)
            raise
        self._diagnostic_rx(frame, line)
        return frame

    def _read_frame(self, deadline):
        while True:
            frame = self._parse_received(self.wire.read(deadline))
            if frame is not None:
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
        self._last_status_request = None
        self._diagnostic_lines = 0
        self._marker_warnings = 0
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

    def _write_request(self, packet, operation, scheduled_due, schedule):
        if not self.request_timing:
            self.wire.write(packet)
            return
        # Only status/heartbeat call this helper. Validate IDs before logging;
        # never interpolate packet bodies, endpoints or exception messages.
        expected = {"status": b"10", "heartbeat": b"02"}[operation]
        server = expected.decode("ascii") if packet[:7] == b"CGC02" + expected else "unavailable"
        device = "none" if operation == "heartbeat" else "unavailable"
        if operation == "status" and server == "10" and packet[15:17] == b"20":
            device = "20"
        marker = packet[7:11]
        marker = marker.decode("ascii") if len(marker) == 4 and marker.isdigit() else "unavailable"
        schedule = schedule if schedule in (
            "initial", "poll", "post_command", "periodic", "probe_wait_end", "direct"
        ) else "direct"
        due = "none" if scheduled_due is None else f"{scheduled_due:.6f}"
        fields = (operation, server, device, marker, len(packet), schedule, due)
        message = ("H4 TX operation=%s server_command=%s device_command=%s marker=%s "
                   "intended_bytes=%d schedule=%s due_mono_s=%s")
        LOG.info(message + " event=write_start observed_mono_s=%.6f", *fields, time.monotonic())
        # Sample actual call entry after the start log, excluding its overhead
        # from write duration while including it in scheduling lateness.
        write_start = time.monotonic()
        try:
            self.wire.write(packet)
        except OSError as error:
            end = time.monotonic()
            lateness = "none" if scheduled_due is None else f"{max(0, write_start-scheduled_due):.6f}"
            category = ("timeout" if isinstance(error, TimeoutError) else
                        "reset" if isinstance(error, ConnectionResetError) else "write-error")
            LOG.info(message + " event=write_failed start_mono_s=%.6f lateness_s=%s "
                     "end_mono_s=%.6f write_duration_s=%.6f failure=%s progress=unknown",
                     *fields, write_start, lateness, end, end-write_start, category)
            raise
        end = time.monotonic()
        lateness = "none" if scheduled_due is None else f"{max(0, write_start-scheduled_due):.6f}"
        LOG.info(message + " event=write_complete start_mono_s=%.6f lateness_s=%s "
                 "end_mono_s=%.6f write_duration_s=%.6f result=local_stack_accepted",
                 *fields, write_start, lateness, end, end-write_start)

    def status(self, now: datetime, *, scheduled_due=None, schedule="direct"):
        if self.wire is None:
            raise RuntimeError("Client is not connected")
        with self._transport("status query"):
            self._last_status_request = time.monotonic()
            self._write_request(status_request(now), "status", scheduled_due, schedule)
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
        next_heartbeat = time.monotonic() + 10
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(min(1 if self.event_diagnostics else 10, remaining))
            self.observe_events()
            now = time.monotonic()
            if now >= next_heartbeat or now >= deadline:
                if self.request_timing:
                    self.heartbeat(scheduled_due=min(next_heartbeat, deadline),
                                   schedule="probe_wait_end" if deadline <= next_heartbeat else "periodic")
                else:
                    self.heartbeat()
                next_heartbeat = now + 10
        return deadline

    def observe_events(self):
        """Diagnostics only: drain idle frames, never publish/confirm mode from them.

        An idle frame may be a delayed/duplicate reply, not necessarily push.
        Explicit session/offline notifications still follow existing handling.
        """
        if not self.event_diagnostics or self.wire is None:
            return
        with self._transport("idle"):
            for _ in range(16):
                line = self.wire.poll()
                if line is None:
                    break
                self._parse_received(line)

    def heartbeat(self, *, scheduled_due=None, schedule="direct"):
        with self._transport("heartbeat write"):
            self._write_request(heartbeat_request(), "heartbeat", scheduled_due, schedule)

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
