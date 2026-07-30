"""TDD for pipeline.run_feed — the feed discovery stage.

Exercises the whole chain with fakes (no network): prefilter -> resolve ->
record-unresolved, then board-fetch keeping ONLY the surfaced ids, with the
skip-already-ingested optimisation and per-board failure isolation.
"""
from __future__ import annotations

import json

import pytest

from ats_worker import db, pipeline
from tests._helpers import NOW, FIXTURES, make_posting as _posting

# Boards the fake adapter "serves": each returns the surfaced id + an extra one
# the feed did NOT surface, to prove we keep only what the feed asked for.
BOARD = {
    ("ashby", "acme"): ["aaaa-1111", "ashby-extra"],
    ("lever", "foobar"): ["bbbb-2222", "lever-extra"],
    ("greenhouse", "acmegh"): ["3333", "9999"],
    ("smartrecruiters", "Acme"): ["12345", "sr-extra"],
}


def _listings():
    return json.loads((FIXTURES / "simplify_listings.json").read_text())


def _make_fetch_fn(calls, raise_for=None):
    def fetch_fn(source, slug, name):
        calls.append((source, slug, name))
        if raise_for and source == raise_for:
            raise RuntimeError("board down")
        return [_posting(i, source=source) for i in BOARD.get((source, slug), [])]
    return fetch_fn


def _detail_serves(source, slug, external_id, name):
    """Fake per-listing fetch: every surfaced id resolves to a valid posting.
    SmartRecruiters AND Workday are feed DETAIL sources now (fetch only the surfaced
    ids, not the whole board), so the board tests route them through here."""
    return _posting(external_id, source=source)


def test_run_feed_keeps_only_surfaced_ids_and_records_unresolved(db_path):
    conn = db.connect(db_path)
    calls: list = []
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=_listings, keep_categories=["Software", "AI/ML/Data", "Quant"],
        fetch_fn=_make_fetch_fn(calls), detail_fetch_fn=_detail_serves,
    )

    # 5 resolvable survivors ingested (ashby, lever, greenhouse, smartrecruiters,
    # workday); each board's extra/decoy postings are NOT kept.
    assert inserted == 5
    rows = db.get_by_status(conn, "new")
    got = {(r["source"], r["external_id"]) for r in rows}
    assert got == {
        ("ashby", "aaaa-1111"), ("lever", "bbbb-2222"), ("greenhouse", "3333"),
        # smartrecruiters + workday are fetched per-id (detail route); the fake echoes
        # the surfaced id — workday surfaces the job's externalPath.
        ("smartrecruiters", "12345"),
        ("workday", "/job/Boston/Engineer_R123"),
    }

    # only the embedded-greenhouse survivor stays unresolved now (workday +
    # smartrecruiters resolve); it's recorded, never dropped.
    unresolved = conn.execute("SELECT reason FROM feed_unresolved").fetchall()
    assert {r["reason"] for r in unresolved} == {"embedded_greenhouse"}
    # inactive / Hardware / explicit-no-sponsorship listings never reach here.
    assert conn.execute("SELECT COUNT(*) FROM feed_unresolved").fetchone()[0] == 1


def test_run_feed_workday_fetches_by_external_path_not_whole_board(db_path):
    # Workday is a feed DETAIL source: the feed surfaces the job's externalPath and
    # fetch_one pulls ONLY that job (never the whole N+1 board). The adapter emits the
    # GUID as external_id, so it dedups with the watchlist.
    conn = db.connect(db_path)
    calls: list = []

    def detail(source, slug, external_id, name):
        if source == "workday":
            calls.append((slug, external_id))
            # mimic the adapter: in == externalPath, out external_id == the GUID
            return _posting("GUID-123", source="workday",
                            job_url=f"https://acme.wd5.myworkdayjobs.com/External{external_id}")
        return _posting(external_id, source=source)

    pipeline.run_feed(
        conn, now=NOW, feed_fn=_listings, keep_categories=["Software", "AI/ML/Data", "Quant"],
        fetch_fn=_make_fetch_fn([]), detail_fetch_fn=detail,
    )
    # exactly one workday fetch, by the surfaced externalPath
    assert calls == [("acme/wd5/External", "/job/Boston/Engineer_R123")]
    wd = conn.execute(
        "SELECT external_id FROM job_postings WHERE source='workday'").fetchall()
    assert len(wd) == 1 and wd[0]["external_id"] == "GUID-123"  # the GUID, not the path


