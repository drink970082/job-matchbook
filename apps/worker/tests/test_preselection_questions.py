import copy
import json
from pathlib import Path

import pytest

from ats_worker.preselection.questions import (
    QuestionContractError,
    question_set_from_value,
    validate_assessment_payload,
)


FIXTURE = Path(__file__).parent / "fixtures/preselection_questions.synthetic.json"
JOB = "A fictional company needs an engineer with Python experience."
CONTEXT = "AS OF 2026-01-01\nBACKGROUND\nSynthetic software work.\nSEARCH\nExplore engineering.\n"


def question_set():
    return question_set_from_value(json.loads(FIXTURE.read_text(encoding="utf-8")))


def answer_payload():
    return {
        "answers": {
            "role_families": {
                "value": ["engineering", "ambiguous"],
                "evidence": [
                    {
                        "source": "jd",
                        "start": JOB.index("engineer"),
                        "end": JOB.index("engineer") + len("engineer"),
                        "quote": "engineer",
                    }
                ],
            },
            "work_alignment": {
                "value": "moderate",
                "evidence": [
                    {
                        "source": "candidate_context",
                        "start": CONTEXT.index("Synthetic"),
                        "end": CONTEXT.index("Synthetic") + len("Synthetic"),
                        "quote": "Synthetic",
                    }
                ],
            },
            "dimension_example": {"value": 2, "evidence": []},
        },
        "explanation": "Synthetic answer with unknowns preserved.",
    }


def test_question_set_builds_versioned_exact_answer_schema_and_identity():
    questions = question_set()
    schema = questions.answer_schema()

    assert questions.sha256 == question_set().sha256
    assert schema["additionalProperties"] is False
    assert schema["properties"]["answers"]["required"] == [
        "role_families",
        "work_alignment",
        "dimension_example",
    ]
    assert schema["properties"]["answers"]["properties"]["dimension_example"]["properties"]["value"]["maximum"] == 4


def test_assessment_response_validates_exact_ids_types_ranges_and_source_spans():
    checked = validate_assessment_payload(
        answer_payload(),
        question_set(),
        variant="direct",
        job_description=JOB,
        candidate_context=CONTEXT,
    )

    assert [answer.question_id for answer in checked.answers] == [
        "role_families",
        "work_alignment",
        "dimension_example",
    ]
    assert checked.answers[0].value == ["engineering", "ambiguous"]
    assert checked.answers[2].value == 2.0
    assert checked.explanation == "Synthetic answer with unknowns preserved."


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["answers"].pop("work_alignment"), "answer IDs"),
        (lambda value: value["answers"].update(extra={"value": "x", "evidence": []}), "answer IDs"),
        (lambda value: value["answers"]["work_alignment"].update(value="great"), "allowed values"),
        (lambda value: value["answers"]["role_families"].update(value=["engineering", "engineering"]), "duplicate values"),
        (lambda value: value["answers"]["dimension_example"].update(value=float("nan")), "finite numeric range"),
        (lambda value: value["answers"]["dimension_example"].update(value=4.1), "finite numeric range"),
        (lambda value: value.update(overall_score=99), "unknown field"),
        (lambda value: value.update(explanation=" "), "non-empty trimmed text"),
    ],
)
def test_assessment_rejects_malformed_answer_contracts(mutate, message):
    value = copy.deepcopy(answer_payload())
    mutate(value)
    with pytest.raises(QuestionContractError, match=message):
        validate_assessment_payload(
            value,
            question_set(),
            variant="direct",
            job_description=JOB,
            candidate_context=CONTEXT,
        )


def test_assessment_rejects_bad_spans_and_variant_incompatible_evidence():
    value = answer_payload()
    value["answers"]["role_families"]["evidence"][0]["quote"] = "fiction"
    with pytest.raises(QuestionContractError, match="does not match its source span"):
        validate_assessment_payload(
            value,
            question_set(),
            variant="direct",
            job_description=JOB,
            candidate_context=CONTEXT,
        )

    value = answer_payload()
    value["answers"]["role_families"]["evidence"] = [
        {"source": "fact", "fact_id": "fact-1"}
    ]
    with pytest.raises(QuestionContractError, match="unavailable fact"):
        validate_assessment_payload(
            value,
            question_set(),
            variant="extracted",
            job_description=JOB,
            candidate_context=CONTEXT,
            fact_ids={"different-fact"},
        )


def test_extracted_answers_can_reference_only_validated_fact_ids():
    value = answer_payload()
    value["answers"]["role_families"]["evidence"] = [
        {"source": "fact", "fact_id": "fact-1"}
    ]
    checked = validate_assessment_payload(
        value,
        question_set(),
        variant="extracted",
        job_description=JOB,
        candidate_context=CONTEXT,
        fact_ids={"fact-1"},
    )
    assert checked.answers[0].evidence[0]["fact_id"] == "fact-1"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(extra="ignored"), "unknown field"),
        (lambda value: value["questions"][0].update(id="Bad ID"), "id is invalid"),
        (lambda value: value["questions"][0].update(allowed_values=[]), "non-empty array"),
        (lambda value: value["questions"][0].update(allowed_values=["x", "x"]), "duplicates"),
        (lambda value: value["questions"][2].update(minimum=float("inf")), "finite ordered"),
        (lambda value: value["questions"][2].update(minimum=5), "finite ordered"),
    ],
)
def test_question_set_parser_rejects_open_or_malformed_schema(mutate, message):
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    mutate(value)
    with pytest.raises(QuestionContractError, match=message):
        question_set_from_value(value)
