"""Push a job-match alert to Telegram.

WHY Telegram: it gives a free, instant push to the user's phone — the
human-in-the-loop step. The message carries just enough to decide whether to
apply (company / title / score / link); the user applies by hand.

`http` is injected (defaults to `requests`) so tests assert the exact endpoint
and payload without hitting the network.
"""
from __future__ import annotations

import json

import requests

_API = "https://api.telegram.org/bot{token}/{method}"


# The fit summary is model prose. It is already persisted and already sanitised, and
# notify.py must never call a model — but a paragraph would still push the message past
# Telegram's 4096-char limit and turn a match into a raise against the retry budget.
_SUMMARY_MAX = 300


def _detail(posting: dict) -> dict:
    """The row's score_detail JSON as a dict, or {}.

    Defensive by design: score_detail is a DB string column that may be NULL,
    empty, malformed, or predate any given feature — every bad shape means 'no line',
    never a crash that would count against the notify retry budget.
    """
    raw = posting.get("score_detail")
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        detail = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return detail if isinstance(detail, dict) else {}


def _recommended_resume(posting: dict) -> str:
    """The recommended resume label from the row's score_detail JSON, or ''."""
    return str(_detail(posting).get("recommended_resume") or "").strip()


def _fit_summary(posting: dict) -> str:
    """The scorer's one-line bottom-line fit, or ''. This is the part of the scorecard
    with decision value — the routing turns on the verdicts, and the summary is what
    says why — so it rides the alert next to the raw score."""
    assessment = _detail(posting).get("assessment")
    if not isinstance(assessment, dict):
        return ""
    summary = " ".join(str(assessment.get("summary") or "").split())
    return summary[:_SUMMARY_MAX - 3] + "..." if len(summary) > _SUMMARY_MAX else summary


def notify_posting(
    posting: dict,
    *,
    token: str,
    chat_id: str,
    http=requests,
    timeout: int = 30,
) -> None:
    """Send a one-message match alert (company / role / score / link).

    A single atomic sendMessage: it either succeeds or raises having sent
    nothing, so the caller's failure handling can't leave a half-sent alert.
    """
    recommended = _recommended_resume(posting)
    summary = _fit_summary(posting)
    text = (
        f"New match: {posting.get('company_name', '')}\n"
        f"Role: {posting.get('job_title', '')}\n"
        f"Score: {posting.get('score', '')}\n"
        + (f"Fit: {summary}\n" if summary else "")
        + (f"Resume: {recommended}\n" if recommended else "")
        + f"{posting.get('job_url', '')}"
    )
    resp = http.post(
        _API.format(token=token, method="sendMessage"),
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
        timeout=timeout,
    )
    resp.raise_for_status()
