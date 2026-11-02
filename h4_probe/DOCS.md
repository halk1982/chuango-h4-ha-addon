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
   `"armed_home"`, or `"unknown"`.
3. Compare the mode with the app. If convenient, use your RF remote to change
   mode during the roughly one-minute sample window and check the next reply.
   You do not need to trigger an alarm.
4. After six samples the add-on stops. That is expected. Leave automatic start
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
- **Panel offline / network error:** check that the normal app can reach your
  panel and that HAOS has outbound Internet access. No port forwarding is needed.
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
The probe deliberately does not reconnect automatically in response to logout
notifications or attempt to defeat the service's session policy.
