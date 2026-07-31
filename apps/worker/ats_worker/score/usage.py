"""Fit-backend quota telemetry: read the operator's remaining budget from the
provider's own usage endpoint and persist a small snapshot for the web UI's bar.

One HTTP GET per score pass, against whichever backend actually scored. Both
providers answer with the same three facts — a plan name, a percent used, and when
the window resets — so `_snapshot` folds them into one shape and the web bar renders
either without branching.

WHY not the codex session rollout (the pre-2026-07-29 approach): `codex exec --json`
streams only thread/turn/item events and never carries `rate_limits`, so the figures
were scraped out of the session rollout — which meant dropping `--ephemeral` on every
scoring call, leaving the full résumé+profile+JD prompt on disk until it was reaped,
and guessing which rollout was "ours" by mtime. `GET /backend-api/codex/usage` returns
the same accounting directly, so scoring calls are `--ephemeral` again and nothing is
written to disk to be cleaned up.

**Which budget this describes.** For codex it is the ChatGPT subscription that
`codex login` authenticated — the same budget the scorer spends. For claude it is the
**Claude Code subscription**, which is NOT what `make_claude_scorer` spends: that
backend bills `ANTHROPIC_API_KEY` (metered API), a separate budget with no
percent-of-quota endpoint. The snapshot therefore records `backend` and the web labels
the bar with it, so the two are never silently conflated.
"""
from __future__ import annotations

import http.client
import json
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime

_TIMEOUT = 10

CODEX_USAGE_URL = "https://chatgpt.com/backend-api/codex/usage"
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

# chatgpt.com sits behind Cloudflare, which 403s urllib's default
# `Python-urllib/3.x` — and 403s a browser-looking `Mozilla/5.0` too. Any honest
# client name passes, so send one rather than impersonating a browser. (Verified
# 2026-07-29: default -> 403, "ats-worker/1.0" -> 200.)
_USER_AGENT = "ats-worker/1.0"

# Claude names its windows; codex reports raw seconds. The `limits[]` rows carry a
# `group` ("session" / "weekly") that maps cleanly to a duration; the legacy flat
# buckets are keyed by name. An unmapped name yields None and the bar falls back to a
# generic label rather than inventing a duration.
_CLAUDE_GROUP_MINUTES = {"session": 300, "weekly": 10080}
_CLAUDE_BUCKET_MINUTES = {
    "five_hour": 300,
    "seven_day": 10080,
    "seven_day_sonnet": 10080,
    "seven_day_opus": 10080,
}


def _read_json(path: str):
    """Parse a JSON file, or None if it's missing/unreadable/malformed."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _get_json(url: str, headers: dict):
    """GET `url` and parse the JSON body, or None on the failures a provider actually
    produces — a timeout, a refused connection, a non-200, a malformed body. Quota
    telemetry is best-effort: none of those may colour a scoring pass.

    It is deliberately NOT a bare `except Exception`. The no-raise guarantee the pass
    depends on lives one level up in `capture_usage`, which wraps everything; keeping
    this catch narrow means a genuinely unanticipated failure still surfaces in a test
    run instead of being silently indistinguishable from a 403.

    It does SAY WHY, though, and that is the point of the shape. The 2026-07-30
    investigation had nothing but a `False` to go on, so an HTTP 403, an expired token, a
    DNS blip and a malformed body were indistinguishable; it was closed as "the passes
    had stopped fit-scoring, so the guarded call never ran", which was true of that
    window and NOT the whole story. On 2026-07-31 the 08:00 pass fit-scored 34 rows and
    still wrote no snapshot, while the same call from a shell 20 seconds later returned
    200 — real, intermittent, still undiagnosed. One line naming the cause is what closes
    it, and a diagnostic on the failure path costs nothing on the happy one.
    """
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                # NOT dead code: urlopen raises for 4xx/5xx, but a 201/202/204/206 is a
                # success to urllib and a failure to us, and lands here.
                print(f"[quota] {url} returned HTTP {resp.status}")
                return None
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # The status IS the diagnosis: 401/403 is auth or a WAF, 429 is throttling —
        # plausible immediately after a burst of paid calls on the same account, which
        # is exactly when this runs — and 5xx is theirs. `urlopen` RAISES for these
        # rather than returning them, so the `resp.status` check above never sees one.
        print(f"[quota] {url} returned HTTP {exc.code} ({exc.reason})")
        return None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        # http.client.HTTPException is in the tuple deliberately: IncompleteRead and
        # BadStatusLine subclass NEITHER OSError nor ValueError, and a truncated body
        # behind a CDN is exactly the intermittent shape being hunted here. Without it
        # they escape to `capture_usage`'s blanket catch and print nothing at all.
        print(f"[quota] {url} failed: {type(exc).__name__}: {exc}")
        return None


def _epoch(value):
    """Normalise a reset timestamp to epoch seconds. Codex sends an int; Claude sends
    an ISO-8601 string (sometimes Z-suffixed, which fromisoformat rejects before 3.11)."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def _snapshot(backend: str, plan_type, limits: list) -> dict:
    """The persisted shape the web reads: {backend, plan_type, limits:[...]}. `limits`
    entries are already normalised `{key, used_percent, window_minutes, resets_at}`.
    `as_of` is stamped at write time by `capture_usage`, not here — the fetchers stay
    pure so a test can compare their output verbatim."""
    return {"backend": backend, "plan_type": plan_type, "limits": limits}


