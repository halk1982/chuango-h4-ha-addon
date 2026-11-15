# Project state

Updated: 2026-11-15 (Europe/Athens). Application baseline: **0.2.5**, code commit
`09ee422` (merged as `e175738`). Recheck the checkout and manifest before work;
documentation revisions can change independently of that application baseline.

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
- A later overnight export showed a much quieter armed-home period with one
  transient recovery, followed by a successful morning disarm and several later
  routine status timeouts. All captured interruptions recovered without a
  restart/fatal exit. This does not establish a mode-dependent cause: time of
  day, client activity and other conditions changed too.
- Local review counterexamples showed that a pre-query heartbeat can produce
  the same timeout counter, and that deliberately keeping a timed-out connection
  can accept a delayed earlier status as a later read. The latter models a
  proposed recovery change, not current bridge behavior; production closes the
  connection. No real alarm was involved and application behavior is unchanged.
- A subsequent authorized external read-only report correlated two ordinary
  status timeouts with the combined HA alarm becoming unavailable for about
  32 seconds, then returning to disarmed without an add-on restart. Raw MQTT
  historical transitions were not available. The report identifies installed
  version 0.2.5, but not its build revision or actual option values. No settings
  or physical alarm state were changed during that collection.

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
- `CGS0202` is heartbeat traffic in this client, not proof of acknowledgement
  of a particular status query. Per-phase counters can include earlier queued
  replies. Clean host probes or ARP broadcasts alone do not isolate the failing
  panel/cloud segment or establish a Wi-Fi disconnection.
- Status queries reuse marker `5555`. An extra query on a timed-out connection
  needs tests for delayed/out-of-order replies, freshness and command gating.
  The per-query deadline has already expired when its timeout is raised;
  a retry needs an explicit bounded budget. Do not deploy this behavior on the
  assumption that keeping TCP open guarantees availability or a current state.
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
- Follow-up Core logs confirmed a current Generic Camera snapshot HTTP-503 fault
  and stream retries after its dashboard card was removed. This is distinct
  from the historical image-proxy HTTP-500 incident. Neither the error counts
  nor the single low H4 resource sample establishes a causal H4/host-load link.
  Camera app/recorder flaps do not establish a camera-network outage.
- Downstream disarm-automation starts closely track availability recoveries.
  The external read-only check reports two private automations trigger on entry
  to disarmed without excluding unavailable-to-disarmed recovery; the daylight
  condition in one sequence occurs after its light-off action. This permits
  recovery-triggered effects, but event-specific traces were not supplied and
  execution/delivery is not confirmed. Propose a prior-state guard before side
  effects; preserve other conditions unless their intended behavior is agreed.
- Outage recovery can wait up to five minutes plus connection/query time after
  connectivity returns. It does not repair the router/Internet/vendor service;
  observing a fault-free period does not prove every recovery branch works.

## Immediate next task

The first read-only collection is complete within its access limits: host ping
probes and a later resource snapshot do not cover the failed H4 TCP flow or
panel Wi-Fi. No synchronized packet/AP/container evidence was obtainable. Do
not repeat requests for unavailable data or infer a cause from these probes.

Prepare private automation edits that accept disarm transitions only from
known armed/triggered states, before notification/light actions. Review the
full YAML and retain unrelated behavior; automation traces should identify
the prior/new states without exposing private targets or message bodies.

For the next diagnostic step, verify actual options in the HA add-on UI.
If receive diagnostics are off, propose enabling only `event_diagnostics` for
a bounded capture (two natural timeouts or at most 30 minutes), with a planned
add-on restart while disarmed, then restore the prior flag. Keep polling,
controls and recovery settings unchanged. This change has not been applied.
Idle draining changes where queued frames are consumed, so a quieter test
alone cannot establish a fix. Evaluate safe send-timing instrumentation if
existing receive metadata is insufficient; no same-session retry is implemented
or recommended for deployment. Return metadata only; keep captures, credentials
and private HA data outside Git. No second H4 login or forced alarm/network
outage is needed.

Watchdog policy is already documented. A separate 20-second load trial remains
an option within the freshness cap, not a proven fix. Leave the camera outside
the primary explanation. No root cause is established and no application
change is made by this review.
Backlog: agree release/tagging and versioned rollback packaging before implementing it.

## Working rules

Follow `AGENTS.md`: use a feature branch and PR; do not push main or merge
without explicit authorization. Keep APKs, credentials, RF codes, private HA
configuration and user logs out of Git. Tests use the venv, loopback mocks and
an isolated broker selected by `MQTT_TEST_PORT`; never the user's alarm/broker.
Update this handoff with meaningful changes. Tool access varies by chat: recheck
capabilities instead of treating earlier GitHub API/workspace failures as
permanent repository limitations.
