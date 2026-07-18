"""Load and validate the worker's `config.yaml`.

WHY a dataclass with explicit defaults rather than a bare dict: the rest of the
pipeline reads `cfg.threshold`, `cfg.companies[i].source`, etc. Centralising the
defaults and the source-allowlist validation here means a typo'd board source is
caught at startup with a clear message instead of blowing up mid-fetch.

`load_config` accepts either a path (str/PathLike) or a raw YAML string so tests
can pass tiny inline documents without touching the filesystem.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

# Must match fetch.ADAPTERS — but importing fetch here would pull in `requests`
# at config-load time, so we keep an explicit local allowlist instead.
# Watchlist-capable sources (boards we can enumerate). Feed-only per-listing
# sources (oracle, jobvite) are intentionally absent — they can't be a watchlist
# company. Must match the watchlist-capable subset of fetch.ADAPTERS.
VALID_SOURCES = ("greenhouse", "lever", "ashby", "workday", "pinpoint",
                 "smartrecruiters", "workable", "icims", "phenom", "custom", "browser")

# Sources whose fetch is driven by a declarative `recipe` (not a slug alone). A
# watchlist row for one of these MUST carry a recipe mapping. `browser` joins here
# in phase 4 (its adapter is gated separately in run.py).
RECIPE_SOURCES = ("custom", "browser")

DEFAULT_THRESHOLD = 75
DEFAULT_SCHEDULE_HOURS = 24

# Discovery feeds (broad listing streams resolved back to boards). Only Simplify
# is wired in v1. The keep-list drops Product/Hardware; the LLM screen still
# judges sponsorship/location from the JD (the feed's flags are too sparse).
VALID_FEEDS = ("simplify",)
DEFAULT_FEED_CATEGORIES = ("Software", "AI/ML/Data", "Quant")


class ConfigError(ValueError):
    """Raised when the config is structurally invalid (bad source, missing field)."""


@dataclass(frozen=True)
class Company:
    source: str
    slug: str
    name: str
    recipe: dict | None = None  # declarative fetch recipe for source in RECIPE_SOURCES


@dataclass(frozen=True)
class Candidate:
    """The candidate's hard-requirement facts, used ONLY by the local screen (never
    by the Claude fit score, which reads the résumé + profile). The screen decides
    disqualification in CODE: work authorization and location gate deterministically
    off the JD text / posting location, internships off the title, and degree /
    clearance compare the candidate's constraint against a fact the 4B model only
    *extracts* from the JD (the model never makes the pass/fail call). Everything
    empty = no screen call, no disqualification. Skills/identity for FIT scoring live
    in the résumé, not here."""
    highest_degree: str = ""
    work_authorization: str = ""
    security_clearance: str = ""
    locations: list[str] = field(default_factory=list)
    # Deterministic hard-constraint (decided in code from the job title, not the LLM):
    # when true, intern/co-op roles are disqualified — the 4B model is unreliable on
    # this, but the title is a clean signal. See score._is_internship.
    exclude_internships: bool = False

    def is_empty(self) -> bool:
        """True when nothing is configured, so screening stays disabled."""
        return not any((
            self.highest_degree.strip(),
            self.work_authorization.strip(),
            self.security_clearance.strip(),
            self.locations,
            self.exclude_internships,
        ))


@dataclass(frozen=True)
class Feed:
    """A discovery feed. `categories` is the cheap pre-filter keep-list; an empty
    `url` means use the adapter's default listings URL."""
    name: str
    enabled: bool = False
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_FEED_CATEGORIES))
    url: str = ""


@dataclass(frozen=True)
class Config:
    companies: list[Company] = field(default_factory=list)
    # Optional coarse pre-filter: keep a posting only if its TITLE contains one of
    # these (case-insensitive). Empty = keep all and let the scorer decide.
    title_filter: list[str] = field(default_factory=list)
    candidate: Candidate = field(default_factory=Candidate)
    feeds: list[Feed] = field(default_factory=list)
    threshold: int = DEFAULT_THRESHOLD
    schedule_hours: int = DEFAULT_SCHEDULE_HOURS
    # Opt-in gate for `browser`-source rows (they drive a headless Chromium via the
    # optional Playwright extra). Off by default so a normal run stays pure `requests`.
    enable_browser_sources: bool = False


def _looks_like_yaml_text(value) -> bool:
    """A path won't contain newlines or YAML punctuation; a doc will."""
    return "\n" in value or ":" in value


