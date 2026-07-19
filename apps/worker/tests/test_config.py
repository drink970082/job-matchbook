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
"""


def test_load_parses_companies_and_title_filter():
    cfg = config.load_config(FULL)
    assert [c.source for c in cfg.companies] == ["greenhouse", "lever"]
    assert cfg.companies[0].slug == "acme"
    assert cfg.companies[0].name == "Acme Inc"
    assert cfg.title_filter == ["engineer", "developer"]
    assert cfg.threshold == 80
    assert cfg.schedule_hours == 12


def test_defaults_applied_when_omitted():
    cfg = config.load_config(
        "companies:\n  - { source: ashby, slug: x, name: X }\n"
    )
    assert cfg.threshold == 75
    assert cfg.schedule_hours == 24
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
        "  - { source: workable, slug: acme, name: Workbl }\n"
    )
    assert [c.source for c in cfg.companies] == ["workday", "pinpoint", "workable"]


def test_feed_only_sources_are_not_watchlist_valid():
    # oracle/jobvite are per-listing (no board to enumerate) so they must NOT be
    # accepted as a watchlist/config company source.
    for src in ("oracle", "jobvite"):
        with pytest.raises(config.ConfigError):
            config.load_config(f"companies:\n  - {{ source: {src}, slug: x, name: X }}\n")


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


def test_rejects_slug_with_bad_chars():
    with pytest.raises(config.ConfigError):
        config.load_config("companies:\n  - {source: greenhouse, slug: 'a b', name: X}")


def test_allows_multipart_slug():
    cfg = config.load_config("companies:\n  - {source: workday, slug: 't/wd3/site', name: X}")
    assert cfg.companies[0].slug == "t/wd3/site"


def test_rejects_slug_with_trailing_newline():
    # Python's `re` `$` matches just before a trailing "\n", but JS `$` (no `m`
    # flag) does not — so a bare `$`-anchored pattern would accept this slug on
    # the worker side while the web guard rejects it. `_SLUG_RE` uses `\Z` (no
    # trailing-newline exception) so both boundaries agree.
    with pytest.raises(config.ConfigError):
        config.load_config(
            "companies:\n  - {source: workday, slug: \"relx/wd3/relx\\n\", name: X}"
        )
    assert config._valid_slug("relx/wd3/relx\n") is False


def test_candidate_defaults_empty_when_absent():
    cfg = config.load_config("companies: []\n")
    assert cfg.candidate.locations == []
    assert cfg.candidate.is_empty()


def test_load_parses_structured_candidate():
    cfg = config.load_config(
        "companies: []\n"
        "candidate:\n"
        "  highest_degree: \"Master's\"\n"
        "  work_authorization: 'needs visa sponsorship'\n"
        "  security_clearance: none\n"
        "  locations: ['remote', 'New York']\n"
        "  exclude_internships: true\n"
    )
    c = cfg.candidate
    assert c.highest_degree == "Master's"
    assert c.work_authorization == "needs visa sponsorship"
    assert c.security_clearance == "none"
    assert c.locations == ["remote", "New York"]
    assert c.exclude_internships is True
    assert not c.is_empty()


def test_exclude_internships_defaults_false():
    cfg = config.load_config("companies: []\ncandidate:\n  highest_degree: \"Master's\"\n")
    assert cfg.candidate.exclude_internships is False


def test_is_empty_false_when_any_single_field_set():
    # run.py uses is_empty() to decide whether to build the screen checklist at all,
    # so ANY one configured hard requirement must flip it to False (screening on).
    cases = (
        "candidate:\n  highest_degree: \"Bachelor's\"\n",
        "candidate:\n  work_authorization: 'US citizen'\n",
        "candidate:\n  security_clearance: 'Secret'\n",
        "candidate:\n  locations: ['remote']\n",
        "candidate:\n  exclude_internships: true\n",
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
    )
    assert cfg.candidate.is_empty() is True


@pytest.mark.parametrize("key", ["threshold", "schedule_hours"])
def test_non_numeric_numeric_fields_raise_config_error(key):
    # The module contract is "fail loud with a ConfigError at startup", not an
    # opaque ValueError from int().
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
