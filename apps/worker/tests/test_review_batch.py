from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ats_worker.review_batch import (
    ReviewBatchError,
    build_review_batch,
    greedy_role_coverage,
    oldest_first,
    page_review_batch,
    priority_order,
    revalidate_review_batch,
    summary,
    uniform_audit_sample,
)


NOW = "2026-10-28T12:00:00Z"
WINDOW = {
    "resume_from": "2026-10-28T10:00:00Z",
    "cutoff_at": NOW,
    "include_historic_backfill": False,
}


def policy(**changes):
    value = {
        "version": "synthetic-policy-v1",
        "recipe_id": "synthetic_age_service_redistribute_v1",
        "k": 4,
        "ranked_slots": 2,
        "audit_slots": 1,
        "unresolved_slots": 1,
        "tie_rule": "priority_then_occurrence_id",
        "seed": 17,
        "page_size": 2,
        "service_age_hours": 4,
        "service_slots": 1,
        "role_coverage_slots": 1,
        "overload_threshold": 2,
        "retry_max_overdue_hours": 72,
        "max_candidate_count": 300,
        "max_replacements": 1,
        "max_revalidation_work": 1000,
        "max_elapsed_seconds": 10,
        "redistribution_order": ["ranked", "audit", "unresolved"],
    }
    value.update(changes)
    if "k" not in changes and any(key in changes for key in ("ranked_slots", "audit_slots", "unresolved_slots")):
        value["k"] = value["ranked_slots"] + value["audit_slots"] + value["unresolved_slots"]
    return value


def candidate(candidate_id="c1", **changes):
    value = {
        "candidate_id": candidate_id,
        "source_id": "board-a",
        "posting_identity": f"posting-{candidate_id}",
        "requisition_id": f"req-{candidate_id}",
        "source_revision": 1,
        "content_revision": 1,
        "content_identity": f"content-{candidate_id}-v1",
        "assessment_version": "assessment-v1",
        "assessment_state": "current",
        "assessment_content_revision": 1,
        "eligibility_state": "eligible",
        "yoe_state": "pass",
        "source_state": "open",
        "confirmed_application": False,
        "manual_terminal": False,
        "kind": "newly_retained",
        "first_eligible_at": "2026-10-28T10:00:00Z",
        "deferred_at": None,
        "retry_due_at": None,
        "priority_order": 1,
        "role_family_ids": ["swe"],
        "group_ids": [],
        "title": "Synthetic engineer",
        "company": "Synthetic company",
        "provenance": [f"source-row-{candidate_id}"],
    }
    value.update(changes)
    return value


def fixture(candidates=None, **changes):
    value = {
        "schema_version": 1,
        "synthetic": True,
        "pool_id": "daily-2026-10-28",
        "now": NOW,
        "window": dict(WINDOW),
        "policy": policy(),
        "candidates": [candidate()],
        "applications": [],
        "duplicate_evidence": [],
    }
    if candidates is not None:
        value["candidates"] = candidates
    value.update(changes)
    return value


def test_policy_requires_explicit_nonnegative_allocations_and_caps():
    value = fixture()
    del value["policy"]["seed"]
    with pytest.raises(ReviewBatchError, match="policy"):
        build_review_batch(value)

    bad_total = fixture()
    bad_total["policy"]["audit_slots"] = -1
    with pytest.raises(ReviewBatchError, match="policy"):
        build_review_batch(bad_total)

    mismatch = fixture()
    mismatch["policy"]["k"] = 5
    with pytest.raises(ReviewBatchError, match="sum to K"):
        build_review_batch(mismatch)

    bad_split = fixture()
    bad_split["policy"]["ranked_slots"] = 1
    bad_split["policy"]["service_slots"] = 2
    with pytest.raises(ReviewBatchError, match="policy"):
        build_review_batch(bad_split)


def test_occurrence_identity_uses_pool_posting_and_source_revision_only():
    first = build_review_batch(fixture([candidate("c1", posting_identity="stable-job")]))
    repeated = build_review_batch(fixture(
        [candidate("c9", posting_identity="stable-job")], pool_id="daily-2026-10-29"
    ))
    changed_revision = build_review_batch(fixture(
        [candidate("c1", posting_identity="stable-job", source_revision=2)]
    ))

    first_entry = first["candidate_records"][0]
    repeated_entry = repeated["candidate_records"][0]
    changed_entry = changed_revision["candidate_records"][0]
    assert first_entry["posting_identity"] == repeated_entry["posting_identity"]
    assert first_entry["occurrence_id"] != repeated_entry["occurrence_id"]
    assert first_entry["occurrence_id"] != changed_entry["occurrence_id"]
    assert first_entry["content_identity"] == "content-c1-v1"


