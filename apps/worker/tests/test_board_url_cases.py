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
    # The same URL as a link in a page, plain and JSON-escaped.
    for html in (f'<a href="{case["url"]}">Jobs</a>',
                 json.dumps({"u": case["url"]}).replace("/", "\\/"),
                 json.dumps({"u": case["url"]}).replace("/", "\\u002F")):
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


@pytest.mark.parametrize("page, want", [
    ("`https://jobs.lever.co/acme`", ["acme"]),
    ("<a href='https://acme.com/out?to=https://jobs.lever.co/acme'>", ["acme"]),
    ("<a href='https://acme.com/out?to=https%3A%2F%2Fjobs.lever.co%2Facme'>", ["acme"]),
    ("https://web.archive.org/web/2020/https://jobs.lever.co/acme", ["acme"]),
    ("https://jobs.lever.co/acme,https://jobs.lever.co/beta", ["acme", "beta"]),
    ("{u:https://jobs.lever.co/acme}", ["acme"]), ("https://jobs.lever.co/acme&x=1", ["acme"]),
    ("https://jobs.lever.co/acme!", ["acme"]), ("(https://jobs.lever.co/acme).", ["acme"]),
    ("<a href='https://boards.greenhouse.io/embed/job_board?x=1&amp;for=acme'>", ["acme"]),
    ("https:\\u002F\\u002Fcareers-acme.icims.com", ["careers-acme"]),
    ("https%3a%2f%2fcareers-acme.icims.com", ["careers-acme"]),
    ("https%253A%252F%252Fcareers-acme.icims.com", ["careers-acme"]), ("u=%2F%2Fcareers-acme.icims.com", ["careers-acme"]),
    ("https:\\x2F\\x2Fcareers-acme.icims.com", ["careers-acme"]), ("\\u003ecareers-acme.icims.com", ["careers-acme"]),
    ("\\njobs.lever.co/acme", ["acme"]), ("see...careers-acme.icims.com.", ["careers-acme"]), ("\\tenant.icims.com", ["tenant"]),
    ("u=https%3A%2F%2Fjobs.lever.co/acme", ["acme"]), ("https://x.com/o?host=careers-acme.icims.com", ["careers-acme"]),
    ("u=https%3A%2F%2Fboards.greenhouse.io/embed/job_board?for=acme", ["acme"]), ("host%3Dcareers-acme.icims.com", ["careers-acme"]),
    ("https://jobs.lever.co/acme?u=https://jobs.ashbyhq.com/beta", ["acme", "beta"]),
    ("https://acme_co.wd5.myworkdayjobs.com/Ext", ["acme_co/wd5/Ext"]), ("careers-acme.icims.com.evil.com", []),
    ("https://jobs.lever.co/acme%2C", ["acme"]), ("https://jobs.lever.co/acme%2F", ["acme"]), ("job-boards.greenhouse.io/embed/job_board?for=acme%26b=1", ["acme"]),
    ("https://jobs.lever.co/acme%20", ["acme"]), ("https://jobs.lever.co/acme%22", ["acme"]), ("https://jobs.lever.co/acme%3Fx=1", ["acme"]),
    ("https://jobs.ashbyhq.com/Acme%20Corp", ["Acme Corp"]),
    ("https://boards.greenhouse.io/embed/job_board?b=https%3A%2F%2Facme.com%2Fcareers&for=acme", ["acme"]),
])
def test_the_probe_reads_a_url_out_of_the_text_around_it(page, want):
    assert [slug for _source, slug in probe.recognize_page(page)] == want


@pytest.mark.parametrize("host", ["localhost\\.x", "acme.localhost\\"])
def test_a_workday_host_label_must_be_a_host_label(host):
    assert resolve_board(f"https://{host}.myworkdayjobs.com/site") is None


@pytest.mark.parametrize("text, want", [
    ("https://Acme.WD5.myworkdayjobs.com", ["acme/wd5"]), ("https:\\x2F\\x2Facme.wd5.myworkdayjobs.com", ["acme/wd5"]),
    ("https%253A%252F%252Facme.wd5.myworkdayjobs.com", ["acme/wd5"]),
    ("acme.wd5.myworkdayjobs.com.evil.com acme.wd5.myworkdayjobs.community", []),
])
def test_the_workday_hint_reads_the_tenant_host(text, want):
    assert probe.workday_hosts(text) == want


def test_the_page_scan_is_linear():
    import time
    start = time.monotonic()
    for unit in ("a.", "-", "_", "a_", "a.co/b?c=", "%2F", "%25", "%2525", "25", "\\", "\\x2f", "x.y.myworkdayjobs.com/", "jobs.lever.co/"):
        probe.recognize_page(unit * (200_000 // len(unit)))
    assert time.monotonic() - start < 20    # seconds when linear; minutes when not


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
    ("https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Ext/jobs", "/wp-json/", set(), "platform=workday -> find the site for slug acme/wd5/{site}"),
    ("https://acme.com/careers", '<a href="https://acme.wd5.myworkdayjobs.com/en-US">', set(), "platform=workday -> find"),
    ("https://acme.wd5.myworkdayjobs.com/Ext", "", set(), "platform? -> the URL is workday slug=acme/wd5/Ext"),
    ("https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Ext/jobs", "https://zed.wd1.myworkdayjobs.com/X", set(), "platform=workday -> find the site for slug acme/wd5/{site}"),
    ("https://acme.com/careers", "https://jobs.lever.co/down /wp-json/", set(), "plain-http ->"),
    ("https://acme.com/careers", "https://jobs.lever.co/down", set(), "platform? -> the page embeds lever slug=down, but could not verify"),
    ("https://acme.com/careers", "https://acme.wd5.myworkdayjobs.com/favicon.ico", set(), "platform=workday -> find the site for slug acme/wd5/{site}"),
    ("https://www.google.com/url?q=https://jobs.lever.co/acme", "", {"acme"}, "platform=lever slug=acme ->"),
    ("https://acme.com/careers", "<p>", set(), "plain-http? ->"),
])
def test_the_probe_verdict(monkeypatch, capsys, url, page, listing, verdict):
    real = probe.verify
    monkeypatch.setattr(probe, "verify", lambda boards: real(boards, has_listings=lambda _s, slug, _n: 1 / 0 if slug == "down" else slug in listing))
    monkeypatch.setattr(probe, "get", lambda _url: SimpleNamespace(status_code=200, text=page))
    monkeypatch.setattr(probe.sys, "argv", ["probe.py", url])
    probe.main()
    assert f"VERDICT: {verdict}" in capsys.readouterr().out
