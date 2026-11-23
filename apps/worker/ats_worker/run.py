"""Entrypoint: wire real adapters and run the pipeline once or on a schedule.

WHY the env/adapter wiring lives only here: every other module is pure and
injected, so this is the single place that knows about secrets and external
services. `run_once` takes already-loaded config/secrets and the worker
callables it builds from them, calling the pipeline stages in order (fetch,
feed, expire, screen).

APScheduler is imported lazily inside the cron path so the test environment —
which lacks apscheduler — can still import and exercise this module.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import requests

from . import config as config_mod
from . import db, jev, pipeline, profile
from .fetch import fetch_company, fetch_one_company, smartrecruiters
from .feed import embedded_gh, simplify
from .screen_providers import PROVIDERS, RETIRED
from .screening import screen_posting
from .screening.errors import provider_failure_category

# qwen3.5:4b runs fully on an 8GB GPU (~3GB resident) and returns clean JSON in
# ~2s/posting with thinking disabled. The 9b (6.6GB) spills to
# CPU on an 8GB card (~100s/call), so it's a poor fit here. Override per-deploy
# with --model or the OLLAMA_MODEL env var.
DEFAULT_OLLAMA_MODEL = PROVIDERS["ollama"].default_model

# The ONLY .env keys argparse defaults read from os.environ (see run.main below).
# Secrets (SCREEN_API_KEY, OPENROUTER_API_KEY) are deliberately excluded: every consumer
# reads them from the in-process `env` dict (run_once(..., env=env) / make_screener),
# never os.environ, so promoting them would only leak them to subprocesses that inherit
# the full environment (the codex CLI).
_ENV_ARGPARSE_KEYS = frozenset({
    "DB_PATH", "OLLAMA_MODEL", "SCREEN_BACKEND", "SCREEN_MODEL",
    "SCREEN_WORKERS", "SCREEN_EFFORT", "SCREEN_LIMIT", "JEV_BACKEND",
})


def capture_usage(*args, **kwargs):
    from .usage import capture_usage as capture
    return capture(*args, **kwargs)


# The screen's default stays the free local backend; see screen_providers for the rule
# that auto-detection never selects a paid one.
DEFAULT_SCREEN_BACKEND = "ollama"
# The subscription quota snapshot, next to the shared DB; the web's /api/quota reads it.
QUOTA_FILE = "quota.json"
SCREEN_EFFORT_VALUES = ("none", "low", "medium", "high", "xhigh", "max")
SCREEN_BACKENDS = tuple(PROVIDERS)
# `extract` runs the JEV packs through the screen's own provider (UNVALIDATED).
JEV_BACKENDS = ("openrouter-native", "extract")


def screen_model_for(backend: str, *, screen_model=None, ollama_model=None):
    """The model a pass actually uses (and records as provenance). Ollama takes
    --model/OLLAMA_MODEL only, so a SCREEN_MODEL left over from a hosted backend never
    reaches it; every other backend takes --screen-model, else its default (None lets
    the claude CLI pick)."""
    if backend == "ollama":
        return ollama_model or PROVIDERS["ollama"].default_model
    return screen_model or PROVIDERS[backend].default_model


def make_screener(backend: str, *, env, http=None, model=None, screen_model=None,
                  screen_effort=None, num_ctx: int = 8192):
    """The `extract(prompt, schema) -> dict` callable for `backend`, or None for
    `none` (deterministic gates only, LOW RECALL on sponsorship). `model` is the Ollama
    tag (--model); `screen_model` the --screen-model override."""
    provider = PROVIDERS.get(backend)
    if provider is None:
        raise ValueError(
            f"unknown screen backend: {backend!r} (want one of {', '.join(SCREEN_BACKENDS)})")
    resolved = screen_model_for(backend, screen_model=screen_model, ollama_model=model)
    if provider.model_required and not resolved:
        raise ValueError(f"SCREEN_BACKEND={backend} needs SCREEN_MODEL (or --screen-model)")
    return provider.build(env, http, resolved,
                          screen_effort if provider.effort else None, num_ctx)

# The feed fetches concurrently (pipeline.run_feed uses a thread pool). requests'
# Session isn't safe to share across threads, so hand each worker thread its own
# (keep-alive within a thread); a shorter timeout caps the wait on a slow host.
_FEED_TIMEOUT = 10
_feed_local = threading.local()


def _feed_session() -> requests.Session:
    s = getattr(_feed_local, "session", None)
    if s is None:
        s = _feed_local.session = requests.Session()
    return s


def load_env(path: str) -> dict:
    """Parse a minimal KEY=VALUE .env file (ignores blanks and # comments)."""
    out: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        # Missing file, or a directory (docker creates an empty dir at the mount
        # target when the bind source doesn't exist) — tolerate both.
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        out[key.strip()] = value
    return out


def _now() -> str:
    """ISO-8601 UTC timestamp with millisecond precision (matches Prisma)."""
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def run_once(cfg, *, db_path, env,
             ollama_model=DEFAULT_OLLAMA_MODEL,
             screen_backend=DEFAULT_SCREEN_BACKEND,
             screen_model=None,
             screen_effort=None,
             screen_limit: int | None = 40,
             fetch_only: bool = False, screen_workers: int = 0,
             refresh_unscored: bool = False,
             refresh_source: str | None = None, refresh_limit: int = 25,
             jev_enabled: bool = False, jev_limit: int = 300,
             jev_max_usd: Decimal = Decimal("0.10"),
             jev_backend: str = "openrouter-native") -> None:
    """Run fetch -> feed -> expire -> screen -> triage exactly once (`fetch_only` stops
    before the screen). The screen never sees the résumé or profile; `jev_backend="extract"`
    sends the JEV profile and experience context to the screen provider.

    Each posting is evaluated once (#225): the stages take only pending postings inside
    the shared window (pipeline.EVALUATION_WINDOW_DAYS), each result records the profile
    version, and a pending posting outside the window is aged out to `not_evaluated`.
    A profile edit therefore re-queues nothing."""
    if jev_enabled and jev_backend not in JEV_BACKENDS:
        raise ValueError(f"unknown jev backend: {jev_backend!r}")
    if jev_enabled and jev_backend == "extract" and screen_backend == "none":
        raise ValueError("jev backend extract needs a screen backend other than none")
    if fetch_only and refresh_unscored:
        raise ValueError("fetch-only and refresh-unscored are mutually exclusive")
    if not fetch_only and screen_limit is not None and screen_limit <= 0:
        raise ValueError("the screen pass requires a positive --screen-limit")
    if refresh_unscored:
        if fetch_only:
            raise ValueError("unscored refresh is a standalone worker mode")
        if refresh_source != "smartrecruiters":
            raise ValueError("unscored refresh requires --refresh-source smartrecruiters")
        if not 1 <= refresh_limit <= pipeline.UNSCORED_REFRESH_MAX:
            raise ValueError("unscored refresh limit must be between 1 and 25")
    elif refresh_source is not None:
        raise ValueError("--refresh-source requires --refresh-unscored")
    conn = db.connect(db_path)
    try:
        now = _now()
        if refresh_unscored:
            pipeline.run_unscored_refresh(
                conn, source=refresh_source, limit=refresh_limit, now=now,
                observation_fn=lambda source, slug, external_id, company_name:
                    smartrecruiters.fetch_one_observation(
                        slug, external_id, company_name,
                        session=_feed_session(), timeout=_FEED_TIMEOUT),
            )
            return
        # The pass record (#247). run_once runs under pass_lock, so start_pass may mark
        # any row still `running` abandoned. A raise below leaves this row `running`.
        provider = PROVIDERS[screen_backend]
        effective_model = screen_model_for(screen_backend, screen_model=screen_model,
                                           ollama_model=ollama_model)
        effective_effort = (screen_effort or "medium") if provider.effort else None
        screen_cfg = None if fetch_only else {
            "backend": screen_backend, "model": effective_model, "effort": effective_effort,
            "limit": screen_limit, "workers": screen_workers or 1}
        triage_cfg = None if not jev_enabled else {
            "backend": jev_backend, "limit": jev_limit,
            "max_usd": None if jev_backend == "extract" else str(jev_max_usd)}
        # The candidate profile, read once up front (before the pass record, which
        # records its scope): its search scope filters fetch, its hard requirements drive
        # the deterministic pre-screen gate and the screen, and triage reads it below. No
        # row or no requirement => no gate, no SCREEN call. A malformed row raises here.
        if db.needs_evaluate_once_migration(conn):
            raise RuntimeError(_LEGACY_DISCARDS)
        prof = _profile_for_pass(conn, cfg, now=now)
        candidate = prof.screen_candidate() if prof else None
        scope = prof or profile.CandidateProfile()
        version = prof.version if prof else None
        run_id = db.start_pass(conn, now=now, fetch_only=fetch_only, jev_enabled=jev_enabled,
                               config=_pass_config(cfg, scope, screen=screen_cfg,
                                                   triage=triage_cfg))
        counts: dict = {}

        def record(stage: str, tally) -> None:
            counts[stage] = tally
            db.update_pass_counts(conn, run_id, counts)

        # The watchlist is DB-owned. Seed it once from config.yaml `companies:`
        # when the table is empty; thereafter the DB (web-managed) is authoritative.
        if db.count_watchlist(conn) == 0 and cfg.companies:
            seeded = db.import_watchlist(conn, _companies_as_dicts(cfg), now=now)
            print(f"seeded watchlist from config: {seeded} companies")
        companies = db.get_watchlist(conn)

        # `browser`-source rows drive a headless Chromium (optional Playwright extra);
        # keep them off the default cycle unless explicitly enabled, so a normal run
        # stays pure `requests` and never imports Playwright.
        if not cfg.enable_browser_sources:
            skipped = [c for c in companies if c["source"] == "browser"]
            if skipped:
                names = ", ".join(f"{c['source']}/{c['slug']}" for c in skipped)
                print(f"skipping {len(skipped)} browser-source row(s) "
                      f"(enable_browser_sources is off): {names}")
            companies = [c for c in companies if c["source"] != "browser"]

        fetch_counts: dict = {}
        pipeline.run_fetch(conn, companies, list(scope.title_include), now=now,
                           fetch_fn=fetch_company, title_exclude=list(scope.title_exclude),
                           max_age_days=scope.max_age_days, candidate=candidate,
                           profile_version=version, counts=fetch_counts)
        record("fetch", fetch_counts)

        # Discovery feeds: broad listing streams resolved back to boards. Runs
        # before the screen so feed-discovered 'new' rows are screened this same pass.
        feed_counts: dict = {}
        for feed in cfg.feeds:
            if not feed.enabled:
                continue
            if feed.name == "simplify":
                pipeline.run_feed(
                    conn, now=now, counts=feed_counts.setdefault(feed.name, {}),
                    feed_fn=lambda f=feed: simplify.fetch(url=f.url or simplify.DEFAULT_URL),
                    keep_categories=feed.categories, feed_name=feed.name,
                    # Bind a per-thread Session + shorter timeout into the network fns
                    # so the concurrent fetches reuse connections and don't stall long.
                    fetch_fn=lambda s, sl, n: fetch_company(
                        s, sl, n, session=_feed_session(), timeout=_FEED_TIMEOUT),
                    detail_fetch_fn=lambda s, sl, e, n: fetch_one_company(
                        s, sl, e, n, session=_feed_session(), timeout=_FEED_TIMEOUT),
                    resolve_embedded_fn=lambda url: embedded_gh.resolve_embedded(
                        url, session=_feed_session(), timeout=_FEED_TIMEOUT),
                    # The same three coarse filters run_fetch gets above. The feed
                    # is the firehose (~18k listings), so this is where they save
                    # the most: without them the majority of what the feed's own
                    # gate passes is material this profile already refuses.
                    title_filter=list(scope.title_include),
                    title_exclude=list(scope.title_exclude),
                    max_age_days=scope.max_age_days,
                    candidate=candidate, profile_version=version,
                )
        record("feed", feed_counts)

        # Re-check a capped batch of live postings and expire the dead ones, so a
        # closed req stops sitting in the queue as a dead link.
        expire_counts: dict = {}
        gone = pipeline.run_expire(
            conn, now=now, counts=expire_counts,
            detail_fetch_fn=lambda s, sl, e, n: fetch_one_company(
                s, sl, e, n, session=_feed_session(), timeout=_FEED_TIMEOUT))
        record("expire", expire_counts)
        if gone:
            print(f"expired {gone} dead posting(s)")

        # A pending posting that left the window is final: nothing evaluates it any more.
        aged = db.age_out(conn, since=pipeline.window_start(now), now=now)
        record("verdict", {"aged_out": aged})
        if aged:
            print(f"[verdict] {aged} posting(s) left the {pipeline.EVALUATION_WINDOW_DAYS}-day "
                  "window unevaluated: not_evaluated")

        # Operator quota control: --fetch-only stops here so a board refresh (and its
        # log) costs zero screen calls. The 'new' rows wait for a later screen pass —
        # fetch is idempotent (upsert DO NOTHING).
        if fetch_only:
            print(f"fetch-only: {len(db.get_by_status(conn, 'new'))} row(s) left "
                  f"'new', skipping screen")
            db.finish_pass(conn, run_id, now=_now(), counts=counts)
            return

        num_ctx = int(env.get("OLLAMA_NUM_CTX", "8192"))
        screen_extract = make_screener(
            screen_backend, env=env, http=requests, model=ollama_model,
            screen_model=effective_model, screen_effort=effective_effort,
            num_ctx=num_ctx)

        def screen_only_fn(posting):
            return screen_posting(posting, extract=screen_extract,
                                   candidate=candidate, num_ctx=num_ctx)

        # Triage is configured when the pass runs it and the profile gives it something to
        # judge (a target role or custom context); otherwise passing the requirements is
        # the posting's final `keep`. Invalid custom packs still count as configured, so
        # those postings wait (pending) for the repair instead of being kept unjudged.
        triage = jev_enabled and prof is not None and prof.triage_texts() is not None
        record("screen", pipeline.run_screen(
            conn, now=now, screen_fn=screen_only_fn, extract=screen_extract,
            candidate=candidate, backend=screen_backend, model=effective_model,
            effort=effective_effort, limit=screen_limit,
            screen_workers=screen_workers or 1, clock=_now,
            profile_version=version, triage=triage))
        # Refresh the quota bar (and its re-login notice) for the subscription the
        # screen just spent; one free GET, best-effort by contract.
        if provider.quota:
            capture_usage(os.path.join(
                os.path.dirname(os.path.realpath(db_path)), QUOTA_FILE), screen_backend)
        if triage:
            if jev_backend == "extract":
                triaged = _run_jev_extract(
                    conn, prof, extract=screen_extract, limit=jev_limit, now=now,
                    max_description_chars=num_ctx * 2,
                    model=f"extract:{jev.EXTRACT_PROMPT_VERSION}:{screen_backend}:"
                          f"{effective_model}:{effective_effort}:jd{num_ctx * 2}")
            else:
                triaged = _run_jev(conn, prof, env=env, limit=jev_limit, max_usd=jev_max_usd,
                                  now=now)
            record("triage", triaged)
        elif jev_enabled:
            _triage_inputs(prof)  # logs why triage has nothing to judge
            print("[triage] passing the requirements is the final keep this pass")
            record("triage", {"skipped": _triage_skip_reason(prof)})
        db.finish_pass(conn, run_id, now=_now(), counts=counts)
    finally:
        conn.close()


_LEGACY_DISCARDS = (
    "this DB awaits the one-time evaluate-once migration (legacy discards or unsettled "
    "screen/triage verdicts): with the worker stopped, run `python3 -m ats_worker.migrate_evaluate_once migrate --db <db>`")


def _run_jev(conn, prof, *, env, limit: int, max_usd: Decimal, now: str) -> dict:
    """Wire the real OpenRouter transport into pipeline.run_jev. A missing key or an
    unreachable model endpoint skips the stage loudly; fetch and screen already ran.
    Returns the stage tally for the pass record, or {"skipped": <closed reason>}."""
    key = (env.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        print("[jev] OPENROUTER_API_KEY is not set; skipping the JEV filter this pass")
        return {"skipped": "no_api_key"}
    inputs = _triage_inputs(prof)
    if inputs is None:
        return {"skipped": _triage_skip_reason(prof)}
    client = jev.OpenRouterClient(requests.Session(), key)
    try:
        resolved = client.resolve_model()
    except Exception as exc:  # noqa: BLE001 - a dead endpoint must not fail the pass
        print(f"[jev] model metadata unavailable ({type(exc).__name__}); skipping this pass")
        return {"skipped": provider_failure_category(exc)}
    tally = pipeline.run_jev(
        conn, now=now, model=resolved, limit=limit, max_usd=max_usd, clock=_now,
        profile_version=prof.version if prof else None,
        jev_fn=lambda posting: jev.assess(posting, inputs=inputs, post=client.post,
                                          resolved_model=resolved))
    return {**tally, "model": resolved}


def _run_jev_extract(conn, prof, *, extract, limit: int, model: str, now: str,
                     max_description_chars: int | None = None) -> dict:
    """JEV_BACKEND=extract: the packs through the screen provider. `model` names the
    backend, model and effort and is recorded on each verdict (provenance, never compared).
    The seam reports no cost: --jev-limit is the cap and --jev-max-usd never trips."""
    inputs = _triage_inputs(prof)
    if inputs is None:
        return {"skipped": _triage_skip_reason(prof)}
    print(f"[jev] backend {model} (UNVALIDATED; no cost reported, --jev-limit caps postings)")
    tally = pipeline.run_jev(
        conn, now=now, model=model, limit=limit, max_usd=Decimal("Infinity"), clock=_now,
        profile_version=prof.version if prof else None,
        jev_fn=lambda posting: jev.assess_extract(posting, inputs=inputs, extract=extract,
                                                  max_description_chars=max_description_chars))
    return {**tally, "model": model}


def _triage_skip_reason(prof) -> str:
    """The pass record's closed skip reason when _triage_inputs returned None."""
    return "no_profile" if prof is None or prof.triage_texts() is None else "invalid_packs"


def _triage_inputs(prof):
    """The triage (JEV) inputs from the candidate profile, or None (logged) when triage
    has nothing to judge against or the stored custom packs are invalid."""
    texts = prof.triage_texts() if prof else None
    if texts is None:
        print("[triage] the candidate profile has no target role and no custom triage "
              "context; skipping triage this pass (set them in Settings or with "
              "set_candidate_profile)")
        return None
    try:
        return jev.inputs_from_texts(texts)
    except ValueError as exc:
        print(f"[triage] the stored custom question packs are invalid ({exc}); skipping "
              "triage. Clear them (set_candidate_profile custom_packs=null) to use the "
              "committed default packs")
        return None


def _profile_for_pass(conn, cfg, *, now: str):
    """The candidate profile this pass runs under, read from the DB.

    config.yaml seeds the row once when none exists (title_filter, title_exclude,
    max_age_days, `candidate:` and the `jev_dir` texts); a config with none of them seeds
    nothing, so a fresh install is configured in Settings or with set_candidate_profile.
    After that the row wins and set config keys are reported, not applied. A malformed
    stored row raises (profile.ProfileError), failing the pass loudly.
    """
    stored = profile.load(conn)
    if stored is None:
        jev_texts = jev.read_files(cfg.jev_dir) if cfg.jev_dir else None
        if jev_texts is not None:
            jev.inputs_from_texts(jev_texts)  # validate before storing
        values = profile.seed_values(cfg, jev_texts=jev_texts)
        if values is None:
            return None
        db.write_candidate_profile(conn, values, actor="config", now=now)
        print("[profile] seeded the candidate profile from config.yaml")
        return profile.load(conn)
    drift = profile.config_drift(cfg, stored)
    if drift:
        print(f"[profile] config.yaml {', '.join(drift)} ignored: the stored candidate "
              "profile wins (edit it in Settings or with set_candidate_profile)")
    return stored


def _pass_config(cfg, scope, *, screen: dict | None, triage: dict | None) -> dict:
    """The effective runtime config a pass records (worker_runs.config_json). Built
    from an explicit allowlist of non-secret values: no env value ever lands here.
    `scope` is the candidate profile the pass runs under (max_age_days is its value,
    not config.yaml's seed)."""
    return {"screen": screen, "triage": triage,
            "feeds": [f.name for f in cfg.feeds if f.enabled],
            "browser_sources": bool(cfg.enable_browser_sources),
            "max_age_days": scope.max_age_days,
            # The pass interval: the web judges an overlong `running` row against it.
            "schedule_hours": cfg.schedule_hours}


def _companies_as_dicts(cfg) -> list[dict]:
    return [{"source": c.source, "slug": c.slug, "name": c.name, "recipe": c.recipe}
            for c in cfg.companies]


# One pipeline pass at a time per DB. Keyed on the resolved --db path (see
# `_lock_path_for`) rather than on the temp dir, because the temp dir is not something
# two passes on the same host agree on: a systemd unit with PrivateTmp=yes, or a cron
# job with a sanitized env, resolves a different one than an interactive shell that
# exports TMPDIR — so both would acquire and both would screen the same rows, which
# is the failure that costs provider quota. The DB path is what they DO agree on.
# Only used when no db path is available (tests); real passes go through
# `_lock_path_for`.
_LOCK_PATH = Path(tempfile.gettempdir()) / "ats-worker-pass.lock"


def _lock_path_for(db_path) -> Path:
    """The pass lock for one database: `<db>.pass.lock`, beside the DB itself.

    `resolve()` so a relative `--db`, a symlinked checkout and an absolute path all
    land on ONE file — the guard is void the moment two passes name it differently.
    Beside the DB rather than in the temp dir for the reason above, and the sidecar
    naming matches what SQLite already puts there (`-wal`, `-shm`); the web container
    bind-mounts that directory but never takes this lock.
    """
    db = Path(db_path).resolve()
    return db.with_name(db.name + ".pass.lock")


class PassInProgress(RuntimeError):
    """Another pipeline pass on this host already holds the lock."""


def _recorded_holder(fd) -> str:
    """The pid recorded in the lock file, but only if a process by that number is
    actually alive — else "unknown".

    The file is never unlinked, so whatever pid it holds outlives its writer. Two ways
    a contender would otherwise report a corpse as the live holder and send the
    operator hunting a process that does not exist: a read-only holder cannot
    overwrite the previous pid at all, and even a writable one has a window between
    taking the flock and writing. Liveness is the only thing that distinguishes them
    from here. A recycled pid can still mislead — which is exactly why the lock is an
    flock and the pid is a diagnostic, not the mechanism.
    """
    raw = os.pread(fd, 32, 0).decode("utf-8", "replace").strip()
    try:
        os.kill(int(raw), 0)
    except ValueError:
        return "unknown"                 # empty file, or not a number
    except ProcessLookupError:
        return "unknown"                 # recorded, but that process is gone
    except PermissionError:
        return raw                       # alive, just not ours to signal (a root pass)
    except OSError:
        return "unknown"
    return raw


def _lock_open_error(path, exc) -> str:
    """The message for a lock we could not open AT ALL. Opening is not contention and
    must never be reported as it, so it names the path and the fix."""
    return (f"cannot open the pass lock at {path}: {exc}. Nothing is wrong with the "
            f"pipeline — fix the file (check its owner and mode) or point --db at a "
            f"directory this user can write.")


@contextmanager
def pass_lock(path=None, db_path=None):
    """Hold the pass lock for one database for the duration of one whole pass.

    `flock` rather than a bare PID file, because staleness then solves itself: the
    kernel drops the lock when the holder dies, so a host killed mid-pass leaves a
    file the next pass can take immediately — no manual cleanup, and no guessing
    whether a recorded pid is the same process or a reused number. Release therefore
    covers every exit: normal return, exception, SIGINT (the `finally` runs), and
    SIGTERM/SIGKILL (the kernel releases it with the process).

    Raises `PassInProgress` at once if another pass holds it — never blocks, never
    queues. The file is only truncated and rewritten with the holder's pid, never
    unlinked: unlinking races (a second process can end up holding a lock on an inode
    that is no longer the one at this path).

    An unwritable lock file degrades to a read-only hold rather than failing: `flock`
    needs no write access, so refusing there would trade a working guard for a broken
    daemon (see the PermissionError branch).
    """
    # `is None`, not `or`, on both: a falsy path ("" from an unset env var, say) would
    # otherwise silently fall back to the process-wide default and lock the real
    # /tmp file — the one case where a caller asking for an isolated lock must not
    # quietly get the shared one. An explicit `path` still wins over `db_path` so a
    # test can point the lock anywhere.
    if path is None:
        path = _LOCK_PATH if db_path is None else _lock_path_for(db_path)
    path = Path(path)
    _flags = os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        # O_NOFOLLOW: the temp dir is world-writable and sticky, so refuse to follow a
        # symlink another user planted at this path rather than truncating its target.
        fd = os.open(str(path), os.O_RDWR | _flags, 0o644)
    except PermissionError:
        # `flock` needs no write access, so an unwritable lock file must not stop the
        # guard from WORKING — it only stops the pid diagnostic. This matters because
        # the failure is otherwise both permanent and invisible: one accidental
        # `sudo python -m ats_worker.run` leaves a root-owned file that is never
        # unlinked (by design, see above), and since the daemon runs no pass at
        # launch, the RuntimeError below would be raised inside the APScheduler job,
        # where the executor catches and logs it. The unit would stay `active
        # (running)`, report a healthy schedule, and never complete a pass — which is
        # the worse failure, not the better one. Degrade to read-only instead.
        try:
            fd = os.open(str(path), os.O_RDONLY | _flags)
            read_only = True
        except OSError as exc:
            # Not even readable — a 0600 file owned by someone else lands HERE, not in
            # the generic branch below, because EACCES is a PermissionError. Nothing to
            # degrade to, so fail loud like any other unopenable lock.
            raise RuntimeError(_lock_open_error(path, exc)) from exc
    except OSError as exc:
        # Opening the lock is NOT contention, and must not be reported as it. A missing
        # TMPDIR, a symlink refused by O_NOFOLLOW (ELOOP), a read-only filesystem
        # (EROFS) — each fails here forever, and "never unlinked" means nothing
        # self-heals. Fail loud and name the path, rather than a traceback or a false
        # "already running".
        raise RuntimeError(_lock_open_error(path, exc)) from exc
    else:
        read_only = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                # flock unsupported or broken on this filesystem (NFS without lockd, some
                # FUSE mounts). Reporting that as contention would refuse EVERY pass
                # forever while telling the operator a pass is already running.
                raise RuntimeError(
                    f"the pass lock at {path} could not be taken: {exc}. This is not "
                    f"contention — the filesystem holding it does not support flock. "
                    f"Put the DB on a local filesystem."
                ) from exc
            raise PassInProgress(
                f"another pipeline pass is already running on this host "
                f"(pid {_recorded_holder(fd)}, lock {path}) — refusing to start a "
                f"second one; a duplicate pass would re-spend screen-provider quota"
            ) from None
        if read_only:
            # The lock is held and doing its job; only the pid record is unavailable,
            # so the file keeps whatever pid its last writable holder left. That is why
            # a contender checks liveness (_recorded_holder) instead of trusting the
            # bytes — otherwise it would name a corpse as the running pass. Say all of
            # it out loud: the operator should fix the file's owner, not learn to
            # ignore a degraded lock.
            print(f"[pass] holding {path} read-only (pid {os.getpid()} NOT recorded — "
                  f"this file is not writable by this user, so it still holds an older "
                  f"pid. Check its owner and mode)", flush=True)
        else:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
            # Printed because the guard is void between two passes that resolve the
            # path differently, and that is otherwise undetectable from the outside.
            print(f"[pass] holding {path} (pid {os.getpid()})", flush=True)
        yield path
    finally:
        os.close(fd)   # releases the flock


# The wall-clock slot set, as APScheduler's `hour=` string. Pure arithmetic and no
# apscheduler import, so the suite can assert the SCHEDULE directly instead of trusting a
# trigger object it has no dependency for.
def cron_hours(schedule_hours: int) -> str:
    """`4` -> `"0,4,8,12,16,20"`; `24` -> `"0"`.

    Only a divisor of 24 is legal (`config.load_config` enforces it), because
    `range(0, 24, h)` for a non-divisor leaves a `24 % h` gap across midnight that is
    always TIGHTER than the configured cadence, and any `h > 24` collapses to `"0"`.
    """
    return ",".join(str(h) for h in range(0, 24, schedule_hours))


def _run_scheduler(job, schedule_hours: int) -> None:  # pragma: no cover
    """Block on the wall-clock scheduler. Not covered, and deliberately thin.

    `requirements-dev.txt` excludes apscheduler by design and CI installs only the dev
    requirements, so the suite cannot import this. Everything decidable without
    apscheduler — the slot arithmetic, the `--run-now` sequencing, the config bound —
    is tested through `cron_hours` and `main` instead; what is left here is wiring.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    # `minute=0` is set EXPLICITLY. CronTrigger's default for a field below the most
    # significant one supplied happens to be 0, which is what we want — but that is a
    # field-ordering rule, not something readable at this call site, and the failure if
    # it ever changed is 60 passes per slot against a paid screen provider.
    trigger = CronTrigger(hour=cron_hours(schedule_hours), minute=0)

    # basicConfig HERE, in the daemon branch only, so importing this module still
    # installs nothing. Without it APScheduler's misfire warnings, max-instances skips
    # and job tracebacks all fall to `logging.lastResort`: message only, level prefix, no
    # TIMESTAMP and no logger name. This is the handler the pass-skip warning wants.
    # It does NOT unify the streams: `lastResort` and a default `basicConfig` are both
    # StreamHandlers on stderr, and the pipeline still `print()`s to stdout. What this
    # buys is timestamps and provenance, which is what journald needs to interleave them.
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    scheduler = BlockingScheduler()
    scheduler.add_job(
        job, trigger,
        # `max_instances` and `coalesce` are BOTH already APScheduler's defaults
        # (`BaseScheduler._configure`: `max_instances=1`, `coalesce=True`). They are
        # restated because each carries a cost if it ever silently changed — a second
        # concurrent pass re-spends paid quota, and un-coalesced catch-up would fire one
        # queued pass per missed slot after a suspend. Neither line changes behavior today.
        max_instances=1,
        coalesce=True,
        # THIS is the only non-default here. APScheduler's is ONE SECOND, so any slot the
        # host was busy through is dropped silently; the deleted eager `once()` was masking
        # that, because a restarted daemon always ran promptly whether or not it had missed
        # anything. Half a cadence capped at an hour — 30 min at h=1, one hour from h=2 up.
        # Know what this does NOT buy: coalescing keeps only the LAST missed run time, and
        # the executor then drops even that one if it is older than the grace window. So a
        # host resuming more than an hour past a slot runs ZERO catch-up passes, not one —
        # it simply waits for the next slot. This covers a slow pass or a brief stall, not
        # a long suspend.
        misfire_grace_time=min(3600, schedule_hours * 1800),
    )

    # Say the schedule out loud. With the eager pass gone a freshly started daemon is
    # otherwise indistinguishable from a hung one for up to `schedule_hours`. The
    # timezone matters as much as the hours: it comes from `tzlocal`, so a UTC host
    # would quietly defeat the whole point of wall-clock slots — set `TZ=` to fix it
    # without touching code.
    print(f"[schedule] passes at {trigger.fields[trigger.FIELD_NAMES.index('hour')]}"
          f":00 {trigger.timezone} (every {schedule_hours}h, wall-clock)", flush=True)
    scheduler.start()


def main(argv=None) -> None:
    # Load .env BEFORE the parser is built: the argparse defaults for --db/--model/
    # --screen-backend/--screen-model read os.environ, so a .env value
    # has to be in os.environ by the time add_argument runs. setdefault = a real process
    # env var (e.g. a shell-exported DB_PATH) still wins and an explicit CLI flag
    # still overrides; --env is peeked first so a custom path is honored.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env", default=".env")
    env = load_env(pre.parse_known_args(argv)[0].env)
    for key, value in env.items():
        if key in _ENV_ARGPARSE_KEYS:
            os.environ.setdefault(key, value)

    parser = argparse.ArgumentParser(description="Job-hunt pipeline worker")
    parser.add_argument("--once", action="store_true", help="run a single pass and exit")
    parser.add_argument("--run-now", action="store_true",
                        help="daemon mode only: run one pass immediately, then keep the "
                             "wall-clock schedule. Restores the old eager startup pass "
                             "on demand")
    parser.add_argument("--fetch-only", action="store_true",
                        help="run fetch/feed/expire then stop, before any screen call "
                             "(quota-free board refresh)")
    # ponytail: no-op alias since the fit scorer was removed; existing service files pass it.
    parser.add_argument("--screen-only", action="store_true",
                        help="accepted for compatibility: a pass is always "
                             "fetch/feed/expire plus the hard-requirements screen")
    parser.add_argument("--refresh-unscored", action="store_true",
                        help="one-shot source-only refresh for existing unscored jobs; "
                             "requires --once and an explicit --refresh-source")
    parser.add_argument("--refresh-source", choices=("smartrecruiters",),
                        help="source adapter for --refresh-unscored (currently "
                             "SmartRecruiters only)")
    parser.add_argument("--refresh-limit", type=int, default=25,
                        help="maximum source requests for --refresh-unscored (1-25)")
    parser.add_argument("--import-companies", action="store_true",
                        help="seed config.yaml companies into the DB watchlist and exit")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")
    # The default targets the checkout layout — ../web/prisma/applications.db is a
    # symlink onto the shared db/applications.db; override via DB_PATH or --db.
    parser.add_argument("--db",
                        default=os.environ.get("DB_PATH", "../web/prisma/applications.db"))
    parser.add_argument("--model",
                        default=os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
                        help="Ollama model tag used for the screen")
    parser.add_argument("--screen-backend", choices=SCREEN_BACKENDS,
                        default=os.environ.get("SCREEN_BACKEND",
                                               DEFAULT_SCREEN_BACKEND),
                        help="hard-requirements screen backend. Default 'ollama' "
                             "(free, local). 'none' runs the deterministic gates "
                             "only and is LOW RECALL on sponsorship")
    parser.add_argument("--screen-model",
                        default=os.environ.get("SCREEN_MODEL"),
                        help="model for the screen backend (Codex defaults to "
                             "gpt-5.6-luna)")
    parser.add_argument("--screen-effort", choices=SCREEN_EFFORT_VALUES,
                        default=os.environ.get("SCREEN_EFFORT"),
                        help="Codex screen reasoning effort (default medium)")
    screen_budget = parser.add_mutually_exclusive_group()
    screen_budget.add_argument("--screen-limit", type=int,
                               help="maximum provider calls per screen pass (default 40; "
                                    "must be positive)")
    screen_budget.add_argument("--screen-unlimited", action="store_true",
                               help="explicitly remove the screen provider-call cap; "
                                    "retains the provider breaker")
    parser.add_argument("--jev", action="store_true",
                        help="after the screen, run triage, the keep/skip stage, with the JEV "
                             "provider (reads the candidate profile; the default "
                             "openrouter-native backend is paid and needs OPENROUTER_API_KEY)")
    parser.add_argument("--jev-backend", default=os.environ.get("JEV_BACKEND", "openrouter-native"),
                        help="openrouter-native (default, measured) or extract (the screen "
                             "backend answers the same packs; UNVALIDATED, no USD cap)")
    parser.add_argument("--jev-limit", type=int,
                        help="max postings the JEV filter assesses per pass (default 300; "
                             "40 with --jev-backend extract)")
    parser.add_argument("--jev-max-usd",
                        help="stop the JEV filter once a pass has spent this much (USD, "
                             "default 0.10; refused with --jev-backend extract)")
    parser.add_argument("--screen-workers", type=int,
                        default=int(os.environ.get("SCREEN_WORKERS", "0")),
                        help="concurrent screen calls (0 = 1)")
    args = parser.parse_args(argv)
    # argparse checks `choices` only on a typed flag, not on the SCREEN_BACKEND default,
    # so an env value is validated here, before any fetch runs.
    if args.screen_backend not in PROVIDERS:
        hint = (f"; use SCREEN_BACKEND={RETIRED[args.screen_backend]}"
                if args.screen_backend in RETIRED else "")
        parser.error(f"unknown screen backend {args.screen_backend!r} "
                     f"(want one of {', '.join(SCREEN_BACKENDS)}){hint}")
    if PROVIDERS[args.screen_backend].model_required and not args.screen_model:
        parser.error(f"SCREEN_BACKEND={args.screen_backend} needs SCREEN_MODEL "
                     "(or --screen-model)")

    # `--run-now` is the daemon's eager first pass; `--once` runs a pass and exits. Asking
    # for both is asking for two different programs, and the likely intent (just run one
    # pass) is exactly `--once`. Fail rather than silently picking one.
    if args.run_now and args.once:
        parser.error("--run-now is for daemon mode: it runs one pass and then STAYS on "
                     "the schedule. For a single pass that exits, use --once alone.")

    if sum((args.fetch_only, args.screen_only, args.refresh_unscored)) > 1:
        parser.error("--fetch-only, --screen-only and --refresh-unscored are mutually "
                     "exclusive")
    if args.refresh_unscored:
        if not args.once:
            parser.error("--refresh-unscored is one-shot: pass --once")
        if args.refresh_source is None:
            parser.error("--refresh-unscored requires --refresh-source smartrecruiters")
        if not 1 <= args.refresh_limit <= pipeline.UNSCORED_REFRESH_MAX:
            parser.error("--refresh-limit must be between 1 and 25")
    elif args.refresh_source is not None:
        parser.error("--refresh-source requires --refresh-unscored")
    if args.screen_unlimited:
        if args.fetch_only:
            parser.error("--screen-unlimited has no effect with --fetch-only")
        args.screen_limit = None
    elif args.screen_limit is None:
        try:
            args.screen_limit = int(os.environ.get("SCREEN_LIMIT", "40"))
        except ValueError:
            parser.error("SCREEN_LIMIT must be an integer")
    if not args.fetch_only and args.screen_limit is not None and args.screen_limit <= 0:
        parser.error("--screen-limit must be a positive provider-call cap")
    if args.screen_workers < 0:
        parser.error("--screen-workers must be >= 0 (0 selects the default)")
    if args.screen_effort and args.screen_effort not in SCREEN_EFFORT_VALUES:
        parser.error("SCREEN_EFFORT must be one of " + ", ".join(SCREEN_EFFORT_VALUES))

    cfg = config_mod.load_config(args.config)
    if args.jev:
        if args.fetch_only or args.refresh_unscored:
            parser.error("--jev runs after the screen; it cannot combine with "
                         "--fetch-only or --refresh-unscored")
        if args.jev_backend not in JEV_BACKENDS:
            parser.error(f"--jev-backend/JEV_BACKEND must be one of {', '.join(JEV_BACKENDS)}")
        if args.jev_backend == "extract" and args.screen_backend == "none":
            parser.error("--jev-backend extract needs a screen backend other than none")
        if args.jev_backend == "extract" and args.jev_max_usd is not None:
            parser.error("--jev-max-usd does not apply to --jev-backend extract (no cost "
                         "is reported); cap it with --jev-limit")
    if args.jev_limit is None:
        # ponytail: extract has no USD cap, so its default is the screen's 40, not 300
        args.jev_limit = 40 if args.jev_backend == "extract" else 300
    if args.jev_max_usd is None:
        args.jev_max_usd = "0.10"
    if args.jev:
        if args.jev_limit <= 0:
            parser.error("--jev-limit must be positive")
        try:
            args.jev_max_usd = Decimal(args.jev_max_usd)
        except ArithmeticError:
            parser.error("--jev-max-usd must be a number")
        if not (args.jev_max_usd.is_finite() and args.jev_max_usd > 0):
            parser.error("--jev-max-usd must be a positive finite number")

    # Force-seed the DB watchlist from config and exit (idempotent). Useful to
    # push newly-added config companies into the table; the normal run also
    # auto-seeds when the watchlist is empty.
    if args.import_companies:
        conn = db.connect(args.db)
        try:
            seeded = db.import_watchlist(conn, _companies_as_dicts(cfg), now=_now())
        finally:
            conn.close()
        print(f"imported {seeded} companies into the watchlist")
        return

    def once(foreground: bool = False):
        # The predicate is "does a refused pass kill the caller", and it is passed
        # EXPLICITLY rather than inferred from `args.once`, because `--run-now` is neither
        # a hand run nor a scheduled firing and inference gets it wrong in the expensive
        # direction. Only a FOREGROUND `--once` exits non-zero, so a wrapper script sees
        # the refusal. Everything in daemon mode — the `--run-now` startup pass and every
        # scheduled slot — logs and carries on, because a daemon that dies because someone
        # happened to be running a pass by hand is worse than a daemon that skips one.
        # A whole pass runs under the lock for THIS db. APScheduler's max_instances=1 stops
        # the scheduler overlapping ITSELF, but not a hand-run pass landing inside a
        # scheduled one — likelier the higher the cadence, and a duplicated pass
        # re-spends screen-provider quota.
        try:
            with pass_lock(db_path=args.db):
                run_once(cfg, db_path=args.db, env=env, ollama_model=args.model,
                         screen_backend=args.screen_backend,
                         screen_model=args.screen_model,
                         screen_effort=args.screen_effort,
                         screen_limit=args.screen_limit,
                         fetch_only=args.fetch_only,
                         screen_workers=args.screen_workers,
                         refresh_unscored=args.refresh_unscored,
                         refresh_source=args.refresh_source,
                         refresh_limit=args.refresh_limit,
                         jev_enabled=args.jev, jev_limit=args.jev_limit,
                         jev_max_usd=Decimal(str(args.jev_max_usd)),
                         jev_backend=args.jev_backend)
        except PassInProgress as exc:
            # A hand run exits non-zero so a wrapper script sees the refusal; a
            # scheduled firing skips this slot and waits for the next one. Neither
            # queues, blocks, or runs a partial pass.
            if foreground:
                raise SystemExit(str(exc)) from None
            # `logging`, not `print`: this and APScheduler's own misfire and
            # max-instances warnings are the same signal — "a pass did not run" — and
            # APScheduler emits its half through `logging`, so one handler carries both.
            # `_run_scheduler` installs that handler; a bare import still installs none,
            # so calling this outside the daemon falls to `logging.lastResort`.
            logging.warning("skipping this pass: %s", exc)

    if args.once:
        once(foreground=True)
        return

    # Seed the candidate profile at startup, not at the first wall-clock slot: until a
    # row exists MCP reports it missing, and a set_candidate_profile would pre-empt it.
    conn = db.connect(args.db)
    try:
        # Every pass writes worker_runs; a DB pushed before #247 would fail each slot
        # while the daemon looked alive. Refuse to start instead.
        if not db.has_table(conn, "worker_runs"):
            raise SystemExit(f"{args.db} has no worker_runs table: the schema is older "
                             "than this worker. Run `make db-push`, then restart.")
        if db.needs_evaluate_once_migration(conn):
            raise SystemExit(f"{args.db}: {_LEGACY_DISCARDS}, then restart.")
        _profile_for_pass(conn, cfg, now=_now())
    finally:
        conn.close()

    # No eager pass. Passes fire on wall-clock slots only, so a restart no longer costs an
    # immediate full pass — which at 6 passes/day made every daemon bounce a 7th. Ask for
    # one with --run-now.
    if args.run_now:
        once()
    _run_scheduler(once, cfg.schedule_hours)


if __name__ == "__main__":
    main()
