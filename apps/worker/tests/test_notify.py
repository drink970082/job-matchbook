"""TDD for Telegram notification. Injected http; no real network."""
from __future__ import annotations

from ats_worker import notify


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"ok": True}


class FakeHttp:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


POSTING = {
    "company_name": "Acme Inc",
    "job_title": "Senior Python Engineer",
    "score": 88,
    "job_url": "https://example.com/jobs/1",
}
TOKEN = "12345:ABC"
CHAT = "999"


def test_sends_message_with_summary_fields():
    http = FakeHttp()
    notify.notify_posting(POSTING, token=TOKEN, chat_id=CHAT, http=http)

    assert len(http.calls) == 1          # message only — no document
    msg_url, msg_kw = http.calls[0]
    assert msg_url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = msg_kw.get("data") or msg_kw.get("json")
    assert str(payload["chat_id"]) == CHAT
    text = payload["text"]
    assert "Acme Inc" in text
    assert "Senior Python Engineer" in text
    assert "88" in text
    assert "https://example.com/jobs/1" in text
