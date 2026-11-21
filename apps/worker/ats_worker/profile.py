"""The candidate profile (#224): one `candidate_profile` row, the only candidate input.

Every stage reads its slice through `CandidateProfile`:

- fetch:   `title_include`, `title_exclude`, `max_age_days` (the search scope)
- screen:  `screen_candidate()` (hard requirements + the derived highest degree)
- triage:  `triage_texts()` (background + preferences, or a verbatim custom context,
           and the committed default packs unless custom packs are stored)

Highest degree and total years are DERIVED from the background rows
(`highest_degree`, `total_years`); the web derives them with the same rule
(apps/web/src/lib/candidate-profile.ts), and both sides run
tests/fixtures/candidate-profile-cases.json.

`seed_values` builds the one-time row: from config.yaml on a fresh install, and from
the legacy `candidate_preferences` / `jev_profile` rows in the operator migration
(ats_worker/migrate_profile.py). It is built so that nothing a stored verdict depends on
moves: the derived degree keeps the legacy degree's rank, and the triage texts keep
their bytes (a free-text JEV profile is carried verbatim as the custom context).

Pure: no DB access here except `load`, which only reads the row via `db`.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config as config_mod
from . import db
from .screening.engine import DEGREE_RANK, _degree_rank

# Ranked lowest first; the vocabulary the web form offers (constants.ts DEGREES).
DEGREES = tuple(DEGREE_RANK[i] for i in sorted(DEGREE_RANK))

DEFAULT_PACKS_DIR = Path(__file__).resolve().parent / "triage_packs"
LIST_FIELDS = ("title_include", "title_exclude", "locations", "target_roles", "open_to",
               "not_interested")
JSON_FIELDS = LIST_FIELDS + ("education", "experience")
# Every column a seed or a set writes (bookkeeping columns excluded).
PROFILE_FIELDS = JSON_FIELDS + ("max_age_days", "work_authorization", "security_clearance",
                                "exclude_internships", "exclude_contract", "custom_packs",
                                "custom_triage_context")


class ProfileError(config_mod.ConfigError):
    """The stored row is malformed; the pass fails loudly rather than guessing."""


# --- derived fields ------------------------------------------------------------

def highest_degree(education) -> str:
    """The highest DEGREES value over the education rows; '' when there are none
    (the screen then does not check degree)."""
    ranks = [DEGREES.index(e["degree"]) for e in education if e.get("degree") in DEGREES]
    return DEGREES[max(ranks)] if ranks else ""


def total_years(experience):
    """Sum of the experience rows, rounded half-up to 0.01 (JS Math.round) and returned
    as an int when whole, so it prints as the web prints it."""
    return _js_number(math.floor(sum(float(e.get("years") or 0) for e in experience) * 100 + 0.5) / 100)


def canonical_degree(value) -> str:
    """A free-text degree ('BS', "Master's", 'PhD') as the DEGREES value of the same
    rank under the screen's own matcher, so the screen decides exactly as before.
    Blank stays blank; text the matcher does not recognize ranks 0, i.e. 'none'."""
    text = str(value or "").strip()
    return DEGREE_RANK[_degree_rank(text)] if text else ""


def _js_number(x):
    x = float(x)
    return int(x) if x.is_integer() else x


# --- the row -------------------------------------------------------------------

@dataclass(frozen=True)
class CandidateProfile:
    title_include: tuple[str, ...] = ()
    title_exclude: tuple[str, ...] = ()
    max_age_days: int = 0
    locations: tuple[str, ...] = ()
    work_authorization: str = ""
    security_clearance: str = ""
    exclude_internships: bool = False
    exclude_contract: bool = False
    education: tuple[dict, ...] = ()
    experience: tuple[dict, ...] = ()
    target_roles: tuple[str, ...] = ()
    open_to: tuple[str, ...] = ()
    not_interested: tuple[str, ...] = ()
    custom_packs: dict | None = None
    custom_triage_context: dict | None = None
    version: int = 1

    @property
    def highest_degree(self) -> str:
        return highest_degree(self.education)

    @property
    def total_years(self):
        return total_years(self.experience)

    def screen_candidate(self) -> dict | None:
        """The screen's checklist, or None when no requirement is set (no screen call)."""
        cand = config_mod.Candidate(
            highest_degree=self.highest_degree, work_authorization=self.work_authorization,
            security_clearance=self.security_clearance, locations=list(self.locations),
            exclude_internships=self.exclude_internships, exclude_contract=self.exclude_contract)
        if cand.is_empty():
            return None
        return {"highest_degree": cand.highest_degree,
                "work_authorization": cand.work_authorization,
                "security_clearance": cand.security_clearance,
                "locations": list(cand.locations),
                "exclude_internships": cand.exclude_internships,
                "exclude_contract": cand.exclude_contract}

    def triage_context(self) -> dict | None:
        """{profile_text, yoe_context} sent to triage, or None when triage has nothing
        to judge against (no target role and no custom context)."""
        if self.custom_triage_context is not None:
            return dict(self.custom_triage_context)
        if not self.target_roles:
            return None
        return render_triage_context(self)

    def triage_texts(self) -> dict | None:
        """The four jev.INPUT_TEXTS (validated by jev.inputs_from_texts), or None."""
        context = self.triage_context()
        if context is None:
            return None
        packs = self.custom_packs or default_packs()
        return {"profile_text": context["profile_text"], "c_pack": packs["preference_pack"],
                "yoe_pack": packs["yoe_pack"], "yoe_context": context["yoe_context"]}


