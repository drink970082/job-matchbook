"""Entrypoint: wire real adapters and run the pipeline once or on a schedule.

WHY the env/adapter wiring lives only here: every other module is pure and
injected, so this is the single place that knows about secrets and external
services. `run_once` takes already-loaded config/secrets and the worker
callables it builds from them, calling the three pipeline stages in order.

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
from .score import make_claude_scorer, make_codex_scorer, score_posting

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


def make_scorer(backend: str, *, env, profile="",
                codex_score_model=DEFAULT_CODEX_SCORE_MODEL,
                anthropic_score_model=DEFAULT_ANTHROPIC_SCORE_MODEL):
    """Pick the fit-score backend. Both twins expose the same
    `score_fit(posting, resumes) -> dict` contract, so only this line changes."""
    if backend == "codex":
        return make_codex_scorer(codex_score_model, profile=profile)
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
             anthropic_score_model=DEFAULT_ANTHROPIC_SCORE_MODEL) -> None:
    """Run fetch -> score -> notify exactly once. `resumes` is the {label: text}
    dict of resume versions; `profile` is optional candidate context — both are
    baked into the fit scorer (the Ollama SCREEN never sees either)."""
    conn = db.connect(db_path)
    try:
        now = _now()
        # The watchlist is DB-owned. Seed it once from config.yaml `companies:`
        # when the table is empty; thereafter the DB (web-managed) is authoritative.
        if db.count_watchlist(conn) == 0 and cfg.companies:
            seeded = db.import_watchlist(conn, _companies_as_dicts(cfg), now=now)
            print(f"seeded watchlist from config: {seeded} companies")
        companies = db.get_watchlist(conn)

        pipeline.run_fetch(conn, companies, cfg.title_filter, now=now)

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

        # Build the screening checklist only when the candidate actually configured
        # hard requirements; an empty candidate skips the SCREEN call entirely (no
        # disqualification), so don't pay for a second Ollama call per posting.
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
        # num_ctx is set explicitly (Ollama's default is small enough to truncate
        # long JDs); override per-deploy via OLLAMA_NUM_CTX without code changes.
        num_ctx = int(env.get("OLLAMA_NUM_CTX", "8192"))

        # Build the fit scorer lazily on first use (both twins are import-safe: the
        # anthropic SDK import / the codex subprocess are deferred to the first call,
        # so this closure is cheap and the hermetic tests touch neither).
        _scorer_cell: list = []

        def score_fn(posting):
            if not _scorer_cell:
                _scorer_cell.append(
                    make_scorer(score_backend, env=env, profile=profile,
                                codex_score_model=codex_score_model,
                                anthropic_score_model=anthropic_score_model)
                )
            return score_posting(
                posting, resumes,
                score_fit=_scorer_cell[0],
                model=ollama_model,          # Ollama model — SCREEN call only now
                ollama_host=env.get("OLLAMA_HOST", "http://localhost:11434"),
                candidate=candidate,
                num_ctx=num_ctx,
            )

        pipeline.run_score(conn, now=now, score_fn=score_fn)

        pipeline.run_notify(
            conn,
            cfg.threshold,
            now=now,
            notify_fn=notify_posting,
            token=env["TELEGRAM_BOT_TOKEN"],
            chat_id=env["TELEGRAM_CHAT_ID"],
        )
    finally:
        conn.close()


def _companies_as_dicts(cfg) -> list[dict]:
    return [{"source": c.source, "slug": c.slug, "name": c.name} for c in cfg.companies]


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
    parser = argparse.ArgumentParser(description="Job-hunt pipeline worker")
    parser.add_argument("--once", action="store_true", help="run a single pass and exit")
    parser.add_argument("--import-companies", action="store_true",
                        help="seed config.yaml companies into the DB watchlist and exit")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")
    # DB_PATH is set by docker-compose to the shared-volume path; the default
    # targets a local (non-Docker) checkout layout.
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

    env = load_env(args.env)
    resumes, profile = load_resumes(args.resume_dir)

    def once():
        run_once(cfg, db_path=args.db, resumes=resumes, profile=profile,
                 env=env, ollama_model=args.model,
                 score_backend=args.score_backend,
                 codex_score_model=args.codex_score_model,
                 anthropic_score_model=args.anthropic_score_model)

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
