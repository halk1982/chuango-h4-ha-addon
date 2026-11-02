# Chuango H4 Status Probe (experimental)

Short, status-only compatibility test for the **original Chuango H4**.
It queries the alarm service and logs the returned panel mode and accessory
status codes. It cannot arm, disarm, trigger the siren, or change settings.

Live compatibility has not yet been established. The amd64 image and 16
protocol/mock-server tests have passed. MQTT and Home Assistant entities are
not implemented yet. See the **Documentation** tab to configure the first run.