def test_new_arrivals_use_half_open_resume_cutoff_and_historic_scope_is_explicit():
    rows = [
        candidate("at-start", first_eligible_at=WINDOW["resume_from"]),
        candidate("at-cutoff", first_eligible_at=WINDOW["cutoff_at"]),
        candidate("before-resume", first_eligible_at="2026-10-28T09:59:59Z"),
        candidate("old", kind="historic", first_eligible_at="2026-10-20T09:00:00Z"),
    ]
    batch = build_review_batch(fixture(rows))
    reasons = {item["candidate_id"]: item["reason"] for item in batch["excluded"]}
    included = {row["candidate_id"] for row in batch["candidate_records"]}
    assert "at-start" in included
    assert "at-cutoff" not in included
    assert reasons["at-cutoff"] == "outside_cutoff_interval"
    assert reasons["before-resume"] == "before_resume_interval"
    assert reasons["old"] == "historic_backfill_not_enabled"

    historic = fixture(rows, window={**WINDOW, "include_historic_backfill": True})
    assert "old" in {row["candidate_id"] for row in build_review_batch(historic)["candidate_records"]}


def test_old_deferred_and_due_retry_are_candidates_but_future_retry_is_not():
    rows = [
        candidate("deferred", kind="deferred", first_eligible_at="2026-10-27T08:00:00Z",
                  deferred_at="2026-10-27T12:00:00Z"),
        candidate("due", kind="retry", first_eligible_at="2026-10-27T08:00:00Z",
                  retry_due_at="2026-10-28T11:59:59Z"),
        candidate("not-due", kind="retry", retry_due_at="2026-10-28T12:00:01Z"),
        candidate("overdue", kind="retry", first_eligible_at="2026-10-27T08:00:00Z",
                  retry_due_at="2026-10-20T11:00:00Z"),
    ]
    batch = build_review_batch(fixture(rows))
    included = {row["candidate_id"] for row in batch["candidate_records"]}
    assert included == {"deferred", "due", "overdue"}
    assert {row["candidate_id"]: row["bucket"] for row in batch["candidate_records"]}["overdue"] == "unresolved"
    assert any(item["reason"] == "retry_not_due" for item in batch["excluded"])
    assert {row["candidate_id"]: row["reason"] for row in batch["candidate_records"]}["overdue"] == "retry_overdue_threshold_exceeded"


def test_utc_offset_boundaries_and_yoe_exclusion_are_independent():
    rows = [
        candidate("equivalent-start", first_eligible_at="2026-10-28T12:00:00+02:00"),
        candidate("equivalent-cutoff", first_eligible_at="2026-10-28T14:00:00+02:00"),
        candidate("yoe-first", assessment_state="stale", yoe_state="exclude"),
    ]
    batch = build_review_batch(fixture(rows))
    reasons = {item["candidate_id"]: item["reason"] for item in batch["excluded"]}
    included = {row["candidate_id"] for row in batch["candidate_records"]}
    assert "equivalent-start" in included
    assert reasons["equivalent-cutoff"] == "outside_cutoff_interval"
    assert reasons["yoe-first"] == "yoe_excluded"


def test_half_open_window_preserves_nanosecond_cutoff_precision():
    window = {
        "resume_from": "2026-10-28T10:00:00.123456789Z",
        "cutoff_at": "2026-10-28T10:00:01Z",
        "include_historic_backfill": False,
    }
    rows = [
        candidate("before", first_eligible_at="2026-10-28T10:00:00.123456788Z"),
        candidate("at-start", first_eligible_at="2026-10-28T10:00:00.123456789Z"),
        candidate("at-end", first_eligible_at="2026-10-28T10:00:01Z"),
    ]
    batch = build_review_batch(fixture(
        rows, window=window, now="2026-10-28T10:00:01.000000001Z"
    ))
    included = {row["candidate_id"] for row in batch["candidate_records"]}
    reasons = {item["candidate_id"]: item["reason"] for item in batch["excluded"]}
    assert included == {"at-start"}
    assert reasons["before"] == "before_resume_interval"
    assert reasons["at-end"] == "outside_cutoff_interval"


