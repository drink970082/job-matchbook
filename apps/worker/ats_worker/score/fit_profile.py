"""The operator's fit vocabulary, and the provenance hashes a stored extraction is
valid against.

WHY THIS EXISTS. The fit scorer's `domain` verdict asks a model to read the operator's
own preference document and return a three-way judgment. That makes the engine
persona-shaped and puts the preference call inside the model. Here the model never sees a
preference: it is handed a closed list of concept *descriptions* and asked which ones a
duty is about. `kind` (target vs anti_target), `priority` and the bonuses stay in code and
are never sent (`concept_wire_entries` is the only thing that goes on the wire).

THE HASHES ARE THE POINT OF STEP 0. A label is only meaningful against the inputs it was
produced under, and those inputs change at different rates, so one hash over everything
would invalidate expensive human work on a cheap edit. Four, each covering exactly what
breaks when it changes:

| hash                     | covers                                   | a change means                    |
|--------------------------|------------------------------------------|-----------------------------------|
| `concept_vocab_hash`     | concept ids + descriptions               | re-run extraction                 |
| `preference_policy_hash` | kind, priority, priority levels + bonuses| re-run the policy arithmetic only |
| `profile_hash`           | `resume/personal_profile.txt`            | re-judge human graded relevance   |
| `resume_hash`            | the résumé texts                         | re-run candidate relations        |

`rubric_hash` (relation/group weights, aggregator config) is the fifth in the plan and is
deliberately NOT here: the rubric arithmetic does not exist yet (it is settled on
development data at step 6), and hashing an empty dict would stamp a hash that means
nothing. It lands with `score/rubric.py`. Nothing is lost — the layer it invalidates
(policy fixtures) is hand-written and needs no human labelling.

Canonicalization matters as much as the digest: whitespace inside a description is
collapsed and keys are sorted, so reflowing the YAML does not invalidate a corpus.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

# Reuse the loader's error type so a bad `fit_profile` block fails at startup like every
# other config mistake, rather than at the first extraction call.
from ats_worker.config import ConfigError

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*\Z")
_WS = re.compile(r"\s+")

TARGET = "target"
ANTI_TARGET = "anti_target"
_KINDS = (TARGET, ANTI_TARGET)

# A description is a sentence or two the model matches a duty against — not a document.
# Long ones cost tokens on every call and blur the boundary between neighbouring concepts.
MAX_DESCRIPTION_CHARS = 600
# Ceilings on the vocabulary itself. The hard maximum is a footgun stop, not a taste
# judgment: 100 overlapping concepts inflate every prompt, starve each class of support in
# any per-class metric, and push the model to fill all three ref slots on every duty.
DEFAULT_WARN_CONCEPTS = 20
DEFAULT_MAX_CONCEPTS = 40


@dataclass(frozen=True)
class PriorityLevel:
    """One declared tier. `rank` orders tiers (1 is best); `bonus` is what the tier is
    worth to the final ordering. Both are the operator's, and neither is assumed by the
    engine — three tiers, five, or none all work."""
    name: str
    rank: int
    bonus: float


@dataclass(frozen=True)
class Concept:
    """One entry in the closed vocabulary. `description` is the ONLY field the model ever
    sees; `kind` and `priority` are preference and stay in code."""
    id: str
    description: str
    kind: str = TARGET
    priority: str = ""  # a priority-level name; always "" when kind == ANTI_TARGET


@dataclass(frozen=True)
class FitProfile:
    concepts: list[Concept] = field(default_factory=list)
    priority_levels: dict[str, PriorityLevel] = field(default_factory=dict)
    # The tier a duty that matches no target concept votes for. Declared, because
    # "matches nothing I asked for" and "matches my lowest tier" must not collapse.
    none_level: str = "none"
    warnings: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not self.concepts

    def by_id(self, concept_id: str) -> Concept | None:
        for concept in self.concepts:
            if concept.id == concept_id:
                return concept
        return None


def _text(value, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} must be a non-empty string, got {value!r}")
    return value.strip()


def _canon(value: str) -> str:
    """Whitespace-canonical form, so a YAML reflow is not a content change."""
    return _WS.sub(" ", value).strip()


def parse_fit_profile(raw) -> FitProfile:
    """Parse and validate the `fit_profile` config block. Empty/absent -> empty profile
    (the extraction path is simply unavailable; nothing else changes).

    Structure is validated, semantics never are: the engine has no opinion about which
    concepts exist or what they are worth, only that the block is internally consistent.
    """
    if raw in (None, {}, []):
        return FitProfile()
    if not isinstance(raw, dict):
        raise ConfigError(f"fit_profile must be a mapping, got {type(raw).__name__}")

    allowed = {"concepts", "priority_levels", "none_level", "max_concepts",
               "warn_concepts", "allow_anti_target_only"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(f"unknown fit_profile key(s): {', '.join(unknown)}")

    levels = _parse_levels(raw.get("priority_levels"))
    none_level = str(raw.get("none_level") or "none")
    if levels and none_level not in levels:
        raise ConfigError(
            f"fit_profile.none_level {none_level!r} is not a declared priority level "
            f"({', '.join(sorted(levels))}). It is the tier a duty matching NO target "
            "concept votes for, so it has to exist.")

    max_concepts = int(raw.get("max_concepts") or DEFAULT_MAX_CONCEPTS)
    warn_concepts = int(raw.get("warn_concepts") or DEFAULT_WARN_CONCEPTS)
    concepts = _parse_concepts(raw.get("concepts"), levels)

    if len(concepts) > max_concepts:
        raise ConfigError(
            f"fit_profile has {len(concepts)} concepts, above max_concepts={max_concepts}. "
            "Every concept is sent on every call and competes for the same three ref "
            "slots; merge the overlapping ones or raise the ceiling deliberately.")
    warnings = []
    if len(concepts) > warn_concepts:
        warnings.append(
            f"fit_profile has {len(concepts)} concepts (warn_concepts={warn_concepts}): "
            "overlapping concepts raise mapping flip and prompt cost.")

    targets = [c for c in concepts if c.kind == TARGET]
    if not targets and not raw.get("allow_anti_target_only"):
        raise ConfigError(
            "fit_profile declares no target concepts. A vocabulary of only anti-targets "
            "can reject but never rank; set allow_anti_target_only: true if that is "
            "really what you want.")
    return FitProfile(concepts=concepts, priority_levels=levels,
                      none_level=none_level, warnings=tuple(warnings))


def _parse_levels(raw) -> dict[str, PriorityLevel]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ConfigError("fit_profile.priority_levels must be a mapping of name -> "
                          "{rank, bonus}")
    levels: dict[str, PriorityLevel] = {}
    for name, body in raw.items():
        where = f"fit_profile.priority_levels.{name}"
        if not isinstance(body, dict):
            raise ConfigError(f"{where} must be a mapping with `rank` and `bonus`")
        try:
            rank = int(body["rank"])
            bonus = float(body["bonus"])
        except KeyError as exc:
            raise ConfigError(f"{where} is missing {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{where}: rank must be an int and bonus a number") from exc
        if rank < 1:
            raise ConfigError(f"{where}.rank must be >= 1 (1 is the best tier)")
        if bonus != bonus or bonus in (float("inf"), float("-inf")):  # NaN / inf
            raise ConfigError(f"{where}.bonus must be finite")
        levels[str(name)] = PriorityLevel(name=str(name), rank=rank, bonus=bonus)
    return levels


def _parse_concepts(raw, levels: dict[str, PriorityLevel]) -> list[Concept]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError("fit_profile.concepts must be a non-empty list")
    concepts: list[Concept] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw):
        where = f"fit_profile.concepts[{i}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} must be a mapping")
        unknown = sorted(set(entry) - {"id", "description", "kind", "priority"})
        if unknown:
            raise ConfigError(f"unknown key(s) in {where}: {', '.join(unknown)}")

        concept_id = _text(entry.get("id"), f"{where}.id")
        if not _ID_RE.match(concept_id):
            raise ConfigError(
                f"{where}.id {concept_id!r} must be lowercase [a-z0-9_-] starting with a "
                "letter or digit — ids are stable keys stored on every label")
        if concept_id in seen:
            raise ConfigError(f"duplicate fit_profile concept id {concept_id!r}")
        seen.add(concept_id)

        description = _canon(_text(entry.get("description"), f"{where}.description"))
        if len(description) > MAX_DESCRIPTION_CHARS:
            raise ConfigError(
                f"{where}.description is {len(description)} chars, over the "
                f"{MAX_DESCRIPTION_CHARS} limit — it is sent on every call and a long "
                "one blurs the boundary with its neighbours")

        kind = str(entry.get("kind") or TARGET).strip()
        if kind not in _KINDS:
            raise ConfigError(f"{where}.kind must be one of {', '.join(_KINDS)}, got {kind!r}")

        priority = str(entry.get("priority") or "").strip()
        if kind == ANTI_TARGET:
            if priority:
                raise ConfigError(
                    f"{where} is an anti_target and may not carry a target priority "
                    f"({priority!r}). An anti-target is not a low tier — it wins over any "
                    "target the role also matches.")
        else:
            if not priority:
                raise ConfigError(f"{where}.priority is required for a target concept")
            if priority not in levels:
                raise ConfigError(
                    f"{where}.priority {priority!r} is not a declared priority level "
                    f"({', '.join(sorted(levels)) or 'none declared'})")
        concepts.append(Concept(id=concept_id, description=description,
                                kind=kind, priority=priority))
    return concepts


# --- provenance hashes ------------------------------------------------------------

def _digest(payload) -> str:
    """A short, stable digest of a canonicalized structure. 16 hex chars: this labels a
    corpus row, it does not authenticate anything."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def concept_vocab_hash(profile: FitProfile) -> str:
    """Covers exactly what the model is shown: each concept's id and description.

    Deliberately NOT `kind`, `priority` or bonuses — re-tagging a target as an
    anti-target does not change a single extracted duty, so it must not invalidate the
    expensive human-labelled extraction layer."""
    return _digest([[c.id, c.description] for c in sorted(profile.concepts, key=lambda c: c.id)])