def test_run_feed_persists_company_slug(db_path):
    # The resolved group slug is stamped onto each ingested posting before upsert.
    conn = db.connect(db_path)
    pipeline.run_feed(
        conn, now=NOW, feed_fn=_listings,
        keep_categories=["Software", "AI/ML/Data", "Quant"], fetch_fn=_make_fetch_fn([]),
        detail_fetch_fn=_detail_serves,
    )
    slugs = dict(conn.execute(
        "SELECT source, company_slug FROM job_postings"
    ).fetchall())
    assert slugs["ashby"] == "acme"
    assert slugs["lever"] == "foobar"
    assert slugs["greenhouse"] == "acmegh"
    assert slugs["smartrecruiters"] == "Acme"
    assert slugs["workday"] == "acme/wd5/External"  # the resolved tenant/dc/site
    # every ingested row carries a non-null slug
    assert all(v is not None for v in slugs.values())


def test_run_feed_skips_boards_whose_surfaced_ids_already_exist(db_path):
    conn = db.connect(db_path)
    # Pre-ingest the only ashby id the feed surfaces.
    db.upsert_postings(conn, [_posting("aaaa-1111", source="ashby")], now=NOW)

    calls: list = []
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=_listings, keep_categories=["Software", "AI/ML/Data", "Quant"],
        fetch_fn=_make_fetch_fn(calls), detail_fetch_fn=_detail_serves,
    )

    fetched_sources = {c[0] for c in calls}
    assert "ashby" not in fetched_sources           # fully satisfied -> board skipped
    # smartrecruiters + workday are now feed DETAIL sources (per-id), not board fetches.
    assert {"lever", "greenhouse"} <= fetched_sources
    assert not ({"smartrecruiters", "workday"} & fetched_sources)
    assert inserted == 4    # lever + greenhouse + smartrecruiters(detail) + workday(detail)


def test_run_feed_isolates_a_failing_board(db_path):
    conn = db.connect(db_path)
    calls: list = []
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=_listings, keep_categories=["Software", "AI/ML/Data", "Quant"],
        fetch_fn=_make_fetch_fn(calls, raise_for="greenhouse"), detail_fetch_fn=_detail_serves,
    )
    # greenhouse aborts; ashby + lever + smartrecruiters + workday still ingest.
    assert inserted == 4
    rows = db.get_by_status(conn, "new")
    assert {r["source"] for r in rows} == {"ashby", "lever", "smartrecruiters", "workday"}

    # greenhouse's list fetch RAISED: its surfaced id is recorded, not dropped.
    n = conn.execute(
        "SELECT COUNT(*) FROM feed_unresolved WHERE reason='list_fetch_failed'"
    ).fetchone()[0]
    assert n == 1


def test_run_feed_record_unresolved_upserts_on_repeat(db_path):
    conn = db.connect(db_path)
    calls: list = []
    for _ in range(2):
        pipeline.run_feed(
            conn, now=NOW, feed_fn=_listings,
            keep_categories=["Software", "AI/ML/Data", "Quant"],
            fetch_fn=_make_fetch_fn(calls), detail_fetch_fn=_detail_serves,
        )
    # url is the upsert key -> still exactly 1 row after two passes (only the
    # embedded-greenhouse listing stays unresolved now).
    assert conn.execute("SELECT COUNT(*) FROM feed_unresolved").fetchone()[0] == 1


