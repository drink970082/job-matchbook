"""One URL -> board fixture, three resolvers: the web's lib/board-url.ts (jest), the
worker's feed/resolve.py, and onboard-board's probe.py, which calls the worker's (#237)."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ats_worker.feed.resolve import resolve_board, resolve_url

CASES = json.loads((Path(__file__).parent / "fixtures" / "board-url-cases.json").read_text())["cases"]
PROBE = Path(__file__).resolve().parents[3] / ".claude/skills/onboard-board/scripts/probe.py"

_spec = importlib.util.spec_from_file_location("probe", PROBE)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


def expected(case):
    return (case["source"], case["slug"]) if case["source"] else None


@pytest.mark.parametrize("case", [c for c in CASES if c.get("job")], ids=lambda c: c["url"])
def test_resolve_url_matches_the_shared_board_cases(case):
    got = resolve_url(case["url"])
    assert got is not None and got[:2] == (case["source"], case["slug"])


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["url"])
def test_resolve_board_matches_the_shared_board_cases(case):
    assert resolve_board(case["url"]) == expected(case)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["url"])
def test_the_probe_recognizes_a_url_exactly_as_the_resolver_does(case):
    want = expected(case)
    assert probe.recognize_url(case["url"]) == want
    # The same URL as a link in a page: every encoding a page carries it in.
    for html in (f'<a href="{case["url"]}">Jobs</a>',
                 json.dumps({"u": case["url"]}).replace("/", "\\/"),
                 f"<script src='{case['url'].replace('&', '&amp;')}'></script>"):
        assert probe.recognize_page(html) == ([want] if want else [])


@pytest.mark.parametrize("url", [
    "", None, "https://[bad", "https://www.icims.com/products", "https://a.b.icims.com/jobs",
    "https://jobs.jobvite.com/acme/job/o1", "https://jobs.lever.co/acme%0A", "ftp://jobs.lever.co/acme",
    "https://boards.greenhouse.io/embed/job_board", "https://evil.com/jobs.lever.co/acme",
])
def test_resolve_board_refuses(url):
    assert resolve_board(url) is None


def test_the_probe_finds_scheme_less_and_repeated_embeds_once_each_in_page_order():
    html = ("<script src='//boards.greenhouse.io/embed/job_board/js?for=acme'></script>"
            "<a href='https://jobs.lever.co/globex/1'></a><a href='https://jobs.lever.co/globex/2'></a>"
            "board: \"jobs.ashbyhq.com/initech\", (see jobs.lever.co/globex). <a href='https://careers-acme.icims.com'>")
    assert probe.recognize_page(html) == [("greenhouse", "acme"), ("lever", "globex"),
                                          ("ashby", "initech"), ("icims", "careers-acme")]


def test_the_probe_checks_at_most_five_embedded_boards():
    html = " ".join(f"https://jobs.lever.co/co{i}" for i in range(9))
    assert len(probe.recognize_page(html)) == 5


def test_the_probe_verifies_through_the_adapters_list_check():
    """Not its own endpoints: the candidate goes to the adapter as {source, slug}."""
    seen = []

    def listed(source, slug, name):
        seen.append((source, slug))
        if slug == "down":
            raise TimeoutError
        return slug != "empty"

    boards = [("lever", "acme"), ("lever", "empty"), ("workday", "t/wd1/site"), ("ashby", "down")]
    hits, misses = probe.verify(boards, has_listings=listed)
    assert seen == boards
    assert hits == [("lever", "acme"), ("workday", "t/wd1/site")]
    assert [(s, slug) for s, slug, _ in misses] == [("lever", "empty"), ("ashby", "down")]
    assert "lists no postings" in misses[0][2] and "timeout" in misses[1][2]


@pytest.mark.parametrize("url, page, listing, verdict", [
    ("https://jobs.lever.co/acme", "", {"acme"}, "platform=lever slug=acme ->"),
    ("jobs.lever.co/acme", "", {"acme"}, "platform=lever slug=acme ->"),                  # no scheme typed
    ("https://jobs.lever.co/acme", '<script id="__NEXT_DATA__">', set(), "platform? -> the URL is lever slug=acme, but board lists no"),
    ("https://acme.com/careers", '<a href="https://jobs.lever.co/acme/1">', {"acme"}, "platform=lever slug=acme ->"),
    ("https://acme.com/careers", '<a href="https://jobs.lever.co/acme/1"> /wp-json/', set(), "plain-http ->"),  # an embed that lists nothing
    ("https://acme.com/careers", 'fetch("/api/pcsx/search")', set(), "platform=phenom ->"),
    ("https://acme.com/careers", "<p>", set(), "plain-http? ->"),
])
def test_the_probe_verdict(monkeypatch, capsys, url, page, listing, verdict):
    real = probe.verify
    monkeypatch.setattr(probe, "verify", lambda boards: real(boards, has_listings=lambda _s, slug, _n: slug in listing))
    monkeypatch.setattr(probe, "get", lambda _url: SimpleNamespace(status_code=200, text=page))
    monkeypatch.setattr(probe.sys, "argv", ["probe.py", url])
    probe.main()
    assert f"VERDICT: {verdict}" in capsys.readouterr().out
