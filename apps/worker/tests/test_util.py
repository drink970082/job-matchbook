"""Direct tests for html_to_text — the most-reused adapter helper.

Previously only exercised transitively through adapter fixtures, which left its
edge cases (nbsp, <br>/block-tag newlines, double-unescape, blank-collapse)
unguarded. The nbsp case also pins a real bug: an unescaped `&nbsp;` becomes
U+00A0, which the whitespace-collapse must fold to a normal space.
"""
from __future__ import annotations

import pytest

from ats_worker.util import html_to_text


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