def test_run_feed_clears_stale_unresolved_row_on_successful_reingest(db_path):
    # A prior pass failed to resolve/fetch this URL and left a feed_unresolved
    # row for it. THIS pass resolves + fetches it successfully — the stale row
    # must be cleared, not left to permanently pollute the Unresolved tab.
    conn = db.connect(db_path)
    url = "https://jobs.ashbyhq.com/acme/aaaa-1111"
    db.record_unresolved(conn, feed="simplify", url=url, company_name="Acme",
                         job_title="Software Engineer", host="jobs.ashbyhq.com",
                         reason="list_fetch_failed", now=NOW)
    assert conn.execute("SELECT COUNT(*) FROM feed_unresolved").fetchone()[0] == 1

    listings = [{
        "url": url, "company_name": "Acme", "title": "Software Engineer",
        "category": "Software", "sponsorship": "Other", "active": True,
    }]
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=["Software"],
        fetch_fn=_make_fetch_fn([]), detail_fetch_fn=_detail_serves,
    )
    assert inserted == 1
    assert {(r["source"], r["external_id"]) for r in db.get_by_status(conn, "new")} == {
        ("ashby", "aaaa-1111")}
    assert conn.execute("SELECT COUNT(*) FROM feed_unresolved").fetchone()[0] == 0


def test_run_feed_detail_source_fetches_each_surfaced_id(db_path):
    # Oracle is a detail-fetch source (no board-list endpoint): run_feed must call
    # detail_fetch_fn per surfaced id and stamp the resolved slug, no keep-filter.
    conn = db.connect(db_path)
    listings = [{
        "url": ("https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/"
                "en/sites/CX_1001/job/210706680"),
        "company_name": "JPMC", "title": "Quant Researcher",
        "category": "Quant", "sponsorship": "Other", "active": True,
    }]
    calls: list = []

    def detail_fetch_fn(source, slug, external_id, name):
        calls.append((source, slug, external_id, name))
        return _posting(external_id, source=source, job_url=f"https://x/{external_id}")

    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=["Quant"],
        fetch_fn=_make_fetch_fn([]), detail_fetch_fn=detail_fetch_fn,
    )
    assert inserted == 1
    assert calls == [("oracle", "jpmc.fa.oraclecloud.com/CX_1001", "210706680", "JPMC")]
    row = db.get_by_status(conn, "new")[0]
    assert (row["source"], row["external_id"]) == ("oracle", "210706680")
    assert row["company_slug"] == "jpmc.fa.oraclecloud.com/CX_1001"


def test_run_feed_detail_isolates_a_bad_listing(db_path):
    conn = db.connect(db_path)
    listings = [
        {"url": f"https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/{i}",
         "company_name": "JPMC", "title": "Quant", "category": "Quant",
         "sponsorship": "Other", "active": True}
        for i in ("good", "bad")
    ]

    def detail_fetch_fn(source, slug, external_id, name):
        if external_id == "bad":
            raise RuntimeError("listing down")
        return _posting(external_id, source=source)

    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=["Quant"],
        fetch_fn=_make_fetch_fn([]), detail_fetch_fn=detail_fetch_fn,
    )
    assert inserted == 1
    assert {r["external_id"] for r in db.get_by_status(conn, "new")} == {"good"}
    # the bad listing is recorded on the unresolved board, not silently dropped.
    rows = conn.execute("SELECT host, reason FROM feed_unresolved").fetchall()
    assert [(r["host"], r["reason"]) for r in rows] == [
        ("jpmc.fa.oraclecloud.com", "detail_fetch_failed")]


def test_run_feed_detail_skips_none_result(db_path):
    conn = db.connect(db_path)
    listings = [{
        "url": "https://jobs.jobvite.com/acme/job/xyz", "company_name": "Acme",
        "title": "SWE", "category": "Software", "sponsorship": "Other", "active": True,
    }]
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=["Software"],
        fetch_fn=_make_fetch_fn([]), detail_fetch_fn=lambda *a: None,
    )
    assert inserted == 0
    assert db.get_by_status(conn, "new") == []
    # a None result is a failure now — recorded on the board, not vanished.
    rows = conn.execute("SELECT host, reason FROM feed_unresolved").fetchall()
    assert [(r["host"], r["reason"]) for r in rows] == [
        ("jobs.jobvite.com", "detail_fetch_failed")]


