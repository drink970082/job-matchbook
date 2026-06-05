"""Push a tailored-job alert to Telegram.

WHY Telegram: it gives a free, instant push to the user's phone with a file
attachment (the tailored PDF) — the human-in-the-loop step. The message carries
just enough to decide whether to apply (company / title / score / link); the PDF
follows as a document so it can be downloaded and reviewed.

`http` is injected (defaults to `requests`) so tests assert the exact endpoints
and payloads without hitting the network.
"""
from __future__ import annotations

import os

import requests

_API = "https://api.telegram.org/bot{token}/{method}"


def notify_posting(
    posting: dict,
    pdf_path: str | None,
    *,
    token: str,
    chat_id: str,
    http=requests,
    timeout: int = 30,
) -> None:
    """Send a summary message, then (if a readable PDF exists) the resume PDF.

    If no PDF was produced (tailoring never converged) OR the file is missing,
    only the message is sent — the user is still alerted, and we never raise
    after the message went out (which would mark the row failed spuriously).
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

    if not pdf_path or not os.path.isfile(pdf_path):
        return

    with open(pdf_path, "rb") as fh:
        doc_resp = http.post(
            _API.format(token=token, method="sendDocument"),
            data={"chat_id": chat_id},
            files={"document": fh},
            timeout=timeout,
        )
    doc_resp.raise_for_status()
