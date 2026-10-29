from datetime import datetime, timedelta, timezone
import json
import multiprocessing
import os
from pathlib import Path
import stat
import time

import pytest

from ats_worker.preselection.extraction import extraction_from_value
from ats_worker.preselection.profile import profile_from_value, render_profile
from ats_worker.preselection.questions import question_set_from_value
from ats_worker.preselection import shadow as shadow_module
from ats_worker.preselection.shadow import (
    AttemptJournal,
    Charge,
    CostCeiling,
    JobEnvelope,
    ModelIdentity,
    ProviderFailure,
    ProviderReply,
    RetryPolicy,
    ShadowBudgetExceeded,
    ShadowDisabledError,
    ShadowIntegrityError,
    ShadowLimits,
    ShadowProviderFailure,
    ShadowResumeAmbiguous,
    SystemClock,
    Usage,
    build_assessment_invocation,
    build_extraction_invocation,
    run_jd_extraction,
    run_shadow_assessment,
)


PROFILE_FIXTURE = Path(__file__).parent / "fixtures/preselection_profile.synthetic.json"
QUESTIONS_FIXTURE = Path(__file__).parent / "fixtures/preselection_questions.synthetic.json"
JD = "A fictional company needs an engineer with 2+ years professional experience."
ASSESSOR = ModelIdentity("fake-provider", "synthetic-assessor", "synthetic-assessor-r1")
EXTRACTOR = ModelIdentity("fake-provider", "synthetic-extractor", "synthetic-extractor-r1")


def approved_profile():
    value = json.loads(PROFILE_FIXTURE.read_text(encoding="utf-8"))
    value["status"] = "approved"
    return profile_from_value(value)


def questions():
    return question_set_from_value(json.loads(QUESTIONS_FIXTURE.read_text(encoding="utf-8")))


def job(description=JD):
    return JobEnvelope("Synthetic Co", "Junior Engineer", "Remote", description)


def _charge(kind="actual", amount="0.05"):
    return Charge(kind, amount, "SYNTHETIC-CREDIT", "fake-call", "2026-01-01", "synthetic-test-fixture")


def limits(**overrides):
    values = {
        "max_total_attempts": 4,
        "max_attempts_per_request": 2,
        "max_elapsed_seconds": 60.0,
        "cost_ceiling": CostCeiling(
            "10.00", "1.00", "SYNTHETIC-CREDIT", "fake-call", "2026-01-01", "synthetic-test-fixture"
        ),
    }
    values.update(overrides)
    return ShadowLimits(**values)


class FakeClock:
    def __init__(self, elapsed_ms=0):
        self._elapsed_ms = multiprocessing.get_context("fork").Value("d", float(elapsed_ms))

    @property
    def elapsed_ms(self):
        return self._elapsed_ms.value

    def utc_now(self):
        return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=self.elapsed_ms)

    def monotonic(self):
        return self.elapsed_ms / 1000

    def advance(self, milliseconds=5):
        with self._elapsed_ms.get_lock():
            self._elapsed_ms.value += milliseconds


class FakeTransport:
    def __init__(self, outcomes, clock=None, clock_advance_ms=5):
        self.outcomes = list(outcomes)
        context = multiprocessing.get_context("fork")
        self._next_outcome = context.Value("i", 0)
        self._call_reader, self._call_writer = context.Pipe(duplex=False)
        self._calls = []
        self.clock = clock
        self.clock_advance_ms = clock_advance_ms

    @property
    def calls(self):
        while self._call_reader.poll():
            self._calls.append(self._call_reader.recv())
        return self._calls

    def complete(self, invocation):
        self._call_writer.send(invocation)
        if self.clock:
            self.clock.advance(self.clock_advance_ms)
        with self._next_outcome.get_lock():
            outcome_index = self._next_outcome.value
            self._next_outcome.value += 1
        if outcome_index >= len(self.outcomes):
            raise AssertionError("fake transport received an unexpected call")
        outcome = self.outcomes[outcome_index]
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return outcome(invocation)
        return outcome


class FakeSleeper:
    def __init__(self, clock, advance_factor=1.0):
        self.clock = clock
        self.advance_factor = advance_factor
        self.delays = []

    def sleep(self, seconds):
        self.delays.append(seconds)
        self.clock.advance(seconds * self.advance_factor * 1000)


class InterruptedSleeper:
    def sleep(self, seconds):
        raise RuntimeError("synthetic crash during backoff")


class NonReturningTransport:
    def __init__(self, marker_path):
        self.marker_path = marker_path

    def complete(self, invocation):
        Path(self.marker_path).write_text(str(os.getpid()), encoding="utf-8")
        while True:
            time.sleep(1)


