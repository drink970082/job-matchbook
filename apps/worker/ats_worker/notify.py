"""Push a job-match alert to Telegram.

WHY Telegram: it gives a free, instant push to the user's phone — the
human-in-the-loop step. The message carries just enough to decide whether to
apply (company / title / score / link); the user applies by hand.

`http` is injected (defaults to `requests`) so tests assert the exact endpoint
and payload without hitting the network.
"""
from __future__ import annotations

import requests

_API = "https://api.telegram.org/bot{token}/{method}"


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
    text = (
        f"New match: {posting.get('company_name', '')}\n"
        f"Role: {posting.get('job_title', '')}\n"
        f"Score: {posting.get('score', '')}\n"
        f"{posting.get('job_url', '')}"
    )
    resp = http.post(
        _API.format(token=token, method="sendMessage"),
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
        timeout=timeout,
    )
    resp.raise_for_status()
