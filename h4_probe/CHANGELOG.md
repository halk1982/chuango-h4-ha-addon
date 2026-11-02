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
