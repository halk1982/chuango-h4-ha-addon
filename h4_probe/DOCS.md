# Start continuous MQTT monitoring

1. Keep the dedicated H4 account that worked in the probe. Keep your panel ID,
   password, timezone and `allow_plaintext` setting.
2. Set `run_mode` to **mqtt**, `interval` to **10**, and leave
   `enable_controls` **disabled**.
3. For the Mosquitto add-on on this HAOS machine, leave all three MQTT connection
   text fields blank. Save and start the bridge.
4. Open **Settings → Devices & services → MQTT → Chuango H4**. The mode,
   accessory-count and command-result sensors appear through MQTT Discovery.
   Ensure the Home Assistant MQTT integration is enabled.

MQTT mode runs until stopped. `samples` only limits probe mode. You can compare
RF/phone-app changes with the mode sensor. Keep the watchdog disabled during
initial testing. Authentication/session revocation stops rather than repeatedly
competing with a phone login.

## Options

| Option | Meaning |
| --- | --- |
| `run_mode` | `probe` for a short log-only test; `mqtt` for continuous HA integration. Defaults to probe after upgrading. |
| `device_id` | The same panel ID that worked in the probe, not the model name or IP address. |
| `username`, `password` | Dedicated authorized H4 app/family account for this panel. Enter only locally. |
| `allow_plaintext` | Explicit acceptance of the app's unencrypted alarm TCP login. |
| `interval` | Seconds between status queries, default 10; replies add some latency. |
| `timezone` | Local IANA timezone, for example `Europe/Athens`. |
| `enable_controls` | Disabled by default. Enables the experimental alarm entity and arm/home/disarm commands. |
| `confirmation_timeout` | Seconds allowed for reading the requested state after a command, default 120. |
| `reconnect_attempts` | Bounded retries for alarm network/offline failures, default 3. No retries for login/session rejection. |
| `mqtt_host` | Empty for HAOS Mosquitto auto-discovery; set a hostname/IP for a different broker. |
| `mqtt_port` | Manual broker port, default 1883. Ignored during auto-discovery. |
| `mqtt_username`, `mqtt_password` | Manual broker credentials. Empty during HAOS auto-discovery. |
| `mqtt_tls` | Certificate-verified TLS for a manually configured broker. Use its TLS port. |
| `samples` | Probe only: number of replies before normal completion. |
| `include_accessories` | Probe only: include raw sensor records. Leave off for compact logs. |
| `event_diagnostics` | Off by default. Log safe identifiers while awaiting replies and between polls. Never changes MQTT state from idle frames. |

MQTT auto-discovery reads the fixed local Supervisor endpoint and does not log
its token, broker password or response. The alarm and MQTT passwords are separate.

## Experimental controls

Only after monitoring works, enable `enable_controls`, save and restart. An
additional **Chuango H4 Alarm** entity appears. Use that entity for a deliberate
first test of arm home, arm away or disarm. These functions use the legitimate
account already configured; the add-on has no siren/panic or account-writing API.

Arm home, arm away and disarm have worked in user tests on one installation,
including through HomeKit. Status timeouts and response-marker errors still
need investigation; this does not establish long-term reliability. Commands
are implemented from static APK traces and tested against mock responses. The
bridge sends once, requires an acknowledgement, then queries actual state. It never publishes the
requested mode as if it had already happened. The command-result sensor reports
pending, confirmed, rejected or not_confirmed. A disconnect may leave the action
outcome unconfirmed; check the panel/app. The bridge never replays that action.

Stored retained commands and duplicates are ignored. Offline/stale/busy commands
are rejected. Disabling controls removes the alarm entity's MQTT discovery
configuration. Keep your broker accessible only to your trusted clients.

After this entity is validated, select it in the existing HomeKit Bridge if you
want HomeKit access. Active-alarm/triggered state
and individual sensor meanings are not yet implemented; accessory count is
reported without guessing sensor semantics.

## Availability and reconnection

A failed status query marks entities unavailable. Normal state messages are not
retained. Last Will marks an unexpectedly disconnected bridge offline. New status
is required after reconnect before availability/controls are enabled. Mode sensor
expiration adds a fallback freshness limit. These checks do not independently
prove the vendor has no caching; compare with your panel during testing.

Transient cloud errors use increasing 30/60/120… second delays, limited by
`reconnect_attempts`. Three stable readings reset that budget. The bridge stops
on an unrecognized protocol response or explicit session/account/login rejection.
From 0.2.3, an exact negative envelope with code `08` on a read-only status query
(server command `10`) uses that same retry budget. Its first delay is 30 seconds;
after an earlier timeout has consumed a retry, it is 60 seconds. A successful
connection alone cannot restore availability; a fresh panel status is required.
No uncertain arm/disarm command is replayed, including when the status read
following its acknowledgement fails. Setting `reconnect_attempts: 0` disables
this recovery too. Exhausting the budget still stops the add-on.

This narrow retry policy does not establish the vendor meaning of code `08`.
Negative handshake, login and mode-command replies, other rejection codes and
malformed negative envelopes retain terminal handling. Exact negative envelopes
now report `phase`, `server_command` and `code`; terminal server rejections have
a separate error message rather than the generic protocol-compatibility label.
These metadata are logged without enabling `event_diagnostics`. Credentials,
server addresses and response bodies are excluded. Startup identifies the bridge
version. Older generic rejection logs cannot establish the phase or exact
envelope, so 0.2.3 is not a demonstrated fix for every previously observed `08`.
MQTT broker reconnection is independent and does not repeat cloud commands.

