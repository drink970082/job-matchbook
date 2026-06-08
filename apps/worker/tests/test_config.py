"""TDD for config loading: defaults, parsing, and source validation."""
from __future__ import annotations

import pytest

from ats_worker import config


FULL = """
companies:
  - { source: greenhouse, slug: acme, name: "Acme Inc" }
  - { source: lever, slug: foobar, name: "Foobar" }
filters:
  keywords: ["engineer", "developer"]
  locations: ["remote", "san francisco"]
threshold: 80
schedule_hours: 12
max_single_page_rounds: 5
"""


def test_load_parses_companies_and_filters():
    cfg = config.load_config(FULL)
    assert [c.source for c in cfg.companies] == ["greenhouse", "lever"]
    assert cfg.companies[0].slug == "acme"
    assert cfg.companies[0].name == "Acme Inc"
    assert cfg.filters.keywords == ["engineer", "developer"]
    assert cfg.filters.locations == ["remote", "san francisco"]
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
    # empty filters allowed
    assert cfg.filters.keywords == []
    assert cfg.filters.locations == []


def test_empty_companies_allowed():
    cfg = config.load_config("companies: []\n")
    assert cfg.companies == []


def test_invalid_source_raises():
    bad = "companies:\n  - { source: workday, slug: x, name: X }\n"
    with pytest.raises(config.ConfigError):
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


def test_load_parses_candidate():
    cfg = config.load_config(
        "companies: []\n"
        "candidate:\n"
        "  profile: 'Entry level (0-2y), Master, needs sponsorship'\n"
        "  dealbreakers:\n"
        "    - 'requires a PhD'\n"
        "    - 'no visa sponsorship'\n"
    )
    assert cfg.candidate.profile == "Entry level (0-2y), Master, needs sponsorship"
    assert cfg.candidate.dealbreakers == ["requires a PhD", "no visa sponsorship"]


def test_candidate_defaults_empty_when_absent():
    cfg = config.load_config("companies: []\n")
    assert cfg.candidate.profile == ""
    assert cfg.candidate.dealbreakers == []
