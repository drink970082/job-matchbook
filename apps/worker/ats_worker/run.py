"""Entrypoint: wire real adapters and run the pipeline once or on a schedule.

WHY the env/adapter wiring lives only here: every other module is pure and
injected, so this is the single place that knows about secrets and external
services. `run_once` takes already-loaded config/secrets and the worker
callables it builds from them, calling the pipeline stages in order (fetch,
retry, score, notify).

APScheduler is imported lazily inside the cron path so the test environment —
which lacks apscheduler — can still import and exercise this module.
"""
from __future__ import annotations

import argparse
import os
import threading
import time
from pathlib import Path

import requests

from . import config as config_mod
from . import db, pipeline
from .fetch import fetch_company, fetch_one_company
from .feed import embedded_gh, simplify
from .notify import notify_posting
from .score import make_claude_scorer, make_codex_scorer, screen_posting

# qwen3.5:4b runs fully on an 8GB GPU (~3GB resident) and returns clean JSON in
# ~2s/posting with thinking disabled (see score.py). The 9b (6.6GB) spills to
# CPU on an 8GB card (~100s/call), so it's a poor fit here. Override per-deploy
# with --model or the OLLAMA_MODEL env var.
DEFAULT_OLLAMA_MODEL = "qwen3.5:4b"
# Fit scoring runs on the ChatGPT-subscription Codex CLI by default: flat-rate instead
# of metered Claude, over a queue where a full re-score is ~640 paid calls. Auth is the
# operator's `codex login` state (auth_mode=chatgpt), NOT an env key — a logged-out host
# fails the pass loudly rather than scoring 0s. Claude remains available for a
# reproducible A/B (--score-backend claude). Override with --score-backend / SCORE_BACKEND.
DEFAULT_SCORE_BACKEND = "codex"
# gpt-5.6-sol — chosen on the GOLDEN SET, which is the only measurement that counts here.
# A synthetic single-prompt probe said gpt-5.6-terra had a tighter spread at half the
# credit rate; on real JDs terra was WORSE on both gate axes (agreement 76% vs 86%,
# flip-rate 38% vs 29%) and calibrated visibly looser/more generous (id=64 a confident
# keep(92,93,92) against a `near` label; id=70 threw a skip(28) between two keep(86+)).
# Synthetic variance probes did not predict real-JD behavior — twice. Don't re-pick a
# model without a full `make eval-score` run. (gpt-5.6-luna: rejected outright, ~3x looser
# spread, despite the docs recommending it for "extraction/classification".)
DEFAULT_CODEX_SCORE_MODEL = "gpt-5.6-sol"
# Sonnet 5 scores fit (real seniority/domain judgment, unlike the local 4B model);
# Sonnet 4.6 doesn't support structured outputs (output_config.format), so it can't
# be used here. Override with --anthropic-score-model or ANTHROPIC_SCORE_MODEL.
DEFAULT_ANTHROPIC_SCORE_MODEL = "claude-sonnet-5"
# Max postings per fit_fn batch call. Batching WOULD be the codex quota win (the
# ChatGPT-subscription quota is MESSAGE-bound, not token-bound — see
# make_codex_scorer), but it is PARKED at 1: the batched==single guard
# (score_eval.py --batched, 2026-07-16) FAILED 19/23 — concatenating JDs in one
# call bled the DOMAIN verdict on borderline rows (adjacent→match on ids 111/125,
# which would then wrongly notify), so per the design's rollout rule "if batched
# verdicts drift, batching does not ship". batch_size=1 == the validated per-JD
# path (one JD per codex exec, no cross-JD context to bleed). The batching code +
# the guard stay for a future fix (smaller batches / stronger per-JD isolation);
# opt back in with --batch-size / CODEX_BATCH_SIZE once the drift is resolved.
# (claude's fit_fn loops per posting regardless, so batch_size is a no-op there.)
DEFAULT_BATCH_SIZE = 1

# The ONLY six .env keys argparse defaults read from os.environ (grepped across
# the whole ats_worker package — see run.main below). Secrets (TELEGRAM_BOT_TOKEN,
# TELEGRAM_CHAT_ID, ANTHROPIC_API_KEY) are deliberately excluded: every consumer
# reads them from the in-process `env` dict (run_once(..., env=env) / make_scorer),
# never os.environ, so promoting them would only leak them to subprocesses that
# inherit the full environment (the codex CLI — see score/backends_codex.py).
_ENV_ARGPARSE_KEYS = frozenset({
    "DB_PATH", "OLLAMA_MODEL", "SCORE_BACKEND", "CODEX_SCORE_MODEL",
    "ANTHROPIC_SCORE_MODEL", "CODEX_BATCH_SIZE",
})


