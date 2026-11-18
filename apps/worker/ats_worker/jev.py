"""JEV keep/skip filter: two native OpenRouter JEV questions per screened posting.

A posting is `skip` when the preference question (policy C) answers `weak` OR the
required-YOE side question answers `three_plus`; everything else is `keep`, including
`unknown`. The verdict only hides a row from the MCP default list; it never changes
`pipeline_status`. Measured basis: docs/SPEC.md §7.1 "JEV keep/skip filter".

Inputs are private operator files in one directory (config `jev_dir`):
  profile-binding.json  approved profile, sent verbatim as C's candidate_context
  question-pack.json    policy C pack (must contain a `preference` choice question)
  yoe-pack.json         side pack (must contain `required_yoe_for_candidate`)
  yoe-context.txt       education/experience facts sent with the YOE question
HTTP is injected; nothing here reads the environment.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .ranking.native import JevContractError, jev_question_set_from_value, validate_jev_response

REQUESTED_MODEL = "typesafe/jev-1.13"
CALL_URL = "https://openrouter.ai/api/v1/systemone"
META_URL = "https://openrouter.ai/api/v1/model/typesafe/jev-1.13"
MAX_REQUEST_BYTES = 32768
RULE_VERSION = "jev-keep-skip-v1"
PREFERENCE_Q = "preference"
YOE_Q = "required_yoe_for_candidate"
ERROR_CATEGORIES = frozenset({"provider_error", "request_too_large",
                              "invalid_response", "unknown_charge"})


class JevError(Exception):
    """One posting's assessment failed; `category` is a fixed safe code."""

    def __init__(self, category: str):
        assert category in ERROR_CATEGORIES
        super().__init__(category)
        self.category = category
        self.cost = Decimal(0)  # settled charges before the failure, for the spend cap


def enc(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class JevInputs:
    profile_text: str
    c_pack: dict
    yoe_pack: dict
    yoe_context: str

    def policy_sha(self, resolved_model: str) -> str:
        """Everything a verdict depends on; a change re-queues every posting."""
        return sha(enc({"rule": RULE_VERSION, "model": resolved_model,
                        "profile": sha(self.profile_text.encode()),
                        "c_pack": sha(enc(self.c_pack)), "yoe_pack": sha(enc(self.yoe_pack)),
                        "yoe_context": sha(self.yoe_context.encode())}))


def _pack(path: Path, required_question: str) -> dict:
    value = json.loads(path.read_bytes())
    ids = {q.id for q in jev_question_set_from_value(value).questions}
    if required_question not in ids:
        raise ValueError(f"{path.name} lacks the {required_question!r} question")
    return value


def load_inputs(directory: str | Path) -> JevInputs:
    d = Path(directory)
    return JevInputs(
        profile_text=(d / "profile-binding.json").read_text(encoding="utf-8"),
        c_pack=_pack(d / "question-pack.json", PREFERENCE_Q),
        yoe_pack=_pack(d / "yoe-pack.json", YOE_Q),
        yoe_context=(d / "yoe-context.txt").read_text(encoding="utf-8").strip(),
    )


def _wire(pack: dict) -> dict:
    return {q["id"]: {k: v for k, v in q.items() if k != "id"} for q in pack["questions"]}


def request_body(posting: dict, pack: dict, candidate_context: str) -> bytes:
    """Byte-for-byte the request shape the 2026-11 measurements used."""
    state = {"company": posting["company_name"], "title": posting["job_title"],
             "location": posting.get("location") or "",
             "job_description": posting.get("description") or "",
             "candidate_context": candidate_context}
    return enc({"model": REQUESTED_MODEL, "questions": _wire(pack), "state": state})


def decide(preference: str, required_yoe: str) -> tuple[str, list[str]]:
    reasons = []
    if preference == "weak":
        reasons.append("preference_weak")
    if required_yoe == "three_plus":
        reasons.append("required_yoe_3_plus")
    return ("skip" if reasons else "keep"), reasons


class OpenRouterClient:
    """Thin native-JEV transport. `session` is a requests-like object (injected)."""

    def __init__(self, session, api_key: str, *, timeout: float = 45.0):
        if not api_key or "\n" in api_key:
            raise ValueError("an OpenRouter API key is required")
        self._session, self._key, self._timeout = session, api_key, timeout

    def resolve_model(self) -> str:
        data = self._session.get(META_URL, timeout=self._timeout).json()["data"]
        if data.get("id") != REQUESTED_MODEL or not data.get("canonical_slug"):
            raise JevError("invalid_response")
        return data["canonical_slug"]

    def post(self, raw: bytes) -> tuple[dict, Decimal]:
        try:
            response = self._session.post(
                CALL_URL, data=raw, timeout=self._timeout, allow_redirects=False,
                headers={"Authorization": "Bearer " + self._key,
                         "Content-Type": "application/json"})
        except Exception as exc:  # noqa: BLE001 - exception text may echo request data
            name = type(exc).__name__
            if "Connect" in name:  # never reached the provider: nothing was charged
                raise JevError("provider_error") from None
            if "Timeout" in name:  # sent but unanswered: the call may have been charged
                raise JevError("unknown_charge") from None
            raise JevError("provider_error") from None
        if response.status_code != 200:
            raise JevError("provider_error")
        try:
            value = response.json()
            usage = value["usage"]
            cost = Decimal(str(usage["cost"]))
        except (ValueError, KeyError, TypeError, InvalidOperation):
            raise JevError("unknown_charge") from None
        if usage.get("is_byok", False) or not cost.is_finite() or cost < 0:
            raise JevError("unknown_charge")
        return value, cost


def assess(posting: dict, *, inputs: JevInputs, post: Callable[[bytes], tuple[dict, Decimal]],
           resolved_model: str) -> dict:
    """Ask both questions for one posting; raise JevError on any failure."""
    calls = ((inputs.c_pack, inputs.profile_text), (inputs.yoe_pack, inputs.yoe_context))
    bodies = [request_body(posting, pack, ctx) for pack, ctx in calls]
    if any(len(b) > MAX_REQUEST_BYTES for b in bodies):
        raise JevError("request_too_large")
    answers, cost = [], Decimal(0)
    for (pack, _), body in zip(calls, bodies):
        try:
            value, charge = post(body)
        except JevError as exc:
            exc.cost = cost
            raise
        cost += charge
        try:
            native = validate_jev_response(value, jev_question_set_from_value(pack),
                                           expected_model=resolved_model)
        except JevContractError:
            error = JevError("invalid_response")
            error.cost = cost
            raise error from None
        answers.append({a.question_id: a.value for a in native.answers})
    verdict, reasons = decide(answers[0][PREFERENCE_Q], answers[1][YOE_Q])
    return {"verdict": verdict, "reasons": reasons, "cost_usd": str(cost),
            "result": {"policy_c": answers[0], "yoe": answers[1]}}
