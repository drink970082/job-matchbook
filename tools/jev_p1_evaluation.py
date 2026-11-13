#!/usr/bin/env python3
"""Synthetic-only selector and bounded-label metrics for the JEV P1 protocol.

Input rows are the already frozen, source-eligible roster. Domain assignments and
labels are independent frozen inputs. This utility has no production imports or
side effects; it reads one explicit JSON file and writes JSON to stdout.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import re
import sys
from typing import Any


SCHEMA = "jev-p1-synthetic-v1"
DOMAIN_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
DOMAINS_REQUIRED = 8
SPECIAL_DOMAINS = {"mixed", "unknown"}
LABELS = {"positive", "negative", "unresolved"}
JEV_STATES = {"high", "medium", "low", "null", "missing", "failed", "deferred", "stale"}
STATE_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
    "null": 3,
    "missing": 3,
    "failed": 3,
    "deferred": 3,
    "stale": 3,
}
ARM_PUBLICATION = "publication_time"
ARM_JEV = "jev"
ARMS = (ARM_PUBLICATION, ARM_JEV)
BUDGETS = ((10, 2), (20, 4), (40, 8))
EXPLORATION_PREFIX = "jev-p1-exploration-v1"

TOP_LEVEL_FIELDS = {
    "schema",
    "pool_is_source_eligible",
    "declared_domains",
    "whole_inventory_exclusions",
    "rows",
}
ROW_FIELDS = {
    "job_id",
    "day",
    "publication_time",
    "domain",
    "jev_state",
    "needs_review",
    "current_successful_binding",
    "label",
}


class InputError(ValueError):
    """Raised when a frozen input does not satisfy the small P1 input contract."""


def _invalid(where: str, detail: str) -> InputError:
    return InputError(f"{where}: {detail}")


def _parse_publication_time(value: Any, where: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise _invalid(where, "must be null or an ISO 8601 timestamp with a UTC offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        raise _invalid(where, "must be null or an ISO 8601 timestamp with a UTC offset") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(where, "timestamp must include a UTC offset")
    try:
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise _invalid(where, "timestamp is outside the supported UTC range") from None


def validate_input(payload: Any) -> tuple[list[str], list[dict[str, Any]], int]:
    """Validate the explicit synthetic snapshot and return normalized copies."""
    if not isinstance(payload, dict):
        raise _invalid("input", "must be a JSON object")
    if set(payload) != TOP_LEVEL_FIELDS:
        missing = sorted(TOP_LEVEL_FIELDS - set(payload))
        extra = sorted(set(payload) - TOP_LEVEL_FIELDS)
        parts = []
        if missing:
            parts.append(f"missing fields {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected fields {', '.join(extra)}")
        raise _invalid("input", "; ".join(parts))
    if payload["schema"] != SCHEMA:
        raise _invalid("schema", f"must equal {SCHEMA!r}")
    if payload["pool_is_source_eligible"] is not True:
        raise _invalid("pool_is_source_eligible", "must be true; rows must already be source-eligible")

    domains = payload["declared_domains"]
    if not isinstance(domains, list) or len(domains) != DOMAINS_REQUIRED:
        raise _invalid("declared_domains", f"must be a list of exactly {DOMAINS_REQUIRED} accepted IDs")
    if any(
        not isinstance(domain, str)
        or not DOMAIN_ID.fullmatch(domain)
        or domain in SPECIAL_DOMAINS
        for domain in domains
    ):
        raise _invalid("declared_domains", "contains an invalid or reserved domain ID")
    if len(set(domains)) != len(domains):
        raise _invalid("declared_domains", "contains duplicate IDs")

    exclusions = payload["whole_inventory_exclusions"]
    if isinstance(exclusions, bool) or not isinstance(exclusions, int) or exclusions < 0:
        raise _invalid("whole_inventory_exclusions", "must be a nonnegative integer")

    source_rows = payload["rows"]
    if not isinstance(source_rows, list):
        raise _invalid("rows", "must be a list")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    allowed_domains = set(domains) | SPECIAL_DOMAINS
    for index, source in enumerate(source_rows):
        where = f"rows[{index}]"
        if not isinstance(source, dict):
            raise _invalid(where, "must be an object")
        if set(source) != ROW_FIELDS:
            missing = sorted(ROW_FIELDS - set(source))
            extra = sorted(set(source) - ROW_FIELDS)
            parts = []
            if missing:
                parts.append(f"missing fields {', '.join(missing)}")
            if extra:
                parts.append(f"unexpected fields {', '.join(extra)}")
            raise _invalid(where, "; ".join(parts))

        job_id = source["job_id"]
        if (
            not isinstance(job_id, str)
            or not job_id
            or job_id != job_id.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in job_id)
        ):
            raise _invalid(f"{where}.job_id", "must be a nonempty printable string without surrounding whitespace")
        if job_id in seen_ids:
            raise _invalid(f"{where}.job_id", f"duplicate ID {job_id!r}")
        seen_ids.add(job_id)

        day_value = source["day"]
        if not isinstance(day_value, str):
            raise _invalid(f"{where}.day", "must be an ISO calendar date")
        try:
            day = date.fromisoformat(day_value)
        except ValueError:
            raise _invalid(f"{where}.day", "must be an ISO calendar date") from None
        if day.isoformat() != day_value:
            raise _invalid(f"{where}.day", "must use YYYY-MM-DD")

        domain = source["domain"]
        if not isinstance(domain, str) or domain not in allowed_domains:
            raise _invalid(f"{where}.domain", "must be a declared ID, 'mixed', or 'unknown'")

        jev_state = source["jev_state"]
        if not isinstance(jev_state, str) or jev_state not in JEV_STATES:
            raise _invalid(f"{where}.jev_state", f"must be one of {', '.join(sorted(JEV_STATES))}")

        label = source["label"]
        if not isinstance(label, str) or label not in LABELS:
            raise _invalid(f"{where}.label", f"must be one of {', '.join(sorted(LABELS))}")

        if not isinstance(source["needs_review"], bool):
            raise _invalid(f"{where}.needs_review", "must be a boolean")
        if not isinstance(source["current_successful_binding"], bool):
            raise _invalid(f"{where}.current_successful_binding", "must be a boolean")

        rows.append(
            {
                "job_id": job_id,
                "day": day_value,
                "publication_time": _parse_publication_time(
                    source["publication_time"], f"{where}.publication_time"
                ),
                "domain": domain,
                "jev_state": jev_state,
                "needs_review": source["needs_review"],
                "current_successful_binding": source["current_successful_binding"],
                "label": label,
            }
        )
    return sorted(domains), rows, exclusions


def _time_key(row: dict[str, Any]) -> tuple[int, int, str]:
    published = row["publication_time"]
    if published is None:
        return (1, 0, row["job_id"])
    # Negative integer microseconds avoids float timestamp rounding in tie ordering.
    micros = (
        ((published.toordinal() * 24 + published.hour) * 60 + published.minute) * 60
        + published.second
    ) * 1_000_000 + published.microsecond
    return (0, -micros, row["job_id"])


def _rank_key(row: dict[str, Any], arm: str) -> tuple[Any, ...]:
    time_key = _time_key(row)
    if arm == ARM_PUBLICATION:
        return time_key
    if arm == ARM_JEV:
        return (STATE_ORDER[row["jev_state"]], *time_key)
    raise ValueError(f"unknown arm: {arm}")


def _exploration_key(row: dict[str, Any]) -> tuple[str, str]:
    digest_input = f"{EXPLORATION_PREFIX}|{row['day']}|{row['job_id']}".encode("utf-8")
    return (hashlib.sha256(digest_input).hexdigest(), row["job_id"])


def _round_robin(
    rows: list[dict[str, Any]], domains: list[str], arm: str, limit: int
) -> list[dict[str, Any]]:
    queues = {
        domain: sorted((row for row in rows if row["domain"] == domain), key=lambda row: _rank_key(row, arm))
        for domain in domains
    }
    selected: list[dict[str, Any]] = []
    positions = {domain: 0 for domain in domains}
    while len(selected) < limit:
        added = False
        for domain in domains:
            position = positions[domain]
            queue = queues[domain]
            if position < len(queue):
                selected.append(queue[position])
                positions[domain] += 1
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
    return selected


def select_day(
    rows: list[dict[str, Any]], domains: list[str], day: str, k: int, r: int, arm: str
) -> tuple[list[dict[str, Any]], set[str]]:
    """Select one day's unique reads, sharing the same pre-label exploration IDs."""
    if arm not in ARMS:
        raise ValueError(f"arm must be one of {ARMS}")
    if k <= 0 or r < 0 or r > k:
        raise ValueError("budget must satisfy K > 0 and 0 <= R <= K")
    day_rows = [row for row in rows if row["day"] == day]
    reserve_rows = sorted(day_rows, key=_exploration_key)[:r]
    reserve_ids = {row["job_id"] for row in reserve_rows}
    main_rows = [
        row
        for row in day_rows
        if row["job_id"] not in reserve_ids and row["domain"] not in SPECIAL_DOMAINS
    ]
    main_slots = k - len(reserve_rows)
    main = _round_robin(main_rows, domains, arm, main_slots)
    return reserve_rows + main, reserve_ids


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def metrics_for_selection(
    pool: list[dict[str, Any]], selected: list[dict[str, Any]], k: int, reserve_ids: set[str]
) -> dict[str, Any]:
    """Compute P1 precision/recall bounds without treating unresolved labels as negatives."""
    selected_ids = {row["job_id"] for row in selected}
    if len(selected_ids) != len(selected):
        raise ValueError("selected rows contain duplicate IDs")
    pool_by_id = {row["job_id"]: row for row in pool}
    if not selected_ids <= pool_by_id.keys():
        raise ValueError("selected rows must be members of the frozen pool")

    selected_counts = Counter(row["label"] for row in selected)
    pool_counts = Counter(row["label"] for row in pool)
    all_positive = pool_counts["positive"]
    selected_positive = selected_counts["positive"]
    selected_unresolved = selected_counts["unresolved"]
    selected_negative = selected_counts["negative"]
    unselected_unresolved = pool_counts["unresolved"] - selected_unresolved
    read_count = len(selected)
    precision_lower = _ratio(selected_positive, read_count)
    precision_upper = _ratio(selected_positive + selected_unresolved, read_count)
    recall_lower_denominator = all_positive + unselected_unresolved
    recall_upper_denominator = all_positive + selected_unresolved
    resolved_only_recall = _ratio(selected_positive, all_positive)

    missed_by_domain = Counter(
        row["domain"]
        for row in pool
        if row["label"] == "positive" and row["job_id"] not in selected_ids
    )
    pool_review = sum(row["needs_review"] for row in pool)
    selected_review = sum(row["needs_review"] for row in selected)
    pool_current = sum(row["current_successful_binding"] for row in pool)
    reserve_positive = sum(
        row["label"] == "positive" and row["job_id"] in reserve_ids for row in selected
    )

    return {
        "selected_ids": [row["job_id"] for row in selected],
        "reads": read_count,
        "unused_slots": k - read_count,
        "label_counts": {
            "positive": selected_positive,
            "negative": selected_negative,
            "unresolved": selected_unresolved,
        },
        "precision_bounds": {
            "lower": precision_lower,
            "upper": precision_upper,
            "denominator": read_count,
        },
        "recall_bounds": {
            "lower": _ratio(selected_positive, recall_lower_denominator),
            "lower_denominator": recall_lower_denominator,
            "upper": _ratio(selected_positive + selected_unresolved, recall_upper_denominator),
            "upper_denominator": recall_upper_denominator,
        },
        "resolved_only_recall": {
            "value": resolved_only_recall,
            "denominator": all_positive,
        },
        "feasibility_ceiling": _ratio(min(k, all_positive), all_positive),
        "all_positive": all_positive,
        "unselected_unresolved": unselected_unresolved,
        "missed_positive_by_domain": {
            domain: missed_by_domain[domain] for domain in sorted(missed_by_domain)
        },
        "current_successful_binding_coverage": {
            "successful": pool_current,
            "denominator": len(pool),
            "fraction": _ratio(pool_current, len(pool)),
        },
        "review_flag_burden": {
            "pool": {
                "flagged": pool_review,
                "denominator": len(pool),
                "fraction": _ratio(pool_review, len(pool)),
            },
            "selected": {
                "flagged": selected_review,
                "denominator": read_count,
                "fraction": _ratio(selected_review, read_count),
            },
        },
        "reserve_positive_recoveries": reserve_positive,
    }


