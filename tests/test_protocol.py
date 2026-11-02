import unittest
from datetime import datetime

from h4.protocol import (
    AuthenticationError, PanelOfflineError, ProtocolError, directory_request,
    forwarded_payload, handshake_request, heartbeat_request, login_request,
    parse_directory, parse_frame, parse_status, require_success, status_request,
)


class ProtocolTests(unittest.TestCase):
    def test_known_requests_from_static_trace(self):
        self.assertEqual(directory_request("PANEL0001"), b"CGCPANEL0001\r\n")
        self.assertEqual(handshake_request(), b"CGC0201555511000\r\n")
        self.assertEqual(heartbeat_request(), b"CGC02025555\r\n")
        self.assertEqual(
            status_request(datetime(2026, 11, 2, 20, 0, 0)),
            b"CGC02105555001720202611022000001\r\n",
        )
        self.assertEqual(
            status_request(datetime(2026, 11, 1, 20, 0, 0)),
            b"CGC02105555001720202611012000007\r\n",
        )

    def test_login_lengths_and_empty_push_metadata(self):
        self.assertEqual(
            login_request("PANEL0001", "owner123", "secret456"),
            b"CGC02045555PANEL000108owner12309secret456107000110108000002en000\r\n",
        )

    def test_credentials_cannot_inject_frames(self):
        for bad in ("user\r\nCGC", "\x00", "\u00e9", "x" * 100, ""):
            with self.subTest(value=repr(bad)), self.assertRaises(ValueError):
                login_request("PANEL0001", bad, "secret456")

    def test_directory_routing(self):
        self.assertEqual(parse_directory("CGS109127.0.0.10530006"), ("127.0.0.1", 30006))
        self.assertEqual(parse_directory("CGS109127.0.0.100"), ("127.0.0.1", 10001))
        for bad in ("CGS0", "CGS1", "CGS100", "CGS109127.0.0.10599999",
                    "CGS109127.0.0.10280extra", "CGS106a/b.cd0280"):
            with self.subTest(response=bad), self.assertRaises(ProtocolError):
                parse_directory(bad)

    def test_failed_login_has_safe_error(self):
        with self.assertRaisesRegex(AuthenticationError, "Login rejected.*03"):
            require_success(parse_frame("CGS02045555003secret-not-to-log"))
        with self.assertRaises(AuthenticationError) as caught:
            require_success(parse_frame("CGS020455550secret-not-to-log"))
        self.assertNotIn("secret-not-to-log", str(caught.exception))

    def test_offline_and_session_revocation(self):
        with self.assertRaises(PanelOfflineError):
            parse_frame("CGS01")
        for line in ("CGS0251", "CGS0252"):
            with self.assertRaises(AuthenticationError):
                parse_frame(line)

    def test_relay_lengths_are_enforced(self):
        self.assertEqual(forwarded_payload(parse_frame("CGS021055551000520100")), "20100")
        for line in ("CGS021055551000620100", "CGS021055551xxxx20100", "CGS021055551"):
            with self.subTest(response=line), self.assertRaises(ProtocolError):
                forwarded_payload(parse_frame(line))

    def test_modes_are_separate_from_alarm_flags(self):
        for code, expected in (("0", "armed_away"), ("1", "disarmed"), ("2", "armed_home"), ("9", "unknown")):
            with self.subTest(code=code):
                self.assertEqual(parse_status("20" + code + "00").mode, expected)

    def test_accessory_fields_preserved_without_semantic_guesses(self):
        status = parse_status("20001" + "0102010320261102200000")
        self.assertEqual(status.mode, "armed_away")
        self.assertEqual(status.as_dict()["accessories"][0], {
            "type_code": "01", "number": "02", "state_code": "0",
            "alarm_flag": "1", "alarm_type_code": "03", "alarm_time": "20261102200000",
        })
        for malformed in ("20001", "20100garbage", "20", "201xx"):
            with self.subTest(payload=malformed), self.assertRaises(ProtocolError):
                parse_status(malformed)

    def test_unrecognized_headers_and_markers(self):
        for line in ("", "CGS0201", "CGC020155551", "CGS020100001", "CGS02xx55551"):
            with self.subTest(line=line), self.assertRaises(ProtocolError):
                parse_frame(line)


if __name__ == "__main__":
    unittest.main()