def test_run_feed_detail_records_invalid_posting(db_path):
    # A scraper that returns a posting with NO description silently lost the JD; it must
    # be rejected (not inserted) and recorded as `empty_description` — NOT
    # `detail_fetch_failed`. The two diagnoses are opposite: a raise/None is usually a
    # dead req (the feed surfaces an externalPath the board no longer serves — normal),
    # while a body that came back and does not parse is a broken scraper. Filing both
    # under one string is why the "may be broken" warning could not say which, six times
    # a day. `empty_description` is the same string the watchlist path uses for the same
    # condition, so ONE query over feed_unresolved covers both paths.
    conn = db.connect(db_path)
    listings = [{
        "url": "https://jobs.jobvite.com/acme/job/xyz", "company_name": "Acme",
        "title": "SWE", "category": "Software", "sponsorship": "Other", "active": True,
    }]
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=["Software"],
        fetch_fn=_make_fetch_fn([]),
        detail_fetch_fn=lambda s, sl, ext, n: _posting(ext, source=s, description=""),
    )
    assert inserted == 0
    assert db.get_by_status(conn, "new") == []
    assert conn.execute(
        "SELECT reason FROM feed_unresolved").fetchone()["reason"] == "empty_description"


def test_the_collapse_warning_names_which_failure_it_saw(db_path, capsys):
    # The warning repeats every pass forever (workday's existing_external_ids prune
    # never matches the feed's externalPath), so it has to be self-diagnosing or it gets
    # tuned out. Two collapses, same count, opposite meanings.
    listing = {"url": "https://jobs.jobvite.com/acme/job/xyz", "company_name": "Acme",
               "title": "SWE", "category": "Software", "sponsorship": "Other",
               "active": True}

    def collapse(detail_fetch_fn):
        conn = db.connect(db_path)
        pipeline.run_feed(conn, now=NOW, feed_fn=lambda: [listing],
                          keep_categories=["Software"], fetch_fn=_make_fetch_fn([]),
                          detail_fetch_fn=detail_fetch_fn)
        return capsys.readouterr().out

    dead = collapse(lambda *a: None)
    assert "dead req" in dead and "unparseable" not in dead.split("dead req")[0]
    broken = collapse(
        lambda s, sl, ext, n: _posting(ext, source=s, description=""))
    assert "1 unparseable" in broken and "scraper may be broken" in broken


def test_run_feed_detail_collapse_warns(db_path, capsys):
    # Every surfaced id fails -> a collapse line is printed (the live "scraper
    # broke" signal), distinct from a board that genuinely had 0 new jobs.
    conn = db.connect(db_path)
    listings = [
        {"url": f"https://jobs.jobvite.com/acme/job/{i}", "company_name": "Acme",
         "title": "SWE", "category": "Software", "sponsorship": "Other", "active": True}
        for i in ("a", "b")
    ]
    pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=["Software"],
        fetch_fn=_make_fetch_fn([]), detail_fetch_fn=lambda *a: None,
    )
    out = capsys.readouterr().out
    assert "detail-fetch collapse" in out and "jobvite" in out


def test_valid_posting_requires_id_title_description():
    good = _posting("1")
    assert pipeline._valid_posting(good)
    for blank in ("external_id", "job_title", "description"):
        assert not pipeline._valid_posting({**good, blank: ""})
        assert not pipeline._valid_posting({**good, blank: None})