def evaluate(payload: Any) -> dict[str, Any]:
    domains, rows, exclusions = validate_input(payload)
    days = sorted({row["day"] for row in rows})
    result: dict[str, Any] = {
        "evidence_kind": "synthetic",
        "schema": SCHEMA,
        "whole_inventory_exclusions": exclusions,
        "budgets": [],
    }
    for day in days:
        day_pool = [row for row in rows if row["day"] == day]
        budget_results = []
        for k, r in BUDGETS:
            reserve_count = min(r, len(day_pool))
            arms: dict[str, Any] = {}
            selected_by_arm: dict[str, list[dict[str, Any]]] = {}
            for arm in ARMS:
                selected, reserve_ids = select_day(rows, domains, day, k, r, arm)
                selected_by_arm[arm] = selected
                arms[arm] = metrics_for_selection(day_pool, selected, k, reserve_ids)
            publication_counts = arms[ARM_PUBLICATION]["label_counts"]
            jev_counts = arms[ARM_JEV]["label_counts"]
            budget_results.append(
                {
                    "K": k,
                    "R": r,
                    "reserve_slots_available": reserve_count,
                    "arms": arms,
                    "paired_day_delta_jev_minus_publication": {
                        "positive_reads": jev_counts["positive"] - publication_counts["positive"],
                        "negative_reads": jev_counts["negative"] - publication_counts["negative"],
                        "unresolved_reads": jev_counts["unresolved"] - publication_counts["unresolved"],
                    },
                }
            )
        result["budgets"].append(
            {
                "day": day,
                "eligible_pool_size": len(day_pool),
                "budget_results": budget_results,
            }
        )
    return result


def _read_input(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InputError(f"cannot read JSON input: {error.__class__.__name__}") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="explicit synthetic frozen-pool JSON file")
    args = parser.parse_args(argv)
    try:
        report = evaluate(_read_input(args.input))
    except InputError as error:
        print(f"jev-p1-evaluation: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
