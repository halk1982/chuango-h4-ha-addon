# Configure the first test

This is an experimental status-only probe. It has not been tested with your
physical H4 yet and does not create Home Assistant entities. It runs briefly,
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
- **Panel offline / network error:** check that the normal app can reach your
  panel and that HAOS has outbound Internet access. No port forwarding is needed.
- **Protocol compatibility check failed:** keep the exact sanitized error text;
  your original H4 or its service may use a different response format.

Share whether the RF remote's changes appeared correctly, or share the error
text. The probe excludes your device ID, username and password from its logs,
but accessory records can reveal sensor information and event times. Redact
those records before sharing.