def test_terminal_and_unlinked_application_exclusions_keep_reasons():
    rows = [
        candidate("linked", requisition_id="req-applied"),
        candidate("manual", manual_terminal=True),
        candidate("closed", source_state="closed"),
        candidate("unknown-source", source_state="unknown"),
        candidate("stale", assessment_state="stale"),
        candidate("missing-yoe", yoe_state="unknown"),
        candidate("yoe-excluded", yoe_state="exclude"),
        candidate("ineligible", eligibility_state="ineligible"),
    ]
    value = fixture(rows, applications=[{
        "application_id": "app-unlinked",
        "confirmed": True,
        "posting_id": None,
        "requisition_id": "req-applied",
        "source_id": "board-a",
    }])
    batch = build_review_batch(value)
    reasons = {item["candidate_id"]: item["reason"] for item in batch["excluded"]}
    buckets = {row["candidate_id"]: row["bucket"] for row in batch["candidate_records"]}
    assert reasons["linked"] == "confirmed_application"
    assert reasons["manual"] == "manual_terminal"
    assert reasons["closed"] == "source_closed"
    assert reasons["yoe-excluded"] == "yoe_excluded"
    assert reasons["ineligible"] == "eligibility_excluded"
    assert buckets["unknown-source"] == "unresolved"
    assert buckets["stale"] == "unresolved"
    assert buckets["missing-yoe"] == "unresolved"
    assert batch["report"]["actually_read"] == "unknown"
    assert batch["report"]["delivered"] == "unknown"


def test_exact_and_corroborated_duplicates_collapse_but_similarity_only_flags():
    rows = [
        candidate("a", source_id="board-a", requisition_id="req-exact", group_ids=["split-1"]),
        candidate("b", source_id="board-a", requisition_id="req-exact", group_ids=["split-2"]),
        candidate("c", source_id="board-b", posting_identity="cross-c"),
        candidate("d", source_id="board-c", posting_identity="cross-d"),
        candidate("unproven", source_id="board-d", posting_identity="cross-unproven",
                  title="Senior Engineer", company="Similar Co"),
        candidate("similar-1", title="Staff Engineer", company="Acme"),
        candidate("similar-2", title="Staff Engineer", company="Acme"),
    ]
    value = fixture(rows, duplicate_evidence=[{
        "kind": "cross_source_corroboration",
        "evidence_id": "fake-corroboration",
        "candidate_ids": ["c", "d"],
    }])
    batch = build_review_batch(value)
    by_id = {row["candidate_id"]: row for row in batch["candidate_records"]}
    assert by_id["a"]["group_ids"] == ["split-1", "split-2"]
    assert by_id["a"]["provenance"] == ["source-row-a", "source-row-b"]
    assert batch["report"]["collapsed_duplicates"] == 2
    assert by_id["c"]["collapsed_candidate_ids"] == ["d"]
    assert by_id["c"]["duplicate_evidence_ids"] == ["fake-corroboration"]
    assert by_id["unproven"]["collapsed_candidate_ids"] == []
    assert by_id["similar-1"]["duplicate_review_flags"] == ["title_company_similarity"]
    assert by_id["similar-2"]["duplicate_review_flags"] == ["title_company_similarity"]


def test_confirmed_exclusion_survives_exact_and_corroborated_duplicate_grouping():
    exact = [
        candidate("exact-applied", requisition_id="req-shared", confirmed_application=True),
        candidate("exact-open", requisition_id="req-shared"),
    ]
    corroborated = [
        candidate("closed", source_id="board-a", posting_identity="cross-a", source_state="closed"),
        candidate("open", source_id="board-b", posting_identity="cross-b"),
    ]
    value = fixture(exact + corroborated, duplicate_evidence=[{
        "kind": "cross_source_corroboration",
        "evidence_id": "cross-evidence",
        "candidate_ids": ["closed", "open"],
    }])
    batch = build_review_batch(value)
    reasons = {row["candidate_id"]: row["reason"] for row in batch["excluded"]}
    records = {row["candidate_id"]: row for row in batch["candidate_records"]}
    assert reasons["exact-applied"] == reasons["exact-open"] == "confirmed_application"
    assert "closed" not in reasons and "open" not in reasons
    assert records["closed"]["bucket"] == "unresolved"
    assert records["closed"]["reason"] == "duplicate_source_state_conflict"
    assert [row["source_state"] for row in records["closed"]["duplicate_member_evidence"]] == ["closed", "open"]
    assert set(records["closed"]["collapsed_candidate_ids"]) == {"open"}

    manual = build_review_batch(fixture([
        candidate("manual-terminal", requisition_id="req-manual", manual_terminal=True),
        candidate("manual-sibling", requisition_id="req-manual"),
    ]))
    manual_reasons = {row["candidate_id"]: row["reason"] for row in manual["excluded"]}
    assert manual_reasons == {
        "manual-terminal": "manual_terminal",
        "manual-sibling": "manual_terminal",
    }


