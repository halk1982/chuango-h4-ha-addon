# Static H4 protocol findings

Scope: supplied H4 Smarthome APK, package `cn.chuango.chuangoh4`, version 5.5.0,
versionCode 32, 36,835,470 bytes. APK SHA-256:
`cf953111b2f22abb4665dc18906757c28a92cf1076807948bb04e0880b303c7f`.
This hash identifies the inspected file; it is not an authenticity guarantee.
The ZIP CRC and DEX Adler-32 checks passed. The DEX header's SHA-1 did not match
its computed content hash. No comparison to a trusted app signing certificate
has been performed. The APK was inspected as data and was not installed/run.

Analysis used Python standard-library ZIP/DEX parsing and focused bytecode
inspection. REA's MCP analysis tools and JADX were unavailable. No new analysis
engines were installed. No vendor endpoints were visited and no credentials or
panel commands were sent. Sources below identify `classes.dex` code-item offsets
or encoded static fields, allowing the findings to be checked independently.

## Evidence and interpretation

All class names below are under `cn.chuango.h4` unless otherwise stated.

| Finding | Static evidence | Confidence / boundary |
| --- | --- | --- |
| Directory service is `www.4g-alarm.com:30010` | Encoded `util.GC.YUMING/YUMING_PORT`; `LoginActivity$2$2$1.run`, code `0x1f693c`, passes these into `TCPClient.getStartContent` with `CSend.huodeIP` | High for packaged code; reachability untested |
| Directory request is `CGC` + panel ID + CRLF | `net.CSend.huodeIP`, `0x20c3cc` | High for builder |
| Directory response has `CGS`, flag, two-digit hostname length, hostname, two-digit port-string length, port | `net.CAccept.getFenfuwuqi`, `0x20b70c`; zero port length selects 10001 | High for parser; server reply not captured |
| Alarm transport uses a Java TCP socket | `net.TCPUtil$1.run`, `0x20f768`; receive uses `BufferedReader.readLine` in `TCPUtil$2.run`, `0x20f954` | High for this path; camera libraries are separate |
| Login password is not transformed along the traced entry/builder/send path | `LoginActivity$2.onClick`, `0x1f6b14` → `ObjUser.setPwd`, `0x20157c` → `CSend.cs_4login`, `0x20be24` → `TCPUtil.sendData`, `0x20fe34` | High for traced path; no live packet capture |
| Client frame prefix is `CGC02`, command (2), marker `5555` (4); CRLF suffix | `CSend.qian`, `0x20c438`; encoded `GC.Biaoji`; corresponding send methods | High for builder; response marker echo assumption tested only synthetically |
| Handshake command 01 body is `11000`; success body is `1` | `CSend.cs_1woshou`, `0x20bbd0`; `CAccept.ca_1woshou`, `0x20b3a4` | High for static trace |
| Login command is 04; result flag at offset 11; account type follows success | `CSend.cs_4login`, `0x20be24`; `CAccept.ca_4Login`, `0x20b42c` | Optional empty push metadata acceptance is unknown |
| Relay command 10 wraps a four-digit payload length; reply adds success flag before length | `CSend.cs_10forwardData`, `0x20b8a4`; `CAccept.ca_10Zhuanfa`, `0x20afdc` | High for static trace |
| Manual status refresh uses device command 20 plus local timestamp and weekday | `fragment.BaojingFragment$3.onRefresh`, `0x202998` → `DSend.ds_20`, `0x20ea88`; `GF.getCurrDate`, `0x215a28` | High for app request; firmware-side effects of timestamp not established |
| Status reply contains mode, accessory count, fixed-width records | `DAccept.da_20`, `0x20d9c0` → `ObjAlarmState.setZhujiMode/setListAlarm` | High for app parser; no real panel record yet |
| Modes 0/1/2 correspond to away/disarmed/home | `BaojingFragment.choosewhich`, `0x203958`; `view.LinearThree.init`; `cn.chuango.chuangoh4.R$drawable` labels `icon_arm/icon_home/icon_disarm` | High for UI mapping; original H4 behavior unverified |
| Mode changes use device command 09 and mode digit | `BaojingFragment$2.onIndicate`, `0x20276c`; `DSend.ds_09`, `0x20e7a8` | Not implemented or transmitted by the probe |

The app also contains ARM/ARM64 native camera libraries including TUTK IOTC.
Their presence does not establish that the alarm path requires those libraries,
or that an offline/local alarm-control API exists. The H4 namespaces and app
filename do not establish compatibility with a particular original H4 firmware.

## Implemented wire interpretation

Lengths below are decimal ASCII character counts. The prototype restricts input
to printable ASCII, so character counts match byte counts. `LPn(value)` denotes
an n-digit zero-padded length followed by the value. Example fixtures in tests
are synthetic; they are not captured vendor traffic.

Login body:

```text
device_id + LP2(username) + LP2(password) + "1"
  + LP2(LP2("") + "01" + "101")
  + LP2(LP2(channel_id) + LP2(push_user_id) + LP2(language))
  + LP3(registration_id)
```

The probe uses empty push IDs and registration ID, with language `en`. The app
has empty-default paths for these fields, but server acceptance without push
registration is still unknown. Its `cs_4login` gets the ID from `ObjUser.id`
(which preferences load from `shebeiid`), replacing its string argument. The
probe explicitly supplies the configured device ID rather than reproducing an
uninitialized in-memory app record.

Status request payload: `20` + `yyyyMMddHHmmss` + ISO weekday (Monday 1–Sunday 7),
wrapped in client command 10. Response payload:

```text
"20" + mode(1) + count(2)
  + count * [type(2), number(2), state(1), alarm_flag(1), alarm_type(2), time(14)]
```

The probe preserves accessory codes; it does not equate alarm flags with live
siren activity or interpret sensor `state` as contact open/closed. Unknown mode
codes become `unknown`. Truncated/extended records fail visibly rather than
being accepted or used to infer disarmed state. The UI also has asynchronous
notification paths; the probe currently queries fresh status instead of
implementing those event formats.

## Validation still needed

1. On the user's own H4/account, confirm directory routing and successful login
   with empty optional metadata, then obtain a well-formed status reply.
2. Compare mode reports while the user changes state with the RF remote. Check
   whether login affects the existing app session.
3. Establish accessory/alarm meanings, notification behavior and reconnection
   before implementing MQTT state and command confirmation.
4. Investigate LAN support separately. Default IP constants for provisioning
   alone do not prove a usable local control protocol.
