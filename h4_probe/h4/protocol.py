"""Protocol reconstructed from H4 Smarthome 5.5.0, not live-device validated.

Only directory lookup, handshake, login, heartbeat and status query builders are
provided. There is deliberately no command or configuration-writing API.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime

MARKER = "5555"
MODES = {"0": "armed_away", "1": "disarmed", "2": "armed_home"}


class ProtocolError(Exception):
    """Malformed or unsupported response; messages never include wire data."""


class AuthenticationError(ProtocolError):
    pass


class PanelOfflineError(ProtocolError):
    pass


def _text(value: str, maximum: int = 99, *, empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value):
        raise ValueError("Invalid protocol field length")
    if any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ValueError("This experimental client supports printable ASCII fields only")
    return value


def _lp(value: str, width: int = 2) -> str:
    _text(value, 10**width - 1)
    return f"{len(value):0{width}d}{value}"


def _request(command: str, body: str = "") -> bytes:
    return f"CGC02{command}{MARKER}{body}\r\n".encode("ascii")


def directory_request(device_id: str) -> bytes:
    return f"CGC{_text(device_id, empty=False)}\r\n".encode("ascii")


def handshake_request() -> bytes:
    return _request("01", "11000")


def heartbeat_request() -> bytes:
    return _request("02")


def login_request(device_id: str, username: str, password: str) -> bytes:
    """Use empty optional push IDs, as supported by the app's empty defaults.

    Whether the service accepts these defaults is an outstanding live check.
    The explicit device ID substitutes for the app's saved ObjUser.id.
    """
    for value in (device_id, username, password):
        _text(value, empty=False)
    client_info = _lp("") + "01" + "101"
    push_info = _lp("") + _lp("") + _lp("en")
    body = (device_id + _lp(username) + _lp(password) + "1"
            + _lp(client_info) + _lp(push_info) + _lp("", 3))
    return _request("04", body)


def status_request(now: datetime) -> bytes:
    # GF.getCurrDate(): local yyyyMMddHHmmss + Monday=1, ..., Sunday=7.
    payload = "20" + now.strftime("%Y%m%d%H%M%S") + str(now.isoweekday())
    return _request("10", _lp(payload, 4))


def _number(value: str) -> int:
    if not value or any(c not in "0123456789" for c in value):
        raise ProtocolError("Expected an ASCII decimal length")
    return int(value)


def parse_directory(line: str) -> tuple[str, int]:
    if not line.startswith("CGS") or len(line) < 4:
        raise ProtocolError("Unrecognized directory response")
    if line[3] != "1":
        raise ProtocolError("Directory did not return a server for this panel")
    body = line[4:]
    if len(body) < 2:
        raise ProtocolError("Truncated directory response")
    size = _number(body[:2])
    if size == 0 or len(body) < 2 + size + 2:
        raise ProtocolError("Truncated directory server address")
    host, body = body[2:2+size], body[2+size:]
    # Server-directed endpoints are expected. Restrict characters and reject
    # protocol separators; private addresses may be needed for a LAN test.
    if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in host):
        raise ProtocolError("Unsupported server hostname")
    size = _number(body[:2])
    if len(body[2:]) != size:
        raise ProtocolError("Directory port length does not match response")
    port = 10001 if size == 0 else _number(body[2:])
    if not 1 <= port <= 65535:
        raise ProtocolError("Invalid server port")
    return host, port


@dataclass(frozen=True)
class Frame:
    command: str
    body: str = field(repr=False)


def parse_frame(line: str) -> Frame:
    if line == "CGS01":
        raise PanelOfflineError("Server reports the panel offline")
    if line.startswith(("CGS0251", "CGS0252")):
        raise AuthenticationError("Session revoked or account removed; probe stopped")
    if len(line) < 11 or not line.startswith("CGS02"):
        raise ProtocolError("Unrecognized response header")
    command = line[5:7]
    _number(command)
    if line[7:11] != MARKER:
        raise ProtocolError("Unexpected response marker")
    return Frame(command, line[11:])


def require_success(frame: Frame) -> str:
    if not frame.body:
        raise ProtocolError("Missing result flag")
    if frame.body[0] != "1":
        code = frame.body[1:3]
        suffix = f" (code {code})" if len(code) == 2 and code.isascii() and code.isdecimal() else ""
        if frame.command == "04":
            raise AuthenticationError("Login rejected" + suffix)
        raise ProtocolError("Server rejected request" + suffix)
    return frame.body[1:]


def forwarded_payload(frame: Frame) -> str:
    if frame.command != "10":
        raise ProtocolError("Expected a forwarded device response")
    body = require_success(frame)
    if len(body) < 4:
        raise ProtocolError("Missing forwarded payload length")
    size = _number(body[:4])
    if len(body[4:]) != size:
        raise ProtocolError("Forwarded payload length does not match response")
    return body[4:]


@dataclass(frozen=True)
class Accessory:
    type_code: str
    number: str
    state_code: str
    alarm_flag: str
    alarm_type_code: str
    alarm_time: str


@dataclass(frozen=True)
class Status:
    mode: str
    mode_code: str
    accessories: tuple[Accessory, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def parse_status(payload: str) -> Status:
    if not payload.startswith("20") or len(payload) < 5:
        raise ProtocolError("Expected a status response (device command 20)")
    mode = payload[2]
    count = _number(payload[3:5])
    body = payload[5:]
    if len(body) != count * 22:
        raise ProtocolError("Accessory count does not match status response length")
    accessories = []
    for i in range(count):
        row = body[i*22:(i+1)*22]
        accessories.append(Accessory(row[:2], row[2:4], row[4], row[5], row[6:8], row[8:22]))
    # Unknown modes must never become an armed/disarmed assertion.
    return Status(MODES.get(mode, "unknown"), mode, tuple(accessories))