def test_requisition_application_evidence_is_scoped_or_visible_as_ambiguous():
    rows = [
        candidate("board-a", source_id="board-a", requisition_id="req-collision"),
        candidate("board-b", source_id="board-b", requisition_id="req-collision"),
    ]
    scoped = build_review_batch(fixture(rows, applications=[{
        "application_id": "scoped-app", "confirmed": True, "posting_id": None,
        "requisition_id": "req-collision", "source_id": "board-a",
    }]))
    excluded = {row["candidate_id"] for row in scoped["excluded"]}
    assert excluded == {"board-a"}
    assert {row["candidate_id"] for row in scoped["candidate_records"]} == {"board-b"}

    ambiguous = build_review_batch(fixture(rows, applications=[{
        "application_id": "ambiguous-app", "confirmed": True, "posting_id": None,
        "requisition_id": "req-collision",
    }]))
    assert {row["reason"] for row in ambiguous["candidate_records"]} == {"application_identity_ambiguous"}
    assert ambiguous["excluded"] == []


def test_stable_posting_occurrences_are_unique_before_audit_sampling():
    rows = [
        candidate("a", posting_identity="same-posting", requisition_id=None),
        candidate("b", posting_identity="same-posting", requisition_id=None),
    ]
    batch = build_review_batch(fixture(rows, policy=policy(
        ranked_slots=0, audit_slots=2, unresolved_slots=0,
        service_slots=0, role_coverage_slots=0,
    )))
    assert batch["report"]["included_occurrence_count"] == 1
    assert len(batch["audit_frame_ids"]) == len(set(batch["audit_frame_ids"])) == 1
    assert len(batch["audit_selected_ids"]) == 1
    assert len({slot["occurrence_id"] for slot in batch["slots"]}) == len(batch["slots"])
    assert batch["report"]["audit_inclusion_probability"] == 1.0


def test_selection_helpers_are_deterministic_prioritize_age_and_cover_roles():
    rows = [
        {"candidate_id": "a", "occurrence_id": "occ-a", "priority_order": 3,
         "first_eligible_at": "2026-10-27T10:00:00Z", "role_family_ids": ["rare"]},
        {"candidate_id": "b", "occurrence_id": "occ-b", "priority_order": 1,
         "first_eligible_at": "2026-10-28T11:00:00Z", "role_family_ids": ["common"]},
        {"candidate_id": "c", "occurrence_id": "occ-c", "priority_order": 2,
         "first_eligible_at": "2026-10-28T09:00:00Z", "role_family_ids": ["common", "rare"]},
    ]
    assert [x["candidate_id"] for x in priority_order(rows)] == ["b", "c", "a"]
    assert [x["candidate_id"] for x in oldest_first(rows)] == ["a", "c", "b"]
    assert [x["candidate_id"] for x in greedy_role_coverage(rows, 1)] == ["c"]
    frame, sample, probability = uniform_audit_sample(rows, 2, seed=7)
    assert len(frame) == len(set(frame)) == 3
    assert len(sample) == len(set(sample)) == 2
    assert probability == pytest.approx(2 / 3)
    assert uniform_audit_sample(rows, 2, seed=7)[1] == sample
    with pytest.raises(ReviewBatchError, match="not unique"):
        uniform_audit_sample([rows[0], dict(rows[0])], 2, seed=7)


def test_age_service_fixed_allocations_redistribution_and_cursor_pages():
    rows = [
        candidate("aged", kind="deferred", first_eligible_at="2026-10-27T01:00:00Z",
                  deferred_at="2026-10-27T02:00:00Z", priority_order=9),
        candidate("fresh", priority_order=1),
        candidate("third", priority_order=2),
        candidate("fourth", priority_order=3),
    ]
    value = fixture(rows, policy=policy(
        ranked_slots=1, audit_slots=0, unresolved_slots=3, role_coverage_slots=0
    ))
    batch = build_review_batch(value)
    assert batch["report"]["initial_selections"] == {"ranked": 1, "audit": 0, "unresolved": 0}
    assert batch["report"]["redistributed_slots"] == {"ranked": 3, "audit": 0, "unresolved": 0}
    assert batch["report"]["unfilled_slots"] == 0
    slots = batch["slots"]
    assert slots[0]["category"] == "ranked"
    assert batch["entries"][slots[0]["candidate_id"]]["candidate_id"] == "aged"

    first_page = page_review_batch(batch)
    assert len(first_page["items"]) == 2
    second_page = page_review_batch(batch, first_page["next_cursor"])
    assert len(second_page["items"]) == 2
    assert second_page["next_cursor"] is None
    assert page_review_batch(batch, first_page["next_cursor"]) == second_page
    with pytest.raises(ReviewBatchError, match="cursor"):
        page_review_batch(batch, "forged")

    changed_policy = fixture(rows, policy=policy(
        ranked_slots=2, audit_slots=0, unresolved_slots=0, version="other-policy"
    ))
    with pytest.raises(ReviewBatchError, match="identity changed"):
        revalidate_review_batch(batch, changed_policy, elapsed_seconds=1)


