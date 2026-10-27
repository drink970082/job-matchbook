"""Legacy fit normalization/fallback with active screen compatibility exports."""
from __future__ import annotations

from ats_worker.model_errors import ModelResponseError as ScoreError
from ats_worker.screening import engine as _engine

for _name in dir(_engine):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_engine, _name)

_SENIORITY_VERDICTS = frozenset(("match", "too_junior", "too_senior"))


_DOMAIN_VERDICTS = frozenset(("match", "adjacent", "mismatch"))


def _normalize_score(data: dict) -> dict:
    """Validate the SCORE call's output: both `score` and a well-formed `assessment`
    scorecard are required, and both fail loudly — a missing score buried as 0 would
    silently exclude the posting from notification, and a malformed assessment means the
    model didn't produce the per-dimension verdicts the ranking + audit depend on (S2.1)."""
    if "score" not in data:
        raise ScoreError(f"response missing required 'score': {data!r}")
    out = {
        "score": _coerce_score(data["score"]),
        "assessment": _normalize_assessment(data.get("assessment")),
        # Lenient: absent/garbled -> False (err toward scoreable), matching the gates.
        "insufficient_context": bool(data.get("insufficient_context")),
    }
    recommended = str(data.get("recommended_resume") or "").strip()
    if recommended:
        out["recommended_resume"] = recommended
    return out


def _normalize_assessment(value) -> dict:
    """Validate + coerce the scorecard. The seniority/domain verdicts must be in-enum
    (raise ScoreError otherwise — they drive D3's seniority floor and the ranking); the
    keyword lists and summary are coerced leniently since they only feed the UI."""
    if not isinstance(value, dict):
        raise ScoreError(f"score missing required 'assessment' object: {value!r}")

    def _verdict(key, allowed):
        entry = value.get(key)
        if not isinstance(entry, dict):
            raise ScoreError(f"assessment.{key} must be an object: {entry!r}")
        verdict = str(entry.get("verdict") or "")
        if verdict not in allowed:
            raise ScoreError(
                f"assessment.{key}.verdict {verdict!r} not one of {sorted(allowed)}")
        return {"verdict": verdict, "note": str(entry.get("note") or "")}

    must = value.get("must_haves") if isinstance(value.get("must_haves"), dict) else {}
    nice = value.get("nice_to_haves") if isinstance(value.get("nice_to_haves"), dict) else {}
    return {
        "seniority": _verdict("seniority", _SENIORITY_VERDICTS),
        "domain": _verdict("domain", _DOMAIN_VERDICTS),
        "must_haves": {"met": _as_str_list(must.get("met")),
                       "missing": _as_str_list(must.get("missing"))},
        "nice_to_haves": {"missing": _as_str_list(nice.get("missing"))},
        "summary": str(value.get("summary") or ""),
    }


def _coerce_score(raw) -> int:
    """Accept int, float, or numeric string (85 / 85.7 / "85"); clamp to 0-100.

    A non-numeric score (e.g. "high") is unusable and raises, rather than being
    silently buried as a 0 that would exclude the posting from notification.
    """
    try:
        value = round(float(raw))
    except (TypeError, ValueError) as exc:
        raise ScoreError(f"score is not numeric: {raw!r}") from exc
    return max(0, min(100, value))


_CONFIRMABLE_CHECKS = frozenset({"degree", "clearance"})


