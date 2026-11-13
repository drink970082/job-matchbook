"""Lossless source indexing and conservative section provenance tests."""

from dataclasses import replace

import pytest

from ats_worker.preselection.citations import (
    CITATION_INDEX_VERSION,
    MAX_CITATION_BLOCK_CHARS,
    CitationBlock,
    CitationIndex,
    CitationIndexError,
    build_citation_index,
)
from ats_worker.preselection.profile import profile_from_value, render_profile


def _profile(background=(), preferences=()):
    return profile_from_value({
        "schema": 1,
        "version": "synthetic-citations-v1",
        "as_of": "2026-11-12",
        "status": "approved",
        "background": [
            {"id": f"background-{index}", "text": text}
            for index, text in enumerate(background)
        ],
        "preferences": [
            {"id": f"preference-{index}", "text": text}
            for index, text in enumerate(preferences)
        ],
    })


def test_lossless_blocks_keep_unicode_whitespace_duplicate_text_and_exact_offsets():
    job_description = (
        "Preamble café\r\n"
        "## Responsibilities:\r\n"
        "Build a systems tool.\r\n\r\n"
        "Build a systems tool.\r\n\r\n"
        "**Minimum Qualifications:**\r\n"
        "Use C++ and preserve Ω data."
    )
    context = render_profile(_profile(
        ["Café engineering experience — whitespace stays exact.", "Worked on Ω systems."],
        ["Preference text remains in the context but is not citable."],
    ))
    index = build_citation_index(job_description, context)

    assert index.version == CITATION_INDEX_VERSION
    assert "".join(block.text for block in index.jd_blocks) == job_description
    assert "".join(block.text for block in index.candidate_context_blocks) == context
    for source, blocks, source_text in (
        ("jd", index.jd_blocks, job_description),
        ("candidate_context", index.candidate_context_blocks, context),
    ):
        assert all(len(block.text) <= MAX_CITATION_BLOCK_CHARS for block in blocks)
        assert all(source_text[block.start:block.end] == block.text for block in blocks)
        assert [block.id for block in blocks] == [
            f"{'J' if source == 'jd' else 'C'}{item:04d}" for item in range(len(blocks))
        ]

    duplicate_blocks = [
        block for block in index.citable_blocks_for("jd")
        if block.text.strip() == "Build a systems tool."
    ]
    assert len(duplicate_blocks) == 2
    assert duplicate_blocks[0].id != duplicate_blocks[1].id
    assert duplicate_blocks[0].start < duplicate_blocks[1].start
    candidate_blocks = index.citable_blocks_for("candidate_context")
    assert [block.text.strip() for block in candidate_blocks] == [
        "Café engineering experience — whitespace stays exact.",
        "Worked on Ω systems.",
    ]
    assert index.lookup("candidate_context", candidate_blocks[0].id) == candidate_blocks[0]


@pytest.mark.parametrize(
    ("heading", "section_kind", "heading_strength"),
    [
        ("## **WHAT YOU’LL DO:**", "duty", "unknown"),
        ("What-you-will-work-on:", "duty", "unknown"),
        ("**MINIMUM QUALIFICATIONS:**", "qualification", "required"),
        ("Required Qualifications Skills:", "qualification", "required"),
        ("Preferred Skills and Experience:", "qualification", "preferred"),
        ("What We’re Looking For:", "qualification", "unknown"),
        ("Job Description:", "unknown", "unknown"),
        ("## Operating Model", "unknown", "unknown"),
        ("CORE OPERATING MODEL", "unknown", "unknown"),
        ("About Example Company:", "unknown", "unknown"),
        ("Benefits and Perks:", "unknown", "unknown"),
    ],
)
def test_heading_provenance_normalizes_only_heading_comparison(
    heading, section_kind, heading_strength
):
    source = f"{heading}\nExact source text: café, C++ and 3–5 years.\n"
    index = build_citation_index(source, "")
    header = index.jd_blocks[0]
    body = index.jd_blocks[1]
    assert header.text == f"{heading}\n"
    assert header.citable is False
    assert body.text == "Exact source text: café, C++ and 3–5 years.\n"
    assert body.citable is True
    assert body.section_kind == section_kind
    assert body.heading_strength == heading_strength
    assert source[body.start:body.end] == body.text


