"""TDD for the single-page tailoring loop. All externals injected as fakes."""
from __future__ import annotations

from ats_worker import tailor

MASTER = r"\documentclass{article}\begin{document}Master resume\end{document}"
JD = "Senior Python Engineer at Acme"
MISSING = ["aws", "kubernetes"]


class FakeClaude:
    """Returns a tex string per call; records prompts it was asked with."""

    def __init__(self, tex="TAILORED"):
        self.prompts = []
        self._tex = tex

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return f"{self._tex}-{len(self.prompts)}"


def make_compile():
    calls = []

    def compile_pdf(tex, out_dir):
        calls.append((tex, out_dir))
        return f"{out_dir}/resume.pdf"

    compile_pdf.calls = calls
    return compile_pdf


def page_counter(sequence):
    """count_pages that yields the given page counts in order."""
    seq = list(sequence)
    state = {"i": 0}

    def count_pages(pdf_path):
        i = state["i"]
        state["i"] = i + 1
        return seq[min(i, len(seq) - 1)]

    return count_pages


def test_converges_first_try():
    claude = FakeClaude()
    out = tailor.tailor_resume(
        MASTER, JD, MISSING,
        claude=claude,
        compile_pdf=make_compile(),
        count_pages=page_counter([1]),
        max_rounds=3,
    )
    assert out["ok"] is True
    assert out["pages"] == 1
    assert out["tex"] == "TAILORED-1"
    assert out["pdf_path"].endswith("resume.pdf")
    assert len(claude.prompts) == 1


def test_converges_after_shrinking():
    claude = FakeClaude()
    out = tailor.tailor_resume(
        MASTER, JD, MISSING,
        claude=claude,
        compile_pdf=make_compile(),
        count_pages=page_counter([2, 2, 1]),
        max_rounds=3,
    )
    assert out["ok"] is True
    assert out["pages"] == 1
    assert len(claude.prompts) == 3
    # The feedback prompts must mention current page count and the 1-page goal.
    feedback = claude.prompts[1]
    assert "2" in feedback
    assert "1 page" in feedback.lower()


def test_never_converges_returns_not_ok_after_max_rounds():
    claude = FakeClaude()
    out = tailor.tailor_resume(
        MASTER, JD, MISSING,
        claude=claude,
        compile_pdf=make_compile(),
        count_pages=page_counter([2, 2, 2, 2]),
        max_rounds=3,
    )
    assert out["ok"] is False
    assert out["pages"] == 2
    assert len(claude.prompts) == 3


def test_first_prompt_forbids_fabrication():
    claude = FakeClaude()
    tailor.tailor_resume(
        MASTER, JD, MISSING,
        claude=claude,
        compile_pdf=make_compile(),
        count_pages=page_counter([1]),
        max_rounds=3,
    )
    first = claude.prompts[0].lower()
    # constraint text against inventing experience
    assert "never" in first or "do not" in first
    assert "fabricat" in first
    # the master content and JD must be embedded
    assert "Master resume" in claude.prompts[0]
    assert JD in claude.prompts[0]
    # missing keywords surfaced so claude can weave the real ones in
    assert "aws" in first
