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


def test_sends_message_and_document_when_pdf_given(tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    http = FakeHttp()
    notify.notify_posting(POSTING, str(pdf), token=TOKEN, chat_id=CHAT, http=http)

    assert len(http.calls) == 2
    msg_url, msg_kw = http.calls[0]
    assert msg_url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = msg_kw.get("data") or msg_kw.get("json")
    assert str(payload["chat_id"]) == CHAT
    text = payload["text"]
    assert "Acme Inc" in text
    assert "Senior Python Engineer" in text
    assert "88" in text
    assert "https://example.com/jobs/1" in text

    doc_url, doc_kw = http.calls[1]
    assert doc_url == f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    doc_payload = doc_kw.get("data")
    assert str(doc_payload["chat_id"]) == CHAT
    assert "files" in doc_kw  # the pdf is uploaded as a file


def test_only_message_when_no_pdf():
    http = FakeHttp()
    notify.notify_posting(POSTING, None, token=TOKEN, chat_id=CHAT, http=http)
    assert len(http.calls) == 1
    assert http.calls[0][0].endswith("/sendMessage")


def test_missing_pdf_file_still_sends_message_without_raising(tmp_path):
    # resume_path is set but the file is gone (cleanup / path mismatch). The
    # alert must still go out, and we must NOT raise (which would mark the row
    # failed AFTER the message was already sent).
    http = FakeHttp()
    notify.notify_posting(POSTING, str(tmp_path / "gone.pdf"),
                          token=TOKEN, chat_id=CHAT, http=http)
    assert len(http.calls) == 1
    assert http.calls[0][0].endswith("/sendMessage")