def make_scorer(backend: str, *, env, profile="",
                codex_score_model=DEFAULT_CODEX_SCORE_MODEL,
                anthropic_score_model=DEFAULT_ANTHROPIC_SCORE_MODEL,
                usage_path=None):
    """Pick the fit-score backend. Both twins expose the same batch-first
    `fit(postings, resumes) -> list[dict]` contract (one scorecard per input
    posting, in order; a single posting is `fit([posting], resumes)[0]`), so
    only this line changes. `usage_path` (codex only) enables free quota-usage
    capture off the scoring call; None disables it."""
    if backend == "codex":
        return make_codex_scorer(codex_score_model, profile=profile,
                                 usage_path=usage_path)
    if backend == "claude":
        return make_claude_scorer(env["ANTHROPIC_API_KEY"], anthropic_score_model,
                                  profile=profile)
    raise ValueError(f"unknown score backend: {backend!r} (want 'codex' or 'claude')")

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


def run_once(cfg, *, db_path, resumes, profile="", env,
             ollama_model=DEFAULT_OLLAMA_MODEL,
             score_backend=DEFAULT_SCORE_BACKEND,
             codex_score_model=DEFAULT_CODEX_SCORE_MODEL,
             anthropic_score_model=DEFAULT_ANTHROPIC_SCORE_MODEL,
             batch_size: int = DEFAULT_BATCH_SIZE) -> None:
    """Run fetch -> retry -> score -> notify exactly once. `resumes` is the
    {label: text} dict of resume versions; `profile` is optional candidate
    context — both are baked into the fit scorer (the Ollama SCREEN never
    sees either)."""
    conn = db.connect(db_path)
    try:
        now = _now()
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

        # Build the screening checklist (candidate hard-requirements) once, up front:
        # run_fetch uses it for the deterministic pre-screen gate, and screen_fn below
        # reuses it. Empty candidate => None => no gate, no SCREEN call.
        if cfg.candidate.is_empty():
            candidate = None
        else:
            candidate = {
                "highest_degree": cfg.candidate.highest_degree,
                "work_authorization": cfg.candidate.work_authorization,
                "security_clearance": cfg.candidate.security_clearance,
                "locations": list(cfg.candidate.locations),
                "exclude_internships": cfg.candidate.exclude_internships,
            }

        pipeline.run_fetch(conn, companies, cfg.title_filter, now=now,
                           fetch_fn=fetch_company, title_exclude=cfg.title_exclude,
                           max_age_days=cfg.max_age_days, candidate=candidate)

        # Discovery feeds: broad listing streams resolved back to boards. Runs
        # before scoring so feed-discovered 'new' rows are scored this same pass.
        for feed in cfg.feeds:
            if not feed.enabled:
                continue
            if feed.name == "simplify":
                pipeline.run_feed(
                    conn, now=now,
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
                )

        # Re-check a capped batch of live postings and expire the dead ones, so a
        # closed req stops sitting in the queue as a dead link.
        gone = pipeline.run_expire(
            conn, now=now,
            detail_fetch_fn=lambda s, sl, e, n: fetch_one_company(
                s, sl, e, n, session=_feed_session(), timeout=_FEED_TIMEOUT))
        if gone:
            print(f"expired {gone} dead posting(s)")

        # Requeue any 'failed' row that hasn't exhausted its attempts budget, so
        # it's rescored in this SAME pass alongside fresh ingests (§9 SPEC.md).
        pipeline.run_retry(conn, now=now)

        # num_ctx is set explicitly (Ollama's default is small enough to truncate
        # long JDs); override per-deploy via OLLAMA_NUM_CTX without code changes.
        num_ctx = int(env.get("OLLAMA_NUM_CTX", "8192"))

        def screen_fn(posting):
            return screen_posting(
                posting,
                http=requests,
                model=ollama_model,
                ollama_host=env.get("OLLAMA_HOST", "http://localhost:11434"),
                candidate=candidate,
                num_ctx=num_ctx,
            )

        # Build the fit scorer lazily on first use (both twins are import-safe: the
        # anthropic SDK import / the codex subprocess are deferred to the first call,
        # so this closure is cheap and the hermetic tests touch neither).
        _scorer_cell: list = []
        # Land the codex quota snapshot next to the REAL db file (resolve the
        # prisma/applications.db symlink) so it sits in the shared db/ mount the
        # web reads as /data/codex_usage.json. See docs/SPEC.md §7.1.
        usage_path = os.path.join(
            os.path.dirname(os.path.realpath(db_path)), "codex_usage.json")

        def fit_fn(postings):
            if not _scorer_cell:
                _scorer_cell.append(
                    make_scorer(score_backend, env=env, profile=profile,
                                codex_score_model=codex_score_model,
                                anthropic_score_model=anthropic_score_model,
                                usage_path=usage_path)
                )
            return _scorer_cell[0](postings, resumes)

        pipeline.run_score(conn, now=now, screen_fn=screen_fn, fit_fn=fit_fn,
                           batch_size=batch_size)

        pipeline.run_notify(
            conn,
            now=now,
            notify_fn=notify_posting,
            token=env["TELEGRAM_BOT_TOKEN"],
            chat_id=env["TELEGRAM_CHAT_ID"],
        )
    finally:
        conn.close()


