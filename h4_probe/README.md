# Chuango H4 MQTT Bridge (experimental)

Mode monitoring for the **original Chuango H4** using MQTT Discovery, plus a
short probe mode and opt-in experimental arm-home, arm-away and disarm commands.

RF and separate-account phone-app status changes have been user-validated in
short runs. Physical commands, active-alarm state, individual sensor meanings,
HomeKit and long-term stability still need validation.

Existing users keep their settings and change `run_mode` from `probe` to `mqtt`
for continuous monitoring. With HAOS Mosquitto, broker settings are automatic.
Controls default to disabled. Read the **Documentation** tab before enabling.
