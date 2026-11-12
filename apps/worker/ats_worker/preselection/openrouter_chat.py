"""Injected direct-only OpenRouter Chat Completions transport for generic assessments.

The adapter makes one bounded request through an injected HTTP client. It asks for source
quotes rather than offsets, resolves exact unique spans locally, and leaves the existing
generic shadow validator responsible for the final assessment contract.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from typing import Any

from ats_worker.preselection.openrouter_jev import (
    JevTransportError,
    _check_json_depth,
    _decimal_text,
    _parse_json_body,
    _reject_duplicate_members,
)
from ats_worker.preselection.questions import (
    QuestionContractError,
    QuestionSet,
    question_set_from_value,
    validate_assessment_payload,
)
from ats_worker.preselection.shadow import (
    ASSESSMENT_PROMPT_VERSION,
    ASSESSMENT_SCHEMA_VERSION,
    ASSESSMENT_SYSTEM_PROMPT,
    Charge,
    Invocation,
    ModelIdentity,
    ProviderFailure,
    ProviderReply,
    Usage,
)


CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUESTED_MODEL = "anthropic/claude-haiku-5.5"
RESOLVED_MODEL = "anthropic/claude-haiku-5.5-20261007"
MODEL_IDENTITY = ModelIdentity("openrouter-chat-completions", REQUESTED_MODEL, RESOLVED_MODEL)
EXPECTED_RESPONSE_MODELS = frozenset({REQUESTED_MODEL, RESOLVED_MODEL})
REPORTED_COST_SOURCE = "openrouter.response.usage.cost"
CHAT_EVIDENCE_NOTE = (
    "For evidence, return source plus one unique exact quote only; no paraphrase, ellipsis, "
    "or offsets. Offsets are derived locally."
)
MAX_REQUEST_BYTES = 24_000
MAX_RESPONSE_BYTES = 128_000
TIMEOUT_SECONDS = 45.0
MAX_COMPLETION_TOKENS = 2048
_MAX_REQUEST_STRING_CHARS = MAX_REQUEST_BYTES


class OpenRouterChatError(ValueError):
    """A selected invocation cannot be serialized to the fixed Haiku route."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _bounded_string_budget(value: Any, *, budget: list[int], depth: int = 0) -> None:
    if depth > 32:
        raise OpenRouterChatError("openrouter_request_complexity_invalid")
    budget[1] += 1
    if budget[1] > 8192:
        raise OpenRouterChatError("openrouter_request_complexity_invalid")
    if isinstance(value, str):
        budget[0] += len(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise OpenRouterChatError("openrouter_request_invalid")
            budget[0] += len(key)
            _bounded_string_budget(item, budget=budget, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _bounded_string_budget(item, budget=budget, depth=depth + 1)
    elif value is None or isinstance(value, (bool, int, float)):
        return
    else:
        raise OpenRouterChatError("openrouter_request_invalid")
    if budget[0] > _MAX_REQUEST_STRING_CHARS:
        raise OpenRouterChatError("openrouter_request_too_large")


def _direct_inputs(invocation: Any) -> tuple[QuestionSet, dict[str, Any]]:
    if type(invocation) is not Invocation:
        raise OpenRouterChatError("openrouter_invocation_invalid")
    if invocation.stage != "assess" or invocation.variant != "direct":
        raise OpenRouterChatError("openrouter_direct_assessment_required")
    if (
        invocation.prompt_version != ASSESSMENT_PROMPT_VERSION
        or invocation.schema_version != ASSESSMENT_SCHEMA_VERSION
        or invocation.system_prompt != ASSESSMENT_SYSTEM_PROMPT
    ):
        raise OpenRouterChatError("openrouter_contract_version_mismatch")
    if invocation.model_identity != MODEL_IDENTITY:
        raise OpenRouterChatError("openrouter_model_identity_mismatch")
    if (
        not isinstance(invocation.request_identity, str)
        or len(invocation.request_identity) != 64
        or any(char not in "0123456789abcdef" for char in invocation.request_identity)
        or not isinstance(invocation.work_item_identity_sha256, str)
        or len(invocation.work_item_identity_sha256) != 64
        or any(char not in "0123456789abcdef" for char in invocation.work_item_identity_sha256)
        or type(invocation.draw_number) is not int
        or invocation.draw_number <= 0
    ):
        raise OpenRouterChatError("openrouter_invocation_invalid")
    payload = invocation.payload
    if not isinstance(payload, dict) or set(payload) != {
        "company", "title", "location", "candidate_context", "questions", "job_description"
    }:
        raise OpenRouterChatError("openrouter_direct_payload_invalid")
    if any(not isinstance(payload[field], str) for field in (
        "company", "title", "location", "candidate_context", "job_description"
    )):
        raise OpenRouterChatError("openrouter_direct_payload_invalid")
    if not payload["company"].strip() or not payload["title"].strip() or not payload["job_description"].strip():
        raise OpenRouterChatError("openrouter_direct_payload_invalid")
    budget = [0, 0]
    _bounded_string_budget(invocation.system_prompt, budget=budget)
    _bounded_string_budget(payload, budget=budget)
    try:
        question_set = question_set_from_value({
            # Invocation carries the validated question values but not the original set
            # version. The answer schema is version independent and is checked below.
            "version": "generic-transport-schema-v1",
            "questions": payload["questions"],
        })
    except (QuestionContractError, OverflowError, RecursionError):
        raise OpenRouterChatError("openrouter_question_set_invalid") from None
    if invocation.output_schema != question_set.answer_schema():
        raise OpenRouterChatError("openrouter_output_schema_mismatch")
    _bounded_string_budget(invocation.output_schema, budget=budget)
    return question_set, payload


def _refined_output_schema(question_set: QuestionSet) -> dict[str, Any]:
    schema = deepcopy(question_set.answer_schema())
    evidence_item = {
        "type": "object",
        "additionalProperties": False,
        "required": ["source", "quote"],
        "properties": {
            "source": {"type": "string", "enum": ["jd", "candidate_context"]},
            "quote": {"type": "string", "minLength": 1},
        },
    }
    for answer in schema["properties"]["answers"]["properties"].values():
        answer["properties"]["evidence"]["items"] = deepcopy(evidence_item)
    return schema


def build_openrouter_chat_request(invocation: Invocation) -> bytes:
    """Build exact bounded request bytes without accessing a key or network."""
    question_set, payload = _direct_inputs(invocation)
    request = {
        "model": REQUESTED_MODEL,
        "messages": [
            {
                "role": "system",
                "content": invocation.system_prompt + "\n\n" + CHAT_EVIDENCE_NOTE,
            },
            {
                "role": "user",
                "content": json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            },
        ],
        "max_tokens": MAX_COMPLETION_TOKENS,
        "stream": False,
        "n": 1,
        "tool_choice": "none",
        "reasoning": {"enabled": False},
        "provider": {
            "only": ["anthropic"],
            "allow_fallbacks": False,
            "require_parameters": True,
        },
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "ats_typed_assessment",
                "strict": True,
                "schema": _refined_output_schema(question_set),
            },
        },
    }
    try:
        body = json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise OpenRouterChatError("openrouter_request_invalid") from None
    if len(body) > MAX_REQUEST_BYTES:
        raise OpenRouterChatError("openrouter_request_too_large")
    return body


