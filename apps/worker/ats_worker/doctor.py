"""Preflight for a worker checkout: `make doctor` (or `python -m ats_worker.doctor`).

Prints one ASCII status line per check and exits non-zero ONLY when a universal
prerequisite is missing (worker python deps + a set-up database). Provider rows
(ollama / codex / claude / node / docker / anthropic key / telegram) print ok/no
but never fail the exit code: which provider is "right" depends on the path the
user picks, and `onboard-me` Step 0 reads these lines to pick it.

Imports only the standard library at load time so it runs even on a checkout whose
deps are missing — the exact state it exists to diagnose (importing `run`/`fetch`
would pull in `bs4`, which may be the missing dep).
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
from collections import namedtuple

Check = namedtuple("Check", "label ok detail core")

# Imports needed to run one pass on the DEFAULT (codex) path; a miss means
# `make setup` was skipped. `anthropic` (claude backend only) and `apscheduler`
# (cron daemon only) are deliberately excluded — both import lazily, so requiring
# them here would false-fail the default codex + `--once` user.
_WORKER_DEPS = ("requests", "bs4", "yaml", "pycountry", "geonamescache")
_DEFAULT_DB = "../web/prisma/applications.db"   # matches run.py --db default
_DEFAULT_OLLAMA = "http://localhost:11434"


def _env_file(path: str) -> dict:
    # ponytail: a deliberate 8-line copy of run.load_env — importing run here would
    # pull .fetch -> bs4, the very dep doctor must be able to run without.
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    out[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _has(find_spec, name: str) -> bool:
    try:
        return find_spec(name) is not None
    except Exception:  # noqa: BLE001 — a broken parent module must read as "missing"
        return False


def _dep_row(find_spec) -> Check:
    missing = [m for m in _WORKER_DEPS if not _has(find_spec, m)]
    return Check("worker python deps", not missing,
                 "all present" if not missing
                 else f"missing {', '.join(missing)} — run: make setup", core=True)


def _db_row(db_path: str, connect) -> Check:
    if not os.path.exists(db_path):
        return Check("database", False, f"{db_path} not found — run: make setup", core=True)
    try:
        conn = connect(db_path)
        conn.execute("SELECT 1 FROM job_postings LIMIT 1")
        conn.close()
        return Check("database", True, db_path, core=True)
    except Exception as exc:  # noqa: BLE001
        return Check("database", False, f"{db_path}: {exc} — run: make db-push", core=True)


def _which_row(label: str, cmd: str, which) -> Check:
    path = which(cmd)
    return Check(label, bool(path), path or f"{cmd} not on PATH", core=False)


def _ollama_row(host: str, http_get) -> Check:
    url = host.rstrip("/") + "/api/tags"
    try:
        status = getattr(http_get(url), "status_code", 0)
        return Check("ollama", status == 200,
                     host if status == 200 else f"{host}: HTTP {status}", core=False)
    except Exception as exc:  # noqa: BLE001
        return Check("ollama", False, f"{host}: {exc}", core=False)


def run_checks(*, env, find_spec, which, http_get, connect, db_path) -> list[Check]:
    """Pure check core — all I/O is injected, so tests pass fakes and the real
    main() wires importlib / shutil / requests / sqlite3."""
    telegram_ok = bool(env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"))
    anthropic_ok = bool(env.get("ANTHROPIC_API_KEY"))
    openai_ok = bool(env.get("OPENAI_API_KEY"))
    return [
        _dep_row(find_spec),
        _db_row(db_path, connect),
        _ollama_row(env.get("OLLAMA_HOST", _DEFAULT_OLLAMA), http_get),
        _which_row("codex CLI", "codex", which),
        _which_row("claude CLI", "claude", which),
        Check("anthropic api key", anthropic_ok,
              "set" if anthropic_ok
              else "unset (needed for SCORE_BACKEND=claude or SCREEN_BACKEND=claude-api)",
              core=False),
        Check("openai api key", openai_ok,
              "set" if openai_ok
              else "unset (needed only for SCREEN_BACKEND=openai-api)", core=False),
        _which_row("node", "node", which),
        _which_row("docker", "docker", which),
        Check("telegram", telegram_ok,
              "configured" if telegram_ok
              else "unset (optional — matches show in the Discovered Jobs tab)", core=False),
    ]


def format_report(checks) -> str:
    width = max(len(c.label) for c in checks)
    return "\n".join(f"  [{'ok' if c.ok else 'no'}] {c.label.ljust(width)}  {c.detail}"
                     for c in checks)


def main(argv=None) -> int:
    env = {**os.environ, **_env_file(".env")}
    db_path = env.get("DB_PATH", _DEFAULT_DB)

    def http_get(url):
        import requests  # lazy: requests itself may be the missing dep
        return requests.get(url, timeout=2)

    checks = run_checks(env=env, find_spec=importlib.util.find_spec, which=shutil.which,
                        http_get=http_get, connect=sqlite3.connect, db_path=db_path)
    print("doctor — worker preflight\n")
    print(format_report(checks))
    core_fail = [c for c in checks if c.core and not c.ok]
    print()
    if core_fail:
        print(f"FAIL: {len(core_fail)} core prerequisite(s) missing "
              f"({', '.join(c.label for c in core_fail)}). Provider rows are informational.")
        return 1
    print("core prerequisites present. Provider rows above are informational — "
          "onboard-me Step 0 reads them to pick your screen/score path.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
