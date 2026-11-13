import unittest

from tools.jev_p1_evaluation import (
    ARM_JEV,
    ARM_PUBLICATION,
    BUDGETS,
    InputError,
    evaluate,
    metrics_for_selection,
    select_day,
    validate_input,
)


DOMAINS = [f"synthetic_{letter}" for letter in "abcdefgh"]


def row(
    job_id,
    *,
    domain="synthetic_a",
    day="2026-11-01",
    publication_time="2026-11-01T09:00:00Z",
    jev_state="high",
    needs_review=False,
    current_successful_binding=True,
    label="negative",
):
    return {
        "job_id": job_id,
        "day": day,
        "publication_time": publication_time,
        "domain": domain,
        "jev_state": jev_state,
        "needs_review": needs_review,
        "current_successful_binding": current_successful_binding,
        "label": label,
    }


def payload(rows, *, exclusions=0):
    return {
        "schema": "jev-p1-synthetic-v1",
        "pool_is_source_eligible": True,
        "declared_domains": list(DOMAINS),
        "whole_inventory_exclusions": exclusions,
        "rows": rows,
    }


class JevP1EvaluationTests(unittest.TestCase):
    def test_exact_budgets_share_reserve_ids_and_obey_k(self):
        rows = [
            row(
                f"job-{domain}-{index}",
                domain=domain,
                publication_time=f"2026-11-01T{9 + index:02d}:00:00Z",
                jev_state=("high" if index == 0 else "low"),
            )
            for domain in DOMAINS[:3]
            for index in range(4)
        ]
        data = payload(rows)
        validated_domains, validated_rows, _ = validate_input(data)
        self.assertEqual(BUDGETS, ((10, 2), (20, 4), (40, 8)))

        for k, r in BUDGETS:
            publication, pub_reserve = select_day(
                validated_rows, validated_domains, "2026-11-01", k, r, ARM_PUBLICATION
            )
            jev, jev_reserve = select_day(
                validated_rows, validated_domains, "2026-11-01", k, r, ARM_JEV
            )
            self.assertEqual(pub_reserve, jev_reserve)
            self.assertLessEqual(len(publication), k)
            self.assertLessEqual(len(jev), k)
            self.assertEqual(len(publication), len({item["job_id"] for item in publication}))
            self.assertEqual(len(jev), len({item["job_id"] for item in jev}))
            self.assertTrue(pub_reserve.issubset({item["job_id"] for item in publication}))

    def test_duplicate_and_invalid_ids_are_rejected(self):
        with self.assertRaisesRegex(InputError, "duplicate ID"):
            validate_input(payload([row("same"), row("same")]))
        for invalid in ("", " padded ", "line\nbreak"):
            with self.subTest(job_id=invalid), self.assertRaises(InputError):
                validate_input(payload([row(invalid)]))

    def test_missing_dates_sort_last_and_equal_time_ties_use_id(self):
        source = [
            row("known-z", publication_time="2026-11-01T09:00:00Z"),
            row("known-a", publication_time="2026-11-01T09:00:00Z"),
            row("missing-z", publication_time=None),
            row("missing-a", publication_time=None),
        ]
        domains, rows, _ = validate_input(payload(source))
        publication, _ = select_day(rows, domains, "2026-11-01", 10, 0, ARM_PUBLICATION)
        self.assertEqual(
            ["known-a", "known-z", "missing-a", "missing-z"],
            [item["job_id"] for item in publication],
        )

    def test_jev_unknown_states_follow_low_and_are_not_dropped(self):
        source = [
            row("low", jev_state="low", publication_time="2026-11-01T12:00:00Z"),
            row("stale", jev_state="stale", publication_time="2026-11-01T13:00:00Z"),
            row("null", jev_state="null", publication_time="2026-11-01T14:00:00Z"),
            row("high", jev_state="high", publication_time="2026-11-01T08:00:00Z"),
            row("failed", jev_state="failed", publication_time="2026-11-01T15:00:00Z"),
        ]
        domains, rows, _ = validate_input(payload(source))
        selected, _ = select_day(rows, domains, "2026-11-01", 10, 0, ARM_JEV)
        self.assertEqual(["high", "low", "failed", "null", "stale"], [x["job_id"] for x in selected])

    def test_unknown_domains_are_reserve_only_and_review_flags_do_not_filter(self):
        unknown_rows = [
            row(f"unknown-{index}", domain="unknown", label="positive" if index == 0 else "negative")
            for index in range(6)
        ]
        domains, rows, _ = validate_input(payload(unknown_rows))
        selected, reserve = select_day(rows, domains, "2026-11-01", 10, 2, ARM_PUBLICATION)
        self.assertEqual(2, len(selected))
        self.assertEqual(reserve, {item["job_id"] for item in selected})

        reviewed_rows = [
            row(f"reviewed-{index}", needs_review=True) for index in range(12)
        ]
        domains, rows, _ = validate_input(payload(reviewed_rows))
        selected, reserve = select_day(rows, domains, "2026-11-01", 10, 2, ARM_PUBLICATION)
        self.assertEqual(10, len(selected))
        self.assertEqual(2, len(reserve))

    def test_unresolved_label_bounds_and_missed_positives_are_explicit(self):
        pool = [
            row("p1", label="positive", domain="synthetic_a"),
            row("p2", label="positive", domain="synthetic_b"),
            row("u1", label="unresolved", domain="synthetic_a"),
            row("u2", label="unresolved", domain="unknown"),
            row("n1", label="negative"),
        ]
        domains, rows, _ = validate_input(payload(pool))
        selected = [next(item for item in rows if item["job_id"] == job_id) for job_id in ("p1", "u1", "n1")]
        metrics = metrics_for_selection(rows, selected, 10, set())
        self.assertEqual(
            {"positive": 1, "negative": 1, "unresolved": 1},
            metrics["label_counts"],
        )
        self.assertEqual(1 / 3, metrics["precision_bounds"]["lower"])
        self.assertEqual(2 / 3, metrics["precision_bounds"]["upper"])
        self.assertEqual(1 / 3, metrics["recall_bounds"]["lower"])
        self.assertEqual(2 / 3, metrics["recall_bounds"]["upper"])
        self.assertEqual(1 / 2, metrics["resolved_only_recall"]["value"])
        self.assertEqual(3, metrics["recall_bounds"]["lower_denominator"])
        self.assertEqual(3, metrics["recall_bounds"]["upper_denominator"])
        self.assertEqual({"synthetic_b": 1}, metrics["missed_positive_by_domain"])

    def test_empty_positive_denominators_are_undefined_not_perfect(self):
        rows = [
            row("negative", label="negative"),
            row("unresolved", label="unresolved"),
        ]
        domains, validated, _ = validate_input(payload(rows))
        metrics = metrics_for_selection(validated, [validated[0]], 10, set())
        self.assertEqual(0.0, metrics["precision_bounds"]["lower"])
        self.assertEqual(0.0, metrics["precision_bounds"]["upper"])
        self.assertEqual(0.0, metrics["recall_bounds"]["lower"])
        self.assertIsNone(metrics["recall_bounds"]["upper"])
        self.assertIsNone(metrics["resolved_only_recall"]["value"])
        self.assertIsNone(metrics["feasibility_ceiling"])

        empty = metrics_for_selection(validated, [], 10, set())
        self.assertIsNone(empty["precision_bounds"]["lower"])
        self.assertIsNone(empty["precision_bounds"]["upper"])
        self.assertEqual(0, empty["precision_bounds"]["denominator"])

    def test_invalid_enum_and_missing_required_field_are_rejected(self):
        bad_enum = payload([row("job", jev_state="best")])
        with self.assertRaisesRegex(InputError, "jev_state"):
            validate_input(bad_enum)

        missing_field = payload([row("job")])
        del missing_field["rows"][0]["label"]
        with self.assertRaisesRegex(InputError, "missing fields label"):
            validate_input(missing_field)

    def test_report_has_synthetic_only_marker_and_paired_budget_counts(self):
        report = evaluate(payload([
            row("a", label="positive", jev_state="high"),
            row("b", label="negative", jev_state="low"),
        ], exclusions=3))
        self.assertEqual("synthetic", report["evidence_kind"])
        self.assertEqual(3, report["whole_inventory_exclusions"])
        self.assertEqual(1, len(report["budgets"]))
        budget = report["budgets"][0]["budget_results"][0]
        self.assertEqual(10, budget["K"])
        self.assertEqual(2, budget["R"])
        self.assertIn("positive_reads", budget["paired_day_delta_jev_minus_publication"])


if __name__ == "__main__":
    unittest.main()
