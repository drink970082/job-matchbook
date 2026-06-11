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
VALID_SOURCES = ("greenhouse", "lever", "ashby", "workday", "pinpoint")

DEFAULT_THRESHOLD = 75
DEFAULT_SCHEDULE_HOURS = 24
DEFAULT_MAX_SINGLE_PAGE_ROUNDS = 3


class ConfigError(ValueError):
    """Raised when the config is structurally invalid (bad source, missing field)."""


@dataclass(frozen=True)
class Company:
    source: str
    slug: str
    name: str


@dataclass(frozen=True)
class Candidate:
    """The candidate's standard application-screening facts, fed to the LLM scorer
    so it can semantically SCREEN each posting against the candidate's hard
    requirements (handles vague wording like "no sponsorship" by reasoning, not a
    brittle keyword list). Each structured field maps 1:1 to a `screen` requirement
    the model gives a pass/fail verdict for; `dealbreakers` adds freeform extras.
    Everything empty = the scorer is never asked to screen (no disqualification).
    Skills/identity for FIT scoring live in the résumé, not here."""
    years_experience: float | None = None
    highest_degree: str = ""
    work_authorization: str = ""
    security_clearance: str = ""
    locations: list[str] = field(default_factory=list)
    dealbreakers: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        """True when nothing is configured, so screening stays disabled."""
        return not any((
            self.years_experience is not None,
            self.highest_degree.strip(),
            self.work_authorization.strip(),
            self.security_clearance.strip(),
            self.locations,
            self.dealbreakers,
        ))


@dataclass(frozen=True)
class Config:
    companies: list[Company] = field(default_factory=list)
    # Optional coarse pre-filter: keep a posting only if its TITLE contains one of
    # these (case-insensitive). Empty = keep all and let the scorer decide.
    title_filter: list[str] = field(default_factory=list)
    candidate: Candidate = field(default_factory=Candidate)
    threshold: int = DEFAULT_THRESHOLD
    schedule_hours: int = DEFAULT_SCHEDULE_HOURS
    max_single_page_rounds: int = DEFAULT_MAX_SINGLE_PAGE_ROUNDS


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
    elif isinstance(source, (bytes, bytearray)):
        text = source.decode()
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

    return Config(
        companies=companies,
        title_filter=title_filter,
        candidate=candidate,
        threshold=int(data.get("threshold", DEFAULT_THRESHOLD)),
        schedule_hours=int(data.get("schedule_hours", DEFAULT_SCHEDULE_HOURS)),
        max_single_page_rounds=int(
            data.get("max_single_page_rounds", DEFAULT_MAX_SINGLE_PAGE_ROUNDS)
        ),
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
        out.append(Company(source=source, slug=str(c["slug"]), name=str(c["name"])))
    return out


def _parse_title_filter(raw) -> list[str]:
    if not isinstance(raw, list):
        raise ConfigError("`title_filter` must be a list of title keywords")
    return [str(k) for k in raw if str(k).strip()]


def _parse_candidate(raw) -> Candidate:
    if not isinstance(raw, dict):
        raise ConfigError("`candidate` must be a mapping")
    years = raw.get("years_experience")
    if years is not None:
        try:
            years = float(years)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"candidate.years_experience must be a number, got {years!r}"
            ) from exc
    locations = [str(l) for l in (raw.get("locations") or []) if str(l).strip()]
    dealbreakers = [str(d) for d in (raw.get("dealbreakers") or []) if str(d).strip()]
    return Candidate(
        years_experience=years,
        highest_degree=str(raw.get("highest_degree") or "").strip(),
        work_authorization=str(raw.get("work_authorization") or "").strip(),
        security_clearance=str(raw.get("security_clearance") or "").strip(),
        locations=locations,
        dealbreakers=dealbreakers,
    )