From 0.2.4, a transport timeout on a status read while an acknowledged command is
still awaiting confirmation spends one configured retry slot immediately. The
ordinary 30-second initial reconnect wait is skipped only for that case. The
query's timeout (currently 15 seconds) is unchanged; reconnection and a fresh
read still take time, so this does not promise instant HomeKit completion.
The warning says `after command acknowledgement` and shows the actual retry
delay, normally `retry 1/3 in 0 seconds` for the first such failure.

An immediate attempt uses the same budget, including any earlier failures.
Pending command tracking is discarded on reconnect; another timeout or failed
connection therefore backs off normally (60 seconds after a first immediate
attempt). Zero retries disables this path. Missing command ACKs, expired
confirmations, non-timeout errors and routine polling failures do not get this
shortcut. Authentication/session/account/protocol rejection handling is unchanged.

Availability is removed during recovery and restored only from new actual
status. The old command's result remains `unconfirmed` across connection loss;
the actual mode still updates normally after recovery. There is no automatic
command replay or optimistic armed/disarmed assertion. This reduces an avoidable
delay; it does not establish why the original status response was missing.

## Keep using the short probe

Set `run_mode: probe` for the previous diagnostic behavior. Use `samples: 12`
and `interval: 10`, close the phone app fully and hold RF-selected disarmed,
home, then disarmed for 30 seconds each. Compare the physical LED with the logs.
`mode_changed` compares received values, not the physical LED independently.
Normal sample completion is logged explicitly.

## Optional receive diagnostics (0.2.1)

This is the first investigation step toward faster updates. It observes message
identifiers while no request is active, as well as during normal replies.
It does **not** update MQTT mode or confirm a command from an idle frame.
Defaults and normal polling frequency remain unchanged when the option is off.

After updating to a merged 0.2.1 release, run a short controlled test:

1. Keep the working dedicated account and select `run_mode: mqtt`. Set
   `event_diagnostics: true`, `enable_controls: false` and `interval: 60`.
   The temporary longer interval gives a clear observation window; HA mode
   updates still wait for polls during this diagnostic release.
2. Close the phone app. Start the bridge and wait for its first normal status
   line. After about ten seconds, use the RF remote to select home, wait twenty
   seconds, then disarm and wait another twenty seconds. Note the RF change
   times and verify the physical LED. There is no need to trigger an alarm.
3. Repeat once while using the phone app on its existing separate account.
   Keep the test to a few minutes and share the compact log plus the change
   times, not credentials or raw packet captures.
4. Return `event_diagnostics` to `false` and `interval` to `10` afterwards.

Synthetic example:

```text
H4 RX phase=idle server_command=10 device_command=01 frame_bytes=80 since_status_request_s=12.345
```

The fields contain only the read phase, validated two-digit command identifiers,
line size excluding its terminator and elapsed time since this client last sent a status query. No
response bodies, mode values, sensor/account details or endpoints are added to
these diagnostic lines. Normal status log lines keep their existing behavior.
Output is limited to 500 receive records per connection.
`envelope=unsupported` records a safe prefix before the existing protocol-error
handling stops the client; it does not accept that message as a valid response.

`phase=idle` describes **when the frame was read**, not when the server sent it.
It can be a late/duplicate reply or bytes buffered after an earlier read, so it
does not alone prove a push update. Correlation with repeated RF/app changes is
needed before implementing event-driven state. Explicit logout/offline messages
are still respected; no extra queries or login sessions are created.

## Response-marker handling (0.2.2)

The client sends marker `5555` in its requests. An established session ignores
frames with a different four-digit numeric marker while awaiting status or a
command acknowledgement, or observing idle traffic. Their payloads cannot set
state, confirm/reject commands, or satisfy a request. Waiting still ends at the
original deadline; an uncertain action is never resent after a timeout or
reconnect. Handshake and login still require the matching marker. Nondecimal
markers and other unrecognized protocol formats still stop visibly.

Default warnings identify only the read phase, server command and frame size,
with five warnings per connection plus a suppression notice. Marker values and
packet bodies are not logged. Command logs separately identify sending,
acknowledgement and actual-state confirmation. An acknowledgement is not proof
of a physical change.

This behavior is covered by synthetic servers, including mismatched-only
streams, wrong-marker rejection/status payloads, logout notifications and
deadline enforcement. The observed 0.2.1 marker error did not include its marker
format, so physical validation of this change is still required.

## Errors

- **CGS0251 / Session ended:** the app handles this as an account logged in
  elsewhere. Keep distinct phone and add-on users. Do not enable repeated login
  restarts to compete for a session.
- **CGS0252 / Account notification:** the app handles this as an account removed.
  The bridge never deletes accounts. Verify it in the app.
- **Network failure:** the message identifies timeout, peer close/reset or other
  transport error, the failing step and safe reply codes. It does not prove spam
  blocking or explain the vendor's session policy.
- **Cannot obtain HAOS MQTT settings:** start Mosquitto, verify its service is
  configured and restart the bridge. Outside HAOS, use manual MQTT settings.
- **MQTT connection rejected:** verify the manual broker credentials/permissions,
  or the configured Mosquitto service for auto-discovery.

The legacy alarm login sends its password over plaintext TCP. `allow_plaintext`
remains necessary for this path. MQTT TLS does not encrypt that separate alarm
connection. Share only sanitized logs; probe accessory details can reveal sensor
information and event times.