def default_packs() -> dict:
    """The committed, system-owned question packs (unvalidated until #182 measures them)."""
    return {"preference_pack": (DEFAULT_PACKS_DIR / "preference-pack.json").read_text(encoding="utf-8"),
            "yoe_pack": (DEFAULT_PACKS_DIR / "yoe-pack.json").read_text(encoding="utf-8")}


def render_triage_context(p: CandidateProfile) -> dict:
    """The triage context from the structured fields. Byte-for-byte the rendering of the
    #206 JEV form (JSON.stringify(_, null, 2) and three yoe lines), so a profile that
    form wrote migrates to the same bytes and keeps its policy hash."""
    education = [{"degree": e["degree"], "field": e.get("field", "")} for e in p.education]
    experience = [{"title": e.get("title", ""), "company": e.get("company", ""),
                   "years": _js_number(e.get("years") or 0)} for e in p.experience]
    profile_text = json.dumps({"target_roles": list(p.target_roles), "open_to": list(p.open_to),
                               "not_interested": list(p.not_interested),
                               "education": education, "experience": experience},
                              indent=2, ensure_ascii=False)
    edu = [" in ".join(x for x in (e["degree"], e["field"]) if x) for e in education]
    exp = [f"{' at '.join(x for x in (e['title'], e['company']) if x)}, {e['years']} years"
           for e in experience]
    yoe_context = "\n".join([
        f"Education: {'; '.join(edu) if edu else 'none listed'}.",
        f"Experience: {'; '.join(exp) if exp else 'none listed'}.",
        f"Total years of experience: {total_years(experience)}.",
    ])
    return {"profile_text": profile_text, "yoe_context": yoe_context}


