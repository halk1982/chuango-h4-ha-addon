# 0.2.5

- Keep MQTT mode alive through prolonged network/panel-offline failures with
  `recover_after_outage: true` (default). After the initial retry budget, wait
  five minutes between further attempts rather than exiting permanently.
- Keep failed connections closed and MQTT unavailable until fresh actual state
  arrives. Cap the retry counter; restore the initial budget after three stable
  readings without repeating fast bursts during an ongoing/flapping outage.
- Keep zero retries and opt-out behavior terminal. Authentication/session/account
  failures, unsupported protocol and server rejections do not enter the ongoing
  outage loop; code-08 status rejections retain their initial retry limit.
- Preserve the post-ACK immediate retry, cancellation during cooldown and the
  rule that uncertain arm/disarm commands are never replayed.
- Validate long-outage recovery, cooldown timing, stability resets, shutdown,
  opt-out/zero settings and terminal-error handling with synthetic failures.
  Physical-network recovery and Supervisor watchdog behavior remain unverified.

# 0.2.4

- Reconnect without the ordinary initial 30-second wait when a status read
  times out while an acknowledged command is still awaiting confirmation.
  Spend one configured retry slot; further failures retain normal backoff.
- Distinguish transport timeouts from other network failures without parsing
  log strings. Leave routine polling, missing-ACK failures, expired confirmation
  windows, rejection handling and query timeouts unchanged.
- Require new actual status to restore availability and keep commands
  unconfirmed across connection loss. Never replay arm/disarm commands.
- Validate the ACK/timeout/reconnect/fresh-status path with a real loopback
  mock, plus retry-budget, backoff, expired-window and no-replay regressions.
  No real alarm or production MQTT broker is contacted by these tests.

# 0.2.3

- Record phase, validated server-command identifier and result code for exact
  negative response envelopes. Report terminal server rejection separately from
  unsupported protocol formats; include the bridge version at MQTT startup.
- Allow an exact code `08` rejection of a read-only status query (command `10`)
  to use the existing bounded network reconnect budget and backoff. Require fresh
  actual status before restoring availability; never replay a mode command.
- Keep handshake/login/mode-command rejections, other codes, malformed envelopes
  and explicit session/account notifications terminal. The vendor meaning of
  `08` and the phase of the previously reported failure remain unknown.
- Validate rejection phases, successful recovery, shared retry limits and no
  command replay with synthetic loopback servers and worker regression tests.
  Recovery from the user's particular physical-network incident is unverified.

# 0.2.2

- Keep an established session waiting for a matching reply when a frame uses
  another four-digit numeric marker. Such frames never supply status or command
  acknowledgements. The original response deadline remains in force; uncertain
  commands are not resent.
- Keep handshake/login markers strict. Nondecimal markers, malformed frames
  and session/account notifications retain their existing failure handling.
- Bound default mismatched-marker warnings to five per connection. Log only
  phase, command identifier and frame size; never marker values or packet bodies.
- Log command send, acknowledgement and state-confirmation phases separately,
  so a status-query timeout is distinguishable from a missing command ACK.
- Validate with synthetic loopback servers and an isolated MQTT broker. The
  exact marker in the reported physical-alarm incident was not captured; this
  change does not establish the format or meaning of that particular frame.

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