def load_config(source) -> Config:
    """Parse a Config from a path (str/PathLike) or a raw YAML string.

    Defaults are applied for any omitted top-level key; empty filters/companies
    are allowed. Raises ConfigError on an unknown company source or a company
    entry missing a required field.
    """
    if hasattr(source, "read_text"):  # pathlib.Path
        text = source.read_text()
    elif isinstance(source, str) and not _looks_like_yaml_text(source) and os.path.exists(source):
        with open(source, "r", encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = source

    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping")

    if "filters" in data:
        # Replaced by a flat `title_filter` (location filtering removed in favour of
        # candidate.locations). Fail loud so an old config isn't silently ignored.
        raise ConfigError(
            "`filters` was replaced by a top-level `title_filter` list (a posting is "
            "kept only if its TITLE contains one of these). Location filtering was "
            "removed — use `candidate.locations` for geography. See config.yaml.example."
        )
    companies = _parse_companies(data.get("companies") or [])
    title_filter = _parse_title_filter(data.get("title_filter") or [])
    candidate = _parse_candidate(data.get("candidate") or {})
    feeds = _parse_feeds(data.get("feeds"))

    return Config(
        companies=companies,
        title_filter=title_filter,
        candidate=candidate,
        feeds=feeds,
        threshold=_int_field(data, "threshold", DEFAULT_THRESHOLD),
        schedule_hours=_int_field(data, "schedule_hours", DEFAULT_SCHEDULE_HOURS),
        enable_browser_sources=bool(data.get("enable_browser_sources", False)),
    )


def _int_field(data: dict, key: str, default: int) -> int:
    """Coerce a top-level int field, raising ConfigError (not a bare ValueError)
    on a non-numeric value so a typo is caught at startup with a clear message."""
    raw = data.get(key, default)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def _parse_companies(raw) -> list[Company]:
    if not isinstance(raw, list):
        raise ConfigError("`companies` must be a list")
    out: list[Company] = []
    for i, c in enumerate(raw):
        if not isinstance(c, dict):
            raise ConfigError(f"companies[{i}] must be a mapping")
        for key in ("source", "slug", "name"):
            if not c.get(key):
                raise ConfigError(f"companies[{i}] missing required field {key!r}")
        source = c["source"]
        if source not in VALID_SOURCES:
            raise ConfigError(
                f"companies[{i}] has unknown source {source!r}; "
                f"must be one of {VALID_SOURCES}"
            )
        recipe = c.get("recipe")
        if recipe is not None and not isinstance(recipe, dict):
            raise ConfigError(f"companies[{i}] `recipe` must be a mapping")
        if source in RECIPE_SOURCES and not isinstance(recipe, dict):
            raise ConfigError(
                f"companies[{i}] source {source!r} requires a `recipe` mapping"
            )
        out.append(Company(source=source, slug=str(c["slug"]),
                           name=str(c["name"]), recipe=recipe))
    return out


def _parse_feeds(raw) -> list[Feed]:
    """Parse the optional `feeds:` mapping (feed-name -> settings). Omitted or
    empty = no feeds. An unknown feed name is a startup error."""
    if not raw:
        return []
    if not isinstance(raw, dict):
        raise ConfigError("`feeds` must be a mapping of feed-name -> settings")
    out: list[Feed] = []
    for name, cfg in raw.items():
        if name not in VALID_FEEDS:
            raise ConfigError(
                f"unknown feed {name!r}; must be one of {VALID_FEEDS}"
            )
        cfg = cfg or {}
        if not isinstance(cfg, dict):
            raise ConfigError(f"feeds.{name} must be a mapping")
        cats_raw = cfg.get("categories")
        if cats_raw is None:
            categories = list(DEFAULT_FEED_CATEGORIES)
        elif isinstance(cats_raw, list):
            categories = [str(c) for c in cats_raw if str(c).strip()]
        else:
            raise ConfigError(f"feeds.{name}.categories must be a list")
        out.append(Feed(
            name=name,
            enabled=bool(cfg.get("enabled", False)),
            categories=categories,
            url=str(cfg.get("url") or ""),
        ))
    return out


def _parse_title_filter(raw) -> list[str]:
    if not isinstance(raw, list):
        raise ConfigError("`title_filter` must be a list of title keywords")
    return [str(k) for k in raw if str(k).strip()]


def _parse_candidate(raw) -> Candidate:
    if not isinstance(raw, dict):
        raise ConfigError("`candidate` must be a mapping")
    locations = [str(l) for l in (raw.get("locations") or []) if str(l).strip()]
    return Candidate(
        highest_degree=str(raw.get("highest_degree") or "").strip(),
        work_authorization=str(raw.get("work_authorization") or "").strip(),
        security_clearance=str(raw.get("security_clearance") or "").strip(),
        locations=locations,
        exclude_internships=bool(raw.get("exclude_internships")),
    )
