"""TDD for config loading: defaults, parsing, and source validation."""
from __future__ import annotations

import pytest

from ats_worker import config


FULL = """
companies:
  - { source: greenhouse, slug: acme, name: "Acme Inc" }
  - { source: lever, slug: foobar, name: "Foobar" }
title_filter: ["engineer", "developer"]
threshold: 80
schedule_hours: 12
max_single_page_rounds: 5
"""


def test_load_parses_companies_and_title_filter():
    cfg = config.load_config(FULL)
    assert [c.source for c in cfg.companies] == ["greenhouse", "lever"]
    assert cfg.companies[0].slug == "acme"
    assert cfg.companies[0].name == "Acme Inc"
    assert cfg.title_filter == ["engineer", "developer"]
    assert cfg.threshold == 80
    assert cfg.schedule_hours == 12
    assert cfg.max_single_page_rounds == 5


def test_defaults_applied_when_omitted():
    cfg = config.load_config(
        "companies:\n  - { source: ashby, slug: x, name: X }\n"
    )
    assert cfg.threshold == 75
    assert cfg.schedule_hours == 24
    assert cfg.max_single_page_rounds == 3
    # empty title_filter allowed
    assert cfg.title_filter == []


def test_empty_companies_allowed():
    cfg = config.load_config("companies: []\n")
    assert cfg.companies == []


def test_invalid_source_raises():
    bad = "companies:\n  - { source: notarealats, slug: x, name: X }\n"
    with pytest.raises(config.ConfigError):
        config.load_config(bad)


def test_new_board_sources_are_valid():
    cfg = config.load_config(
        "companies:\n"
        "  - { source: workday, slug: 'tenant/wd5/site', name: WD }\n"
        "  - { source: pinpoint, slug: wolve, name: Pin }\n"
    )
    assert [c.source for c in cfg.companies] == ["workday", "pinpoint"]


def test_old_filters_key_raises_migration_error():
    bad = "companies: []\nfilters:\n  keywords: ['engineer']\n"
    with pytest.raises(config.ConfigError, match="title_filter"):
        config.load_config(bad)


def test_load_from_path(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(FULL)
    cfg = config.load_config(p)
    assert cfg.threshold == 80
    assert cfg.companies[1].source == "lever"


def test_missing_company_fields_raise():
    bad = "companies:\n  - { source: greenhouse, name: X }\n"  # no slug
    with pytest.raises(config.ConfigError):
        config.load_config(bad)


def test_load_parses_candidate_dealbreakers():
    cfg = config.load_config(
        "companies: []\n"
        "candidate:\n"
        "  dealbreakers:\n"
        "    - 'requires a PhD'\n"
        "    - 'no visa sponsorship'\n"
    )
    assert cfg.candidate.dealbreakers == ["requires a PhD", "no visa sponsorship"]
    assert not cfg.candidate.is_empty()


def test_candidate_defaults_empty_when_absent():
    cfg = config.load_config("companies: []\n")
    assert cfg.candidate.dealbreakers == []
    assert cfg.candidate.is_empty()


def test_load_parses_structured_candidate():
    cfg = config.load_config(
        "companies: []\n"
        "candidate:\n"
        "  years_experience: 1\n"
        "  highest_degree: \"Master's\"\n"
        "  work_authorization: 'needs visa sponsorship'\n"
        "  security_clearance: none\n"
        "  locations: ['remote', 'New York']\n"
        "  dealbreakers:\n"
        "    - 'requires an active clearance'\n"
    )
    c = cfg.candidate
    assert c.years_experience == 1.0
    assert c.highest_degree == "Master's"
    assert c.work_authorization == "needs visa sponsorship"
    assert c.security_clearance == "none"
    assert c.locations == ["remote", "New York"]
    assert c.dealbreakers == ["requires an active clearance"]
    assert not c.is_empty()


def test_candidate_years_experience_non_numeric_raises():
    bad = "companies: []\ncandidate:\n  years_experience: 'a lot'\n"
    with pytest.raises(config.ConfigError):
        config.load_config(bad)


def test_is_empty_false_when_any_single_field_set():
    # run.py uses is_empty() to decide whether to build the screen checklist at all,
    # so ANY one configured hard requirement must flip it to False (screening on).
    cases = (
        "candidate:\n  years_experience: 0\n",       # 0 years is still "configured"
        "candidate:\n  highest_degree: \"Bachelor's\"\n",
        "candidate:\n  work_authorization: 'US citizen'\n",
        "candidate:\n  security_clearance: 'Secret'\n",
        "candidate:\n  locations: ['remote']\n",
        "candidate:\n  dealbreakers: ['no internships']\n",
    )
    for body in cases:
        cfg = config.load_config("companies: []\n" + body)
        assert cfg.candidate.is_empty() is False, body


def test_is_empty_true_for_blank_and_whitespace_only_fields():
    # Whitespace-only strings and empty lists must NOT count as configured, so an
    # effectively-blank candidate still skips screening.
    cfg = config.load_config(
        "companies: []\n"
        "candidate:\n"
        "  highest_degree: '   '\n"
        "  work_authorization: ''\n"
        "  locations: []\n"
        "  dealbreakers: []\n"
    )
    assert cfg.candidate.is_empty() is True


@pytest.mark.parametrize("key", ["threshold", "schedule_hours", "max_single_page_rounds"])
def test_non_numeric_numeric_fields_raise_config_error(key):
    # The module contract is "fail loud with a ConfigError at startup", not an
    # opaque ValueError from int(). Mirrors years_experience handling.
    bad = f"companies: []\n{key}: not-a-number\n"
    with pytest.raises(config.ConfigError, match="must be an integer"):
        config.load_config(bad)


def test_root_not_a_mapping_raises():
    with pytest.raises(config.ConfigError, match="mapping"):
        config.load_config("- a\n- b\n")


def test_companies_not_a_list_raises():
    with pytest.raises(config.ConfigError, match="must be a list"):
        config.load_config("companies: 42\n")


def test_candidate_not_a_mapping_raises():
    with pytest.raises(config.ConfigError, match="mapping"):
        config.load_config("companies: []\ncandidate: [1, 2]\n")


def test_slug_and_name_coerced_to_str():
    cfg = config.load_config(
        "companies:\n  - { source: greenhouse, slug: 12345, name: 678 }\n"
    )
    assert cfg.companies[0].slug == "12345"
    assert cfg.companies[0].name == "678"


def test_load_from_plain_string_path(tmp_path):
    # A filename (no newline/colon) must be read from disk, not parsed as YAML.
    p = tmp_path / "cfg.yaml"
    p.write_text("companies: []\nthreshold: 88\n")
    cfg = config.load_config(str(p))
    assert cfg.threshold == 88
