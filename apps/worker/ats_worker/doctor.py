"""Preflight for a worker checkout: `make doctor` (or `python -m ats_worker.doctor`).

Prints one ASCII status line per check and exits non-zero ONLY when a universal
prerequisite is missing (worker python deps + a set-up database). Every other row
— screen backend, ollama, codex CLI, claude CLI, screen api, node, docker,
daemon dep, worker daemon — prints ok/no but never fails the exit code:
which provider is "right" depends on the path the user picks, and `onboard-me`
Step 0 reads these lines to pick it.

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

from .screen_providers import DEFAULT_API_BASE_URL, PROVIDERS  # stdlib-only

Check = namedtuple("Check", "label ok detail core")

# Imports needed to run one fetch -> screen pass; a miss means `make setup` was
# skipped. `apscheduler` (cron daemon only) is deliberately excluded — it imports
# lazily, so requiring it here would
# false-fail a `--once` user on the default ollama screen.
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


def _daemon_dep_row(find_spec) -> Check:
    """`apscheduler` — needed ONLY by the daemon, which is why it is not in _WORKER_DEPS.

    Reported because the failure is otherwise invisible until it is expensive: `--once`
    never imports it, so a checkout set up from requirements-dev alone passes every other
    row, installs cleanly as a systemd unit, and then crash-loops into `failed` a couple
    of minutes later — after `systemd-analyze verify` has said nothing is wrong.
    """
    ok = _has(find_spec, "apscheduler")
    return Check("daemon dep", ok,
                 "apscheduler present" if ok
                 else "apscheduler MISSING — `--once` works, the daemon will crash-loop "
                      "(pip install -r requirements.txt)", core=False)


def _daemon_row(run_cmd) -> Check:
    """Is the worker supervised, i.e. running as the systemd user unit?

    Informational like the other provider rows: a hand-run `--once` workflow is a
    perfectly good way to use this, so an unsupervised checkout is not a failure. It is
    reported because a daemon that ISN'T running looks identical to one that is simply
    between wall-clock slots — the pipeline is silent either way.
    """
    code, out = run_cmd(["systemctl", "--user", "is-active", "ats-worker"])
    state = (out or "").strip() or "unknown"
    return Check("worker daemon (systemd unit)", code == 0,
                 "active (systemd --user)" if code == 0
                 else f"{state} — optional; a hand-run `python -m ats_worker.run` does "
                      "NOT show here. See deploy/ats-worker.service.example",
                 core=False)


def _backend_row(env) -> Check:
    """Which SCREEN_BACKEND is selected and what it needs; lists the registry so the
    operator (or onboard-me Step 0) sees every choice and which one is metered."""
    name = env.get("SCREEN_BACKEND") or "ollama"
    choices = ", ".join(f"{n} (metered)" if p.paid else n for n, p in PROVIDERS.items())
    provider = PROVIDERS.get(name)
    if provider is None:
        return Check("screen backend", False, f"{name!r} is not a backend; one of: {choices}",
                     core=False)
    return Check("screen backend", True,
                 f"{name} -> needs {provider.doctor_hint}. Choices: {choices}", core=False)


def _api_row(env) -> Check:
    model = env.get("SCREEN_MODEL")
    base = env.get("SCREEN_API_BASE_URL") or DEFAULT_API_BASE_URL
    key = "key set" if env.get("SCREEN_API_KEY") else "no key"
    return Check("screen api", bool(model),
                 f"{base}, model {model}, {key}" if model
                 else "SCREEN_MODEL unset (needed only for SCREEN_BACKEND=api)", core=False)


def run_checks(*, env, find_spec, which, http_get, connect, db_path, run_cmd) -> list[Check]:
    """Pure check core — all I/O is injected, so tests pass fakes and the real
    main() wires importlib / shutil / requests / sqlite3 / subprocess."""
    openrouter_ok = bool(env.get("OPENROUTER_API_KEY"))
    return [
        _dep_row(find_spec),
        _db_row(db_path, connect),
        _backend_row(env),
        _ollama_row(env.get("OLLAMA_HOST", _DEFAULT_OLLAMA), http_get),
        _which_row("codex CLI", "codex", which),
        _which_row("claude CLI", "claude", which),
        _api_row(env),
        Check("openrouter api key", openrouter_ok,
              "set" if openrouter_ok
              else "unset (needed only for the --jev keep/skip filter)", core=False),
        _which_row("node", "node", which),
        _which_row("docker", "docker", which),
        _daemon_dep_row(find_spec),
        _daemon_row(run_cmd),
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

    def run_cmd(argv):
        import subprocess  # lazy, and only reached on the daemon row
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=5)
            return p.returncode, p.stdout
        except (OSError, subprocess.SubprocessError):
            # No systemd, or no user manager. Not an error: the daemon is optional.
            return 1, "unavailable"

    checks = run_checks(env=env, find_spec=importlib.util.find_spec, which=shutil.which,
                        http_get=http_get, connect=sqlite3.connect, db_path=db_path,
                        run_cmd=run_cmd)
    print("doctor — worker preflight\n")
    print(format_report(checks))
    core_fail = [c for c in checks if c.core and not c.ok]
    print()
    if core_fail:
        print(f"FAIL: {len(core_fail)} core prerequisite(s) missing "
              f"({', '.join(c.label for c in core_fail)}). Provider rows are informational.")
        return 1
    print("core prerequisites present. Provider rows above are informational — "
          "onboard-me Step 0 reads them to pick your screen path.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