def test_clock_and_final_order_are_bound_to_batch_and_cursor_identity():
    rows = [
        candidate("old", kind="deferred", first_eligible_at="2026-10-28T09:00:00Z",
                  deferred_at="2026-10-28T09:00:00Z", priority_order=99),
        candidate("high", priority_order=1),
        candidate("next", priority_order=2),
    ]
    scoped_policy = policy(
        k=2, ranked_slots=2, audit_slots=0, unresolved_slots=0,
        service_age_hours=4, service_slots=1, role_coverage_slots=0, page_size=1,
    )
    at_noon = build_review_batch(fixture(rows, policy=scoped_policy))
    later = build_review_batch(fixture(
        rows, policy=scoped_policy, now="2026-10-28T14:00:00Z"
    ))
    assert [slot["candidate_id"] for slot in at_noon["slots"]] == ["high", "next"]
    assert [slot["candidate_id"] for slot in later["slots"]] == ["old", "high"]
    assert at_noon["batch_id"] != later["batch_id"]
    assert at_noon["snapshot_id"] != later["snapshot_id"]
    with pytest.raises(ReviewBatchError, match="cursor"):
        page_review_batch(later, page_review_batch(at_noon)["next_cursor"])


def test_audit_frame_is_frozen_and_probability_uses_actual_frame_size():
    rows = [candidate(f"c{i}", priority_order=i) for i in range(8)]
    value = fixture(rows, policy=policy(ranked_slots=2, audit_slots=3, unresolved_slots=0))
    batch = build_review_batch(value)
    assert len(batch["audit_frame_ids"]) == 6
    assert len(batch["audit_selected_ids"]) == 3
    assert batch["report"]["audit_inclusion_probability"] == pytest.approx(0.5)
    assert len(set(batch["audit_selected_ids"])) == 3


def test_revalidation_marks_changed_versions_and_replaces_within_caps_without_reordering():
    rows = [candidate(f"c{i}", priority_order=i) for i in range(6)]
    value = fixture(rows, policy=policy(ranked_slots=2, audit_slots=0, unresolved_slots=0))
    batch = build_review_batch(value)
    first_page = page_review_batch(batch)
    first_slot = batch["slots"][0]
    selected_id = first_slot["candidate_id"]
    live = [dict(row) for row in rows]
    changed = next(row for row in live if row["candidate_id"] == selected_id)
    changed["content_revision"] = 2
    changed["content_identity"] = "content-changed"
    changed["assessment_state"] = "stale"
    refreshed = fixture(live, policy=value["policy"], pool_id=value["pool_id"],
                        now="2026-10-28T12:00:01Z", window=value["window"])

    updated = revalidate_review_batch(batch, refreshed, elapsed_seconds=1)
    assert updated["slots"][0]["slot_id"] == first_slot["slot_id"]
    assert updated["slots"][0]["invalidated"]["reason"] == "content_changed"
    assert updated["slots"][0]["replacement"]["candidate_id"] != selected_id
    assert updated["slots"][0]["replacement"]["replacement_for_slot_id"] == first_slot["slot_id"]
    assert updated["report"]["invalidations"] == 1
    assert updated["report"]["replacement_entries"] == 1
    assert page_review_batch(updated)["items"][0]["slot_id"] == first_page["items"][0]["slot_id"]

    no_time = revalidate_review_batch(batch, refreshed, elapsed_seconds=11)
    assert no_time["report"]["replacement_entries"] == 0
    assert no_time["report"]["time_cap_reached"] is True


def test_revalidation_reports_closure_and_application_reasons_and_honors_replacement_cap():
    rows = [candidate(f"c{i}", priority_order=i) for i in range(6)]
    value = fixture(rows, policy=policy(ranked_slots=2, audit_slots=0, unresolved_slots=0))
    batch = build_review_batch(value)
    selected = [slot["candidate_id"] for slot in batch["slots"]]
    current = [dict(row) for row in rows]
    close_id, apply_id = selected
    next(row for row in current if row["candidate_id"] == close_id)["source_state"] = "closed"
    app_candidate = next(row for row in current if row["candidate_id"] == apply_id)
    app_candidate["requisition_id"] = "newly-applied"
    updated = revalidate_review_batch(
        batch,
        fixture(current, policy=value["policy"], applications=[{
            "application_id": "confirmed-now",
            "confirmed": True,
            "posting_id": None,
            "requisition_id": "newly-applied",
            "source_id": app_candidate["source_id"],
        }]),
        elapsed_seconds=1,
    )
    reasons = {slot["invalidated"]["candidate_id"]: slot["invalidated"]["reason"]
               for slot in updated["slots"] if slot["invalidated"]}
    assert reasons[close_id] == "source_closed"
    assert reasons[apply_id] == "confirmed_application"
    assert all(slot["replacement"]["candidate_id"] != slot["candidate_id"]
               for slot in updated["slots"] if slot["replacement"])

    no_replacement_policy = policy(
        ranked_slots=2, audit_slots=0, unresolved_slots=0, max_replacements=0
    )
    capped_batch = build_review_batch(fixture(rows, policy=no_replacement_policy))
    capped_current = [dict(row) for row in rows]
    next(row for row in capped_current if row["candidate_id"] == capped_batch["slots"][0]["candidate_id"])["source_revision"] = 2
    capped = revalidate_review_batch(
        capped_batch, fixture(capped_current, policy=no_replacement_policy), elapsed_seconds=1
    )
    assert capped["report"]["replacement_entries"] == 0
    assert capped["report"]["active_slots"] == 1
    assert capped["report"]["unfilled_slots"] == 1