class LargePlainReplyTransport:
    def __init__(self, marker_path, size=100_000_000):
        self.marker_path = str(marker_path)
        self.size = size

    def complete(self, invocation):
        Path(self.marker_path).write_text(str(os.getpid()), encoding="utf-8")
        return reply(ASSESSOR, {"large": "x" * self.size})


def _sleep_and_write_marker(marker_path):
    Path(marker_path).write_text("unpickled in parent", encoding="utf-8")
    time.sleep(0.5)


class SlowUnpickleValue:
    def __init__(self, marker_path):
        self.marker_path = str(marker_path)

    def __reduce__(self):
        return (_sleep_and_write_marker, (self.marker_path,))


def extraction_payload(description=JD, coverage="complete"):
    quote = "2+ years professional experience"
    start = description.index(quote)
    return {
        "schema": 1,
        "coverage": coverage,
        "facts": [
            {
                "id": "experience-floor",
                "quote": quote,
                "start": start,
                "end": start + len(quote),
                "category": "experience",
                "strength": "required",
                "experience_kind": "professional_relevant",
                "minimum_years": 2,
                "maximum_years": None,
                "alternative_group_id": None,
            }
        ],
        "alternative_groups": [],
    }


def assessment_payload(variant="direct", profile=None):
    context = render_profile(profile or approved_profile())
    return {
        "answers": {
            "role_families": {
                "value": ["engineering"],
                "evidence": (
                    [{"source": "fact", "fact_id": "experience-floor"}]
                    if variant == "extracted"
                    else [
                        {
                            "source": "jd",
                            "start": JD.index("engineer"),
                            "end": JD.index("engineer") + len("engineer"),
                            "quote": "engineer",
                        }
                    ]
                ),
            },
            "work_alignment": {
                "value": "moderate",
                "evidence": [
                    {
                        "source": "candidate_context",
                        "start": context.index("Interested"),
                        "end": context.index("Interested") + len("Interested"),
                        "quote": "Interested",
                    }
                ],
            },
            "dimension_example": {"value": 2, "evidence": []},
        },
        "explanation": "Synthetic explanation; no overall score was requested.",
    }


def reply(identity, payload, charge=None, usage=None):
    return ProviderReply(
        identity,
        payload,
        usage or Usage(12, 7, None),
        charge or _charge(),
    )


def test_shadow_assessment_is_default_off_and_rejects_draft_profile_before_transport():
    transport = FakeTransport([])
    journal = AttemptJournal.empty()

    with pytest.raises(ShadowDisabledError):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(),
            SystemClock(),
            lambda value: None,
        )
    draft_value = json.loads(PROFILE_FIXTURE.read_text(encoding="utf-8"))
    draft = profile_from_value(draft_value)
    with pytest.raises(ShadowIntegrityError, match="approved candidate profile"):
        run_shadow_assessment(
            job(),
            draft,
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(),
            SystemClock(),
            lambda value: None,
            enabled=True,
        )
    assert transport.calls == []
    assert journal.records == []


def test_direct_assessment_payload_contains_exact_profile_one_full_job_and_questions():
    profile = approved_profile()
    invocation = build_assessment_invocation(
        job(), profile, questions(), ASSESSOR, variant="direct"
    )
    context = render_profile(profile)

    assert invocation.stage == "assess"
    assert invocation.variant == "direct"
    assert set(invocation.payload) == {
        "company",
        "title",
        "location",
        "candidate_context",
        "questions",
        "job_description",
    }
    assert invocation.payload["candidate_context"] == context
    assert invocation.payload["job_description"] == JD
    assert not {"job_id", "profile_hash", "resume", "provenance", "score"}.intersection(
        invocation.payload
    )