def test_unknown_template_heading_resets_previous_duty_provenance():
    source = (
        "Responsibilities\nOwn a technical duty.\n"
        "About Example Company\nCompany facts follow.\n"
        "What you will do\nOwn a later technical duty."
    )
    index = build_citation_index(source, "")
    assert [(block.text, block.section_kind, block.citable) for block in index.jd_blocks] == [
        ("Responsibilities\n", "duty", False),
        ("Own a technical duty.\n", "duty", True),
        ("About Example Company\n", "unknown", False),
        ("Company facts follow.\n", "unknown", True),
        ("What you will do\n", "duty", False),
        ("Own a later technical duty.", "duty", True),
    ]


def test_candidate_headers_search_and_empty_profile_are_never_citable():
    profile = _profile(
        ["Background paragraph one.", "Background paragraph two."],
        ["Search preference one.", "Search preference two."],
    )
    context = render_profile(profile)
    index = build_citation_index("A job duty.", context)
    citable = index.citable_blocks_for("candidate_context")
    assert [block.text.strip() for block in citable] == [
        "Background paragraph one.",
        "Background paragraph two.",
    ]
    assert all(block.id not in index.citable_ids_for("candidate_context") for block in (
        index.candidate_context_blocks[0],
        index.candidate_context_blocks[1],
        index.candidate_context_blocks[-3],
        index.candidate_context_blocks[-2],
        index.candidate_context_blocks[-1],
    ))
    search_body = next(block for block in index.candidate_context_blocks if "Search preference" in block.text)
    assert search_body.citable is False

    empty_context = render_profile(_profile())
    empty_index = build_citation_index("A job duty.", empty_context)
    assert empty_index.citable_ids_for("candidate_context") == ()
    assert "".join(block.text for block in empty_index.candidate_context_blocks) == empty_context

    unstructured = build_citation_index("A job duty.", "Candidate text without canonical headers.")
    assert unstructured.citable_ids_for("candidate_context") == ()


def test_ambiguous_candidate_search_boundary_fails_closed_without_losing_source():
    context = "AS OF 2026-11-12\nBACKGROUND\nFirst paragraph.\nSEARCH\nSEARCH\nPreferences.\n"
    index = build_citation_index("A job duty.", context)
    assert "".join(block.text for block in index.candidate_context_blocks) == context
    assert index.citable_ids_for("candidate_context") == ()


def test_long_lines_split_at_whitespace_or_safe_hard_limit_without_loss():
    source = ("λ word\u2003" * 250) + "Z" * 2100
    index = build_citation_index(source, "")
    assert len(index.jd_blocks) > 2
    assert all(len(block.text) <= MAX_CITATION_BLOCK_CHARS for block in index.jd_blocks)
    assert all(block.citable for block in index.jd_blocks)
    assert "".join(block.text for block in index.jd_blocks) == source
    assert all(source[block.start:block.end] == block.text for block in index.jd_blocks)


def test_non_citable_heading_id_cannot_resolve_and_index_rejects_tampering():
    index = build_citation_index("Responsibilities\nDo the work.", "")
    heading = index.jd_blocks[0]
    assert heading.id not in index.citable_ids_for("jd")
    with pytest.raises(CitationIndexError, match="noncitable"):
        index.resolve("jd", heading.id)
    with pytest.raises(CitationIndexError, match="not present"):
        index.resolve("candidate_context", heading.id)

    changed = replace(index.jd_blocks[1], text="Altered evidence.")
    with pytest.raises(CitationIndexError, match="exact source span"):
        CitationIndex(index.job_description, index.candidate_context, (heading, changed), ())
