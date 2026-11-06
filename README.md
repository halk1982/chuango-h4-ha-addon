# Chuango H4 Home Assistant bridge

Experimental integration for the **original Chuango H4**, using its existing
cloud service and a dedicated app/family account. User testing has confirmed
RF and phone-app changes between disarmed, home and away in two complete short
runs. This establishes mode reading on that installation, not every firmware or
long-term connection reliability.

Version **0.2.0** adds a continuous MQTT bridge. The existing short probe remains
available and is still the default after an update. The add-on keeps its original
slug, so existing users update their current installation.

## Update and start MQTT monitoring

1. In the Add-on/App Store, select **⋮ → Check for updates**, open your installed
   add-on and update to **0.2.2**. Its display name is now **Chuango H4 MQTT Bridge
   (experimental)**.
2. Keep your existing panel ID, dedicated account, password, timezone and
   `allow_plaintext` setting. Set `run_mode: mqtt`, `interval: 10` and
   `enable_controls: false`.
3. With the **Mosquitto add-on in HAOS**, leave `mqtt_host`, `mqtt_username` and
   `mqtt_password` empty. The bridge obtains the broker connection settings
   through the local Supervisor service API. Those credentials are never logged.
4. Save and start. In **Settings → Devices & services → MQTT**, find the
   **Chuango H4** device. It has a mode sensor, accessory-count sensor and
   command-result diagnostic. Home Assistant's MQTT integration must be enabled.
5. Compare the mode sensor with normal RF/app changes. MQTT mode runs
   continuously; `samples` and `include_accessories` apply only to probe mode.

A failed alarm query marks MQTT entities unavailable. Alarm state messages are
not retained. MQTT Last Will marks a crashed/disconnected bridge offline. The
bridge publishes availability only after receiving and publishing a new status.
Unknown mode codes remain unknown. Sensor expiration is an additional freshness
limit; it does not prove that the vendor itself has no caching.

Keep the watchdog off while testing. After a longer successful MQTT run, start
on boot can be enabled if desired. Authentication/session revocation stops the
bridge instead of starting a login loop. Transient network/offline errors use
bounded retries after 30, 60, 120… seconds; the budget resets after three stable
status reads. Default: three retry attempts. MQTT broker connections reconnect
independently without creating additional alarm logins.

## Experimental arm/disarm controls

After mode monitoring works, you can explicitly set `enable_controls: true`,
save and restart. This creates an MQTT alarm-control-panel entity supporting
**arm home, arm away and disarm**. Disabling controls removes its discovery
configuration while preserving the monitoring sensors.

Arm home, arm away and disarm have worked in user tests on one installation,
including through HomeKit. Intermittent status timeouts and response-marker
errors remain under investigation; long-term reliability is not established.
Commands and their acknowledgement format come from the APK and have
mock-server tests. A command is sent once, then the bridge reads actual panel
state. An acknowledgement alone
never sets the reported mode. The command-result diagnostic changes from pending
to confirmed, rejected or not_confirmed. Default confirmation deadline: 120
seconds, allowing for panel exit delays. Uncertain/failed commands are never
replayed after reconnect.

Stored retained commands, duplicate deliveries, unsupported commands and
commands received while offline, stale or busy are ignored. MQTT access should
remain restricted to your trusted Home Assistant setup. No siren, panic, account
or settings-write commands are provided. Triggered-alarm state and individual
sensor meanings have not yet been validated and are not inferred from raw codes.

Once the alarm entity is tested, it can be selected in your existing HomeKit
Bridge. A user-tested HA template can combine its mode/control with a separate
ESP siren detector. The add-on itself does not supply triggered-alarm state.

## Response markers (0.2.2)

Established sessions ignore responses with a different four-digit numeric
marker while continuing to wait for a matching reply within the original
deadline. These frames cannot update mode or acknowledge/reject a command.
Handshake/login remain strict, and commands are never replayed on reconnect.
Bounded warnings and command-phase logs provide safe metadata without packet
bodies. The exact format of the reported 0.2.1 marker error was not captured;
the new handling is mock-tested and still needs physical validation.

## Faster-update investigation

The first diagnostic change (0.2.1) adds disabled-by-default `event_diagnostics`.
It logs safe incoming identifiers between polls and during requests without
using idle frames as alarm state. A single socket buffer preserves partial and
coalesced packets. No extra queries or sessions are introduced.

See the [controlled RF/app test](h4_probe/DOCS.md#optional-receive-diagnostics-021).
An idle frame may be late, duplicated or previously buffered; it does not alone
prove server push. A subsequent implementation PR depends on that evidence.
Changes use feature branches and PR review, as recorded in [AGENTS.md](AGENTS.md).

## First installation

For a repository Home Assistant can fetch without signing in, add this URL in
**Settings → Add-ons/Apps → Store → ⋮ → Repositories**:

```text
https://github.com/halk1982/chuango-h4-ha-addon
```

Install **Chuango H4 MQTT Bridge (experimental)**. amd64 and aarch64 are declared;
only amd64 container builds have been verified here. A 32-bit armv7 host is not
supported. Private repositories can instead be copied to `/addons/h4_probe`
through your existing local Samba/SSH access. Do not put GitHub tokens in URLs.

The **Documentation** tab explains all options and the short probe test.

## Transport and scope

The inspected app's alarm login path uses **plaintext TCP**, including its
password. `allow_plaintext` remains required. This is separate from MQTT TLS,
which is configurable and verifies certificates. No app APK or vendor binary is
needed at runtime. The bridge does not claim a local/LAN alarm API.

Use a dedicated authorized app/family user for the same panel. Separate accounts
coexisted in the user's short test; other connection/session limits remain
possible. Keep credentials in your HAOS configuration, never chat or GitHub.
Logs exclude the panel ID, usernames, passwords and response bodies.

## Development

Use the existing isolated checkout; no extra Git worktree is needed.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r h4_probe/requirements.txt
PYTHONPATH=h4_probe .venv/bin/python -m unittest discover -s tests -v
docker build -t chuango-h4-bridge:dev h4_probe
```

The real-broker tests are opt-in: point `MQTT_TEST_PORT` at an isolated local
Mosquitto listener before running the suite. They verify discovery, fresh-state
availability, Last Will and no retained-command replay. Other tests use loopback
mock alarm servers; none contact the vendor or a physical panel.

For a short interactive probe with Python 3.12 and timezone data (no MQTT library
needed for probe mode):

```sh
PYTHONPATH=h4_probe python3 -m h4 --allow-plaintext --samples 12 --interval 10
```

For MQTT outside HAOS, use `--options` with a private JSON file containing
`run_mode: "mqtt"` and manual MQTT connection settings. See
[protocol evidence and limits](docs/protocol.md).