def test_assessment_identity_changes_with_job_profile_questions_variant_and_model():
    profile = approved_profile()
    base = build_assessment_invocation(job(), profile, questions(), ASSESSOR, variant="direct")
    changed_job = build_assessment_invocation(
        job("A different fictional JD."), profile, questions(), ASSESSOR, variant="direct"
    )
    value = json.loads(PROFILE_FIXTURE.read_text(encoding="utf-8"))
    value["background"][0]["text"] = "A different synthetic fact."
    changed_profile = build_assessment_invocation(
        job(), profile_from_value({**value, "status": "approved"}), questions(), ASSESSOR, variant="direct"
    )
    changed_identity = build_assessment_invocation(
        job(), profile, questions(), ModelIdentity("fake-provider", "synthetic-assessor", "r2"), variant="direct"
    )
    qvalue = json.loads(QUESTIONS_FIXTURE.read_text(encoding="utf-8"))
    qvalue["version"] = "synthetic-questions-v2"
    changed_questions = build_assessment_invocation(
        job(), profile, question_set_from_value(qvalue), ASSESSOR, variant="direct"
    )
    changed_draw = build_assessment_invocation(
        job(), profile, questions(), ASSESSOR, variant="direct", draw_number=2
    )
    assert len(
        {
            base.request_identity,
            changed_job.request_identity,
            changed_profile.request_identity,
            changed_identity.request_identity,
            changed_questions.request_identity,
            changed_draw.request_identity,
        }
    ) == 6

    extraction = build_extraction_invocation(job(), EXTRACTOR)
    other_job_extraction = build_extraction_invocation(
        JobEnvelope("Synthetic Co", "Different Role", "Remote", JD), EXTRACTOR
    )
    assert extraction.request_identity != other_job_extraction.request_identity
    assert extraction.payload == other_job_extraction.payload
    assert "company" not in extraction.payload


def test_fake_direct_shadow_run_validates_answers_and_journals_accounting(tmp_path):
    clock = FakeClock()
    transport = FakeTransport([reply(ASSESSOR, assessment_payload())], clock)
    journal = AttemptJournal.empty()
    journal_path = tmp_path / "synthetic-shadow.json"

    result = run_shadow_assessment(
        job(),
        approved_profile(),
        questions(),
        "direct",
        ASSESSOR,
        transport,
        journal,
        limits(),
        clock,
        lambda current: current.save(journal_path),
        enabled=True,
    )

    assert result.status == "completed"
    assert result.assessment is not None
    assert result.assessment.answers[0].value == ["engineering"]
    assert result.assessment_from_cache is False
    assert result.extraction_from_cache is False
    assert len(transport.calls) == 1
    assert journal.records[0].status == "succeeded"
    assert journal.records[0].variant == "direct"
    assert stat.S_IMODE(journal_path.stat().st_mode) == 0o600
    assert AttemptJournal.load(journal_path).aggregate()["actual_charges"] == [
        {"currency": "SYNTHETIC-CREDIT", "billing_unit": "fake-call", "amount": "0.05"}
    ]


def test_extractor_gets_only_full_jd_and_extracted_assessment_omits_original_jd(tmp_path):
    clock = FakeClock()
    profile = approved_profile()
    extraction_reply = reply(EXTRACTOR, extraction_payload())
    assessment_reply = reply(ASSESSOR, assessment_payload("extracted", profile))
    transport = FakeTransport([extraction_reply, assessment_reply], clock)
    journal = AttemptJournal.empty()
    result = run_shadow_assessment(
        job(),
        profile,
        questions(),
        "extracted",
        ASSESSOR,
        transport,
        journal,
        limits(),
        clock,
        lambda current: current.save(tmp_path / "extracted-journal.json"),
        enabled=True,
        extraction_identity=EXTRACTOR,
    )

    extractor_invocation, assessment_invocation = transport.calls
    assert set(extractor_invocation.payload) == {"job_description", "schema"}
    assert extractor_invocation.payload["job_description"] == JD
    assert render_profile(profile) not in json.dumps(extractor_invocation.payload)
    assert "company" not in extractor_invocation.payload
    assert "No candidate profile" in extractor_invocation.system_prompt
    assert "job_description" not in assessment_invocation.payload
    assert assessment_invocation.payload["job_facts"]["facts"][0]["quote"] == "2+ years professional experience"
    assert assessment_invocation.payload["candidate_context"] == render_profile(profile)
    assert result.extraction is not None and result.assessment is not None
    assert journal.records[0].variant == "extract"
    assert journal.records[1].variant == "extracted"
    work_item = journal.records[0].work_item_identity_sha256
    extracted_arm = journal.aggregate()["per_work_item_variant"][work_item]["extracted"]
    assert extracted_arm["attempts_by_stage"] == {"assess": 1, "extract_jd": 1}
    assert extracted_arm["actual_charges"] == [
        {"currency": "SYNTHETIC-CREDIT", "billing_unit": "fake-call", "amount": "0.10"}
    ]


def test_incomplete_extraction_routes_unresolved_without_assessment_call(tmp_path):
    clock = FakeClock()
    transport = FakeTransport([reply(EXTRACTOR, extraction_payload(coverage="incomplete"))], clock)
    result = run_shadow_assessment(
        job(),
        approved_profile(),
        questions(),
        "extracted",
        ASSESSOR,
        transport,
        AttemptJournal.empty(),
        limits(),
        clock,
        lambda current: current.save(tmp_path / "incomplete.json"),
        enabled=True,
        extraction_identity=EXTRACTOR,
    )

    assert result.status == "unresolved_input"
    assert result.assessment is None
    assert len(transport.calls) == 1