def _str_list(value, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ProfileError(f"candidate_profile.{name} must be a JSON list of strings")
    return tuple(x for x in (s.strip() for s in value) if x)


def _rows(value, name: str) -> list[dict]:
    if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
        raise ProfileError(f"candidate_profile.{name} must be a JSON list of objects")
    return value


def _json(raw, name: str):
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        raise ProfileError(f"candidate_profile.{name} is not valid JSON") from None


def _only_keys(entry: dict, field: str, keys: tuple[str, ...]) -> None:
    extra = sorted(set(entry) - set(keys))
    if extra:
        raise ProfileError(f"candidate_profile.{field}: an entry takes only {', '.join(keys)} "
                           f"(got {', '.join(extra)})")


def from_row(row: dict) -> CandidateProfile:
    """Parse and validate a stored row (a sqlite3.Row as dict). Raises ProfileError on a
    malformed or off-vocabulary value: the screen reads work authorization by substring
    and the degree by rank, so a bad value must fail the pass, not disable a check."""
    lists = {k: _str_list(_json(row.get(k, "[]"), k), k) for k in LIST_FIELDS}
    education = []
    for e in _rows(_json(row.get("education", "[]"), "education"), "education"):
        _only_keys(e, "education", ("degree", "field"))
        if e.get("degree") not in DEGREES:
            raise ProfileError(f"candidate_profile.education degree {e.get('degree')!r} is not "
                               f"one of {DEGREES}")
        education.append({"degree": e["degree"], "field": str(e.get("field") or "")})
    experience = []
    for e in _rows(_json(row.get("experience", "[]"), "experience"), "experience"):
        _only_keys(e, "experience", ("title", "company", "years"))
        years = e.get("years", 0)
        if isinstance(years, bool) or not isinstance(years, (int, float)) or not 0 <= years <= 60:
            raise ProfileError("candidate_profile.experience years must be a number from 0 to 60")
        experience.append({"title": str(e.get("title") or ""), "company": str(e.get("company") or ""),
                           "years": years})
    auth = str(row.get("work_authorization") or "").strip().lower()
    if auth and auth not in config_mod.VALID_WORK_AUTHORIZATION:
        raise ProfileError(f"candidate_profile.work_authorization {auth!r} is not one of "
                           f"{config_mod.VALID_WORK_AUTHORIZATION}")
    packs = _json(row.get("custom_packs"), "custom_packs")
    if packs is not None and (not isinstance(packs, dict)
                              or not all(isinstance(packs.get(k), str) for k in ("preference_pack", "yoe_pack"))):
        raise ProfileError("candidate_profile.custom_packs must hold preference_pack and yoe_pack texts")
    context = _json(row.get("custom_triage_context"), "custom_triage_context")
    if context is not None and (not isinstance(context, dict)
                                or not all(isinstance(context.get(k), str) for k in ("profile_text", "yoe_context"))):
        raise ProfileError("candidate_profile.custom_triage_context must hold profile_text and yoe_context texts")
    return CandidateProfile(
        **lists, max_age_days=int(row.get("max_age_days") or 0),
        work_authorization=auth, security_clearance=str(row.get("security_clearance") or "").strip(),
        exclude_internships=bool(row.get("exclude_internships")),
        exclude_contract=bool(row.get("exclude_contract")),
        education=tuple(education), experience=tuple(experience),
        custom_packs=packs, custom_triage_context=context, version=int(row.get("version") or 1))


def load(conn) -> CandidateProfile | None:
    row = db.get_candidate_profile(conn)
    return None if row is None else from_row(row)


# --- the one-time seed -----------------------------------------------------------

def _dumps(value) -> str:
    # The web's JSON.stringify bytes, so restating a seeded value is a no-op there.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _same_pack(a: str, b: str) -> bool:
    """Packs hash as parsed JSON (jev.JevInputs.policy_sha), so compare them that way."""
    from . import jev
    return jev.enc(json.loads(a)) == jev.enc(json.loads(b))


def _legacy_form(profile_text: str) -> dict | None:
    """The structured fields of a profile the #206 form wrote, else None (free text)."""
    try:
        value = json.loads(profile_text)
    except ValueError:
        return None
    keys = ("target_roles", "open_to", "not_interested", "education", "experience")
    if not isinstance(value, dict) or set(value) != set(keys):
        return None
    try:
        lists = {k: list(_str_list(value[k], k)) for k in keys[:3]}
        return {**lists, "education": _rows(value["education"], "education"),
                "experience": _rows(value["experience"], "experience")}
    except ProfileError:
        return None


def seed_values(cfg, *, preferences: dict | None = None, jev_texts: dict | None = None) -> dict | None:
    """The column values of the one-time row, or None when there is nothing to seed.

    `cfg` supplies the search scope (title_filter -> title_include, title_exclude,
    max_age_days) and, when no legacy `preferences` row is given, the `candidate:`
    block. `jev_texts` is a legacy `jev_profile` row or the `jev_dir` files
    (jev.INPUT_TEXTS). Nothing a stored verdict depends on moves:

    - education: one row at the legacy degree's rank (or the #206 form's rows when
      their highest equals it); none when no degree was set, so degree stays unchecked;
    - the triage context: rendered from the fields when that reproduces the stored
      bytes, else carried verbatim (custom_triage_context);
    - packs: null when equal to the committed defaults, else carried (custom_packs).
    """
    if preferences is not None:
        req = {k: preferences.get(k) for k in ("highest_degree", "work_authorization",
                                                "security_clearance", "locations",
                                                "exclude_internships", "exclude_contract")}
        locs = req["locations"]
        req["locations"] = json.loads(locs) if isinstance(locs, str) else list(locs or [])
    else:
        c = cfg.candidate
        req = {"highest_degree": c.highest_degree, "work_authorization": c.work_authorization,
               "security_clearance": c.security_clearance, "locations": list(c.locations),
               "exclude_internships": c.exclude_internships, "exclude_contract": c.exclude_contract}
    degree = canonical_degree(req["highest_degree"])
    education = [{"degree": degree, "field": ""}] if degree else []
    fields: dict[str, Any] = {"experience": [], "target_roles": [], "open_to": [],
                              "not_interested": [], "custom_packs": None,
                              "custom_triage_context": None}
    if jev_texts is not None:
        form = _legacy_form(jev_texts["profile_text"])
        if form is not None:
            rows = [{"degree": canonical_degree(e.get("degree")), "field": str(e.get("field") or "")}
                    for e in form["education"]]
            if degree and highest_degree(rows) == degree:
                education = rows
            fields.update(target_roles=form["target_roles"], open_to=form["open_to"],
                          not_interested=form["not_interested"],
                          experience=[{"title": str(e.get("title") or ""),
                                       "company": str(e.get("company") or ""),
                                       "years": _js_number(e.get("years") or 0)}
                                      for e in form["experience"]])
        context = {"profile_text": jev_texts["profile_text"],
                   "yoe_context": jev_texts["yoe_context"].strip()}
        probe = CandidateProfile(education=tuple(education),
                                 experience=tuple(fields["experience"]),
                                 target_roles=tuple(fields["target_roles"]),
                                 open_to=tuple(fields["open_to"]),
                                 not_interested=tuple(fields["not_interested"]))
        if form is None or not probe.target_roles or render_triage_context(probe) != context:
            fields["custom_triage_context"] = _dumps(context)
        defaults = default_packs()
        if not (_same_pack(jev_texts["c_pack"], defaults["preference_pack"])
                and _same_pack(jev_texts["yoe_pack"], defaults["yoe_pack"])):
            fields["custom_packs"] = _dumps({"preference_pack": jev_texts["c_pack"],
                                             "yoe_pack": jev_texts["yoe_pack"]})
    values = {
        "title_include": _dumps(list(cfg.title_filter)), "title_exclude": _dumps(list(cfg.title_exclude)),
        "max_age_days": int(cfg.max_age_days),
        "locations": _dumps([str(x) for x in req["locations"] if str(x).strip()]),
        "work_authorization": str(req["work_authorization"] or "").strip().lower(),
        "security_clearance": str(req["security_clearance"] or "").strip(),
        "exclude_internships": bool(req["exclude_internships"]),
        "exclude_contract": bool(req["exclude_contract"]),
        "education": _dumps(education), "experience": _dumps(fields["experience"]),
        "target_roles": _dumps(fields["target_roles"]), "open_to": _dumps(fields["open_to"]),
        "not_interested": _dumps(fields["not_interested"]),
        "custom_packs": fields["custom_packs"],
        "custom_triage_context": fields["custom_triage_context"],
    }
    empty = from_row(values) == CandidateProfile()
    return None if empty and preferences is None and jev_texts is None else values


def config_drift(cfg, p: CandidateProfile) -> list[str]:
    """The config.yaml keys that are set and differ from the stored row (ignored, logged)."""
    seeded = seed_values(cfg)
    stored_scope = {"title_filter": p.title_include, "title_exclude": p.title_exclude,
                    "max_age_days": p.max_age_days}
    drift = [k for k, v in (("title_filter", tuple(cfg.title_filter)),
                            ("title_exclude", tuple(cfg.title_exclude)),
                            ("max_age_days", cfg.max_age_days))
             if v and v != stored_scope[k]]
    if not cfg.candidate.is_empty() and seeded is not None:
        mine = from_row(seeded)
        if (mine.screen_candidate() or {}) != (p.screen_candidate() or {}):
            drift.append("candidate")
    if cfg.jev_dir:
        drift.append("jev_dir")
    return drift
