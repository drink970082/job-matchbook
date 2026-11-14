"""Hermetic tests for the native JEV contract used by the P3 prototype."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from ats_worker.ranking.native import (
    NATIVE_JEV_CONTRACT,
    JevContractError,
    NativeJevQuestionSet,
    jev_question_set_from_value,
    native_jev_journal_payload,
    validate_jev_response,
    validate_native_jev_journal_payload,
)


QUESTIONS = {
    "version": "synthetic-role-v1",
    "questions": [
        {
            "id": "role",
            "type": "choice",
            "instructions": "Classify the synthetic role evidence.",
            "criteria": {"expanded": "More scope.", "stable": "Same scope.", "unknown": "Unclear."},
        },
        {"id": "certainty", "type": "noul", "instructions": "Estimate a bounded chance."},
        {
            "id": "risk",
            "type": "score",
            "instructions": "Rate synthetic risk.",
            "criteria": ["Low", "Moderate", "High"],
        },
    ],
}
MODEL = "fake-jev-test-v1"


def native_reply():
    return {
        "id": "synthetic-response-1",
        "model": MODEL,
        "provider": "synthetic-route",
        "answers": {
            "role": {
                "type": "choice", "choice": "stable",
                "probabilities": {"expanded": 0.2, "stable": 0.7, "unknown": 0.1},
                "confidence": 0.7,
            },
            "certainty": {"type": "noul", "noul": 0.35},
            "risk": {
                "type": "score", "score": 1.25,
                "legend": {"0": "Low", "1": "Moderate", "2": "High"},
                "probabilities": {"0": 0.2, "1": 0.6, "2": 0.2},
                "confidence": 0.6,
            },
        },
        "usage": {
            "input_tokens": 123, "output_tokens": 41, "cached_input_tokens": 5,
            "cost": 0.0123, "is_byok": False,
            "cost_details": {
                "upstream_inference_cost": 0.0123,
                "upstream_inference_prompt_cost": 0.01,
                "upstream_inference_completions_cost": 0.0023,
            },
        },
    }


def test_native_choice_noul_score_contract_and_journal_roundtrip():
    question_set = jev_question_set_from_value(QUESTIONS)
    assert isinstance(question_set, NativeJevQuestionSet)
    assert question_set.sha256 == jev_question_set_from_value(json.loads(json.dumps(QUESTIONS))).sha256
    validated = validate_jev_response(native_reply(), question_set, expected_model=MODEL)
    answers = {answer.question_id: answer for answer in validated.answers}
    assert answers["role"].choice == "stable"
    assert dict(answers["role"].probabilities) == {"expanded": 0.2, "stable": 0.7, "unknown": 0.1}
    assert answers["certainty"].noul == 0.35
    assert answers["risk"].score == 1.25
    assert dict(answers["risk"].legend) == {"0": "Low", "1": "Moderate", "2": "High"}
    assert question_set.wire_map()["certainty"]["type"] == "noul"

    wrapper = native_jev_journal_payload(question_set, native_reply())
    replayed = validate_native_jev_journal_payload(
        json.loads(json.dumps(wrapper)), expected_question_set=question_set, expected_model=MODEL,
    )
    assert {answer.question_id for answer in replayed.answers} == {"role", "certainty", "risk"}
    assert wrapper["native_contract"] == NATIVE_JEV_CONTRACT


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(extra="field"),
        lambda value: value.update(version=" "),
        lambda value: value.update(questions=[]),
        lambda value: value.update(questions=[None]),
        lambda value: value["questions"][0].update(id="BadID"),
        lambda value: value["questions"][0].update(instructions=" padded "),
        lambda value: value["questions"][0].update(criteria={}),
        lambda value: value["questions"][0].update(criteria={"long" * 40: "text"}),
        lambda value: value["questions"][0].update(criteria={"stable": "line\nbreak"}),
        lambda value: value["questions"][1].update(extra="field"),
        lambda value: value["questions"][2].update(criteria=[]),
        lambda value: value["questions"][2].update(criteria=["same", "same"]),
    ],
)
def test_question_set_rejects_invalid_shapes_and_criteria(mutate):
    value = deepcopy(QUESTIONS)
    mutate(value)
    with pytest.raises(JevContractError):
        jev_question_set_from_value(value)


@pytest.mark.parametrize("question_type", [[], {}, True, "unsupported"])
def test_question_set_rejects_invalid_question_types(question_type):
    value = {"version": "synthetic-v1", "questions": [
        {"id": "field", "type": question_type, "instructions": "text"},
    ]}
    with pytest.raises(JevContractError):
        jev_question_set_from_value(value)


def test_question_set_rejects_duplicate_ids_and_extra_noul_criteria():
    duplicate = deepcopy(QUESTIONS)
    duplicate["questions"][1]["id"] = duplicate["questions"][0]["id"]
    with pytest.raises(JevContractError, match="duplicated"):
        jev_question_set_from_value(duplicate)
    invalid_noul = deepcopy(QUESTIONS)
    invalid_noul["questions"][1]["criteria"] = ["not supported"]
    with pytest.raises(JevContractError, match="object shape"):
        jev_question_set_from_value(invalid_noul)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(extra="field"),
        lambda payload: payload.update(model="wrong-model"),
        lambda payload: payload.update(id=" padded "),
        lambda payload: payload.update(answers=[]),
        lambda payload: payload["answers"]["role"].update(type="score"),
        lambda payload: payload["answers"]["role"].update(confidence=1.01),
        lambda payload: payload["answers"]["role"].update(probabilities={"stable": 1.0}),
        lambda payload: payload["answers"]["role"].update(
            probabilities={"expanded": 0.1, "stable": 0.1, "unknown": 0.1}),
        lambda payload: payload["answers"]["role"].update(choice="not-allowed"),
        lambda payload: payload["answers"]["certainty"].update(extra="field"),
        lambda payload: payload["answers"]["certainty"].update(noul=1.1),
        lambda payload: payload["answers"]["risk"].update(score=2.1),
        lambda payload: payload["answers"]["risk"].update(legend={"0": "wrong", "1": "Moderate", "2": "High"}),
        lambda payload: payload["answers"]["risk"].update(probabilities={"0": 1.0}),
        lambda payload: payload["answers"].pop("risk"),
    ],
)
def test_native_response_rejects_malformed_or_unbound_answers(mutate):
    payload = native_reply()
    mutate(payload)
    with pytest.raises(JevContractError):
        validate_jev_response(payload, jev_question_set_from_value(QUESTIONS), expected_model=MODEL)


@pytest.mark.parametrize(
    "usage",
    [
        [],
        {"input_tokens": True},
        {"input_tokens": -1},
        {"cost": -0.1},
        {"cost": float("nan")},
        {"is_byok": "false"},
        {"extra": 1},
        {"cost_details": []},
        {"cost_details": {"upstream_inference_cost": 0.1}},
        {"cost_details": {
            "upstream_inference_cost": 0.1,
            "upstream_inference_prompt_cost": 0.1,
            "upstream_inference_completions_cost": -0.1,
        }},
    ],
)
def test_native_usage_rejects_malformed_accounting(usage):
    payload = native_reply()
    payload["usage"] = usage
    with pytest.raises(JevContractError):
        validate_jev_response(payload, jev_question_set_from_value(QUESTIONS), expected_model=MODEL)


@pytest.mark.parametrize("value", [None, [], {"version": "v1", "questions": []}])
def test_question_set_rejects_non_object_empty_or_unknown_shape(value):
    with pytest.raises(JevContractError):
        jev_question_set_from_value(value)


@pytest.mark.parametrize("mutation", ["wrapper", "contract", "qset_hash", "invocation", "frozen", "response_type", "response_hash", "response_content"])
def test_native_journal_rejects_changed_or_unbound_payload(mutation):
    question_set = jev_question_set_from_value(QUESTIONS)
    wrapper = native_jev_journal_payload(question_set, native_reply())
    if mutation == "wrapper":
        wrapper["extra"] = "field"
    elif mutation == "contract":
        wrapper["native_contract"] = "generic-answer-v1"
    elif mutation == "qset_hash":
        wrapper["question_set"]["questions"][0]["criteria"]["stable"] = "Changed."
    elif mutation == "invocation":
        changed = deepcopy(QUESTIONS)
        changed["questions"][0]["criteria"]["stable"] = "Changed."
        with pytest.raises(JevContractError, match="invocation"):
            validate_native_jev_journal_payload(wrapper, expected_question_set=jev_question_set_from_value(changed))
        return
    elif mutation == "frozen":
        with pytest.raises(JevContractError, match="frozen evaluation"):
            validate_native_jev_journal_payload(wrapper, expected_question_set_sha256="0" * 64)
        return
    elif mutation == "response_type":
        wrapper["response"] = []
    elif mutation == "response_hash":
        wrapper["response_sha256"] = "invalid"
    else:
        wrapper["response"]["answers"]["role"]["choice"] = "expanded"
    with pytest.raises(JevContractError):
        validate_native_jev_journal_payload(wrapper, expected_model=MODEL)


def test_native_response_rejects_oversized_integer_and_journal_unhashable_response():
    payload = native_reply()
    payload["answers"]["certainty"]["noul"] = 10**400
    with pytest.raises(JevContractError, match="numeric size"):
        validate_jev_response(payload, jev_question_set_from_value(QUESTIONS), expected_model=MODEL)
    with pytest.raises(JevContractError, match="cannot be canonically hashed"):
        native_jev_journal_payload(jev_question_set_from_value(QUESTIONS), {"bad": object()})
