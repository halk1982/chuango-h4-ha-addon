# Project workflow

- Work on a feature branch and open a pull request for each change. Do not push
  directly to `main` or merge a PR without an explicit user request.
- Use the existing checkout. Cloud tasks are isolated; do not create a Git
  worktree unless the user asks for one.
- Keep APKs, credentials, private option files, user logs and packet bodies out
  of Git. Diagnostic output must contain only safe metadata.
- Run the relevant tests with the virtual environment. Real-broker tests use an
  isolated local Mosquitto instance selected by `MQTT_TEST_PORT`; never use the
  user's actual alarm or MQTT broker for automated tests.
- Distinguish static protocol evidence, mock tests and user-validated behavior.
  Changes to alarm mode must never be published as confirmed from a command
  acknowledgement alone.

## Project continuity

- Read `PROJECT_STATE.md` at the start of every task and verify its assumptions
  against the current checkout. Treat source/configuration as authoritative.
- Update it in the same PR when behavior, validation, user-reported deployment
  status, known limitations or the immediate next task changes.
- Distinguish implemented behavior, local tests, user-reported observations and
  unknowns. Keep the handoff concise and keep private installation data out.
