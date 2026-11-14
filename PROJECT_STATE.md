# Project state

Updated: 2026-11-15 (Europe/Athens). Verified release baseline: main at
`e175738`, version **0.2.5**. Recheck the checkout and manifest before new work.

## Project and stack

`halk1982/chuango-h4-ha-addon` is an experimental Home Assistant add-on for the
original Chuango H4. It bridges the vendor's cloud TCP protocol to MQTT
Discovery. Stack: Python 3.12, pinned paho-mqtt 2.1.0, Docker, Home Assistant
and Mosquitto. Vendor transport is plaintext TCP with explicit opt-in; a local
LAN alarm API has not been established. A short status-only probe remains
available; continuous integration uses `run_mode: mqtt`.

## Completed and validation

- MQTT mode/status/accessory-count reporting and opt-in Home/Away/Disarm
  controls. Each command is sent once; only actual status can confirm its mode.
- 0.2.2: established sessions ignore other four-digit numeric markers within
  the original deadline. Their payloads cannot supply state or command results;
  handshake/login markers and malformed formats remain strict.
- 0.2.3: exact code-08 rejections of a status query (server command 10) use
  bounded reconnects. Sanitized diagnostics identify phase, command and code.
- 0.2.4: a status timeout while an acknowledged command awaits confirmation can
  spend one existing retry immediately, without resending the command. Further
  failures back off; the normal query timeout remains unchanged.
- 0.2.5: `recover_after_outage: true` by default. After the initial retry budget,
  network/panel-offline failures wait five minutes between further attempts.
  Three stable reads reset the budget. Zero retries disables recovery; opting
  out restores the old terminal limit. Authentication/session/account and
  unsupported protocol failures still stop. Code-08 status rejections never
  enter the ongoing outage loop.
- Local validation on 2026-11-08: **80 tests passed**, including three isolated
  Mosquitto tests; amd64 container build and smoke check passed. That application
  tree is now merged into main. No physical alarm was operated by the agent;
  aarch64 container execution was not verified here.
- User validated physical controls through HA/HomeKit and separate Telegram
  alerts. Last user-confirmed installation: 0.2.5, updated on 2026-11-08.
- User report on 2026-11-14: **six days of use without a failure**. No new logs
  accompanied that report; it does not establish which recovery paths ran.
- Subsequent offline review of a user-supplied export found frequent status-read
  timeouts, with every captured interruption recovering and no captured process
  restart/fatal exit. Exact status-query code-08 rejections also recovered. This
  supports that bounded recovery path on the installation; the five-minute
  ongoing-outage path was not exercised in that export. Process uptime and HA
  control availability must be assessed separately. Detailed logs stay private.

## File responsibilities

| File | Responsibility |
| --- | --- |
| `h4_probe/h4/protocol.py` | Request builders, frame/status parsing, mode mapping and rejection types |
| `h4_probe/h4/client.py` | Directory lookup, TCP session, queries, ACKs and safe diagnostics |
| `h4_probe/h4/bridge.py` | Worker, polling, command confirmation and cloud recovery |
| `h4_probe/h4/mqtt_bridge.py` | Discovery, availability, freshness and command gating |
| `h4_probe/h4/__main__.py` | CLI, options and terminal error reporting |
| `h4_probe/config.yaml` | Add-on version, options, defaults and schema |
| `h4_probe/Dockerfile`, `h4_probe/requirements.txt` | Runtime image and pinned dependency |
| `tests/` | Protocol, loopback, MQTT, marker, confirmation and outage regressions |
| `README.md`, `h4_probe/DOCS.md`, `h4_probe/CHANGELOG.md` | Usage, recovery policy and version history |
| `docs/protocol.md` | Static protocol evidence and its validation limits |

## Decisions and known limits

- Never assert an armed/disarmed state from an ACK. Never replay an uncertain
  command. Restore availability only from fresh status; remain unavailable
  during an outage. Command tracking is discarded across connection loss.
- Polling remains necessary. Reliable siren/detector push is not implemented;
  server command 53 and the vendor meaning of rejection 08 are not decoded.
  Accessory discovery does not establish live detector events.
- Do not casually increase polling intervals: control freshness currently caps
  at 30 seconds (`min(30, interval + 20)`). Last testing recommendation:
  10-second polling, start on boot enabled, watchdog disabled to avoid restarting
  intentional authentication/session stops.
- Keep independent local siren/RF detection. HomeKit uses an external HA alarm
  template combining cloud mode/control with a local siren sensor. Add-on mode
  logs do not show that template's Triggered state. An earlier intermittent
  HomeKit disarm issue was not fully isolated; subsequent user tests worked.
- Detector correlation, Home-mode PIR exclusions, Telegram messages and camera
  photos are separate private HA configuration, not add-on features. Those
  files are not in Git and must not be assumed available in another chat.
- A newly reported Generic Camera dashboard card is an unresolved possible
  source of shared-host load. A historical Core log had a heavy Generic Camera
  error loop, but its identity/causality must not be assumed for the current card.
  Camera app/recorder flaps do not themselves establish a camera-network outage.
- Outage recovery can wait up to five minutes plus connection/query time after
  connectivity returns. It does not repair the router/Internet/vendor service;
  observing a fault-free period does not prove every recovery branch works.

## Immediate next task

Investigate increased status-read warnings before changing add-on code. The user
reports removing the new camera card; no post-removal log has been reviewed yet.
Compare roughly one hour after removal with the retained baseline, keeping H4
polling at 10 seconds and other settings unchanged. Correlate fresh camera errors
and host resource measurements with recovery windows; obtain redacted camera
entity/card/source configuration if that lead remains relevant. The vendor/panel
path and host-specific stalls remain candidates; no root cause is established.
Defer the 20-second query-load experiment until the card comparison is assessed,
so variables do not change together. Continue gathering outage-recovery evidence.
Backlog: agree release/tagging and versioned rollback packaging before implementing it.

## Working rules

Follow `AGENTS.md`: use a feature branch and PR; do not push main or merge
without explicit authorization. Keep APKs, credentials, RF codes, private HA
configuration and user logs out of Git. Tests use the venv, loopback mocks and
an isolated broker selected by `MQTT_TEST_PORT`; never the user's alarm/broker.
Update this handoff with meaningful changes. Tool access varies by chat: recheck
capabilities instead of treating earlier GitHub API/workspace failures as
permanent repository limitations.