def _unique_quote_span(source_text: str, quote: Any) -> tuple[int, int]:
    if not isinstance(quote, str) or not quote:
        raise QuestionContractError("evidence quote must be non-empty text")
    start = source_text.find(quote)
    if start < 0 or source_text.find(quote, start + 1) >= 0:
        raise QuestionContractError("evidence quote must match one unique source span")
    return start, start + len(quote)


def _normalise_assessment(
    value: Any,
    question_set: QuestionSet,
    *,
    job_description: str,
    candidate_context: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"answers", "explanation"}:
        raise QuestionContractError("assessment shape differs from the generic contract")
    answers = value["answers"]
    if not isinstance(answers, dict) or set(answers) != {question.id for question in question_set.questions}:
        raise QuestionContractError("assessment answer IDs differ from the generic contract")
    normalised_answers: dict[str, Any] = {}
    source_texts = {"jd": job_description, "candidate_context": candidate_context}
    for question in question_set.questions:
        raw_answer = answers[question.id]
        if not isinstance(raw_answer, dict) or set(raw_answer) != {"value", "evidence"}:
            raise QuestionContractError("assessment answer shape differs from the generic contract")
        evidence = raw_answer["evidence"]
        if not isinstance(evidence, list):
            raise QuestionContractError("assessment evidence must be an array")
        normalised_evidence = []
        for raw_reference in evidence:
            if not isinstance(raw_reference, dict) or set(raw_reference) != {"source", "quote"}:
                raise QuestionContractError("evidence must contain only a source and exact quote")
            source = raw_reference["source"]
            if source not in source_texts:
                raise QuestionContractError("evidence source is unavailable in the direct invocation")
            start, end = _unique_quote_span(source_texts[source], raw_reference["quote"])
            normalised_evidence.append({
                "source": source,
                "start": start,
                "end": end,
                "quote": raw_reference["quote"],
            })
        normalised_answers[question.id] = {
            "value": raw_answer["value"],
            "evidence": normalised_evidence,
        }
    normalised = {"answers": normalised_answers, "explanation": value["explanation"]}
    validate_assessment_payload(
        normalised,
        question_set,
        variant="direct",
        job_description=job_description,
        candidate_context=candidate_context,
    )
    return normalised


def _usage_and_charge(raw_response: dict[str, Any], rate_date: str) -> tuple[Usage, Charge]:
    usage_data = raw_response.get("usage")
    if not isinstance(usage_data, dict):
        return Usage(None, None, None), Charge.unknown()

    def token_count(value: Any) -> int | None:
        return value if type(value) is int and value >= 0 else None

    prompt_details = usage_data.get("prompt_tokens_details")
    cached = prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None
    usage = Usage(
        token_count(usage_data.get("prompt_tokens")),
        token_count(usage_data.get("completion_tokens")),
        token_count(cached),
    )
    cost = _decimal_text(usage_data.get("cost"))
    charge = (
        Charge("actual", cost, "USD", "request", rate_date, REPORTED_COST_SOURCE)
        if cost is not None
        else Charge.unknown()
    )
    return usage, charge