def test_revalidation_work_cap_limits_full_analysis_and_hides_unverified_slots():
    rows = [candidate(f"c{i}", priority_order=i) for i in range(5)]
    scoped_policy = policy(
        ranked_slots=2, audit_slots=0, unresolved_slots=0,
        max_revalidation_work=2, max_replacements=2,
    )
    batch = build_review_batch(fixture(rows, policy=scoped_policy))
    changed = [dict(row) for row in rows]
    selected_ids = {slot["candidate_id"] for slot in batch["slots"]}
    for row in changed:
        if row["candidate_id"] in selected_ids:
            row["content_revision"] = 2
            row["content_identity"] = f"{row['content_identity']}-changed"
            row["assessment_state"] = "stale"
    updated = revalidate_review_batch(
        batch, fixture(changed, policy=scoped_policy), elapsed_seconds=1
    )
    assert updated["report"]["revalidation_work"] == 2
    assert updated["report"]["replacement_entries"] == 0
    assert updated["report"]["work_cap_reached"] is True
    assert updated["report"]["revalidation_complete"] is False
    assert updated["report"]["unverified_slots"] == 2
    assert all(item["candidate"] is None for item in page_review_batch(updated)["items"])
    assert {row["reason"] for row in summary(updated)["unverified_sample"]} == {
        "revalidation_work_cap_reached"
    }


def test_audit_replacement_stays_inside_the_frozen_low_rank_frame():
    rows = [candidate(f"c{i}", priority_order=i) for i in range(6)]
    scoped_policy = policy(
        ranked_slots=1, audit_slots=1, unresolved_slots=0,
        service_slots=0, role_coverage_slots=0,
    )
    batch = build_review_batch(fixture(rows, policy=scoped_policy))
    audit_slot = next(slot for slot in batch["slots"] if slot["category"] == "audit")
    original_audit_id = audit_slot["candidate_id"]
    changed = [dict(row) for row in rows]
    target = next(row for row in changed if row["candidate_id"] == original_audit_id)
    target["content_revision"] = 2
    target["content_identity"] = "new-content"
    target["assessment_state"] = "stale"
    updated = revalidate_review_batch(
        batch, fixture(changed, policy=scoped_policy), elapsed_seconds=1
    )
    updated_audit = next(slot for slot in updated["slots"] if slot["category"] == "audit")
    assert updated_audit["replacement"]["candidate_id"] != original_audit_id
    assert updated_audit["replacement"]["occurrence_id"] in batch["audit_frame_ids"]


def test_revalidation_work_cap_counts_candidate_search_and_sorting():
    rows = [candidate(f"c{i}", priority_order=i) for i in range(5)]
    base_policy = policy(ranked_slots=2, audit_slots=0, unresolved_slots=0, max_revalidation_work=10_000)
    baseline = build_review_batch(fixture(rows, policy=base_policy))
    stable = revalidate_review_batch(
        baseline, fixture(rows, policy=base_policy), elapsed_seconds=1
    )
    analysis_and_slot_cost = stable["report"]["revalidation_work"]

    selected_id = baseline["slots"][0]["candidate_id"]
    changed = [dict(row) for row in rows]
    target = next(row for row in changed if row["candidate_id"] == selected_id)
    target["source_state"] = "closed"
    tight_policy = policy(
        ranked_slots=2, audit_slots=0, unresolved_slots=0,
        max_revalidation_work=analysis_and_slot_cost + 1,
    )
    tight_batch = build_review_batch(fixture(rows, policy=tight_policy))
    limited = revalidate_review_batch(
        tight_batch, fixture(changed, policy=tight_policy), elapsed_seconds=1
    )
    assert limited["report"]["work_cap_reached"] is True
    assert limited["report"]["revalidation_work"] == analysis_and_slot_cost + 1
    assert limited["report"]["revalidation_complete"] is False
    assert limited["candidate_records"] == []
    assert all(item["candidate"] is None for item in page_review_batch(limited)["items"])


