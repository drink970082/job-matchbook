"""Direct tests for html_to_text — the most-reused adapter helper.

Previously only exercised transitively through adapter fixtures, which left its
edge cases (nbsp, <br>/block-tag newlines, double-unescape, blank-collapse)
unguarded. The nbsp case also pins a real bug: an unescaped `&nbsp;` becomes
U+00A0, which the whitespace-collapse must fold to a normal space.
"""
from __future__ import annotations

import pytest

from ats_worker.util import (get_redirect_safe, html_to_text, is_safe_public_url,
                             join_present, to_iso_date)
from tests._helpers import FakeResponse, FakeSession


def test_to_iso_date_keeps_iso_date_prefix():
    assert to_iso_date("2026-04-17T05:58:03-04:00") == "2026-04-17"
    assert to_iso_date("2026-04-17") == "2026-04-17"


def test_to_iso_date_converts_epoch_millis():
    assert to_iso_date(1553186035299) == "2019-03-21"   # lever createdAt (ms, UTC)


def test_to_iso_date_none_or_garbage_is_none():
    assert to_iso_date(None) is None
    assert to_iso_date("") is None
    assert to_iso_date("bad") is None


def test_none_and_empty_become_empty_string():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""


@pytest.mark.parametrize("raw", ["x<br>y", "x<br/>y", "x<BR>y", "x<br />y"])
def test_br_becomes_newline_case_insensitive(raw):
    assert html_to_text(raw) == "x\ny"


def test_block_close_tags_become_newlines():
    assert html_to_text("<p>a</p><p>b</p>") == "a\nb"
    assert html_to_text("<li>one</li><li>two</li>") == "one\ntwo"


def test_tags_are_stripped():
    out = html_to_text("<div><strong>Hello</strong> world</div>")
    assert "<" not in out and ">" not in out
    assert "Hello world" in out


def test_double_escaped_entities_resolved():
    # Greenhouse double-escapes some content; two unescape passes resolve it.
    assert html_to_text("Python &amp;amp; Go") == "Python & Go"


def test_tag_only_input_is_empty():
    assert html_to_text("<div></div>") == ""


def test_blank_runs_collapse_to_one_blank_line():
    assert html_to_text("a\n\n\n\nb") == "a\n\nb"


def test_nbsp_is_collapsed_to_normal_space():
    # &nbsp; unescapes to U+00A0; it must not survive into the text.
    out = html_to_text("Senior&nbsp;Engineer")
    assert "\xa0" not in out
    assert out == "Senior Engineer"


def test_multiple_nbsp_collapse():
    assert html_to_text("a&nbsp;&nbsp;&nbsp;b") == "a b"


def test_is_safe_public_url_blocks_ssrf_targets():
    assert is_safe_public_url("https://boards.greenhouse.io/x") is True
    assert is_safe_public_url("http://169.254.169.254/latest/meta-data/") is False
    assert is_safe_public_url("http://127.0.0.1/") is False
    assert is_safe_public_url("http://localhost/") is False
    assert is_safe_public_url("http://[::1]/") is False
    assert is_safe_public_url("http://10.0.0.5/") is False
    assert is_safe_public_url("file:///etc/passwd") is False
    assert is_safe_public_url(None) is False


def test_is_safe_public_url_blocks_legacy_ipv4_and_dotless_bypasses():
    # inet_aton accepts these with NO DNS query, so ip_address() alone is
    # bypassable — the OS resolver still connects them straight to the numeric
    # address. All decode to a blocked (loopback/link-local) target.
    assert is_safe_public_url("http://2852039166/latest/meta-data/") is False  # decimal 169.254.169.254
    assert is_safe_public_url("http://2130706433:8931/x") is False  # decimal 127.0.0.1
    assert is_safe_public_url("http://0177.0.0.1/") is False  # octal 127.0.0.1
    assert is_safe_public_url("http://127.1/") is False  # short-form 127.0.0.1
    assert is_safe_public_url("http://localhost./") is False  # trailing-dot FQDN
    assert is_safe_public_url("http://[::1%25eth0]/") is False  # IPv6 zone-id (%-host)
    assert is_safe_public_url("https://boards.greenhouse.io/x") is True  # still allowed