class OpenRouterChatTransport:
    """One injected synchronous request; caller HTTP configuration must disable retries."""

    def __init__(self, *, http: Any, api_key: str, rate_date: str) -> None:
        if not callable(getattr(http, "post", None)):
            raise ValueError("OpenRouter Chat requires an injected HTTP POST function")
        if (
            not isinstance(api_key, str)
            or not api_key.strip()
            or api_key.strip() != api_key
            or len(api_key) > 4096
            or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in api_key)
        ):
            raise ValueError("OpenRouter Chat requires an injected API key")
        try:
            if not isinstance(rate_date, str) or date.fromisoformat(rate_date).isoformat() != rate_date:
                raise ValueError
        except ValueError:
            raise ValueError("OpenRouter Chat rate_date must be an ISO calendar date") from None
        self._http = http
        self._api_key = api_key
        self._rate_date = rate_date

    def __repr__(self) -> str:
        return "OpenRouterChatTransport(credentials hidden)"

    @staticmethod
    def _provider_failure(
        error_code: str,
        *,
        model_identity: ModelIdentity | None,
        usage: Usage | None = None,
        charge: Charge | None = None,
        delivery: str = "not_sent",
        circuit_breaker: bool = False,
    ) -> ProviderFailure:
        return ProviderFailure(
            error_code=error_code,
            retryable=False,
            delivery=delivery,
            model_identity=model_identity,
            usage=usage or Usage(None, None, None),
            charge=charge or Charge.unknown(),
            circuit_breaker=circuit_breaker,
        )

    def complete(self, invocation: Invocation) -> ProviderReply:
        try:
            body = build_openrouter_chat_request(invocation)
        except OpenRouterChatError as exc:
            identity = getattr(invocation, "model_identity", None)
            if not isinstance(identity, ModelIdentity):
                identity = MODEL_IDENTITY
            raise self._provider_failure(exc.error_code, model_identity=identity) from None

        try:
            response = self._http.post(
                CHAT_COMPLETIONS_URL,
                data=body,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=TIMEOUT_SECONDS,
                allow_redirects=False,
                stream=True,
            )
        except Exception:
            raise self._provider_failure(
                "openrouter_delivery_unknown",
                model_identity=MODEL_IDENTITY,
                delivery="unknown",
            ) from None

        status = getattr(response, "status_code", None)
        if type(status) is not int or status != 200:
            error_usage = Usage(None, None, None)
            error_charge = Charge.unknown()
            try:
                error_response = _parse_json_body(response, MAX_RESPONSE_BYTES)
                error_usage, error_charge = _usage_and_charge(error_response, self._rate_date)
            except JevTransportError:
                pass
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            raise self._provider_failure(
                "openrouter_http_rejected",
                model_identity=MODEL_IDENTITY,
                usage=error_usage,
                charge=error_charge,
                delivery="unknown",
            )
        try:
            raw_response = _parse_json_body(response, MAX_RESPONSE_BYTES)
        except JevTransportError:
            raise self._provider_failure(
                "openrouter_response_unavailable",
                model_identity=MODEL_IDENTITY,
                delivery="completed",
            ) from None
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        usage, charge = _usage_and_charge(raw_response, self._rate_date)

        def invalid(code: str, *, breaker: bool = False) -> ProviderFailure:
            return self._provider_failure(
                code,
                model_identity=MODEL_IDENTITY,
                usage=usage,
                charge=charge,
                delivery="completed",
                circuit_breaker=breaker,
            )

        if raw_response.get("provider") != "Anthropic":
            raise invalid("openrouter_provider_mismatch", breaker=True)
        response_model = raw_response.get("model")
        if not isinstance(response_model, str) or response_model not in EXPECTED_RESPONSE_MODELS:
            raise invalid("openrouter_response_model_mismatch", breaker=True)
        choices = raw_response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise invalid("openrouter_response_cardinality_invalid")
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            raise invalid("openrouter_finish_reason_invalid")
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise invalid("openrouter_message_invalid")
        refusal = message.get("refusal")
        if refusal not in (None, ""):
            raise invalid("openrouter_refusal")
        tool_calls = message.get("tool_calls")
        if tool_calls not in (None, []):
            raise invalid("openrouter_tool_call_rejected")
        content = message.get("content")
        if not isinstance(content, str):
            raise invalid("openrouter_content_invalid")
        try:
            if len(content.encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise invalid("openrouter_content_invalid")
            parsed = json.loads(content, object_pairs_hook=_reject_duplicate_members)
            _check_json_depth(parsed)
            question_set, payload = _direct_inputs(invocation)
            normalized = _normalise_assessment(
                parsed,
                question_set,
                job_description=payload["job_description"],
                candidate_context=payload["candidate_context"],
            )
        except (JevTransportError, OpenRouterChatError, QuestionContractError,
                UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError, TypeError):
            raise invalid("openrouter_assessment_invalid") from None
        return ProviderReply(MODEL_IDENTITY, normalized, usage, charge)