def test_retry_is_counted_and_resume_reuses_success_without_duplicate_call(tmp_path):
    clock = FakeClock()
    journal_path = tmp_path / "resumable.json"
    journal = AttemptJournal.empty()
    failure = ProviderFailure(
        error_code="rate_limited",
        retryable=True,
        delivery="not_sent",
        model_identity=ASSESSOR,
        usage=Usage(None, None, None),
        charge=_charge(amount="0"),
    )
    transport = FakeTransport([failure, reply(ASSESSOR, assessment_payload())], clock)
    sleeper = FakeSleeper(clock)
    arguments = (
        job(),
        approved_profile(),
        questions(),
        "direct",
        ASSESSOR,
        transport,
        journal,
        limits(),
        clock,
        lambda current: current.save(journal_path),
    )
    result = run_shadow_assessment(
        *arguments,
        enabled=True,
        retry_policy=RetryPolicy(1, 0.02, 0.02, 1.0),
        sleeper=sleeper,
    )
    assert result.status == "completed"
    assert [record.status for record in journal.records] == ["retryable_failure", "succeeded"]
    assert [record.attempt_number for record in journal.records] == [1, 2]
    assert [record.retry_of for record in journal.records] == [None, 1]
    assert sleeper.delays == [0.02]
    assert journal.aggregate()["reported_usage"]["input_tokens"]["unknown_attempts"] == 1
    assert len(journal.aggregate()["per_successful_assessment"]) == 1
    assert next(iter(journal.aggregate()["per_work_item"].values()))["attempts"] == 2
    assert AttemptJournal.from_json(journal.to_json()).records[1].retry_of == 1

    tampered = json.loads(journal.to_json())
    tampered["records"][1]["retry_of"] = None
    with pytest.raises(ShadowIntegrityError, match="retry must link"):
        AttemptJournal.from_json(json.dumps(tampered))

    resumed_journal = AttemptJournal.load(journal_path)
    no_call_transport = FakeTransport([])
    resumed = run_shadow_assessment(
        job(),
        approved_profile(),
        questions(),
        "direct",
        ASSESSOR,
        no_call_transport,
        resumed_journal,
        limits(),
        clock,
        lambda current: current.save(journal_path),
        enabled=True,
        retry_policy=RetryPolicy(1, 0.02, 0.02, 1.0),
    )
    assert resumed.assessment_from_cache is True
    assert no_call_transport.calls == []
    assert len(resumed_journal.records) == 2


def test_public_entrypoint_kills_and_reaps_a_nonreturning_transport(tmp_path):
    clock = FakeClock()
    journal_path = tmp_path / "blocked-call.json"
    journal = AttemptJournal.empty()
    transport = NonReturningTransport(tmp_path / "worker.pid")
    started = time.monotonic()
    with pytest.raises(ShadowResumeAmbiguous, match="delivery and charge are unknown"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(max_elapsed_seconds=0.05),
            clock,
            lambda current: current.save(journal_path),
            enabled=True,
        )
    assert time.monotonic() - started < 0.5
    assert journal.records[0].status == "ambiguous"
    assert journal.records[0].delivery == "unknown"
    assert journal.records[0].charge["kind"] == "unknown"
    assert journal.records[0].elapsed_ms <= 150
    worker_pid = int((tmp_path / "worker.pid").read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(worker_pid, 0)

    resumed_transport = FakeTransport([])
    with pytest.raises(ShadowResumeAmbiguous):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            resumed_transport,
            AttemptJournal.load(journal_path),
            limits(max_elapsed_seconds=0.05),
            clock,
            lambda current: None,
            enabled=True,
        )
    assert resumed_transport.calls == []


def test_reply_untrusted_objects_are_not_unpickled_in_parent(tmp_path):
    clock = FakeClock()
    journal = AttemptJournal.empty()
    marker = tmp_path / "parent-unpickle-marker"
    payload = assessment_payload()
    payload["untrusted"] = SlowUnpickleValue(marker)
    transport = FakeTransport([reply(ASSESSOR, payload)], clock)

    started = time.monotonic()
    with pytest.raises(Exception):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(max_elapsed_seconds=0.3),
            clock,
            lambda current: None,
            enabled=True,
        )

    assert not marker.exists(), "provider output executed pickle code in the parent process"
    assert time.monotonic() - started < 0.65
    assert journal.records[0].status == "integrity_failure"
    assert journal.records[0].delivery == "completed"
    assert journal.records[0].charge["kind"] == "actual"


