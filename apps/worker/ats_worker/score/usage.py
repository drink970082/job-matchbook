"""Codex quota telemetry: read the `rate_limits` record out of a codex session
rollout and persist a small usage snapshot for the web UI's quota bar.

WHY the rollout, not stdout: `codex exec --json` streams only thread/turn/item
events — it does NOT carry `rate_limits` (verified on 0.144.5). The quota
figures (codex's own /status accounting) live ONLY in the session rollout,
which `--ephemeral` suppresses. `make_codex_scorer` drops `--ephemeral` when
capturing, then `_capture_usage` reads the rollout and deletes it so a long
scoring pass doesn't litter ~/.codex/sessions.
"""
from __future__ import annotations

import json
import os


def _find_key(obj, key):
    """Depth-first search for the first value under `key` anywhere in a nested
    dict/list. Returns None if absent."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_key(v, key)
            if found is not None:
                return found
    return None


def _usage_snapshot(rate_limits: dict) -> dict:
    """Reduce a codex `rate_limits` record to the persisted snapshot shape:
    {plan_type, limits:[{key, used_percent, window_minutes, resets_at}, ...]}.
    Only non-null limits with a used_percent are kept."""
    out = {"plan_type": rate_limits.get("plan_type"), "limits": []}
    for key in ("primary", "secondary"):
        lim = rate_limits.get(key)
        if isinstance(lim, dict) and lim.get("used_percent") is not None:
            out["limits"].append({
                "key": key,
                "used_percent": lim.get("used_percent"),
                "window_minutes": lim.get("window_minutes"),
                "resets_at": lim.get("resets_at"),
            })
    return out


def _sessions_dir() -> str:
    return os.path.expanduser("~/.codex/sessions")


def _rollout_mtime_ceiling() -> float:
    """Newest codex rollout mtime right now (0.0 if none). Captured BEFORE a scoring
    call so the rollout that call writes can be identified as the one newer than this."""
    ceiling = 0.0
    for root, _d, files in os.walk(_sessions_dir()):
        for f in files:
            if f.startswith("rollout-") and f.endswith(".jsonl"):
                try:
                    t = os.path.getmtime(os.path.join(root, f))
                except OSError:
                    continue
                if t > ceiling:
                    ceiling = t
    return ceiling


def _rollouts_after(mtime: float):
    """All codex session rollouts with mtime > `mtime`, as `(mtime, path)` sorted
    oldest-first (newest last). Used by `_capture_usage` to detect a concurrent
    codex session: exactly one entry means this call's rollout is unambiguous;
    zero or several means another session is running and nothing should be deleted."""
    out = []
    for root, _d, files in os.walk(_sessions_dir()):
        for f in files:
            if f.startswith("rollout-") and f.endswith(".jsonl"):
                p = os.path.join(root, f)
                try:
                    t = os.path.getmtime(p)
                except OSError:
                    continue
                if t > mtime:
                    out.append((t, p))
    return sorted(out)


def _capture_usage(path: str, since_mtime: float) -> None:
    """Best-effort: read the `rate_limits` record from the codex session rollout THIS
    scoring call just wrote, atomically write a usage snapshot to `path`, then delete
    the rollout so a long pass doesn't litter ~/.codex/sessions. Never raises — quota
    telemetry must not break a score.

    Why the rollout, not stdout: `codex exec --json` streams only thread/turn/item
    events — it does NOT carry `rate_limits` (verified on 0.144.5). The quota figures
    (codex's own /status accounting) live ONLY in the session rollout, which
    `--ephemeral` suppresses. So the scorer drops `--ephemeral` when capturing, reads
    the rollout, then removes it (equivalent to ephemeral, but we extract usage first).

    Deletion is guarded, not merely mtime-picked: codex owns the rollout filename, so
    there is no schema-independent way to tag "ours" — instead, gather EVERY rollout
    newer than `since_mtime` and delete ONLY when there is exactly one. Zero or two-plus
    means a concurrent codex session (interactive or another scoring run) landed in the
    same window, and removing its rollout would nuke that session's history; ambiguous
    cases leave every rollout in place (still safe under the assumed-sequential
    `run_once` loop, just conservative when that assumption breaks). The snapshot is
    still read from the newest rollout regardless of the delete decision. The web reads
    `path` across the container boundary, so the write is atomic (tmp + os.replace)."""
    try:
        newer = _rollouts_after(since_mtime)
        if not newer:
            return
        roll = newer[-1][1]
        latest = None
        with open(roll, encoding="utf-8") as fh:
            for line in fh:
                if "rate_limits" in line:
                    latest = line
        # Delete ONLY when this is unambiguously the sole new rollout: a concurrent
        # codex session would also land here, and removing its rollout would nuke the
        # operator's session history. Ambiguous -> leave every rollout in place.
        if len(newer) == 1:
            try:
                os.remove(roll)  # cleanup — we've extracted what we need
            except OSError:
                pass
        if not latest:
            return
        rl = _find_key(json.loads(latest), "rate_limits")
        if not isinstance(rl, dict):
            return
        snapshot = _usage_snapshot(rl)
        if not snapshot["limits"]:
            return
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh)
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 — telemetry is best-effort; a score must not fail on it
        pass