# --- codex / ChatGPT ------------------------------------------------------


def _codex_auth() -> tuple[str, str] | None:
    """`(access_token, account_id)` from the codex login state, or None if not logged
    in. `CODEX_HOME` is codex's own override, honoured here so a non-default install
    still resolves."""
    home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    data = _read_json(os.path.join(home, "auth.json"))
    tokens = (data or {}).get("tokens")
    if not isinstance(tokens, dict):
        return None
    token, account = tokens.get("access_token"), tokens.get("account_id")
    if not token or not account:
        return None
    return str(token), str(account)


def fetch_codex_usage() -> dict | None:
    """Codex quota as a snapshot, or None if unavailable. Reads the SAME accounting
    `codex /status` shows: `rate_limit.primary_window` / `secondary_window`, each
    carrying `used_percent`, `limit_window_seconds` and `reset_at` (epoch)."""
    auth = _codex_auth()
    if not auth:
        home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
        print(f"[quota] codex: not logged in (no readable tokens in {home}/auth.json)")
        return None
    token, account = auth
    data = _get_json(CODEX_USAGE_URL, {
        "Authorization": f"Bearer {token}",
        "chatgpt-account-id": account,
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
    })
    if not isinstance(data, dict):
        if data is not None:            # _get_json already spoke for a None
            print(f"[quota] codex: 200 but body is {type(data).__name__}, not an object")
        return None
    rate = data.get("rate_limit")
    if not isinstance(rate, dict):
        print(f"[quota] codex: 200 but no rate_limit object: {str(data)[:160]}")
        return None
    limits = []
    for key in ("primary", "secondary"):
        window = rate.get(f"{key}_window")
        if not isinstance(window, dict) or window.get("used_percent") is None:
            continue
        secs = window.get("limit_window_seconds")
        limits.append({
            "key": key,
            "used_percent": window.get("used_percent"),
            "window_minutes": int(secs // 60) if isinstance(secs, (int, float)) else None,
            "resets_at": _epoch(window.get("reset_at")),
        })
    if not limits:
        # The suspect path with no status code to show for it: a 200 whose windows carry
        # a null used_percent. Print the payload or the next hunt starts from zero again.
        print(f"[quota] codex: 200 but no usable window: {str(rate)[:160]}")
        return None
    return _snapshot("codex", data.get("plan_type"), limits)


# --- claude / Claude Code -------------------------------------------------


def _claude_token() -> str | None:
    """The Claude Code OAuth access token, or None if not logged in. `CLAUDE_CONFIG_DIR`
    is Claude Code's own override."""
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    data = _read_json(os.path.join(home, ".credentials.json"))
    token = ((data or {}).get("claudeAiOauth") or {}).get("accessToken")
    return str(token) if token else None


def _claude_limits(data: dict) -> list:
    """Normalise either response shape. The response carries BOTH today, but the
    `limits[]` array is the richer one: each row has a `group` ("session"/"weekly")
    that maps to a duration, and a `weekly_scoped` row names the model it is scoped to
    (`scope.model.display_name`) — which is the difference between "72% of the weekly
    pool" and "2% of the Fable slice". Fall back to the flat named buckets
    (`five_hour`, `seven_day`, ... each `{utilization, resets_at}`) so an account on
    either side of that migration still renders."""
    rows = data.get("limits")
    if isinstance(rows, list):
        out = []
        for row in rows:
            if not isinstance(row, dict) or row.get("percent") is None:
                continue
            kind = str(row.get("kind") or "usage")
            model = (((row.get("scope") or {}).get("model") or {}).get("display_name"))
            out.append({
                "key": f"{kind} ({model})" if model else kind,
                "used_percent": row.get("percent"),
                "window_minutes": _CLAUDE_GROUP_MINUTES.get(str(row.get("group") or "")),
                "resets_at": _epoch(row.get("resets_at")),
            })
        if out:
            return out
    out = []
    for key, minutes in _CLAUDE_BUCKET_MINUTES.items():
        bucket = data.get(key)
        if not isinstance(bucket, dict) or bucket.get("utilization") is None:
            continue
        out.append({
            "key": key,
            "used_percent": bucket.get("utilization"),
            "window_minutes": minutes,
            "resets_at": _epoch(bucket.get("resets_at")),
        })
    return out


def fetch_claude_usage() -> dict | None:
    """Claude Code subscription quota as a snapshot, or None if unavailable.

    Read the module docstring before wiring this to a spend decision: this is the
    **subscription** budget, while `make_claude_scorer` bills `ANTHROPIC_API_KEY`."""
    token = _claude_token()
    if not token:
        print("[quota] claude: not logged in (no readable credentials)")
        return None
    data = _get_json(CLAUDE_USAGE_URL, {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
    })
    if not isinstance(data, dict):
        if data is not None:
            print(f"[quota] claude: 200 but body is {type(data).__name__}, not an object")
        return None
    limits = _claude_limits(data)
    if not limits:
        print(f"[quota] claude: 200 but no usable limit rows: {str(data)[:160]}")
        return None
    return _snapshot("claude", data.get("plan_type") or data.get("subscription_type"),
                     limits)


# --- persistence ----------------------------------------------------------

_FETCHERS = {"codex": fetch_codex_usage, "claude": fetch_claude_usage}


def capture_usage(path: str, backend: str) -> bool:
    """Best-effort: fetch `backend`'s quota and atomically write the snapshot to
    `path`. Returns whether a snapshot was written. Never raises — telemetry must not
    fail a scoring pass, and a stale snapshot beats an aborted run.

    A failed fetch leaves the PREVIOUS snapshot in place rather than truncating it: a
    transient 429 or an expired token should dim the bar's freshness (the web reads
    the file mtime as `as_of`), not blank it. That is exactly why the write stamps
    `as_of` INTO the snapshot as well: a stale reading and a fresh one are otherwise
    indistinguishable to anyone reading the file (a `cat`, a CLI, an agent), and a
    silently stale reading has already made one `--score-limit` decision come out ~17
    points optimistic. The caller announces a `False` return; see run.run_once.

    The web reads `path` across the container boundary, so the write is atomic
    (tmp + os.replace); the tmp filename is per-call-unique (pid + thread id) so two
    passes writing at once can never share one tmp file and clobber each other."""
    try:
        fetch = _FETCHERS.get(backend)
        if fetch is None:
            print(f"[quota] no usage fetcher for backend {backend!r}")
            return False
        snapshot = fetch()
        if not snapshot:
            return False                 # the fetcher already said why
        snapshot["as_of"] = datetime.now().astimezone().isoformat(timespec="seconds")
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh)
        os.replace(tmp, path)
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort; a pass must not fail on it
        # This catch is the reason `_get_json` may stay narrow, and it must therefore
        # SPEAK. Silence here is what made the 2026-07-30/31 hunt cost two days: the
        # write half (permissions, a full disk, a bad path) and any exception type the
        # fetchers do not anticipate both landed here and produced nothing at all.
        print(f"[quota] capture failed: {type(exc).__name__}: {exc}")
        return False
