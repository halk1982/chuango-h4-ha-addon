# 0.2.1

- Add opt-in `event_diagnostics` to inspect incoming messages between polls in
  MQTT and probe modes. Polling remains the source of reported state.
- Log only read phase, validated command identifiers, frame size and elapsed
  time since the last status request; no response bodies or sensor/account data.
- Share one bounded socket buffer between normal reads and nonblocking idle
  observation so fragmented/coalesced messages remain intact.
- Bound diagnostic output to 500 receive lines per connection. Diagnostics are
  disabled by default; no extra queries or changes to command confirmation.
- Document a controlled RF/app test. Idle frames may be delayed/duplicate
  replies; they do not alone prove server push or justify an MQTT state update.

# 0.2.0

- Add continuous MQTT mode with Home Assistant discovery and automatic HAOS
  Mosquitto service settings. Existing installations default to short probe mode.
- Publish mode/accessory-count sensors and availability; normal state messages
  are not retained. Last Will and fresh-state gating handle broker/bridge loss.
- Add opt-in experimental arm-home, arm-away and disarm controls. Send once,
  validate the acknowledgement and confirm through actual status reads.
- Ignore stored retained/duplicate, stale/offline and busy commands; do not
  replay uncertain actions after reconnect.
- Add bounded cloud reconnect backoff; explicit authentication/session failures
  stop without login loops. Keep broker reconnect independent of alarm logins.
- Checksum-pin paho-mqtt 2.1.0. Validate with mock alarm servers and an isolated
  real Mosquitto broker. Physical commands and HomeKit remain unverified.

# 0.1.2

- Distinguish transport timeouts, peer-closed connections, resets, refused
  connections and DNS failures, with the failing connection/query step.
- Include bounded, sanitized reply command codes in transport diagnostics;
  credentials, server addresses and message bodies are excluded.
- Use compact status logs by default: mode, mode-change indicator and accessory
  count. Raw accessory records are optional through `include_accessories`.
- Log normal completion explicitly so it is distinct from a disconnect.
- Add a controlled RF test: hold each mode for 30 seconds with the app closed
  before testing simultaneous phone-app access. No polling or reconnect changes.

# 0.1.1

- Report `CGS0251` (the app's logged-in-elsewhere notification) separately from
  `CGS0252` (its account-removed notification). Version 0.1.0 combined these into
  one ambiguous error, so an older log cannot establish which code arrived.
- Keep the exact recognized notification code in sanitized diagnostic output.
- Stop on either notification without automatically logging in again.
- Explain a short test to distinguish app-session replacement from other
  disconnects. No polling-frequency or transport changes.

# 0.1.0

- Initial status-only probe, command-line client and HAOS add-on.
- Directory lookup, login, heartbeat and status refresh from static APK analysis.
- No arm/disarm commands, MQTT entities or automatic reconnection.
