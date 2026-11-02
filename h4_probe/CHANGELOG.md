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
