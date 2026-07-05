"""Entrypoint: wire real adapters and run the pipeline once or on a schedule.

WHY the env/adapter wiring lives only here: every other module is pure and
injected, so this is the single place that knows about secrets and external
services. `run_once` takes already-loaded config/secrets and the worker
callables it builds from them, calling the four pipeline stages in order.

APScheduler is imported lazily inside the cron path so the test environment —
which lacks apscheduler — can still import and exercise this module.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time

import requests

from . import config as config_mod
from . import db, pipeline
from .fetch import fetch_company, fetch_one_company
from .feed import embedded_gh, simplify
from .notify import notify_posting
from .score import make_claude_scorer, score_posting
from .tailor import make_claude, pypdf_count, tailor_resume, tectonic_compile

# qwen3.5:4b runs fully on an 8GB GPU (~3GB resident) and returns clean JSON in
# ~2s/posting with thinking disabled (see score.py). The 9b (6.6GB) spills to
# CPU on an 8GB card (~100s/call), so it's a poor fit here. Override per-deploy
# with --model or the OLLAMA_MODEL env var.
DEFAULT_OLLAMA_MODEL = "qwen3.5:4b"
# Sonnet 4.6 for tailoring: it only reorders/rephrases existing resume content
# (never fabricates), so the cheaper tier is plenty and far more cost-effective
# than Opus for a step that may run several rounds per high-scoring job.
# Override with --anthropic-model or the ANTHROPIC_MODEL env var.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
# Sonnet 5 scores fit (real seniority/domain judgment, unlike the local 4B model);
# Sonnet 4.6 doesn't support structured outputs (output_config.format), so it can't
# be used here. Override with --anthropic-score-model or ANTHROPIC_SCORE_MODEL.
DEFAULT_ANTHROPIC_SCORE_MODEL = "claude-sonnet-5"

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


def resume_out_dir(base: str, posting) -> str:
    """Per-posting output directory under the shared resume volume.

    Unique per (source, external_id) so concurrent tailors never clobber each
    other's resume.pdf, and rooted at `base` (the dir the Next.js app serves
    from via RESUME_DIR) so the stored resume_path is web-readable.
    """
    return os.path.join(base, f"{posting['source']}_{posting['external_id']}")


def run_once(cfg, *, db_path, resume_text, master_tex, env, resume_dir="../../resumes",
             ollama_model=DEFAULT_OLLAMA_MODEL,
             anthropic_model=DEFAULT_ANTHROPIC_MODEL,
             anthropic_score_model=DEFAULT_ANTHROPIC_SCORE_MODEL) -> None:
    """Run fetch -> score -> tailor -> notify exactly once.

    Tailored PDFs are written under `resume_dir` (a volume shared with the web
    app); the stored resume_path therefore resolves under the app's RESUME_DIR.
    """
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
                "years_experience": cfg.candidate.years_experience,
                "highest_degree": cfg.candidate.highest_degree,
                "work_authorization": cfg.candidate.work_authorization,
                "security_clearance": cfg.candidate.security_clearance,
                "locations": list(cfg.candidate.locations),
                "dealbreakers": list(cfg.candidate.dealbreakers),
                "exclude_internships": cfg.candidate.exclude_internships,
            }
        # num_ctx is set explicitly (Ollama's default is small enough to truncate
        # long JDs); override per-deploy via OLLAMA_NUM_CTX without code changes.
        num_ctx = int(env.get("OLLAMA_NUM_CTX", "8192"))

        # Build the Claude scorer lazily on first use (make_claude_scorer is
        # import-safe: the SDK import is deferred to the scorer's first call, so
        # this closure is cheap and the hermetic tests never touch anthropic).
        _scorer_cell: list = []

        def score_fn(posting):
            if not _scorer_cell:
                _scorer_cell.append(
                    make_claude_scorer(env["ANTHROPIC_API_KEY"], anthropic_score_model)
                )
            return score_posting(
                posting, resume_text,
                score_fit=_scorer_cell[0],
                model=ollama_model,          # Ollama model — SCREEN call only now
                ollama_host=env.get("OLLAMA_HOST", "http://localhost:11434"),
                candidate=candidate,
                num_ctx=num_ctx,
            )

        pipeline.run_score(conn, now=now, score_fn=score_fn)

        # Built lazily on first use so importing anthropic only happens when a
        # posting actually needs tailoring (keeps the smoke test SDK-free).
        _claude_cell: list = []

        def tailor_fn(posting):
            if not _claude_cell:
                _claude_cell.append(make_claude(env["ANTHROPIC_API_KEY"], anthropic_model))
            claude = _claude_cell[0]
            out_dir = resume_out_dir(resume_dir, posting)
            os.makedirs(out_dir, exist_ok=True)
            return tailor_resume(
                master_tex,
                f"{posting['job_title']} at {posting['company_name']}\n\n{posting['description']}",
                _missing_keywords(posting),
                claude=claude,
                compile_pdf=tectonic_compile,
                count_pages=pypdf_count,
                max_rounds=cfg.max_single_page_rounds,
                out_dir=out_dir,
            )

        pipeline.run_tailor(conn, cfg.threshold, now=now, tailor_fn=tailor_fn)

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
    return [{"source": c.source, "slug": c.slug, "name": c.name} for c in cfg.companies]


def _missing_keywords(posting) -> list[str]:
    raw = posting.get("score_detail")
    if not raw:
        return []
    try:
        return json.loads(raw).get("missing_keywords", [])
    except (ValueError, TypeError):
        return []


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise SystemExit(
            f"Could not read required resume file {path!r}: {exc}.\n"
            f"Provide your resume in apps/worker/resume/ (see resume/README.md)."
        ) from exc


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Job-hunt pipeline worker")
    parser.add_argument("--once", action="store_true", help="run a single pass and exit")
    parser.add_argument("--import-companies", action="store_true",
                        help="seed config.yaml companies into the DB watchlist and exit")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")
    # DB_PATH / RESUME_DIR are set by docker-compose to the shared-volume paths;
    # the defaults target a local (non-Docker) checkout layout.
    parser.add_argument("--db",
                        default=os.environ.get("DB_PATH", "../web/prisma/applications.db"))
    parser.add_argument("--resume-dir",
                        default=os.environ.get("RESUME_DIR", "../../resumes"))
    parser.add_argument("--resume", default="resume/resume.txt")
    parser.add_argument("--master-tex", default="resume/master.tex")
    parser.add_argument("--model",
                        default=os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
                        help="Ollama model tag used for scoring")
    parser.add_argument("--anthropic-model",
                        default=os.environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL),
                        help="Anthropic model used for resume tailoring")
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
    resume_text = _read_text(args.resume)
    master_tex = _read_text(args.master_tex)

    def once():
        run_once(cfg, db_path=args.db, resume_text=resume_text,
                 master_tex=master_tex, env=env, resume_dir=args.resume_dir,
                 ollama_model=args.model, anthropic_model=args.anthropic_model,
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
