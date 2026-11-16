# Project state

Updated: 2026-11-16 (Europe/Athens). This branch implements **0.2.6** request-send
timing on latest checked main `dca9c4f` (0.2.5). The earlier documentation branch
`docs/observed-recovery-effects` / `14060ac` is merged as PR #9; do not duplicate
it. Last user-reported installation remains 0.2.5, exact image revision unknown.
Recheck the checkout and manifest before work; local validation is not deployment.

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
- 0.2.6: separate boolean `request_timing`, false by default, in MQTT/probe modes.
  Only status and heartbeat writes gain start and completion/failure records.
  Fields include validated command IDs, the unchanged marker, intended bytes,
  monotonic due/start/end, lateness and write duration; failures report a safe
  category and unknown partial progress. `sendall` completion establishes local
  stack acceptance only. Initial/post-command reads have no periodic due time.
  No idle draining is enabled by timing; receive-age semantics, scheduling,
  deadlines, recovery, confirmation and no-replay behavior are preserved.
- Local validation on 2026-11-16: **94 tests passed, none skipped**, in the
  Python 3.12 venv and in the rebuilt amd64 container, including all three
  isolated Mosquitto tests. Fourteen new tests cover flag defaults/independence,
  timing calculations (including logging overhead), privacy, unknown partial
  write progress, original receive-age/deadline semantics and loopback recovery
  after a completed write with no reply. Ordinary recovery retains its 30-second
  delay; post-ACK timeout recovery retains its immediate retry, with a closed
  old connection and no command replay. Container CLI help and 0.2.6 version
  smoke checks passed. Docker used the cloud session CA via a BuildKit secret
  in a temporary Dockerfile outside Git; TLS and dependency hashes stayed
  verified. No physical alarm, production broker or HAOS deployment was used;
  aarch64 execution and physical diagnostic capture remain unverified.
- Implementation commit `7b82803` is pushed on `feature/request-send-timing`.
  Git fetch/push work. PR listing and creation were rechecked, but the proxy
  rejects CONNECT to `api.github.com` with HTTP 403 before GitHub can respond;
  that host is absent from the current restricted allowlist. An existing CLI
  token variable is present; its API scope is untested, not proven missing.
  The environment draft now adds only `api.github.com`, preserving other
  settings/presets. Saving the draft does not apply network access. Review/save
  that addition in environment settings, then retry PR creation with the
  existing authentication. Until then, use the GitHub compare/new-PR page:
  https://github.com/halk1982/chuango-h4-ha-addon/compare/main...feature/request-send-timing
  No PR has been created, and no merge, release or physical operation occurred.
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
- User relays Hermes's later observations with receive diagnostics enabled:
  normal parsed statuses about every 10.6 seconds (server 10 / device 20), with
  parsed receive logging quiet before selected status timeouts. Ordinary first
  retries wait 30 seconds, then recovery takes roughly 1–2 seconds; selected HA
  unavailable periods lasted about 32 seconds. Missing parsed logs do not prove
  no packets arrived. The ~25-second gap can include the 10-second poll wait and
  15-second query timeout; a blocked status read can delay worker heartbeats.
  No underlying cause is established. New timing capture has not yet run.

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
- Private disarm-notification and red-lights-off automations: **guards verified**,
  per the user's relayed Hermes confirmation on 2026-11-16. The earlier
  unavailable-to-disarmed trigger issue is addressed; do not repeat this task
  without new evidence. Those private changes are outside this add-on and have
  not been inspected directly in this workspace.
- Outage recovery can wait up to five minutes plus connection/query time after
  connectivity returns. It does not repair the router/Internet/vendor service;
  observing a fault-free period does not prove every recovery branch works.

## Immediate next task

The first read-only collection is complete within its access limits: host ping
probes and a later resource snapshot do not cover the failed H4 TCP flow or
panel Wi-Fi. No synchronized packet/AP/container evidence was obtainable. Do
not repeat requests for unavailable data or infer a cause from these probes.

Review the 0.2.6 timing PR before any merge or deployment. After an authorized
update, follow `h4_probe/DOCS.md`'s first bounded capture: change only
`request_timing` to true, preserving actual `event_diagnostics`, polling,
controls, recovery and other settings. Plan the restart while disarmed; collect
two natural status timeouts or at most 30 minutes, then restore only the timing
flag to false and restart in a safe window. No capture has been performed here.
Ask the user to forward the focused read-only collection request to Hermes;
do not contact him directly. Collect safe TX/RX and retry/recovery metadata,
version, nonsecret option values, timezone and HA availability transitions.

Distinguish scheduling delay, time spent in the local write and completion
followed by no parsed response. Actual write start is sampled after the start
record, including its overhead in lateness but excluding it from write duration.
Monotonic times are not HA wall-clock timestamps. Neither successful writes
nor quiet receive logs establish delivery, packet absence or a network cause.
Idle draining still depends only on the pre-existing receive-diagnostics flag.
Do not implement same-connection status retries: the fixed marker can let a
late earlier reply satisfy a later query. Production closes timed-out sessions.
Keep captures, credentials and private HA data outside Git. No second H4 login,
forced outage or physical alarm operation is needed.

Watchdog policy is already documented. A separate 20-second load trial remains
an option within the freshness cap, not a proven fix. Leave the camera outside
the primary explanation. No root cause is established.
Backlog: agree release/tagging and versioned rollback packaging before implementing it.

## Working rules

Follow `AGENTS.md`: use a feature branch and PR; do not push main or merge
without explicit authorization. Keep APKs, credentials, RF codes, private HA
configuration and user logs out of Git. Tests use the venv, loopback mocks and
an isolated broker selected by `MQTT_TEST_PORT`; never the user's alarm/broker.
Update this handoff with meaningful changes. Tool access varies by chat: recheck
capabilities instead of treating earlier GitHub API/workspace failures as
permanent repository limitations.