def test_run_feed_embedded_greenhouse_fallback_resolves(db_path):
    # An embedded-greenhouse listing can't resolve purely; the injected I/O resolver
    # recovers the board token, and it ingests via the normal greenhouse list path.
    conn = db.connect(db_path)
    listings = [{
        "url": "https://steelpoint-llc.com/careers/?gh_jid=7453484003",
        "company_name": "Steel Point", "title": "Software Engineer",
        "category": "Software", "sponsorship": "Other", "active": True,
    }]

    def fetch_fn(source, slug, name):
        assert (source, slug) == ("greenhouse", "steelpointsolutions")
        return [_posting("7453484003", source="greenhouse"),
                _posting("decoy", source="greenhouse")]  # decoy is dropped

    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=["Software"],
        fetch_fn=fetch_fn,
        resolve_embedded_fn=lambda url: ("greenhouse", "steelpointsolutions", "7453484003"),
    )
    assert inserted == 1
    assert {(r["source"], r["external_id"]) for r in db.get_by_status(conn, "new")} == {
        ("greenhouse", "7453484003")}
    # resolved -> nothing left on the unresolved board
    assert conn.execute("SELECT COUNT(*) FROM feed_unresolved").fetchone()[0] == 0


def test_run_feed_embedded_greenhouse_none_stays_unresolved(db_path):
    # The resolver returns None (token JS-injected) -> recorded as embedded_greenhouse.
    conn = db.connect(db_path)
    listings = [{
        "url": "https://nuro.ai/careersitem?gh_jid=7351066", "company_name": "Nuro",
        "title": "SWE", "category": "Software", "sponsorship": "Other", "active": True,
    }]
    pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=["Software"],
        fetch_fn=_make_fetch_fn([]), resolve_embedded_fn=lambda url: None,
    )
    assert conn.execute(
        "SELECT reason FROM feed_unresolved").fetchone()["reason"] == "embedded_greenhouse"


def test_run_feed_embedded_greenhouse_resolver_error_is_isolated(db_path):
    # A failing company-page fetch never aborts the feed; the listing just stays
    # unresolved (recorded as embedded_greenhouse), like any unresolvable URL.
    conn = db.connect(db_path)
    listings = [{
        "url": "https://x.com/careers?gh_jid=999", "company_name": "X", "title": "SWE",
        "category": "Software", "sponsorship": "Other", "active": True,
    }]

    def boom(url):
        raise RuntimeError("company page down")

    pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=["Software"],
        fetch_fn=_make_fetch_fn([]), resolve_embedded_fn=boom,
    )
    assert conn.execute(
        "SELECT reason FROM feed_unresolved").fetchone()["reason"] == "embedded_greenhouse"


def test_run_feed_skips_listing_without_url(db_path):
    conn = db.connect(db_path)
    pipeline.run_feed(
        conn, now=NOW,
        feed_fn=lambda: [{"category": "Software", "active": True, "sponsorship": "Other"}],
        keep_categories=["Software"], fetch_fn=_make_fetch_fn([]),
    )
    assert conn.execute("SELECT COUNT(*) FROM feed_unresolved").fetchone()[0] == 0
    assert db.get_by_status(conn, "new") == []


# --- the operator's coarse filters, applied at the feed --------------------
#
# run_fetch has always run title_filter / title_exclude / max_age_days over what it
# fetches; run_feed did not, so none of the three applied to a feed-discovered
# posting. These pin the shared rule AND the two silent-failure modes of the key
# translation the feed needs (title vs job_title, epoch vs ISO date).

def _listing(title, *, date_posted=None,
             url="https://jobs.ashbyhq.com/acme/aaaa-1111"):
    return {"url": url, "company_name": "Acme", "title": title,
            "category": "Software", "sponsorship": "Other", "active": True,
            "date_posted": date_posted}


# NOW is 2026-06-04, so 1780272000 is 3 days old and 1767225600 is ~155 days old.
RECENT_EPOCH = 1780272000
STALE_EPOCH = 1767225600


def test_run_feed_drops_a_title_excluded_listing_before_it_costs_anything(db_path):
    # The cost claim: a refused listing must be dropped BEFORE the resolve, because
    # past that line it also buys a board detail fetch and a screen call, every pass.
    conn = db.connect(db_path)
    resolves: list = []

    def resolve_fn(url):
        resolves.append(url)
        return ("ashby", "acme", "aaaa-1111")

    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: [_listing("Staff Software Engineer")],
        keep_categories=["Software"], fetch_fn=_make_fetch_fn([]),
        resolve_fn=resolve_fn, title_exclude=["staff"],
    )
    assert inserted == 0
    assert resolves == []
    # Not an unresolved-backlog item: the operator's own config refused it.
    assert conn.execute("SELECT COUNT(*) FROM feed_unresolved").fetchone()[0] == 0


