"""Bounded fit EXTRACTION: schema, prompt assembly, validation, evidence verification.

SHADOW ONLY. Nothing here is imported by `pipeline.py` or `run.py`, and that is a
CORRECTNESS requirement, not caution. The live fit call's response carries a secondary
`screen` block that `merge_fallback_screen` uses to refill a degree/clearance check
`demote_for_confirmation` deliberately removed; replacing that response with an
extraction record would leave the refill with nothing to read and materialize a pass
verdict out of a blind check. The current scorer keeps deciding score, domain and the
gate until the rebuild's single cutover (step 7 of
docs/superpowers/plans/2026-08-03-fit-scoring-rebuild.md). This module writes no status,
no gate input, and never touches `score_detail`.

WHAT MAKES IT DIFFERENT FROM `score.txt`. Three things, and each one closes a measured
failure:

1. **The model never sees a preference.** It is handed opaque refs and concept
   DESCRIPTIONS (`fit_profile.py`) and asked which ones a duty is about. Priority, kind
   and every bonus stay in code. If the model emitted the tier directly, this would be
   today's `domain` verdict with new field names and its flip would survive the rename.
2. **The vocabulary is closed and validated.** `_normalize_extraction` raises on any
   out-of-enum value or unknown ref, so a drift in what the model answers is a loud
   failure rather than a silently mis-parsed record — today's free-text `BACKGROUND:`
   field runs 17% off-vocabulary across 501 rows with nothing noticing.
3. **Evidence survives a code check.** Every item quotes the posting verbatim and code
   confirms the quote is there, generalizing the shipped sponsorship-quote mechanism.

REFS ARE MINTED PER RUN, NOT PER REQUEST. The design record calls for a throwaway ref per
request so a stable id (`t_ml_platform`) cannot leak its own kind to the model — but a
per-request ref also changes the system prefix on every call, which breaks the
byte-identical `cache_control: ephemeral` prefix in `prompts.py` and costs one of the two
named token levers. Per-RUN minting gets the whole benefit (refs are opaque, the order is
shuffled, nothing is positional, and the mapping is not reused across runs) at no cache
cost, because every call in a run shares one prefix.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata

from ats_worker.prompts import EXTRACT_HEADER
from ._batch import align_results
from .backends_claude_cli import claude_json
from .backends_codex import codex_json
from .errors import ScoreError
from .fit_profile import FitProfile
from .prompts import _job_block

# The closed vocabularies. Out-of-enum raises: see the module docstring, point 2.
IMPORTANCE = ("core", "supporting", "incidental")
RELATIONS = ("direct_match", "adjacent_match", "weak_match", "missing", "unknown")
MAPPING_STATUS = ("mapped", "none", "uncertain")
REQUIREMENT_TYPES = ("eligibility", "credential", "skill", "experience")

# Relations that assert the résumé shows something, and therefore owe a quote. `missing`
# and `unknown` assert the opposite and must carry none.
EVIDENCED_RELATIONS = ("direct_match", "adjacent_match", "weak_match")

# Item caps. These bound the coverage denominator against fragmentation (splitting one
# duty into four is otherwise a way to move a weighted ratio) as much as they bound cost.
MAX_DUTIES = 5
MAX_QUALIFICATIONS = 8
MAX_NICE_TO_HAVES = 5
MAX_REFS = 3

_WS = re.compile(r"\s+")
# Unicode punctuation a model normalizes away when it "copies verbatim". Quote checking
# has to survive that or the check fails on correct answers, which teaches nothing.
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = {**dict.fromkeys(map(ord, "‘’‛′"), "'"),
           **dict.fromkeys(map(ord, "“”‟″"), '"')}


def normalize_quote(text: str) -> str:
    """Fold the differences a faithful copy can still introduce: unicode form, smart
    dashes and quotes, case, and whitespace runs (a JD's line breaks land mid-sentence).
    Everything else — wording, punctuation, order — must match, so a paraphrase still
    fails."""
    folded = unicodedata.normalize("NFKC", str(text or ""))
    folded = folded.translate(_DASHES).translate(_QUOTES)
    return _WS.sub(" ", folded).strip().casefold()


# --- concept refs -----------------------------------------------------------------

def mint_refs(profile: FitProfile, run_token: str) -> tuple[list[dict], dict]:
    """Mint one opaque ref per concept for a run, and shuffle the order.

    Returns `(wire_entries, ref_to_id)` — the entries are exactly what goes on the wire
    (`ref` + `description`, never `kind`, `priority` or the stable id), and the mapping is
    how an answer comes back. Deterministic in `run_token` so a shadow run is
    reproducible from its artifact; opaque because a ref that reads like `t_ml_platform`
    hands the model the preference this design exists to withhold.
    """
    entries: list[dict] = []
    ref_to_id: dict[str, str] = {}
    for concept in profile.concepts:
        for salt in range(64):  # a 2-byte ref collides at ~0.3% over 20 concepts
            seed = f"{run_token}:{concept.id}:{salt}".encode("utf-8")
            ref = "c_" + hashlib.blake2s(seed, digest_size=2).hexdigest()
            if ref not in ref_to_id:
                break
        else:  # pragma: no cover - 64 consecutive collisions is not reachable in practice
            raise ScoreError(f"could not mint a unique ref for concept {concept.id!r}")
        ref_to_id[ref] = concept.id
        entries.append({"ref": ref, "description": concept.description})
    random.Random(run_token).shuffle(entries)
    return entries, ref_to_id


def concept_block(entries: list[dict]) -> str:
    """The `=== CONCEPTS ===` section: refs and descriptions, nothing else."""
    lines = [f"{entry['ref']}: {entry['description']}" for entry in entries]
    return "=== CONCEPTS ===\n" + "\n".join(lines)


def extractor_system_sections(entries: list[dict], resumes: dict) -> list[str]:
    """The system prefix for the extraction call: rubric header, the concept list, then
    one section per labeled résumé version.

    NO PERSONAL PROFILE. That omission is the design — `personal_profile.txt` is the
    operator's preferences, and this call must not be able to read them.
    """
    return [EXTRACT_HEADER, concept_block(entries),
            *(f"=== RESUME ({label}) ===\n{text}" for label, text in resumes.items())]


# --- schema -----------------------------------------------------------------------

def _evidence_schema(nullable: bool) -> dict:
    return {
        "type": ["object", "null"] if nullable else "object",
        "properties": {"quote": {"type": "string"}, "source": {"type": "string"}},
        "required": ["quote", "source"],
        "additionalProperties": False,
    }


def _relations_schema(resume_labels: list) -> dict:
    """One relation record PER RÉSUMÉ, rather than one relation plus a
    `recommended_resume` the model picks.

    With a single relation field the model can cite résumé A on one duty and résumé B on
    the next, producing a composite fit no single résumé earns — detectable only after
    the fact. A per-résumé map makes the mixing structurally impossible instead: code
    scores each version independently and takes the argmax, so the recommendation is a
    derivation, not a model output.
    """
    per_resume = {
        "type": "object",
        "properties": {
            "relation": {"type": "string", "enum": list(RELATIONS)},
            "resume_evidence": _evidence_schema(nullable=True),
        },
        "required": ["relation", "resume_evidence"],
        "additionalProperties": False,
    }
    labels = [str(label) for label in resume_labels]
    return {
        "type": "object",
        "properties": {label: json.loads(json.dumps(per_resume)) for label in labels},
        "required": labels,
        "additionalProperties": False,
    }


def _item_schema(refs: list[str], resume_labels: list, *, kind: str) -> dict:
    """One extracted item. `kind` picks the JD-side half: duties carry importance and a
    concept mapping, requirements carry a requirement_type."""
    properties: dict = {}
    if kind == "duty":
        properties["label"] = {"type": "string"}
        properties["importance"] = {"type": "string", "enum": list(IMPORTANCE)}
        properties["concept_mapping"] = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": list(MAPPING_STATUS)},
                # Enum-constrained to the refs minted for THIS run, so a schema-enforcing
                # backend cannot invent one. `_normalize_extraction` re-checks anyway —
                # the check has to hold on a backend that ignores the schema too.
                "refs": {"type": "array", "items": {"type": "string", "enum": list(refs)}},
            },
            "required": ["status", "refs"],
            "additionalProperties": False,
        }
    else:
        properties["requirement"] = {"type": "string"}
        properties["requirement_type"] = {"type": "string", "enum": list(REQUIREMENT_TYPES)}
    properties["job_evidence"] = _evidence_schema(nullable=False)
    properties["resume_relations"] = _relations_schema(resume_labels)
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def extraction_schema(refs: list[str], resume_labels: list) -> dict:
    """The structured-output schema handed to the CLI.

    Absent by design: no score, no confidence, no target_priority, no anti_target, no
    evidence_coverage, no recommended_resume. Every number in this system is computed in
    code from these categories — `SCORING 9.1` is the measurement that closed that
    question.
    """
    return {
        "type": "object",
        "properties": {
            "duties": {"type": "array", "items": _item_schema(refs, resume_labels, kind="duty")},
            "required_qualifications": {
                "type": "array", "items": _item_schema(refs, resume_labels, kind="requirement")},
            "nice_to_haves": {
                "type": "array", "items": _item_schema(refs, resume_labels, kind="requirement")},
            "summary": {"type": "string"},
            "insufficient_context": {"type": "boolean"},
        },
        "required": ["duties", "required_qualifications", "nice_to_haves",
                     "summary", "insufficient_context"],
        "additionalProperties": False,
    }


def batch_extraction_schema(refs: list[str], resume_labels: list) -> dict:
    """The `{"results":[...]}` envelope with a `job_ref` tag, matching what the two CLI
    fit backends already send — so `_batch.align_results` realigns an extraction batch by
    the same rule and a mis-attributed record fails the batch loudly."""
    element = extraction_schema(refs, resume_labels)
    element["properties"]["job_ref"] = {"type": "integer"}
    element["required"].append("job_ref")
    return {
        "type": "object",
        "properties": {"results": {"type": "array", "items": element}},
        "required": ["results"],
        "additionalProperties": False,
    }


# --- validation -------------------------------------------------------------------

def _enum(value, allowed, where: str) -> str:
    text = str(value or "").strip()
    if text not in allowed:
        raise ScoreError(f"{where} {text!r} not one of {', '.join(allowed)}")
    return text


def _evidence(value, where: str, *, required: bool):
    if value in (None, {}):
        if required:
            raise ScoreError(f"{where} is required for this relation")
        return None
    if not isinstance(value, dict):
        raise ScoreError(f"{where} must be an object or null: {value!r}")
    quote = str(value.get("quote") or "").strip()
    if not quote:
        if required:
            raise ScoreError(f"{where}.quote is empty")
        return None
    return {"quote": quote, "source": str(value.get("source") or "").strip()}


def _relations(value, resume_labels: list, where: str) -> dict:
    if not isinstance(value, dict):
        raise ScoreError(f"{where} must be an object keyed by résumé label: {value!r}")
    out = {}
    for label in resume_labels:
        entry = value.get(label)
        if not isinstance(entry, dict):
            raise ScoreError(f"{where}.{label} missing — every résumé version needs its "
                             "own relation, so no version can answer for another")
        relation = _enum(entry.get("relation"), RELATIONS, f"{where}.{label}.relation")
        evidence = _evidence(entry.get("resume_evidence"), f"{where}.{label}.resume_evidence",
                             required=relation in EVIDENCED_RELATIONS)
        out[label] = {"relation": relation, "resume_evidence": evidence}
    return out


def _item(raw, i: int, *, kind: str, group: str, ref_to_id: dict, resume_labels: list) -> dict:
    where = f"{group}[{i}]"
    if not isinstance(raw, dict):
        raise ScoreError(f"{where} must be an object: {raw!r}")
    item: dict = {}
    if kind == "duty":
        item["label"] = str(raw.get("label") or "").strip()
        item["importance"] = _enum(raw.get("importance"), IMPORTANCE, f"{where}.importance")
        item["concept_mapping"] = _mapping(raw.get("concept_mapping"), ref_to_id,
                                           f"{where}.concept_mapping")
    else:
        item["requirement"] = str(raw.get("requirement") or "").strip()
        if not item["requirement"]:
            raise ScoreError(f"{where}.requirement is empty")
        item["requirement_type"] = _enum(raw.get("requirement_type"), REQUIREMENT_TYPES,
                                         f"{where}.requirement_type")
    item["job_evidence"] = _evidence(raw.get("job_evidence"), f"{where}.job_evidence",
                                     required=True)
    item["resume_relations"] = _relations(raw.get("resume_relations"), resume_labels,
                                          f"{where}.resume_relations")
    return item


def _mapping(raw, ref_to_id: dict, where: str) -> dict:
    """Validate the concept mapping and translate wire refs back to stable concept ids.

    `status` is an explicit field rather than a sentinel id ("none" / "uncertain" posing
    as a concept) so id validation, hashing and the aggregator have no special branches —
    and the consistency rule below is checkable at all.
    """
    if not isinstance(raw, dict):
        raise ScoreError(f"{where} must be an object: {raw!r}")
    status = _enum(raw.get("status"), MAPPING_STATUS, f"{where}.status")
    refs = raw.get("refs") or []
    if not isinstance(refs, list):
        raise ScoreError(f"{where}.refs must be a list: {refs!r}")
    if len(refs) > MAX_REFS:
        raise ScoreError(f"{where}.refs holds {len(refs)} refs, over the {MAX_REFS} cap")
    ids = []
    for ref in refs:
        concept_id = ref_to_id.get(str(ref))
        if concept_id is None:
            raise ScoreError(f"{where}.refs names {ref!r}, which was not minted for this run")
        if concept_id not in ids:
            ids.append(concept_id)
    if status == "mapped" and not ids:
        raise ScoreError(f"{where}.status is 'mapped' with no refs")
    if status == "none" and ids:
        raise ScoreError(f"{where}.status is 'none' but carries refs {ids}")
    return {"status": status, "concept_ids": ids}


def _group(raw, *, kind: str, group: str, cap: int, ref_to_id: dict,
           resume_labels: list) -> list[dict]:
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ScoreError(f"{group} must be a list: {raw!r}")
    if len(raw) > cap:
        # Truncating silently would make the coverage denominator a function of how
        # verbose the model felt. Fail instead — the cap is in the prompt AND the schema.
        raise ScoreError(f"{group} holds {len(raw)} items, over the {cap} cap")
    return [_item(entry, i, kind=kind, group=group, ref_to_id=ref_to_id,
                  resume_labels=resume_labels)
            for i, entry in enumerate(raw)]


def normalize_extraction(data, *, ref_to_id: dict, resume_labels: list) -> dict:
    """Validate one extraction record and translate refs to stable concept ids.

    Raises `ScoreError` on anything out-of-vocabulary, over a cap, referring to an
    unminted ref, or internally inconsistent. Loud, because the whole value of a closed
    vocabulary is that a drift in the answer cannot be absorbed silently.
    """
    if not isinstance(data, dict):
        raise ScoreError(f"extraction response was not an object: {data!r}")
    labels = [str(label) for label in resume_labels]
    return {
        "duties": _group(data.get("duties"), kind="duty", group="duties",
                         cap=MAX_DUTIES, ref_to_id=ref_to_id, resume_labels=labels),
        "required_qualifications": _group(
            data.get("required_qualifications"), kind="requirement",
            group="required_qualifications", cap=MAX_QUALIFICATIONS,
            ref_to_id=ref_to_id, resume_labels=labels),
        "nice_to_haves": _group(
            data.get("nice_to_haves"), kind="requirement", group="nice_to_haves",
            cap=MAX_NICE_TO_HAVES, ref_to_id=ref_to_id, resume_labels=labels),
        # Display only — no rule may read it (notify.py's `Fit:` line is its consumer).
        "summary": str(data.get("summary") or "").strip(),
        "insufficient_context": bool(data.get("insufficient_context")),
    }


# --- evidence verification --------------------------------------------------------

_GROUPS = ("duties", "required_qualifications", "nice_to_haves")


def verify_evidence(record: dict, job_text: str, resumes: dict) -> dict:
    """Check every quote against the text it claims to come from, and apply the two rules
    that are NOT symmetric.

    THE TWO SIDES FAIL DIFFERENTLY, and one rule for both gets one of them backwards:

    - **A job-side quote that is not in the posting means the model may have invented the
      requirement itself.** The item is DROPPED. It never lowers the candidate's score —
      penalising a candidate for a requirement the model made up is the worst outcome
      available here. When the invented item was a core duty or a required qualification
      that is *material*, and the record says so, because a record built on invention
      should be re-derived rather than quietly scored.
    - **A résumé-side quote that is not in the résumé means the requirement is real and
      the claimed candidate evidence is not.** The item is KEPT, its relation is marked
      unverified, and it stays in the denominator: this is exactly the "invented a
      capability" failure the extraction is meant to catch, so it must cost the score
      rather than disappear from it.

    Returns a new record: verified items in place, dropped ones under `dropped_items`,
    and the counters the eval reads under `evidence`.
    """
    job_norm = normalize_quote(job_text)
    resume_norm = {str(label): normalize_quote(text) for label, text in (resumes or {}).items()}

    out = dict(record)
    dropped: list[dict] = []
    material_failure = False
    checked = unverified_resume = 0

    for group in _GROUPS:
        kept = []
        for item in record.get(group) or []:
            checked += 1
            quote = normalize_quote((item.get("job_evidence") or {}).get("quote", ""))
            if not quote or quote not in job_norm:
                is_material = (group == "required_qualifications"
                               or item.get("importance") == "core")
                material_failure = material_failure or is_material
                dropped.append({"group": group, "item": item, "material": is_material,
                                "reason": "job_evidence_not_in_posting"})
                continue
            item = dict(item)
            item["resume_relations"] = {
                label: _verify_relation(entry, resume_norm.get(label, ""))
                for label, entry in (item.get("resume_relations") or {}).items()}
            unverified_resume += sum(
                1 for entry in item["resume_relations"].values()
                if entry.get("resume_evidence") is not None
                and not entry.get("resume_evidence_verified"))
            kept.append(item)
        out[group] = kept

    out["dropped_items"] = dropped
    out["evidence"] = {
        "items_checked": checked,
        "job_quote_failures": len(dropped),
        "material_job_quote_failure": material_failure,
        "resume_quote_failures": unverified_resume,
    }
    return out


def make_extractor(profile: FitProfile, run_token: str, *, backend: str, model: str,
                   timeout: int = 600, **backend_kwargs):
    """Build an `extract(postings, resumes) -> list[dict]` callable for a shadow run.

    Refs are minted ONCE here, so every call in the run shares one system prefix (see the
    module docstring on why per-run beats per-request). The mapping and the wire entries
    hang off the returned callable as `ref_to_id` / `concept_entries` so the run's
    artifact can record exactly what the model was shown — without that, a stored record
    naming `ml_platform` cannot be re-checked against the list that produced it.

    `backend` is `codex` or `claude`; both go through the tool-less CLI invocation the
    production fit backends use. There is no Ollama path yet: the local model is a step-8
    candidate and gets measured on this corpus, not assumed into it.
    """
    runners = {"codex": codex_json, "claude": claude_json}
    if backend not in runners:
        raise ScoreError(f"unknown extraction backend {backend!r}; expected "
                         f"{' or '.join(sorted(runners))}")
    if profile.is_empty():
        raise ScoreError("extraction needs a `fit_profile` block in config.yaml — the "
                         "concept vocabulary IS the task")
    entries, ref_to_id = mint_refs(profile, run_token)
    refs = [entry["ref"] for entry in entries]
    run_cli = runners[backend]

    def extract(postings: list[dict], resumes: dict) -> list[dict]:
        labels = [str(label) for label in resumes]
        # Same JOB block as the fit call: no truncation, no Location line — geography is
        # the screen's business and must not reach a fit judgment.
        blocks = [f"=== JOB job_ref={posting['id']} ===\n"
                  + _job_block(posting, 0, include_location=False)
                  for posting in postings]
        prompt = "\n\n".join([*extractor_system_sections(entries, resumes), *blocks])
        data = run_cli(prompt, batch_extraction_schema(refs, labels),
                       model=model, timeout=timeout, **backend_kwargs)
        aligned = align_results(data, postings, backend=backend)
        return [verify_evidence(
            normalize_extraction(raw, ref_to_id=ref_to_id, resume_labels=labels),
            posting.get("description", ""), resumes)
            for posting, raw in zip(postings, aligned)]

    extract.ref_to_id = dict(ref_to_id)
    extract.concept_entries = list(entries)
    return extract


def _verify_relation(entry: dict, resume_norm: str) -> dict:
    """Mark whether this résumé-side quote is actually in that résumé. The relation is
    left untouched: the arithmetic decides what an unverified claim is worth, and it must
    be able to tell an unverified `direct_match` from an honest `missing`."""
    entry = dict(entry)
    evidence = entry.get("resume_evidence")
    if evidence is None:
        entry["resume_evidence_verified"] = None  # nothing was claimed
        return entry
    quote = normalize_quote(evidence.get("quote", ""))
    entry["resume_evidence_verified"] = bool(quote and resume_norm and quote in resume_norm)
    return entry
