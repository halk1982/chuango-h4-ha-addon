# Configure the first test

This is an experimental status-only probe. Initial user testing has confirmed
successful status reads; state transitions and concurrent sessions still need
validation. It does not create Home Assistant entities. It runs briefly,
logs the replies, then stops. It cannot send arm/disarm or settings commands.

## Enter your settings

Open the add-on's **Configuration** tab and fill in:

| Option | What to enter |
| --- | --- |
| `device_id` | Your panel's device ID, as used when adding it to the app; check its label/QR information. Use the device identifier, not the model name H4 or a Wi-Fi address. |
| `username` | Your existing H4 app username. |
| `password` | Your existing H4 app password. |
| `allow_plaintext` | Enable only after reading the transport limitation below. |
| `samples` | Keep `6` for the first run. |
| `interval` | Keep `10` seconds for the first run. |
| `timezone` | Your local IANA timezone, for example `Europe/Athens`. |
| `include_accessories` | Keep disabled for short status logs. Enable only when raw sensor records are needed for diagnosis. |

Enter credentials only here, on your own Home Assistant installation. Do not
send them through chat or commit them to GitHub. Click **Save**.

**Transport limitation:** the inspected app's alarm login path sends the app
password over plaintext TCP. This probe reproduces that transport and refuses
to connect until `allow_plaintext` is enabled. Support for TLS has not been
established. Login may affect your existing app session; concurrent-session
behavior and acceptance of empty optional push metadata are unverified.

## Run it

1. Open **Info**, click **Start**, then open **Logs**.
2. Look for a JSON line containing `"mode": "disarmed"`, `"armed_away"`,
   `"armed_home"`, or `"unknown"`. `mode_changed` is `null` for the first reply,
   then `true` when the returned mode code differs from the previous reply.
   It compares service replies; it does not independently verify the panel LED
   or prove that a response is fresh. `accessory_count` is always included.
3. For a controlled RF test, use `samples: 12` and `interval: 10`. Fully close
   the phone app, then use your RF remote to select disarmed, home and disarmed,
   holding each mode for at least 30 seconds. Check the panel LED and compare
   the log. Quicker changes may occur between polls and be missed. You do not
   need to trigger an alarm.
4. After the configured samples the add-on logs normal completion and stops.
   That is expected. Leave automatic start
   and watchdog disabled. Click **Start** again for another short test.

Accessory state/alarm fields are raw codes, not yet verified contact/siren
states. Errors do not produce an assumed armed or disarmed state.

## If something goes wrong

- **Invalid options:** check the three required fields, timezone and
  `allow_plaintext` setting, then save again.
- **Authentication failed:** verify the ID and app login details locally.
  The probe stops without automatic login retries. Server-specific optional
  metadata requirements remain a possibility.
- **Session ended / CGS0251:** the app handles this as an account logged in
  elsewhere. A competing phone-app login is a possible cause. This is a
  different notification from account removal; it is not a rate-limit message.
- **Account notification / CGS0252:** the app handles this as an account removed.
  Verify the account in the app. The probe does not delete or modify accounts.
- **Panel offline:** the service reported the panel offline.
- **Network failure:** version 0.1.2 identifies the failing step and whether it
  timed out, was closed/reset by the peer, or failed to connect/resolve. A status
  timeout means a fresh expected status reply did not arrive before the
  deadline. It does not establish spam blocking, an offline panel, or a session
  restriction. Listed reply codes contain no message bodies. Check that HAOS
  has outbound Internet access; no port forwarding is needed.
- **Protocol compatibility check failed:** keep the exact sanitized error text;
  your original H4 or its service may use a different response format.

Share whether the RF remote's changes appeared correctly, or share the error
text. The probe excludes your device ID, username and password from its logs,
but accessory records can reveal sensor information and event times. Redact
those records before sharing.

## Check whether the phone app replaces the probe's session

Version 0.1.0 logged one combined error for `CGS0251` and `CGS0252`. An older log
cannot tell us which of these arrived. Update to 0.1.1 for separate messages.

1. Close the H4 phone app fully. Start the probe with `samples: 12` and
   `interval: 10`, then use the RF remote for any normal mode changes during
   the roughly two-minute window.
2. If that run remains connected, start another run and open/log into the phone
   app partway through it. Note whether `CGS0251` then appears in the probe log.
3. If it does, this supports session replacement by the app. Stop the probe
   after the test; repeatedly restarting it could displace the phone session.

If the H4 app offers **Add family member / User management**, a separate
authorized user for the add-on is a possible long-term solution. Whether this
panel/service allows both accounts to stay connected still needs testing.
Successful login with that user alone does not establish simultaneous access.
If the RF-only test works, repeat once with the phone app opening partway
through. Record the phone behavior and the probe's last error. Avoid continuously
restarting either client to compete for a session.
The probe deliberately does not reconnect automatically in response to logout
notifications or attempt to defeat the service's session policy.