def test_ordinary_oversized_reply_is_bounded_and_accounted(tmp_path):
    clock = FakeClock()
    journal = AttemptJournal.empty()
    marker = tmp_path / "large-reply-worker.pid"
    transport = LargePlainReplyTransport(marker)

    started = time.monotonic()
    with pytest.raises((ShadowResumeAmbiguous, ShadowIntegrityError)):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(max_elapsed_seconds=0.25),
            clock,
            lambda current: None,
            enabled=True,
        )

    assert time.monotonic() - started < 0.65
    assert marker.exists()
    worker_pid = int(marker.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(worker_pid, 0)
    record = journal.records[0]
    assert record.status in {"ambiguous", "integrity_failure"}
    if record.status == "ambiguous":
        assert record.delivery == "unknown"
        assert record.usage["input_tokens"] is None
        assert record.charge["kind"] == "unknown"
    else:
        assert record.delivery == "completed"
        assert record.usage["input_tokens"] == 12
        assert record.charge["kind"] == "actual"


def test_response_validation_is_inside_the_killable_deadline(tmp_path, monkeypatch):
    original_validate = shadow_module.validate_assessment_payload
    marker = tmp_path / "validator-process.pid"

    def slow_validate(*args, **kwargs):
        marker.write_text(str(os.getpid()), encoding="utf-8")
        time.sleep(0.9)
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(shadow_module, "validate_assessment_payload", slow_validate)
    clock = FakeClock()
    journal = AttemptJournal.empty()
    transport = FakeTransport([reply(ASSESSOR, assessment_payload())], clock)

    started = time.monotonic()
    with pytest.raises(ShadowResumeAmbiguous, match="delivery and charge are unknown"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(max_elapsed_seconds=0.4),
            clock,
            lambda current: None,
            enabled=True,
        )

    assert time.monotonic() - started < 0.7
    assert journal.records[0].status == "ambiguous"
    assert journal.records[0].delivery == "unknown"
    assert journal.records[0].usage == {"input_tokens": None, "output_tokens": None, "cached_input_tokens": None}
    assert journal.records[0].charge["kind"] == "unknown"
    worker_pid = int(marker.read_text(encoding="utf-8"))
    assert worker_pid != os.getpid()
    with pytest.raises(ProcessLookupError):
        os.kill(worker_pid, 0)


def test_parent_wire_decode_is_checked_against_the_remaining_deadline(monkeypatch):
    clock = FakeClock()
    journal = AttemptJournal.empty()
    transport = FakeTransport([reply(ASSESSOR, assessment_payload())], clock)
    original_loads = shadow_module.json.loads

    def expire_during_decode(payload):
        if type(payload) is bytes:
            clock.advance(100)
        return original_loads(payload)

    monkeypatch.setattr(shadow_module.json, "loads", expire_during_decode)

    with pytest.raises(ShadowResumeAmbiguous, match="delivery and charge are unknown"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(max_elapsed_seconds=0.05),
            clock,
            lambda current: None,
            enabled=True,
        )

    assert journal.records[0].status == "ambiguous"
    assert journal.records[0].delivery == "unknown"
    assert journal.records[0].charge["kind"] == "unknown"
    assert journal.records[0].usage["input_tokens"] is None


def test_backoff_exhaustion_does_not_start_an_attempt_after_deadline(tmp_path):
    clock = FakeClock()
    journal = AttemptJournal.empty()
    failure = ProviderFailure(
        error_code="rate_limited",
        retryable=True,
        delivery="not_sent",
        model_identity=ASSESSOR,
        usage=Usage(None, None, None),
        charge=_charge(amount="0.25"),
    )
    transport = FakeTransport([failure, reply(ASSESSOR, assessment_payload())], clock, clock_advance_ms=0)
    sleeper = FakeSleeper(clock)
    with pytest.raises(ShadowBudgetExceeded, match="during retry backoff"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(max_elapsed_seconds=0.1, max_attempts_per_request=2),
            clock,
            lambda current: current.save(tmp_path / "backoff-budget.json"),
            enabled=True,
            retry_policy=RetryPolicy(1, 0.2, 0.2, 1.0),
            sleeper=sleeper,
        )
    assert len(sleeper.delays) == 1
    assert 0 < sleeper.delays[0] < 0.2
    assert len(transport.calls) == 1
    assert len(journal.records) == 1
    assert journal.records[0].status == "retryable_failure"
    assert journal.aggregate()["actual_charges"] == [
        {"currency": "SYNTHETIC-CREDIT", "billing_unit": "fake-call", "amount": "0.25"}
    ]


def test_nonretryable_and_policy_exhausted_errors_do_not_sleep_or_replay(tmp_path):
    for retryable, max_retries, expected_status in (
        (False, 1, "failed"),
        (True, 0, "retryable_failure"),
    ):
        clock = FakeClock()
        journal = AttemptJournal.empty()
        failure = ProviderFailure(
            error_code="terminal" if not retryable else "retry-disabled",
            retryable=retryable,
            delivery="not_sent",
            model_identity=ASSESSOR,
            usage=Usage(None, None, None),
            charge=_charge(amount="0.25"),
        )
        transport = FakeTransport([failure, reply(ASSESSOR, assessment_payload())], clock)
        sleeper = FakeSleeper(clock)
        with pytest.raises(ShadowProviderFailure):
            run_shadow_assessment(
                job(),
                approved_profile(),
                questions(),
                "direct",
                ASSESSOR,
                transport,
                journal,
                limits(),
                clock,
                lambda current: current.save(tmp_path / f"terminal-{retryable}.json"),
                enabled=True,
                retry_policy=RetryPolicy(max_retries, 0.02, 0.02, 1.0),
                sleeper=sleeper,
            )
        assert len(transport.calls) == 1
        assert sleeper.delays == []
        assert journal.records[0].status == expected_status


def test_resume_completes_persisted_backoff_before_retry(tmp_path):
    clock = FakeClock()
    journal_path = tmp_path / "pending-backoff.json"
    journal = AttemptJournal.empty()
    failure = ProviderFailure(
        error_code="rate_limited",
        retryable=True,
        delivery="not_sent",
        model_identity=ASSESSOR,
        usage=Usage(None, None, None),
        charge=_charge(amount="0.10"),
    )
    policy = RetryPolicy(1, 0.02, 0.02, 1.0)
    first_transport = FakeTransport([failure, reply(ASSESSOR, assessment_payload())], clock)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            first_transport,
            journal,
            limits(),
            clock,
            lambda current: current.save(journal_path),
            enabled=True,
            retry_policy=policy,
            sleeper=InterruptedSleeper(),
        )
    assert len(first_transport.calls) == 1
    assert journal.records[0].retry_delay_seconds == 0.02
    assert journal.records[0].retry_backoff_completed is False

    resumed_journal = AttemptJournal.load(journal_path)
    resumed_transport = FakeTransport([reply(ASSESSOR, assessment_payload())], clock)
    sleeper = FakeSleeper(clock)
    result = run_shadow_assessment(
        job(),
        approved_profile(),
        questions(),
        "direct",
        ASSESSOR,
        resumed_transport,
        resumed_journal,
        limits(),
        clock,
        lambda current: current.save(journal_path),
        enabled=True,
        retry_policy=policy,
        sleeper=sleeper,
    )
    assert result.status == "completed"
    assert sleeper.delays == [0.02]
    assert resumed_journal.records[0].retry_backoff_completed is True
    assert resumed_journal.records[1].retry_of == resumed_journal.records[0].attempt_id
    assert len(resumed_transport.calls) == 1