def test_revalidation_time_cap_short_circuits_before_candidate_validation(monkeypatch):
    import ats_worker.review_batch as review_batch

    scoped_policy = policy(
        ranked_slots=1, audit_slots=0, unresolved_slots=0,
        role_coverage_slots=0, service_slots=0,
        max_revalidation_work=0, max_elapsed_seconds=0,
    )
    batch = build_review_batch(fixture([candidate("selected")], policy=scoped_policy))
    calls = 0
    real_validate = review_batch._validate_candidate

    def counted(value, work=None):
        nonlocal calls
        calls += 1
        return real_validate(value, work)

    monkeypatch.setattr(review_batch, "_validate_candidate", counted)
    failed = revalidate_review_batch(
        batch, fixture([candidate("selected")], policy=scoped_policy), elapsed_seconds=1
    )
    assert calls == 0
    assert failed["report"]["time_cap_reached"] is True
    assert failed["report"]["revalidation_work"] == 0
    assert failed["current_validation_status"] == "incomplete"
    assert failed["candidate_records"] == []
    assert page_review_batch(failed)["items"][0]["candidate"] is None


def test_real_cli_persisted_revalidation_keeps_history_and_cumulative_caps(tmp_path):
    worker_root = Path(__file__).parents[1]
    env = {**os.environ, "PYTHONPATH": str(worker_root)}
    rows = [candidate(name, priority_order=index) for index, name in enumerate(("a", "b", "c"))]
    scoped_policy = policy(
        ranked_slots=1, audit_slots=0, unresolved_slots=0,
        service_slots=0, role_coverage_slots=0,
        max_replacements=1, max_revalidation_work=1000,
    )
    fixture_path = tmp_path / "pool.json"
    state_path = tmp_path / "state.json"

    def write_fixture(candidates):
        fixture_path.write_text(json.dumps(fixture(candidates, policy=scoped_policy)))

    def run(action, elapsed=None):
        args = [sys.executable, "-m", "ats_worker.review_batch_cli", "--action", action,
                "--state", str(state_path)]
        if action in {"create", "revalidate"}:
            args.extend(["--fixture", str(fixture_path)])
        if elapsed is not None:
            args.extend(["--elapsed-seconds", str(elapsed)])
        completed = subprocess.run(args, cwd=worker_root, env=env, text=True,
                                   capture_output=True, check=False)
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    write_fixture(rows)
    created = run("create")
    original_id = created["first_page"]["items"][0]["candidate"]["candidate_id"]
    first_rows = [dict(row) for row in rows]
    next(row for row in first_rows if row["candidate_id"] == original_id)["source_state"] = "closed"
    write_fixture(first_rows)
    first = run("revalidate", elapsed=1)
    first_state = json.loads(state_path.read_text())
    first_slot = first_state["slots"][0]
    replacement_id = first_slot["current_candidate_id"]
    assert replacement_id != original_id
    assert len(first_slot["replacement_history"]) == 1
    assert first["report"]["invalidations"] == 1
    assert first["report"]["replacement_entries"] == 1

    second_rows = [dict(row) for row in rows]
    for row in second_rows:
        if row["candidate_id"] in {original_id, replacement_id}:
            row["source_state"] = "closed"
    write_fixture(second_rows)
    second = run("revalidate", elapsed=1)
    second_state = json.loads(state_path.read_text())
    second_slot = second_state["slots"][0]
    assert second["report"]["invalidations"] == 2
    assert second["report"]["replacement_entries"] == 1
    assert second["report"]["observed_elapsed_seconds"] == 2
    assert second["report"]["last_observed_elapsed_seconds"] == 1
    assert second["report"]["replacement_cap_reached"] is True
    assert second_slot["current_candidate_id"] is None
    assert [entry["candidate_id"] for entry in second_slot["replacement_history"]] == [replacement_id]
    assert [event["candidate_id"] for event in second_slot["invalidation_history"]] == [original_id, replacement_id]
    assert second["first_page"]["items"][0]["candidate"] is None
    assert second["invalidation_history_sample"] == [
        {"slot_id": second_slot["slot_id"], "candidate_id": original_id, "reason": "source_closed"},
        {"slot_id": second_slot["slot_id"], "candidate_id": replacement_id, "reason": "source_closed"},
    ]