def demote_for_confirmation(screen: dict) -> dict | None:
    """Turn a degree/clearance-ONLY disqualification into a keep that carries a
    `needs_confirmation` marker, or return None to leave the discard alone.

    See `_CONFIRMABLE_CHECKS` for why these two and not the others. Volume is small —
    degree/clearance-only discards were 30 of 3,262 — so each one buys a single paid fit
    call instead of being deleted unreviewed (docs/PROGRESS.md item 3).

    The failing verdicts are **removed** rather than flipped to pass. That is what makes
    this a re-check and not an override: `merge_fallback_screen` fills only the checks the
    screen left ABSENT, so clearing them is exactly how the fit scorer's own Stage 4
    extraction gets to answer, with the same CODE arbitration applying the candidate's
    constraint. Flipping them to `pass` would materialize a verdict nothing produced —
    the 2026-07-23 blind-check-as-pass defect, in a new place.

    Returns None (leave it discarded) when any failing check is outside
    `_CONFIRMABLE_CHECKS`, and when the verdict carries no per-check entries at all: an
    unreadable disqualification shape is not evidence that the disqualification is wrong,
    and routing it would mean paying for every discard whose shape we cannot classify.
    """
    checks = screen.get("screen")
    if not isinstance(checks, dict) or not checks:
        return None
    # An entry that is not a well-formed verdict is the no-entries case in miniature: it
    # cannot be classified, so it must not be silently skipped on the way to a demotion
    # (skipping would let `{"degree": fail, "location": "not in USA"}` route and carry the
    # unreadable check through as if it had passed). Not producible in-repo today —
    # `_screen_verdict` and `deterministic_screen` always write `{"pass":…, "note":…}` —
    # but the doctrine has to hold for the shape, not for today's callers.
    if not all(isinstance(v, dict) and "pass" in v for v in checks.values()):
        return None
    failed = [k for k, v in checks.items() if not v.get("pass")]
    if not failed or not _CONFIRMABLE_CHECKS.issuperset(failed):
        return None
    return {
        "screen": {k: v for k, v in checks.items() if k not in failed},
        "disqualified": False,
        "disqualification_reason": "",
        "needs_confirmation": sorted(failed),
    }


def merge_fallback_screen(screen: dict, card: dict, posting: dict,
                          candidate: dict | None) -> dict:
    """Consume the fit scorer's secondary hard-requirement extraction — but ONLY for
    checks the screen produced no verdict for.

    Why fallback and not a second vote: on a working screen backend a second independent
    checker doubles the false-positive surface, and a spurious "requires PhD" would
    SILENTLY DISCARD a good posting — the exact failure the err-toward-keep design
    exists to avoid. This is insurance for the gap (SCREEN_BACKEND=none, or a screen
    failure that err-toward-keep already swallowed), not redundancy.

    Sponsorship keeps the same quote verification as the screen, so a hallucinated
    quote cannot disqualify here either.

    A screen that already disqualified has nothing left to gap-fill, so it is
    returned untouched.
    """
    if not candidate or not isinstance(card, dict):
        return screen
    if screen.get("disqualified"):
        return screen
    extracted = card.get("screen")
    if not isinstance(extracted, dict):
        return screen
    already = screen.get("screen") or {}
    gaps = {k: v for k, v in extracted.items() if k not in already}
    if not gaps:
        return screen
    verdict = _screen_verdict({"screen": gaps}, candidate,
                              str(posting.get("description") or ""),
                              str(posting.get("job_title") or ""))
    # ONLY the gap checks may add a disqualification here, and the entries are not the
    # whole story — the VERDICT has to be narrowed too. `_screen_verdict` re-rules every
    # check the CANDIDATE configured, not just the ones in `gaps`, and `authorization`
    # produces a verdict from the NO_SPONSOR_PHRASES floor even with no entry and no
    # snippets. So an unfiltered read lets the blunt floor overturn a check the screen
    # already answered — persisting `authorization: {"pass": true}` next to
    # `disqualification_reason: "authorization: ..."`, and throwing away the paid call
    # that had just kept the row. Dormant while `already` held every configured check
    # (gaps empty -> early return above); reachable the moment a caller clears one, which
    # is exactly what `demote_for_confirmation` does.
    filled = {k: v for k, v in (verdict.get("screen") or {}).items() if k in gaps}
    merged = dict(already)
    merged.update(filled)
    # Rebuilt from `filled` rather than taken from `verdict`, same reason and same shape
    # `_screen_verdict` uses ("key: note", or bare key when there is no note).
    extra = "; ".join(f"{k}: {v.get('note')}" if v.get("note") else k
                      for k, v in filled.items() if not v.get("pass"))
    prior = screen.get("disqualification_reason") or ""
    reason = "; ".join(r for r in (prior, extra) if r)
    return {
        "screen": merged,
        "disqualified": bool(screen.get("disqualified")) or bool(extra),
        "disqualification_reason": reason,
    }
