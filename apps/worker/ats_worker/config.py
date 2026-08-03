"""Load and validate the worker's `config.yaml`.

WHY a dataclass with explicit defaults rather than a bare dict: centralising the
defaults and the source-allowlist validation here means a typo'd board source is
caught at startup with a clear message instead of blowing up mid-fetch.

The WATCHLIST no longer lives here — it is DB-owned (`watched_companies`, read by
`db.get_watchlist`). `cfg.companies` survives for exactly two one-time seeding
sites in run.py: filling an empty watchlist on first run, and the explicit
seed path. The pipeline itself never reads it.

`load_config` accepts either a path (str/PathLike) or a raw YAML string so tests
can pass tiny inline documents without touching the filesystem.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields

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

DEFAULT_SCHEDULE_HOURS = 24

# Discovery feeds (broad listing streams resolved back to boards). Only Simplify
# is wired in v1. The keep-list drops Product/Hardware; the LLM screen still
# judges sponsorship/location from the JD (the feed's flags are too sparse).
VALID_FEEDS = ("simplify",)
DEFAULT_FEED_CATEGORIES = ("Software", "AI/ML/Data", "Quant")

# The documented `candidate.work_authorization` vocabulary (config.yaml.example and
# the onboard-me skill hand over exactly these). It is a CLOSED set because the
# screen reads the value by substring ("sponsor"): an off-vocabulary string like
# "F-1 OPT" reads as "does not need sponsorship" and silently disables the whole
# authorization check. Blank stays legal — that means "don't screen on this".
VALID_WORK_AUTHORIZATION = ("citizen", "permanent resident",
                            "authorized-no-sponsorship", "needs visa sponsorship")


class ConfigError(ValueError):
    """Raised when the config is structurally invalid (bad source, missing field)."""


# Slug is interpolated into a fetch URL host/path by the board adapters (e.g.
# f"https://{slug}.icims.com"). Allow alnum . _ - and single '/'-joined segments
# (workday "tenant/dc/site", phenom "host/domain"); block host-injection
# metacharacters (@ : ? # % \ whitespace) and path traversal.
_SLUG_RE = re.compile(r"^[A-Za-z0-9._/-]+\Z")


def _valid_slug(slug: str) -> bool:
    return (bool(_SLUG_RE.match(slug)) and ".." not in slug
            and not slug.startswith("/") and not slug.endswith("/") and "//" not in slug)


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
    # Years of professional experience, read ONLY by the free seniority pre-ordering
    # (score/seniority.py) to turn a bar the JD states into a verdict about THIS
    # candidate. It is not a screen check and can never discard a posting: a bar this
    # candidate does not clear sends the row to the back of the score queue.
    # 0 = new grad / entry level, which is what the 2026-07-30 measurement calibrated on.
    years_experience: int = 0

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
    # Optional negative title pre-filter: DROP a posting whose title contains one of
    # these (case-insensitive) — the complement of title_filter. Empty = drop none.
    title_exclude: list[str] = field(default_factory=list)
    # Optional fetch-time freshness gate: drop a posting whose posted_at is older than
    # this many days. 0 = off. Dateless/unparseable posted_at is always kept.
    max_age_days: int = 0
    candidate: Candidate = field(default_factory=Candidate)
    # The fit vocabulary (`score/fit_profile.py`): the operator's concept list and
    # priority tiers. None = not configured, which is legal — it only makes the
    # bounded-extraction path unavailable and changes nothing else. Typed loosely here
    # because the parser lives beside the scorer that consumes it, not beside the loader.
    fit_profile: object | None = None
    feeds: list[Feed] = field(default_factory=list)
    schedule_hours: int = DEFAULT_SCHEDULE_HOURS
    # Opt-in gate for `browser`-source rows (they drive a headless Chromium via the
    # optional Playwright extra). Off by default so a normal run stays pure `requests`.
    enable_browser_sources: bool = False


def _looks_like_yaml_text(value) -> bool:
    """A path won't contain newlines or YAML punctuation; a doc will."""
    return "\n" in value or ":" in value


