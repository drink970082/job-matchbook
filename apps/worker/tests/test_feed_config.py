"""Tests for the `feeds:` config block parsing (config.py)."""
from __future__ import annotations

import pytest

from ats_worker import config as cfgmod
from ats_worker.config import ConfigError, DEFAULT_FEED_CATEGORIES


def test_no_feeds_block_means_empty_list():
    cfg = cfgmod.load_config("companies: []\n")
    assert cfg.feeds == []


def test_simplify_feed_defaults():
    cfg = cfgmod.load_config("feeds:\n  simplify:\n    enabled: true\n")
    assert len(cfg.feeds) == 1
    feed = cfg.feeds[0]
    assert feed.name == "simplify"
    assert feed.enabled is True
    assert feed.categories == list(DEFAULT_FEED_CATEGORIES)
    assert feed.url == ""


def test_simplify_feed_overrides():
    cfg = cfgmod.load_config(
        "feeds:\n"
        "  simplify:\n"
        "    enabled: false\n"
        "    categories: [Software, Quant]\n"
        "    url: https://example.com/feed.json\n"
    )
    feed = cfg.feeds[0]
    assert feed.enabled is False
    assert feed.categories == ["Software", "Quant"]
    assert feed.url == "https://example.com/feed.json"


def test_unknown_feed_name_is_an_error():
    with pytest.raises(ConfigError):
        cfgmod.load_config("feeds:\n  linkedin:\n    enabled: true\n")


def test_feeds_must_be_a_mapping():
    with pytest.raises(ConfigError):
        cfgmod.load_config("feeds: [simplify]\n")


def test_feed_categories_must_be_a_list():
    with pytest.raises(ConfigError):
        cfgmod.load_config("feeds:\n  simplify:\n    categories: Software\n")