def preference_policy_hash(profile: FitProfile) -> str:
    """Covers the preference half the model never sees: kind, priority, the declared
    tiers and their bonuses. A change here means re-deriving the arithmetic, not
    re-labelling."""
    return _digest({
        "concepts": [[c.id, c.kind, c.priority]
                     for c in sorted(profile.concepts, key=lambda c: c.id)],
        "levels": [[lvl.name, lvl.rank, lvl.bonus]
                   for lvl in sorted(profile.priority_levels.values(), key=lambda x: x.name)],
        "none_level": profile.none_level,
    })


def profile_hash(profile_text: str) -> str:
    """Covers `resume/personal_profile.txt`. The extractor never reads it — this stamps
    the HUMAN labelling layer, whose graded-relevance judgments are made by a person
    reading that document."""
    return _digest(_canon(str(profile_text or "")))


def resume_hash(resumes: dict) -> str:
    """Covers the résumé texts, which are what candidate relations are relations TO."""
    return _digest({str(k): _canon(str(v or "")) for k, v in (resumes or {}).items()})


def provenance(profile: FitProfile, *, profile_text: str = "", resumes: dict | None = None) -> dict:
    """The stamp every extraction record and every corpus row carries.

    Stored as a flat dict rather than a single string so a consumer can say WHICH input
    moved — the whole reason there is more than one hash.
    """
    return {
        "concept_vocab_hash": concept_vocab_hash(profile),
        "preference_policy_hash": preference_policy_hash(profile),
        "profile_hash": profile_hash(profile_text),
        "resume_hash": resume_hash(resumes or {}),
    }
