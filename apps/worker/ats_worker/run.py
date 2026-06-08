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
import os
import time

from . import config as config_mod
from . import db, pipeline
from .notify import notify_posting
from .score import score_posting
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
             anthropic_model=DEFAULT_ANTHROPIC_MODEL) -> None:
    """Run fetch -> score -> tailor -> notify exactly once.

    Tailored PDFs are written under `resume_dir` (a volume shared with the web
    app); the stored resume_path therefore resolves under the app's RESUME_DIR.
    """
    conn = db.connect(db_path)
    try:
        now = _now()
        companies = [
            {"source": c.source, "slug": c.slug, "name": c.name} for c in cfg.companies
        ]
        filters = {
            "keywords": cfg.filters.keywords,
            "locations": cfg.filters.locations,
        }

        pipeline.run_fetch(conn, companies, filters, now=now)

        candidate = {
            "profile": cfg.candidate.profile,
            "dealbreakers": list(cfg.candidate.dealbreakers),
        }

        def score_fn(posting):
            return score_posting(
                posting, resume_text,
                model=ollama_model,
                ollama_host=env.get("OLLAMA_HOST", "http://localhost:11434"),
                candidate=candidate,
            )

        pipeline.run_score(conn, resume_text, now=now, score_fn=score_fn)

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

        pipeline.run_tailor(conn, master_tex, cfg.threshold, now=now, tailor_fn=tailor_fn)

        pipeline.run_notify(
            conn,
            now=now,
            notify_fn=notify_posting,
            token=env["TELEGRAM_BOT_TOKEN"],
            chat_id=env["TELEGRAM_CHAT_ID"],
        )
    finally:
        conn.close()


def _missing_keywords(posting) -> list[str]:
    import json

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
    args = parser.parse_args(argv)

    cfg = config_mod.load_config(args.config)
    env = load_env(args.env)
    resume_text = _read_text(args.resume)
    master_tex = _read_text(args.master_tex)

    def once():
        run_once(cfg, db_path=args.db, resume_text=resume_text,
                 master_tex=master_tex, env=env, resume_dir=args.resume_dir,
                 ollama_model=args.model, anthropic_model=args.anthropic_model)

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