def test_ambiguous_delivery_after_restart_is_not_retried(tmp_path):
    clock = FakeClock()
    journal_path = tmp_path / "ambiguous.json"
    journal = AttemptJournal.empty()
    transport = FakeTransport([RuntimeError("synthetic timeout")], clock)
    kwargs = {
        "job": job(),
        "profile": approved_profile(),
        "questions": questions(),
        "variant": "direct",
        "identity": ASSESSOR,
        "transport": transport,
        "journal": journal,
        "limits": limits(),
        "clock": clock,
        "persist": lambda current: current.save(journal_path),
        "enabled": True,
    }
    with pytest.raises(ShadowResumeAmbiguous):
        run_shadow_assessment(**kwargs)
    assert journal.records[0].status == "ambiguous"
    resumed_transport = FakeTransport([])
    kwargs["transport"] = resumed_transport
    kwargs["journal"] = AttemptJournal.load(journal_path)
    with pytest.raises(ShadowResumeAmbiguous):
        run_shadow_assessment(**kwargs)
    assert resumed_transport.calls == []


def test_retry_resume_keeps_original_elapsed_budget_and_rejects_changed_limits(tmp_path):
    first_clock = FakeClock()
    journal_path = tmp_path / "elapsed-budget.json"
    journal = AttemptJournal.empty()
    failure = ProviderFailure(
        error_code="rate_limited",
        retryable=True,
        delivery="not_sent",
        model_identity=ASSESSOR,
        usage=Usage(None, None, None),
        charge=_charge(amount="0"),
    )
    with pytest.raises(ShadowBudgetExceeded, match="run deadline"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            FakeTransport([failure], first_clock),
            journal,
            limits(max_attempts_per_request=2, max_elapsed_seconds=0.5),
            first_clock,
            lambda current: current.save(journal_path),
            enabled=True,
            sleeper=FakeSleeper(first_clock, advance_factor=10),
        )

    resumed_clock = FakeClock(elapsed_ms=10)
    resumed_transport = FakeTransport([reply(ASSESSOR, assessment_payload())], resumed_clock)
    resumed_journal = AttemptJournal.load(journal_path)
    with pytest.raises(ShadowIntegrityError, match="different limits"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            resumed_transport,
            resumed_journal,
            limits(max_attempts_per_request=2, max_elapsed_seconds=1.0),
            resumed_clock,
            lambda current: current.save(journal_path),
            enabled=True,
        )
    assert resumed_transport.calls == []

    with pytest.raises(ShadowIntegrityError, match="wall clock moved backwards"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            resumed_transport,
            resumed_journal,
            limits(max_attempts_per_request=2, max_elapsed_seconds=0.5),
            FakeClock(elapsed_ms=-1),
            lambda current: current.save(journal_path),
            enabled=True,
        )
    assert resumed_transport.calls == []

    # Resume with the original limit and a clock beyond its persisted start time.
    with pytest.raises(ShadowBudgetExceeded, match="run deadline"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            resumed_transport,
            resumed_journal,
            limits(max_attempts_per_request=2, max_elapsed_seconds=0.5),
            FakeClock(elapsed_ms=1000),
            lambda current: current.save(journal_path),
            enabled=True,
        )
    assert resumed_transport.calls == []