def _companies_as_dicts(cfg) -> list[dict]:
    return [{"source": c.source, "slug": c.slug, "name": c.name, "recipe": c.recipe}
            for c in cfg.companies]


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise SystemExit(
            f"Could not read required resume file {path!r}: {exc}.\n"
            f"Provide your resume in apps/worker/resume/ (see resume/README.md)."
        ) from exc


def load_resumes(dir_path: str) -> tuple[dict[str, str], str]:
    """Load every *.txt in dir_path as a labeled resume version, plus the
    optional personal_profile.txt as about-the-candidate context.

    Label = filename stem minus a leading 'resume_' ('resume_quant_dev.txt' ->
    'quant_dev'; bare 'resume.txt' -> 'resume'), so today's single-file layout
    keeps working unchanged. Sorted by filename for a deterministic,
    cache-stable prompt prefix. Zero resumes or two files deriving the same
    label are config errors -> SystemExit (never a silent overwrite).
    """
    resumes: dict[str, str] = {}
    seen: dict[str, str] = {}  # label -> filename that claimed it
    profile = ""
    for f in sorted(Path(dir_path).glob("*.txt")):
        if f.name.startswith("."):
            continue  # dotfiles (e.g. macOS ._resume.txt sidecars) are never resumes
        if f.name == "personal_profile.txt":
            profile = _read_text(str(f))
            continue
        label = f.stem.removeprefix("resume_") or f.stem
        if label in seen:
            raise SystemExit(
                f"Resume label {label!r} comes from both {seen[label]} and "
                f"{f.name} — rename one (label = filename minus 'resume_')."
            )
        seen[label] = f.name
        resumes[label] = _read_text(str(f))
    if not resumes:
        raise SystemExit(
            f"No resume *.txt files found in {dir_path!r}. Provide at least one "
            f"(see resume/README.md)."
        )
    return resumes, profile


def main(argv=None) -> None:
    # Load .env BEFORE the parser is built: the argparse defaults for --db/--model/
    # --score-backend/--codex-score-model/--batch-size read os.environ, so a .env value
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
    parser.add_argument("--import-companies", action="store_true",
                        help="seed config.yaml companies into the DB watchlist and exit")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")
    # The default targets the checkout layout — ../web/prisma/applications.db is a
    # symlink onto the shared db/applications.db; override via DB_PATH or --db.
    parser.add_argument("--db",
                        default=os.environ.get("DB_PATH", "../web/prisma/applications.db"))
    parser.add_argument("--resume-dir", default="resume",
                        help="directory of resume *.txt versions (+ optional "
                             "personal_profile.txt)")
    parser.add_argument("--model",
                        default=os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
                        help="Ollama model tag used for scoring")
    parser.add_argument("--score-backend", choices=("codex", "claude"),
                        default=os.environ.get("SCORE_BACKEND", DEFAULT_SCORE_BACKEND),
                        help="fit-score backend: codex (ChatGPT subscription, flat-rate) "
                             "or claude (metered API)")
    parser.add_argument("--codex-score-model",
                        default=os.environ.get("CODEX_SCORE_MODEL",
                                               DEFAULT_CODEX_SCORE_MODEL),
                        help="Codex CLI model used for fit scoring")
    parser.add_argument("--anthropic-score-model",
                        default=os.environ.get("ANTHROPIC_SCORE_MODEL",
                                               DEFAULT_ANTHROPIC_SCORE_MODEL),
                        help="Anthropic model used for fit scoring")
    parser.add_argument("--batch-size", type=int,
                        default=int(os.environ.get("CODEX_BATCH_SIZE",
                                                   str(DEFAULT_BATCH_SIZE))),
                        help="max postings per fit_fn batch call. Default 1 "
                             "(batching PARKED — failed the batched==single guard; "
                             "see DEFAULT_BATCH_SIZE); raise once the domain-verdict "
                             "drift is fixed. No-op on the claude backend (loops).")
    args = parser.parse_args(argv)

    cfg = config_mod.load_config(args.config)

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

    resumes, profile = load_resumes(args.resume_dir)

    def once():
        run_once(cfg, db_path=args.db, resumes=resumes, profile=profile,
                 env=env, ollama_model=args.model,
                 score_backend=args.score_backend,
                 codex_score_model=args.codex_score_model,
                 anthropic_score_model=args.anthropic_score_model,
                 batch_size=args.batch_size)

    if args.once:
        once()
        return

    # Cron mode — apscheduler imported lazily so tests never need it.
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    scheduler.add_job(once, "interval", hours=cfg.schedule_hours)
    once()  # run immediately, then on the interval
    scheduler.start()


if __name__ == "__main__":
    main()
