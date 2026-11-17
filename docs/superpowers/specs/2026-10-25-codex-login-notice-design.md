# Codex login notice

**Status:** approved

The operator requests a small notice in the existing Codex usage bar when the ATS
login needs renewal, showing `codex login --device-auth`, prefixed with
`CODEX_HOME="<home>"` only when the worker reports a non-default codex home
(`codex_home` in the snapshot, `$HOME`-relative). Which codex account the worker uses
is the operator's `CODEX_HOME`, set outside the repo (e.g. a systemd drop-in).

Use the existing worker-written shared usage snapshot. Missing credentials or HTTP
401 set `auth_required`; preserve prior Codex quota values. A successful capture
clears the flag. HTTP 403, throttling, malformed replies and network failures do not
establish login failure and retain the previous snapshot. Standalone Codex screening
captures telemetry at the end of each pass, including passes with no new work.
The notice is checked at pass completion and displayed on the UI's next poll.

No new dependency, credential mount into the web container, schema change or paid
model probe. This follows PRINCIPLES 2 (deterministic state), 6 (item isolation), and
12 (private data); credentials stay on the worker host. A timestamp-only expiration
check is rejected because Codex normally refreshes access tokens automatically.