def test_run_feed_age_gates_on_the_feeds_epoch_date(db_path):
    # The feed publishes date_posted as a Unix epoch int; _too_old parses an ISO
    # date. Hand the raw int through and it is unparseable -> kept -> max_age_days
    # silently never fires, which is the LARGER half of what these filters catch.
    conn = db.connect(db_path)
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: [_listing("Software Engineer",
                                                 date_posted=STALE_EPOCH)],
        keep_categories=["Software"], fetch_fn=_make_fetch_fn([]),
        detail_fetch_fn=_detail_serves, max_age_days=30,
    )
    assert inserted == 0
    assert db.get_by_status(conn, "new") == []


def test_run_feed_keeps_a_listing_inside_the_age_window(db_path):
    conn = db.connect(db_path)
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: [_listing("Software Engineer",
                                                 date_posted=RECENT_EPOCH)],
        keep_categories=["Software"], fetch_fn=_make_fetch_fn([]),
        detail_fetch_fn=_detail_serves, max_age_days=30,
    )
    assert inserted == 1


def test_run_feed_re_gates_on_the_boards_date_not_the_feeds(db_path):
    # The feed says fresh; the board's own posted_at is 13 months old (evergreen
    # greenhouse reqs Simplify re-lists). The stored date is the board's, so it is
    # the one that must be judged — else the gate passes and the DB holds a row
    # older than max_age_days, which the watchlist path never does.
    conn = db.connect(db_path)
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: [_listing("Software Engineer",
                                                 date_posted=RECENT_EPOCH)],
        keep_categories=["Software"], max_age_days=30,
        fetch_fn=lambda s, sl, n: [_posting("aaaa-1111", source=s,
                                            posted_at="2025-06-16")],
    )
    assert inserted == 0
    assert db.get_by_status(conn, "new") == []


@pytest.mark.parametrize("bad", [None, "", "not-a-date", [], {}, "2026-06-01"])
def test_run_feed_keeps_a_listing_with_no_readable_date(db_path, bad):
    # Err toward keep, the same policy the board path applies to a dateless posting.
    # Parametrized rather than looped over one connection: a loop reusing the same url
    # makes every iteration after the first a no-op upsert, so the assertion would pass
    # on iteration 1 alone and the other cases would measure nothing.
    # "2026-06-01" is an ISO date, NOT the epoch int the feed actually sends — int()
    # rejects it, so it must land here (kept) rather than be silently half-parsed.
    conn = db.connect(db_path)
    inserted = pipeline.run_feed(
        conn, now=NOW, keep_categories=["Software"], fetch_fn=_make_fetch_fn([]),
        detail_fetch_fn=_detail_serves, max_age_days=30,
        feed_fn=lambda: [_listing("Software Engineer", date_posted=bad)],
    )
    assert inserted == 1
    assert len(db.get_by_status(conn, "new")) == 1


def test_run_feed_reads_the_feeds_title_key_not_job_title(db_path):
    # The feed keys the title as `title`; prefilter_postings reads `job_title`. Skip
    # the translation and a non-empty title_filter matches NOTHING — the feed goes
    # silently to zero rows rather than erroring.
    conn = db.connect(db_path)
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: [_listing("Software Engineer")],
        keep_categories=["Software"], fetch_fn=_make_fetch_fn([]),
        detail_fetch_fn=_detail_serves, title_filter=["engineer"],
    )
    assert inserted == 1


def test_run_feed_title_filter_still_refuses_an_off_target_role(db_path):
    conn = db.connect(db_path)
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: [_listing("Recruiting Coordinator")],
        keep_categories=["Software"], fetch_fn=_make_fetch_fn([]),
        detail_fetch_fn=_detail_serves, title_filter=["engineer"],
    )
    assert inserted == 0