@pytest.mark.parametrize("count", [0, 1, 200, 201])
def test_real_cli_processes_empty_small_and_over_200_synthetic_pools(tmp_path, count):
    worker_root = Path(__file__).parents[1]
    candidates = [candidate(f"c{i}", priority_order=i) for i in range(count)]
    value = fixture(candidates, policy=policy(
        ranked_slots=2, audit_slots=1, unresolved_slots=1,
        max_candidate_count=max(300, count),
    ))
    fixture_path = tmp_path / f"pool-{count}.json"
    state_path = tmp_path / f"state-{count}.json"
    fixture_path.write_text(json.dumps(value))
    env = {**os.environ, "PYTHONPATH": str(worker_root)}
    completed = subprocess.run(
        [sys.executable, "-m", "ats_worker.review_batch_cli", "--action", "create",
         "--fixture", str(fixture_path), "--state", str(state_path)],
        cwd=worker_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    output = json.loads(completed.stdout)
    assert output["scope"] == "synthetic_review_batch"
    assert output["synthetic"] is True
    assert output["report"]["available_count"] == count
    assert state_path.exists()


def test_cli_requires_explicit_fixture_and_state_paths(tmp_path):
    worker_root = Path(__file__).parents[1]
    completed = subprocess.run(
        [sys.executable, "-m", "ats_worker.review_batch_cli"],
        cwd=worker_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "--fixture" in completed.stderr and "--state" in completed.stderr


def test_cli_errors_do_not_echo_synthetic_private_text(tmp_path):
    worker_root = Path(__file__).parents[1]
    value = fixture([candidate("bad", title="PRIVATE-TEXT-SENTINEL", source_revision=0)])
    fixture_path = tmp_path / "bad.json"
    state_path = tmp_path / "state.json"
    fixture_path.write_text(json.dumps(value))
    env = {**os.environ, "PYTHONPATH": str(worker_root)}
    completed = subprocess.run(
        [sys.executable, "-m", "ats_worker.review_batch_cli", "--action", "create",
         "--fixture", str(fixture_path), "--state", str(state_path)],
        cwd=worker_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "PRIVATE-TEXT-SENTINEL" not in completed.stdout + completed.stderr
    assert not state_path.exists()


def test_fresh_import_does_not_load_runtime_db_network_or_scorer_modules(tmp_path):
    worker_root = Path(__file__).parents[1]
    env = {**os.environ, "PYTHONPATH": str(worker_root)}
    code = (
        "import sys; import ats_worker.review_batch; import ats_worker.review_batch_cli; "
        "bad={'requests','sqlite3','ats_worker.run','ats_worker.config','ats_worker.score'}; "
        "assert not bad.intersection(sys.modules), bad.intersection(sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=worker_root, env=env, text=True,
        capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_committed_fixture_runs_real_projection_and_keeps_text_out_of_the_view(tmp_path):
    worker_root = Path(__file__).parents[1]
    fixture_path = worker_root / "tests/fixtures/review_batch_contract.json"
    state_path = tmp_path / "fixture-state.json"
    env = {**os.environ, "PYTHONPATH": str(worker_root)}
    completed = subprocess.run(
        [sys.executable, "-m", "ats_worker.review_batch_cli", "--action", "create",
         "--fixture", str(fixture_path), "--state", str(state_path)],
        cwd=worker_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    output = json.loads(completed.stdout)
    assert output["report"]["available_count"] == 6
    assert output["report"]["unresolved_count"] == 1
    assert output["report"]["excluded_count"] == 1
    assert "Synthetic engineer" not in completed.stdout
    assert "Acme" not in completed.stdout
    assert "Synthetic engineer" not in state_path.read_text()

    cursor = output["first_page"]["next_cursor"]
    resumed = subprocess.run(
        [sys.executable, "-m", "ats_worker.review_batch_cli", "--action", "page",
         "--state", str(state_path), "--cursor", cursor],
        cwd=worker_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert resumed.returncode == 0, resumed.stderr
    resumed_page = json.loads(resumed.stdout)
    assert resumed_page["start"] == 2
    assert resumed_page["batch_id"] == output["batch_id"]

    changed_fixture = json.loads(fixture_path.read_text())
    selected_id = output["first_page"]["items"][0]["candidate"]["candidate_id"]
    selected = next(row for row in changed_fixture["candidates"] if row["candidate_id"] == selected_id)
    selected["content_revision"] = 2
    selected["content_identity"] = "synthetic-changed-content"
    selected["assessment_state"] = "stale"
    changed_path = tmp_path / "changed-pool.json"
    changed_path.write_text(json.dumps(changed_fixture))
    revalidated = subprocess.run(
        [sys.executable, "-m", "ats_worker.review_batch_cli", "--action", "revalidate",
         "--fixture", str(changed_path), "--state", str(state_path), "--elapsed-seconds", "1"],
        cwd=worker_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert revalidated.returncode == 0, revalidated.stderr
    revised_output = json.loads(revalidated.stdout)
    assert revised_output["report"]["invalidations"] == 1
    assert revised_output["report"]["replacement_entries"] == 1
    assert revised_output["first_page"]["items"][0]["slot_id"] == output["first_page"]["items"][0]["slot_id"]
    assert "Synthetic engineer" not in revalidated.stdout