def test_draws_have_distinct_identities_and_per_job_variant_and_draw_totals():
    clock = FakeClock()
    journal = AttemptJournal.empty()
    transport = FakeTransport(
        [reply(ASSESSOR, assessment_payload()), reply(ASSESSOR, assessment_payload())], clock
    )
    for draw_number in (1, 2):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(),
            clock,
            lambda current: None,
            enabled=True,
            draw_number=draw_number,
        )

    report = journal.aggregate()
    assert report["attempts_by_draw"] == {"1": 1, "2": 1}
    assert report["attempts_by_variant"] == {"direct": 2}
    assert report["per_variant"]["direct"]["actual_charges"] == [
        {"currency": "SYNTHETIC-CREDIT", "billing_unit": "fake-call", "amount": "0.10"}
    ]
    assert report["per_draw"]["1"]["actual_charges"] == [
        {"currency": "SYNTHETIC-CREDIT", "billing_unit": "fake-call", "amount": "0.05"}
    ]
    assert len(report["per_work_item"]) == 1
    assert next(iter(report["per_work_item"].values()))["attempts"] == 2
    assert [row["draw_number"] for row in report["per_successful_assessment"]] == [1, 2]


def test_unknown_charge_stops_before_any_followup_and_is_not_reported_as_zero(tmp_path):
    clock = FakeClock()
    journal = AttemptJournal.empty()
    unknown = reply(ASSESSOR, assessment_payload(), charge=Charge.unknown())
    transport = FakeTransport([unknown], clock)
    with pytest.raises(ShadowBudgetExceeded, match="actual charge was unknown"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(),
            clock,
            lambda current: current.save(tmp_path / "unknown-cost.json"),
            enabled=True,
        )
    assert journal.records[0].status == "budget_stop"
    assert journal.aggregate()["unknown_charge_attempts"] == 1
    assert journal.aggregate()["actual_charges"] == []
    assert len(transport.calls) == 1
    followup_transport = FakeTransport([reply(ASSESSOR, assessment_payload())], clock)
    with pytest.raises(ShadowBudgetExceeded, match="prior attempt reached a terminal budget stop"):
        run_shadow_assessment(
            JobEnvelope("Synthetic Co", "Other Role", "Remote", JD),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            followup_transport,
            journal,
            limits(),
            clock,
            lambda current: None,
            enabled=True,
        )
    assert followup_transport.calls == []


