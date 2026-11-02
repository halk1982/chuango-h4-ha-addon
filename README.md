# Chuango H4 Home Assistant project

Experimental interoperability work for the **original Chuango H4**. The current
deliverable is a **status-only compatibility probe**, available as an HAOS
add-on or a Python command. Initial user testing has confirmed status reads;
mode transitions, alarm behavior and concurrent app sessions remain under test.

The add-on declares amd64 and aarch64 support; the container has been built and
tested on amd64 only. User feedback covers an initial HAOS status-read run.

It sends directory lookup, handshake, login, heartbeat and status-refresh
requests reconstructed from H4 Smarthome 5.5.0. It has no arm, disarm, siren,
account-management or settings-writing commands. No APK or vendor library is
needed at runtime. MQTT and HomeKit integration are not implemented yet.

## Install from GitHub on HAOS

No ZIP download, terminal or manual file copying is needed for a public
repository. The standard Add-on Store installer must be able to fetch the
repository without signing into GitHub; private repositories need a different
installation route.

1. Open Home Assistant, then **Settings → Add-ons → Add-on Store**.
2. Open the **⋮** menu at the top right and choose **Repositories**.
3. Paste this URL, click **Add**, and close the dialog:

   ```text
   https://github.com/halk1982/chuango-h4-ha-addon
   ```

4. Find **Chuango H4 Status Probe (experimental)** under **Chuango H4
   experiments**, open it and click **Install**. If it is not visible yet,
   use **⋮ → Check for updates** and refresh the page. The first installation
   builds the image on your HAOS machine and needs access to Docker Hub.
5. Open the add-on's **Documentation** tab for the configuration and first-test
   guide, or follow the instructions below.

On newer Home Assistant versions the same menus may be named **Apps** and
**App Store**.

## Configure and run the first test

1. Open the add-on's **Configuration** tab. Enter the device ID from your H4's
   label/QR information and the username/password used by its app. Enter them
   locally; do not send them through chat or commit them to Git. Keep six
   samples and a ten-second interval for the first run. Use your local timezone.
2. Read the transport limitation below. If acceptable, enable
   `allow_plaintext`, then click **Save**.
3. Return to **Info**, click **Start**, and open **Logs**. Leave automatic start
   and watchdog disabled; this is a short diagnostic run.
4. Check that the logged `mode` matches the app. During the sample window you
   can use your normal RF remote to change mode and check the next sample.
   There is no need to trigger an alarm. The probe stops after the configured
   samples, or immediately on authentication/protocol/network failure.

If the repository cannot be added, check its visibility and the error shown by
Home Assistant. If the add-on fails to install, share the build error. This
version declares amd64 and aarch64; a 32-bit armv7 host is not supported.

Expected output is JSON with `mode` (`disarmed`, `armed_away`, `armed_home`, or
`unknown`), `mode_code`, `mode_changed`, `accessory_count`, observation time and
sample number. `mode_changed` is `null` for the first sample and then compares
the returned code with the previous reply. Raw accessory records require
`include_accessories: true` (or `--include-accessories` on the command line).
These are service-reported values, not an independent check of the physical
panel. Hold RF-selected modes for 30 seconds to compare them with the logs.
The probe does not create HA entities. Accessory state/alarm fields retain their
raw codes until their live meanings are verified. A missing response produces
an error, never a guessed or cached disarmed state. Stop the add-on at any time.

**Transport limitation:** the inspected alarm login path uses plaintext TCP,
including the app password. This probe reproduces that path and refuses to
connect until `allow_plaintext` is explicitly enabled. TLS support has not been
established; the probe does not disable any TLS verification. Login may affect
the existing app session; concurrent-session behavior remains unverified. Empty
optional push metadata may also be rejected by the server. No automated login
retries or account modifications are performed.

If the test fails, share only the sanitized error text. If it works, share
whether changing mode with the RF remote was reflected correctly. Device IDs,
usernames and passwords are excluded from probe output. Accessory records can
still disclose sensor information and event times; redact them before sharing.

If opening the phone app ends the probe session, see the
[session test and notification guide](h4_probe/DOCS.md#check-whether-the-phone-app-replaces-the-probes-session).
Version 0.1.1 distinguishes the app's logged-in-elsewhere notification (`CGS0251`)
from its account-removed notification (`CGS0252`). Version 0.1.0 combined them,
so its existing error text cannot identify which one arrived. A logout is not
evidence of rate limiting. The probe stops rather than automatically competing
with the phone app for a session.

## Alternative local installation

If you intentionally keep the repository private, copy the complete `h4_probe`
directory to HAOS's `/addons` directory through your existing Samba or SSH
access. The result must include `/addons/h4_probe/config.yaml` and
`/addons/h4_probe/h4/`. Refresh the Add-on Store and install it under local
add-ons, then follow the same configuration instructions. Do not put GitHub
tokens into repository URLs.

## Run on a computer instead

Python 3.12 with IANA timezone data is sufficient; there are no Python package
dependencies. From the repository root:

```sh
PYTHONPATH=h4_probe python3 -m h4 --allow-plaintext --samples 6 --interval 10
```

The command prompts for the ID and username, and hides password entry. It never
accepts credentials in command-line arguments. Alternatively, pass `--options`
with a private JSON file matching the add-on option names. Keep that file
outside the checkout or named `options.json` (ignored by Git), with permissions
restricted to its owner. Default timezone: `Europe/Athens`.

## Development validation

Use the existing checkout; a cloud task is already isolated and needs no extra
Git worktree. From this directory:

```sh
PYTHONPATH=h4_probe python3 -m unittest discover -s tests -v
docker build -t chuango-h4-probe:dev h4_probe
```

Tests use synthetic protocol records and real loopback mock servers. They do
not contact Chuango, log into an account, or communicate with a panel. Passing
them validates the implementation against the static interpretation, not live
compatibility. See [protocol notes](docs/protocol.md) for evidence and limits.

## Following the compatibility check

The intended integration is an HAOS add-on publishing confirmed state using
MQTT Discovery. Confirm original-H4 status first, then validate command
acknowledgements and state confirmation before exposing arm/disarm controls.
Connection loss must mark entities unavailable. Alarm/sensor code meanings,
push events, reconnection and concurrent app sessions still need validation.