# --- get_redirect_safe: per-hop redirect re-validation --------------------

def test_get_redirect_safe_follows_a_legit_redirect_to_a_public_target():
    redirect = FakeResponse(status_code=302, is_redirect=True,
                            headers={"location": "https://boards.greenhouse.io/final"})
    final = FakeResponse(text="the final body", status_code=200)
    sess = FakeSession(responses=[redirect, final])

    resp = get_redirect_safe(sess, "https://example.com/start", timeout=5)

    assert resp.text == "the final body"
    assert [c[1] for c in sess.calls] == [
        "https://example.com/start", "https://boards.greenhouse.io/final",
    ]


def test_get_redirect_safe_refuses_redirect_to_internal_target_without_requesting_it():
    # The security invariant: a hop's Location is validated BEFORE it is ever
    # requested, so an internal target must never appear in the session's
    # recorded calls, even though it was reachable via a 302 from a public URL.
    redirect = FakeResponse(status_code=302, is_redirect=True,
                            headers={"location": "http://169.254.169.254/latest/meta-data/"})
    sess = FakeSession(responses=[redirect])

    with pytest.raises(ValueError):
        get_redirect_safe(sess, "https://example.com/start", timeout=5)

    assert len(sess.calls) == 1  # only the initial (safe) hop was requested
    assert not any("169.254.169.254" in c[1] for c in sess.calls)


def test_get_redirect_safe_raises_after_too_many_redirects():
    # Every hop targets a public host (so no ValueError from an unsafe target) —
    # this must fail purely on hop count, not on safety.
    responses = [
        FakeResponse(status_code=302, is_redirect=True,
                    headers={"location": f"https://example.com/hop{i}"})
        for i in range(6)  # max_redirects defaults to 5 -> 6 hops is one too many
    ]
    sess = FakeSession(responses=responses)

    with pytest.raises(ValueError):
        get_redirect_safe(sess, "https://example.com/start", timeout=5)

    assert len(sess.calls) == 6


# --- join_present -----------------------------------------------------------
# Shared by three adapters that each spell a location as flat sibling fields
# (workable city/state/country, smartrecruiters city/region/country, jobvite's
# JSON-LD addressLocality/addressRegion/addressCountry). Each had its own copy of
# the comprehension; these pin the behavior all three depended on.

def test_join_present_joins_in_key_order_not_dict_order():
    obj = {"country": "US", "city": "Boulder", "state": "CO"}
    assert join_present(obj, ("city", "state", "country")) == "Boulder, CO, US"


def test_join_present_returns_none_when_nothing_is_set():
    assert join_present({}, ("city", "state")) is None
    assert join_present({"city": None, "state": ""}, ("city", "state")) is None


def test_join_present_drops_blank_values_rather_than_joining_them():
    # The bug this guards: a present-but-empty city yielding ", CO, US".
    obj = {"city": "   ", "state": "CO", "country": "US"}
    assert join_present(obj, ("city", "state", "country")) == "CO, US"


def test_join_present_strips_and_coerces_non_strings():
    # Board JSON is untyped: a region can arrive as a number.
    obj = {"city": "  Austin  ", "state": 78701}
    assert join_present(obj, ("city", "state")) == "Austin, 78701"


def test_join_present_treats_falsy_scalars_as_absent():
    # 0 and False are falsy, so the original comprehension skipped them; keeping
    # that means a numeric-zero region never becomes the string "0".
    assert join_present({"city": 0, "state": False}, ("city", "state")) is None
    # ...but a "0" STRING is real data and survives.
    assert join_present({"city": "0"}, ("city",)) == "0"


def test_join_present_ignores_keys_absent_from_the_object():
    assert join_present({"city": "Boulder"}, ("city", "state", "country")) == "Boulder"