def test_estimated_charge_is_reported_separately_and_stops_budgeted_calls(tmp_path):
    clock = FakeClock()
    journal = AttemptJournal.empty()
    estimate = reply(ASSESSOR, assessment_payload(), charge=_charge(kind="estimate"))
    transport = FakeTransport([estimate], clock)

    with pytest.raises(ShadowBudgetExceeded, match="actual charge was unknown"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(),
            clock,
            lambda current: current.save(tmp_path / "estimated-cost.json"),
            enabled=True,
        )

    report = journal.aggregate()
    assert report["actual_charges"] == []
    assert report["estimated_charges"] == [
        {"currency": "SYNTHETIC-CREDIT", "billing_unit": "fake-call", "amount": "0.05"}
    ]
    assert report["estimated_charge_attempts"] == 1
    assert report["cost_reserve_attempts"] == 1


def test_extracted_assessment_rejects_stale_jd_facts_and_identity_mismatch_is_terminal():
    extraction = extraction_from_value(extraction_payload(), JD)
    with pytest.raises(ShadowIntegrityError, match="different JD version"):
        build_assessment_invocation(
            job("Changed JD."),
            approved_profile(),
            questions(),
            ASSESSOR,
            variant="extracted",
            extraction=extraction,
        )


def test_provider_resolved_model_mismatch_is_recorded_as_integrity_failure(tmp_path):
    clock = FakeClock()
    journal = AttemptJournal.empty()
    wrong_identity = ModelIdentity("fake-provider", "synthetic-assessor", "unexpected-model")
    transport = FakeTransport([reply(wrong_identity, assessment_payload())], clock)
    with pytest.raises(ShadowIntegrityError, match="identity differs from request"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(),
            clock,
            lambda current: current.save(tmp_path / "model-mismatch.json"),
            enabled=True,
        )
    assert journal.records[0].status == "integrity_failure"
    assert journal.records[0].error_code == "ShadowIntegrityError"
    assert journal.records[0].circuit_breaker is True
    with pytest.raises(ShadowProviderFailure, match="circuit breaker is open"):
        run_shadow_assessment(
            JobEnvelope("Synthetic Co", "Other Role", "Remote", JD),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            FakeTransport([]),
            journal,
            limits(),
            clock,
            lambda current: None,
            enabled=True,
        )


def test_malformed_charge_and_failure_metadata_are_terminal_and_journaled(tmp_path):
    for index, outcome in enumerate(
        [
            reply(ASSESSOR, assessment_payload(), charge=Charge([], None, None, None, None, None)),
            ProviderFailure(
                error_code="bad_delivery",
                retryable=True,
                delivery=[],
                model_identity=ASSESSOR,
                usage=Usage(None, None, None),
                charge=_charge(amount="0"),
                circuit_breaker=True,
            ),
        ]
    ):
        journal = AttemptJournal.empty()
        with pytest.raises(ShadowIntegrityError):
            run_shadow_assessment(
                job(),
                approved_profile(),
                questions(),
                "direct",
                ASSESSOR,
                FakeTransport([outcome], FakeClock()),
                journal,
                limits(),
                FakeClock(),
                lambda current: current.save(tmp_path / f"invalid-{index}.json"),
                enabled=True,
            )
        assert journal.records[0].status == "integrity_failure"
        assert journal.records[0].delivery == ("completed" if index == 0 else "unknown")
        if index == 1:
            assert journal.records[0].circuit_breaker is True


def test_attempt_limits_and_explicit_cost_and_time_bounds_are_required(tmp_path):
    clock = FakeClock()
    journal = AttemptJournal.empty()
    transport = FakeTransport([reply(ASSESSOR, assessment_payload())], clock)
    with pytest.raises(ShadowIntegrityError, match="explicit cost ceiling"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(cost_ceiling=None),
            clock,
            lambda current: None,
            enabled=True,
        )
    with pytest.raises(ShadowIntegrityError, match="max_elapsed_seconds"):
        run_shadow_assessment(
            job(),
            approved_profile(),
            questions(),
            "direct",
            ASSESSOR,
            transport,
            journal,
            limits(max_elapsed_seconds=None),
            clock,
            lambda current: None,
            enabled=True,
        )
    assert transport.calls == []


def test_journal_rejects_duplicate_json_members_and_bad_permissions(tmp_path):
    with pytest.raises(ShadowIntegrityError, match="duplicate journal JSON"):
        AttemptJournal.from_json(
            '{"schema":3,"schema":3,"run_started_at":null,"limits_identity_sha256":null,"records":[]}'
        )
    path = tmp_path / "insecure.json"
    path.write_text(
        '{"schema":3,"run_started_at":null,"limits_identity_sha256":null,"records":[]}'
    )
    path.chmod(0o644)
    with pytest.raises(ShadowIntegrityError, match="permissions"):
        AttemptJournal.load(path)
