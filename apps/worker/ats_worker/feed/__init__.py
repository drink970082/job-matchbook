"""Discovery feeds: ingest a broad listing stream, resolve each to a board.

A *feed* is a transport, never a `job_postings.source` — it surfaces (company,
apply-URL) pairs which `resolve` maps back to the underlying board so dedup on
(source, external_id) holds across the feed and the watchlist. Pipeline glue
lives in pipeline.run_feed; this package is the pure parts:

  - simplify  — fetch the raw listings.json
  - prefilter — cheap metadata gate (active / category / sponsorship)
  - resolve   — URL -> (source, slug, external_id) | None  (+ classify_reason)
"""
from __future__ import annotations

from . import prefilter, resolve, simplify

__all__ = ["simplify", "prefilter", "resolve"]
