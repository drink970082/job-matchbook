"""TDD for Telegram notification. Injected http; no real network."""
from __future__ import annotations

import json

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


def _sent_text(http):
    payload = http.calls[0][1].get("data") or http.calls[0][1].get("json")
    return payload["text"]


def test_message_includes_recommended_resume_line():
    http = FakeHttp()
    posting = dict(POSTING, score_detail=json.dumps(
        {"matched_keywords": [], "recommended_resume": "quant_dev"}))
    notify.notify_posting(posting, token=TOKEN, chat_id=CHAT, http=http)
    text = _sent_text(http)
    assert "Resume: quant_dev" in text
    # the line sits above the URL so the link stays last (Telegram previews it)
    assert text.index("Resume: quant_dev") < text.index("https://example.com/jobs/1")


def test_message_omits_resume_line_when_absent_or_malformed():
    for detail in (None, "", "not json", json.dumps({"reasoning": "x"}),
                   json.dumps(["a", "list"]), 123,):
        http = FakeHttp()
        posting = dict(POSTING, score_detail=detail)
        notify.notify_posting(posting, token=TOKEN, chat_id=CHAT, http=http)
        assert "Resume:" not in _sent_text(http)


def test_message_carries_the_persisted_fit_summary():
    http = FakeHttp()
    posting = dict(POSTING, score_detail=json.dumps(
        {"assessment": {"summary": "Strong  systems\nmatch, light on kdb."}}))
    notify.notify_posting(posting, token=TOKEN, chat_id=CHAT, http=http)
    text = _sent_text(http)
    # whitespace collapsed so a multi-line summary stays one line in the alert
    assert "Fit: Strong systems match, light on kdb." in text
    assert text.index("Fit:") < text.index("https://example.com/jobs/1")


def test_a_long_summary_is_truncated_rather_than_bursting_the_message_limit():
    http = FakeHttp()
    posting = dict(POSTING, score_detail=json.dumps(
        {"assessment": {"summary": "x" * 5000}}))
    notify.notify_posting(posting, token=TOKEN, chat_id=CHAT, http=http)
    text = _sent_text(http)
    assert len(text) < 4096          # Telegram's sendMessage cap
    assert "Fit: " + "x" * (notify._SUMMARY_MAX - 3) + "..." in text


def test_message_omits_fit_line_when_absent_or_malformed():
    for detail in (None, "", "not json", json.dumps({"assessment": "not a dict"}),
                   json.dumps({"assessment": {"summary": ""}}),
                   json.dumps({"assessment": {}}), json.dumps(["a", "list"]), 123,):
        http = FakeHttp()
        posting = dict(POSTING, score_detail=detail)
        notify.notify_posting(posting, token=TOKEN, chat_id=CHAT, http=http)
        assert "Fit:" not in _sent_text(http)
