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

MQTT auto-discovery reads the fixed local Supervisor endpoint and does not log
its token, broker password or response. The alarm and MQTT passwords are separate.

## Experimental controls

Only after monitoring works, enable `enable_controls`, save and restart. An
additional **Chuango H4 Alarm** entity appears. Use that entity for a deliberate
first test of arm home, arm away or disarm. These functions use the legitimate
account already configured; the add-on has no siren/panic or account-writing API.

**Physical commands have not yet been user-validated.** They are implemented
from static APK traces and tested against mock responses. The bridge sends once,
requires an acknowledgement, then queries actual state. It never publishes the
requested mode as if it had already happened. The command-result sensor reports
pending, confirmed, rejected or not_confirmed. A disconnect may leave the action
outcome unconfirmed; check the panel/app. The bridge never replays that action.

Stored retained commands and duplicates are ignored. Offline/stale/busy commands
are rejected. Disabling controls removes the alarm entity's MQTT discovery
configuration. Keep your broker accessible only to your trusted clients.

After this entity is validated, select it in the existing HomeKit Bridge if you
want HomeKit access. That path still needs testing. Active-alarm/triggered state
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
MQTT broker reconnection is independent and does not repeat cloud commands.

## Keep using the short probe

Set `run_mode: probe` for the previous diagnostic behavior. Use `samples: 12`
and `interval: 10`, close the phone app fully and hold RF-selected disarmed,
home, then disarmed for 30 seconds each. Compare the physical LED with the logs.
`mode_changed` compares received values, not the physical LED independently.
Normal sample completion is logged explicitly.

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