# Divisors of 24, i.e. every cadence that tiles a day evenly. Not a config knob —
# it is arithmetic, and it is spelled out so the error message can name the options.
_LEGAL_SCHEDULE_HOURS = (1, 2, 3, 4, 6, 8, 12, 24)


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
    _reject_unknown_keys(data, Config, "top-level config")
    # Imported here, not at module level: `score.fit_profile` raises this module's
    # ConfigError, so a top-level import in both directions would be a cycle.
    from ats_worker.score.fit_profile import parse_fit_profile

    companies = _parse_companies(data.get("companies") or [])
    title_filter = _parse_title_filter(data.get("title_filter") or [])
    candidate = _parse_candidate(data.get("candidate") or {})
    feeds = _parse_feeds(data.get("feeds"))

    schedule_hours = _int_field(data, "schedule_hours", DEFAULT_SCHEDULE_HOURS)
    if schedule_hours < 1:
        # Kept separate from the divisibility check below so 0 and negatives get their
        # own message. `range(0, 24, 0)` raises ValueError outright, and a NEGATIVE step
        # yields an empty slot list -> a daemon that starts clean, prints a schedule, and
        # never fires. No lower bound is a footgun either way.
        raise ConfigError(
            f"schedule_hours must be >= 1 (got {schedule_hours}); a 0 or negative "
            "interval hot-loops the whole watchlist."
        )
    if 24 % schedule_hours:
        # AFTER the `< 1` check so 0 keeps its own message. Passes fire on WALL-CLOCK
        # slots (`run.cron_hours` -> `range(0, 24, h)`), which only tiles the day when h
        # divides 24. A non-divisor leaves a `24 % h` gap across midnight that is always
        # TIGHTER than the configured cadence — 5 gives 0,5,10,15,20 and then 4 hours to
        # the next midnight slot. Worse, anything above 24 collapses to a single `hour=0`,
        # so `schedule_hours: 48` ("every other day", legal until now) silently becomes
        # DAILY: a 2x change in paid fit-scorer spend from a file nobody edited. Fail at
        # load, before the daemon is up.
        raise ConfigError(
            f"schedule_hours must divide 24 evenly (got {schedule_hours}); passes run on "
            f"wall-clock slots, so pick one of {', '.join(map(str, _LEGAL_SCHEDULE_HOURS))}."
        )

    return Config(
        companies=companies,
        title_filter=title_filter,
        title_exclude=_parse_title_filter(data.get("title_exclude") or []),
        max_age_days=_int_field(data, "max_age_days", 0),
        candidate=candidate,
        fit_profile=parse_fit_profile(data.get("fit_profile")),
        feeds=feeds,
        schedule_hours=schedule_hours,
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


def _reject_unknown_keys(data: dict, cls, where: str) -> None:
    """Fail loud on an unrecognised key so a stale or typo'd field can't silently
    no-op — e.g. the removed top-level `threshold`, which used to be read and now
    isn't. (Candidate `years_experience` was such a key and came BACK on 2026-07-31:
    the free seniority pre-ordering reads it.) Allowed keys are the dataclass fields, so
    this can't drift from the schema. Mirrors the `filters` migration guard above."""
    allowed = {f.name for f in fields(cls)}
    unknown = sorted(k for k in data if k not in allowed)
    if unknown:
        raise ConfigError(
            f"unknown {where} key(s) {unknown}; allowed: {sorted(allowed)}"
        )


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
        slug = str(c["slug"])
        if not _valid_slug(slug):
            raise ConfigError(f"companies[{i}] slug {slug!r} has invalid characters")
        recipe = c.get("recipe")
        if recipe is not None and not isinstance(recipe, dict):
            raise ConfigError(f"companies[{i}] `recipe` must be a mapping")
        if source in RECIPE_SOURCES and not isinstance(recipe, dict):
            raise ConfigError(
                f"companies[{i}] source {source!r} requires a `recipe` mapping"
            )
        out.append(Company(source=source, slug=slug,
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
    _reject_unknown_keys(raw, Candidate, "candidate")
    locations = [str(l) for l in (raw.get("locations") or []) if str(l).strip()]
    work_authorization = str(raw.get("work_authorization") or "").strip()
    if work_authorization and work_authorization.lower() not in VALID_WORK_AUTHORIZATION:
        raise ConfigError(
            f"candidate.work_authorization {work_authorization!r} is not one of "
            f"{VALID_WORK_AUTHORIZATION}. The screen reads this value by substring, so "
            "anything else (e.g. 'F-1 OPT') silently disables the authorization check. "
            "Leave it blank to skip that check. See config.yaml.example."
        )
    return Candidate(
        highest_degree=str(raw.get("highest_degree") or "").strip(),
        work_authorization=work_authorization,
        security_clearance=str(raw.get("security_clearance") or "").strip(),
        locations=locations,
        exclude_internships=bool(raw.get("exclude_internships")),
        years_experience=_int_field(raw, "years_experience", 0),
    )
