"""Isolated durable accounting and repeat summaries for the JEV Stage 1 pilot.

This module has no provider, key, profile-loader, legacy scorer, database, or network
dependency. The operator's supervised shadow transport is wrapped at its injected
``complete`` seam; this ledger reserves and fsyncs before allowing that call.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Iterator, Mapping, Protocol

from ats_worker.preselection.jev import (
    JevContractError,
    NativeJevQuestionSet,
    ValidatedNativeAssessment,
    jev_question_set_from_value,
    validate_native_jev_journal_payload,
)


LEDGER_SCHEMA_VERSION = 1
STAGE1_REPORT_SCHEMA_VERSION = 1
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_EVENT_LIMIT = 8 * 1024 * 1024
_DECIMAL_LIMIT = 64


class ConvergenceError(ValueError):
    """A convergence ledger or repeat report violates its frozen contract."""


class CampaignBudgetExceeded(ConvergenceError):
    """The durable campaign limits do not permit another attempt."""


class CampaignLedgerIntegrityError(ConvergenceError):
    """The retained ledger is malformed, changed, truncated, or inconsistent."""


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ConvergenceError("value cannot be canonically encoded") from exc


def _decimal(value: str | Decimal, path: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise ConvergenceError(f"{path} must be a decimal string or Decimal")
    raw = str(value)
    if not raw or len(raw) > _DECIMAL_LIMIT or raw.strip() != raw:
        raise ConvergenceError(f"{path} is outside the decimal text limit")
    try:
        result = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ConvergenceError(f"{path} must be a finite non-negative amount") from None
    if not result.is_finite() or result < 0:
        raise ConvergenceError(f"{path} must be a finite non-negative amount")
    parts = result.as_tuple()
    if len(parts.digits) > 40 or abs(parts.exponent) > 24 or abs(result.adjusted()) > 12:
        raise ConvergenceError(f"{path} exceeds the bounded decimal range")
    return result


def _decimal_text(value: Decimal) -> str:
    # _decimal has already bounded the exponent and precision, so fixed format is safe.
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _validate_text(value: Any, path: str, *, maximum: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        raise ConvergenceError(f"{path} must be bounded, non-empty trimmed text")
    return value


def _sha256(value: Any, path: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise ConvergenceError(f"{path} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class CampaignConfig:
    """Immutable USD accounting rules for one isolated stage-one campaign."""

    campaign_id: str
    stage_id: str = "stage1"
    historical_spend: str = "0.002003148"
    historical_attempts: int = 10
    global_ceiling: str = "10"
    ordinary_dispatch_ceiling: str = "9"
    stage_ceiling: str = "0.50"
    reserve_per_attempt: str = "0.15"
    max_global_attempts: int = 5000
    max_stage_attempts: int = 40

    def validate(self) -> None:
        _validate_text(self.campaign_id, "campaign_id", maximum=128)
        if self.stage_id != "stage1":
            raise ConvergenceError("this ledger implementation only admits stage1")
        historical = _decimal(self.historical_spend, "historical_spend")
        global_cap = _decimal(self.global_ceiling, "global_ceiling")
        ordinary_cap = _decimal(self.ordinary_dispatch_ceiling, "ordinary_dispatch_ceiling")
        stage_cap = _decimal(self.stage_ceiling, "stage_ceiling")
        reserve = _decimal(self.reserve_per_attempt, "reserve_per_attempt")
        if global_cap <= 0 or ordinary_cap <= 0 or stage_cap <= 0 or reserve <= 0:
            raise ConvergenceError("campaign ceilings and reserve must be positive")
        if ordinary_cap > global_cap or stage_cap > global_cap:
            raise ConvergenceError("campaign phase ceilings cannot exceed the global ceiling")
        if historical > stage_cap or historical > ordinary_cap or historical > global_cap:
            raise ConvergenceError("historical spend already exceeds a configured ceiling")
        if type(self.historical_attempts) is not int or self.historical_attempts < 0:
            raise ConvergenceError("historical_attempts must be a non-negative integer")
        if type(self.max_global_attempts) is not int or self.max_global_attempts <= 0:
            raise ConvergenceError("max_global_attempts must be positive")
        if type(self.max_stage_attempts) is not int or self.max_stage_attempts <= 0:
            raise ConvergenceError("max_stage_attempts must be positive")
        if self.historical_attempts > self.max_global_attempts:
            raise ConvergenceError("historical attempts already exceed the global attempt cap")
        if reserve > stage_cap or reserve > ordinary_cap or reserve > global_cap:
            raise ConvergenceError("per-attempt reserve exceeds a configured ceiling")

    @property
    def identity_sha256(self) -> str:
        self.validate()
        normalized = asdict(self)
        for field in (
            "historical_spend",
            "global_ceiling",
            "ordinary_dispatch_ceiling",
            "stage_ceiling",
            "reserve_per_attempt",
        ):
            normalized[field] = _decimal_text(_decimal(normalized[field], field))
        return hashlib.sha256(_canonical_json(normalized)).hexdigest()


@dataclass(frozen=True)
class CampaignReservation:
    reservation_id: str
    campaign_id: str
    stage_id: str
    run_id: str
    request_identity: str
    work_item_identity_sha256: str
    draw_number: int
    reserved_amount: str


@dataclass(frozen=True)
class CampaignSnapshot:
    campaign_id: str
    stage_id: str
    attempts: int
    stage_attempts: int
    settled_spend: str
    pending_reserve: str
    pending_reservation_id: str | None
    has_unknown_settlement: bool
    has_over_reserve_charge: bool
    global_ceiling: str
    ordinary_dispatch_ceiling: str
    stage_ceiling: str
    reserve_per_attempt: str


@dataclass
class _LedgerState:
    events: list[dict[str, Any]]
    attempts: int
    stage_attempts: int
    settled_spend: Decimal
    pending: CampaignReservation | None
    unknown: bool
    over_reserve: bool
    settlement_by_id: dict[str, dict[str, Any]]
    previous_hash: str | None


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CampaignLedgerIntegrityError("campaign ledger contains duplicate JSON members")
        value[key] = item
    return value


class CampaignLedger:
    """Locked JSONL ledger; every paid transport dispatch must reserve first."""

    def __init__(self, path: str | os.PathLike[str], config: CampaignConfig) -> None:
        config.validate()
        self.path = Path(path)
        self.config = config

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError:
            raise CampaignLedgerIntegrityError("campaign lock cannot be opened safely") from None
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _anchor(self) -> dict[str, Any]:
        return {
            "kind": "campaign",
            "schema_version": LEDGER_SCHEMA_VERSION,
            "campaign_id": self.config.campaign_id,
            "config_sha256": self.config.identity_sha256,
            "historical_spend": _decimal_text(_decimal(self.config.historical_spend, "historical_spend")),
            "historical_attempts": self.config.historical_attempts,
            "previous_event_sha256": None,
        }

    def _state(self) -> _LedgerState:
        if not self.path.exists():
            return _LedgerState([], self.config.historical_attempts, 0,
                                _decimal(self.config.historical_spend, "historical_spend"),
                                None, False, False, {}, None)
        try:
            if self.path.is_symlink() or not self.path.is_file():
                raise CampaignLedgerIntegrityError("campaign ledger is not a regular file")
            stat_result = self.path.stat()
            if stat_result.st_size > _EVENT_LIMIT:
                raise CampaignLedgerIntegrityError("campaign ledger exceeds its retained size limit")
            raw = self.path.read_bytes()
        except CampaignLedgerIntegrityError:
            raise
        except OSError:
            raise CampaignLedgerIntegrityError("campaign ledger cannot be read") from None
        if not raw or not raw.endswith(b"\n"):
            raise CampaignLedgerIntegrityError("campaign ledger is empty or has a truncated final event")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise CampaignLedgerIntegrityError("campaign ledger is not valid UTF-8") from None
        lines = text.splitlines()
        if not lines or any(not line for line in lines):
            raise CampaignLedgerIntegrityError("campaign ledger contains an empty event")
        events: list[dict[str, Any]] = []
        previous_hash: str | None = None
        state = _LedgerState([], self.config.historical_attempts, 0,
                             _decimal(self.config.historical_spend, "historical_spend"),
                             None, False, False, {}, None)
        for index, line in enumerate(lines):
            try:
                event = json.loads(
                    line,
                    object_pairs_hook=_pairs_no_duplicates,
                    parse_constant=lambda _value: (_ for _ in ()).throw(
                        CampaignLedgerIntegrityError("campaign ledger contains a non-finite JSON number")
                    ),
                )
            except CampaignLedgerIntegrityError:
                raise
            except (json.JSONDecodeError, RecursionError, ValueError):
                raise CampaignLedgerIntegrityError("campaign ledger contains malformed JSON") from None
            if not isinstance(event, dict) or set(event) != {
                "body", "event_sha256"
            }:
                raise CampaignLedgerIntegrityError("campaign ledger event envelope is invalid")
            body = event["body"]
            if not isinstance(body, dict):
                raise CampaignLedgerIntegrityError("campaign ledger event body is invalid")
            digest = event["event_sha256"]
            if not isinstance(digest, str) or _HEX64.fullmatch(digest) is None:
                raise CampaignLedgerIntegrityError("campaign ledger event hash is invalid")
            if hashlib.sha256(_canonical_json(body)).hexdigest() != digest:
                raise CampaignLedgerIntegrityError("campaign ledger event hash does not match content")
            if body.get("previous_event_sha256") != previous_hash:
                raise CampaignLedgerIntegrityError("campaign ledger event chain is broken")
            if index == 0:
                if body != self._anchor():
                    raise CampaignLedgerIntegrityError("campaign ledger anchor differs from frozen configuration")
            else:
                self._apply_event(state, body)
            events.append(body)
            previous_hash = digest
        state.events = events
        state.previous_hash = previous_hash
        return state

    def _apply_event(self, state: _LedgerState, body: dict[str, Any]) -> None:
        kind = body.get("kind")
        if kind == "reserve":
            expected = {
                "kind", "reservation_id", "campaign_id", "stage_id", "run_id",
                "request_identity", "work_item_identity_sha256", "draw_number",
                "reserved_amount", "previous_event_sha256",
            }
            if set(body) != expected:
                raise CampaignLedgerIntegrityError("campaign reservation event has an invalid shape")
            reservation_id = _validate_text(body["reservation_id"], "reservation_id", maximum=128)
            if reservation_id in state.settlement_by_id or (
                state.pending is not None and state.pending.reservation_id == reservation_id
            ):
                raise CampaignLedgerIntegrityError("campaign reservation ID is duplicated")
            if state.pending is not None or state.unknown:
                raise CampaignLedgerIntegrityError("campaign has overlapping or unknown reservations")
            if body["campaign_id"] != self.config.campaign_id or body["stage_id"] != self.config.stage_id:
                raise CampaignLedgerIntegrityError("campaign reservation has a different campaign identity")
            run_id = _validate_text(body["run_id"], "run_id", maximum=128)
            request_identity = _validate_text(body["request_identity"], "request_identity", maximum=256)
            work_hash = _sha256(body["work_item_identity_sha256"], "work_item_identity_sha256")
            draw = body["draw_number"]
            if type(draw) is not int or draw <= 0:
                raise CampaignLedgerIntegrityError("campaign draw number is invalid")
            reserved = _decimal(body["reserved_amount"], "reserved_amount")
            if reserved != _decimal(self.config.reserve_per_attempt, "reserve_per_attempt"):
                raise CampaignLedgerIntegrityError("campaign reservation amount differs from frozen reserve")
            state.attempts += 1
            state.stage_attempts += 1
            state.pending = CampaignReservation(
                reservation_id, self.config.campaign_id, self.config.stage_id, run_id,
                request_identity, work_hash, draw, _decimal_text(reserved),
            )
            return
        if kind == "settle":
            expected = {
                "kind", "reservation_id", "status", "amount", "currency", "billing_unit",
                "rate_date", "rate_source", "previous_event_sha256",
            }
            if set(body) != expected:
                raise CampaignLedgerIntegrityError("campaign settlement event has an invalid shape")
            reservation_id = _validate_text(body["reservation_id"], "reservation_id", maximum=128)
            reservation = state.pending
            if reservation is None or reservation.reservation_id != reservation_id:
                raise CampaignLedgerIntegrityError("campaign settlement has no matching pending reservation")
            status = body["status"]
            if status == "unknown":
                if any(body[name] is not None for name in ("amount", "currency", "billing_unit", "rate_date", "rate_source")):
                    raise CampaignLedgerIntegrityError("unknown settlement contains price details")
                state.unknown = True
            elif status == "settled":
                amount = _decimal(body["amount"], "settlement amount")
                if body["currency"] != "USD":
                    raise CampaignLedgerIntegrityError("settled campaign charge is not USD")
                for name in ("billing_unit", "rate_source"):
                    _validate_text(body[name], name, maximum=256)
                _validate_text(body["rate_date"], "rate_date", maximum=10)
                try:
                    if date.fromisoformat(body["rate_date"]).isoformat() != body["rate_date"]:
                        raise ValueError
                except ValueError:
                    raise CampaignLedgerIntegrityError("settlement rate date is invalid") from None
                if amount > _decimal(reservation.reserved_amount, "reserved_amount"):
                    state.over_reserve = True
                state.settled_spend += amount
            else:
                raise CampaignLedgerIntegrityError("campaign settlement status is invalid")
            state.settlement_by_id[reservation_id] = body
            state.pending = None
            return
        raise CampaignLedgerIntegrityError("campaign ledger event kind is unsupported")

    def _append(self, state: _LedgerState, body: dict[str, Any]) -> None:
        body = {**body, "previous_event_sha256": state.previous_hash}
        envelope = {
            "body": body,
            "event_sha256": hashlib.sha256(_canonical_json(body)).hexdigest(),
        }
        encoded = _canonical_json(envelope) + b"\n"
        if len(encoded) > 16_384:
            raise CampaignLedgerIntegrityError("campaign ledger event exceeds its size limit")
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags, 0o600)
            try:
                os.fchmod(fd, 0o600)
                offset = 0
                while offset < len(encoded):
                    written = os.write(fd, encoded[offset:])
                    if written <= 0:
                        raise OSError("short campaign ledger write")
                    offset += written
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            raise CampaignLedgerIntegrityError("campaign event could not be durably appended") from None
        state.events.append(body)
        state.previous_hash = envelope["event_sha256"]

    def _ensure_anchor(self, state: _LedgerState) -> None:
        if not state.events:
            self._append(state, self._anchor())

    def snapshot(self) -> CampaignSnapshot:
        with self._locked():
            state = self._state()
            self._ensure_anchor(state)
            pending = state.pending
            return CampaignSnapshot(
                campaign_id=self.config.campaign_id,
                stage_id=self.config.stage_id,
                attempts=state.attempts,
                stage_attempts=state.stage_attempts,
                settled_spend=_decimal_text(state.settled_spend),
                pending_reserve=pending.reserved_amount if pending else "0",
                pending_reservation_id=pending.reservation_id if pending else None,
                has_unknown_settlement=state.unknown,
                has_over_reserve_charge=state.over_reserve,
                global_ceiling=_decimal_text(_decimal(self.config.global_ceiling, "global_ceiling")),
                ordinary_dispatch_ceiling=_decimal_text(_decimal(self.config.ordinary_dispatch_ceiling, "ordinary_dispatch_ceiling")),
                stage_ceiling=_decimal_text(_decimal(self.config.stage_ceiling, "stage_ceiling")),
                reserve_per_attempt=_decimal_text(_decimal(self.config.reserve_per_attempt, "reserve_per_attempt")),
            )

    def reserve_attempt(
        self,
        *,
        phase: str,
        run_id: str,
        request_identity: str,
        work_item_identity_sha256: str,
        draw_number: int | None,
    ) -> CampaignReservation:
        if phase != self.config.stage_id:
            raise CampaignBudgetExceeded("campaign phase differs from the frozen stage")
        run_id = _validate_text(run_id, "run_id", maximum=128)
        request_identity = _validate_text(request_identity, "request_identity", maximum=256)
        work_hash = _sha256(work_item_identity_sha256, "work_item_identity_sha256")
        if type(draw_number) is not int or draw_number <= 0:
            raise ConvergenceError("draw_number must be a positive integer")
        with self._locked():
            state = self._state()
            if state.unknown:
                raise CampaignBudgetExceeded("campaign has an unknown charge and is stopped")
            if state.over_reserve:
                raise CampaignBudgetExceeded("campaign is stopped after an actual charge exceeded its reserve")
            if state.pending is not None:
                raise CampaignBudgetExceeded("campaign has an unresolved in-flight reservation")
            if state.attempts >= self.config.max_global_attempts:
                raise CampaignBudgetExceeded("global campaign attempt cap is exhausted")
            if state.stage_attempts >= self.config.max_stage_attempts:
                raise CampaignBudgetExceeded("stage attempt cap is exhausted")
            reserve = _decimal(self.config.reserve_per_attempt, "reserve_per_attempt")
            exposure = state.settled_spend + reserve
            if exposure > _decimal(self.config.global_ceiling, "global_ceiling"):
                raise CampaignBudgetExceeded("global campaign reserve ceiling would be exceeded")
            if exposure > _decimal(self.config.ordinary_dispatch_ceiling, "ordinary_dispatch_ceiling"):
                raise CampaignBudgetExceeded("ordinary dispatch reserve ceiling would be exceeded")
            if exposure > _decimal(self.config.stage_ceiling, "stage_ceiling"):
                raise CampaignBudgetExceeded("stage reserve ceiling would be exceeded")
            self._ensure_anchor(state)
            reservation_id = f"{self.config.stage_id}-{state.attempts + 1:05d}-{os.urandom(8).hex()}"
            reservation = CampaignReservation(
                reservation_id, self.config.campaign_id, phase, run_id, request_identity,
                work_hash, draw_number, _decimal_text(reserve),
            )
            self._append(state, {
                "kind": "reserve",
                "reservation_id": reservation.reservation_id,
                "campaign_id": reservation.campaign_id,
                "stage_id": reservation.stage_id,
                "run_id": reservation.run_id,
                "request_identity": reservation.request_identity,
                "work_item_identity_sha256": reservation.work_item_identity_sha256,
                "draw_number": reservation.draw_number,
                "reserved_amount": reservation.reserved_amount,
            })
            return reservation

    def settle(self, reservation_id: str, charge: Any | None) -> CampaignSnapshot:
        reservation_id = _validate_text(reservation_id, "reservation_id", maximum=128)
        evidence = self._charge_event(charge)
        with self._locked():
            state = self._state()
            previous = state.settlement_by_id.get(reservation_id)
            if previous is not None:
                candidate = {
                    "kind": "settle",
                    "reservation_id": reservation_id,
                    **evidence,
                }
                if {key: value for key, value in previous.items() if key != "previous_event_sha256"} != candidate:
                    raise CampaignLedgerIntegrityError("reservation was settled with different charge evidence")
                return self._snapshot_from_state(state)
            if state.pending is None or state.pending.reservation_id != reservation_id:
                raise CampaignLedgerIntegrityError("settlement does not match the pending campaign reservation")
            self._append(state, {
                "kind": "settle",
                "reservation_id": reservation_id,
                **evidence,
            })
            # Apply the same validation and accounting rules used during replay.
            body = state.events[-1]
            state.pending = None
            state.settlement_by_id[reservation_id] = body
            if evidence["status"] == "unknown":
                state.unknown = True
            else:
                amount = _decimal(evidence["amount"], "settlement amount")
                state.settled_spend += amount
                pending_reserve = _decimal(
                    next(event["reserved_amount"] for event in reversed(state.events[:-1])
                         if event.get("kind") == "reserve" and event.get("reservation_id") == reservation_id),
                    "reserved_amount",
                )
                if amount > pending_reserve:
                    state.over_reserve = True
            return self._snapshot_from_state(state)

    def _charge_event(self, charge: Any | None) -> dict[str, Any]:
        if charge is None:
            return {"status": "unknown", "amount": None, "currency": None,
                    "billing_unit": None, "rate_date": None, "rate_source": None}
        kind = getattr(charge, "kind", None)
        amount = getattr(charge, "amount", None)
        currency = getattr(charge, "currency", None)
        billing_unit = getattr(charge, "billing_unit", None)
        rate_date = getattr(charge, "rate_date", None)
        rate_source = getattr(charge, "rate_source", None)
        if kind != "actual" or currency != "USD" or amount is None or not billing_unit or not rate_source:
            return {"status": "unknown", "amount": None, "currency": None,
                    "billing_unit": None, "rate_date": None, "rate_source": None}
        try:
            amount_text = _decimal_text(_decimal(amount, "provider charge"))
        except ConvergenceError:
            return {"status": "unknown", "amount": None, "currency": None,
                    "billing_unit": None, "rate_date": None, "rate_source": None}
        for value, name in ((billing_unit, "billing_unit"), (rate_source, "rate_source")):
            try:
                _validate_text(value, name, maximum=256)
            except ConvergenceError:
                return {"status": "unknown", "amount": None, "currency": None,
                        "billing_unit": None, "rate_date": None, "rate_source": None}
        try:
            _validate_text(rate_date, "rate_date", maximum=10)
            if date.fromisoformat(rate_date).isoformat() != rate_date:
                raise ValueError
        except (ConvergenceError, ValueError):
            return {"status": "unknown", "amount": None, "currency": None,
                    "billing_unit": None, "rate_date": None, "rate_source": None}
        return {
            "status": "settled", "amount": amount_text, "currency": "USD",
            "billing_unit": billing_unit, "rate_date": rate_date, "rate_source": rate_source,
        }

    def _snapshot_from_state(self, state: _LedgerState) -> CampaignSnapshot:
        pending = state.pending
        return CampaignSnapshot(
            self.config.campaign_id, self.config.stage_id, state.attempts, state.stage_attempts,
            _decimal_text(state.settled_spend), pending.reserved_amount if pending else "0",
            pending.reservation_id if pending else None, state.unknown, state.over_reserve,
            _decimal_text(_decimal(self.config.global_ceiling, "global_ceiling")),
            _decimal_text(_decimal(self.config.ordinary_dispatch_ceiling, "ordinary_dispatch_ceiling")),
            _decimal_text(_decimal(self.config.stage_ceiling, "stage_ceiling")),
            _decimal_text(_decimal(self.config.reserve_per_attempt, "reserve_per_attempt")),
        )


class _Transport(Protocol):
    def complete(self, invocation: Any) -> Any: ...


class BudgetedTransport:
    """Reserve and settle every injected provider completion inside its caller process."""

    def __init__(self, inner: _Transport, ledger: CampaignLedger, *, run_id: str, phase: str = "stage1") -> None:
        self.inner = inner
        self.ledger = ledger
        self.run_id = _validate_text(run_id, "run_id", maximum=128)
        self.phase = phase

    def complete(self, invocation: Any) -> Any:
        reservation = self.ledger.reserve_attempt(
            phase=self.phase,
            run_id=self.run_id,
            request_identity=getattr(invocation, "request_identity", None),
            work_item_identity_sha256=getattr(invocation, "work_item_identity_sha256", None),
            draw_number=getattr(invocation, "draw_number", None),
        )
        try:
            result = self.inner.complete(invocation)
        except Exception as exc:
            # ProviderFailure carries explicit charge evidence. Other exceptions leave the
            # reservation pending because delivery cannot be proven from this seam.
            if hasattr(exc, "charge"):
                self.ledger.settle(reservation.reservation_id, getattr(exc, "charge"))
            raise
        self.ledger.settle(reservation.reservation_id, getattr(result, "charge", None))
        return result


@dataclass(frozen=True)
class ContradictionPolicy:
    """Explicit question/value map; role question IDs are supplied per frozen profile."""

    preference_question_id: str
    primary_value: str
    adjacent_value: str
    avoided_value: str
    first_target_role_ids: tuple[str, ...]
    supported_value: str

    def validate(self, questions: NativeJevQuestionSet) -> None:
        for value in (
            self.preference_question_id,
            self.primary_value,
            self.adjacent_value,
            self.avoided_value,
            self.supported_value,
        ):
            _validate_text(value, "contradiction policy value", maximum=128)
        if not isinstance(self.first_target_role_ids, tuple) or any(
            not isinstance(value, str) for value in self.first_target_role_ids
        ):
            raise ConvergenceError("first_target_role_ids must be a tuple of question IDs")
        by_id = {item.id: item for item in questions.questions}
        preference = by_id.get(self.preference_question_id)
        if preference is None or preference.question_type != "choice":
            raise ConvergenceError("contradiction policy preference question must be a Choice")
        for value in (self.primary_value, self.adjacent_value, self.avoided_value):
            if value not in dict(preference.choice_criteria):
                raise ConvergenceError("contradiction policy preference value is outside frozen criteria")
        if len(set(self.first_target_role_ids)) != len(self.first_target_role_ids) or not self.first_target_role_ids:
            raise ConvergenceError("contradiction policy requires unique first-target role question IDs")
        for question_id in self.first_target_role_ids:
            question = by_id.get(question_id)
            if question is None or question.question_type != "choice":
                raise ConvergenceError("first-target role IDs must name frozen Choice questions")
            if self.supported_value not in dict(question.choice_criteria):
                raise ConvergenceError("supported value is outside a first-target role's frozen criteria")


@dataclass(frozen=True)
class Stage1Manifest:
    campaign_id: str
    profile_sha256: str
    model_identity: str
    question_set: NativeJevQuestionSet
    expected_draws: tuple[tuple[str, int], ...]
    contradiction_policy: ContradictionPolicy | None = None

    def validate(self) -> None:
        _validate_text(self.campaign_id, "campaign_id", maximum=128)
        _sha256(self.profile_sha256, "profile_sha256")
        _validate_text(self.model_identity, "model_identity", maximum=256)
        try:
            canonical_questions = jev_question_set_from_value(self.question_set.as_dict())
        except (AttributeError, JevContractError):
            raise ConvergenceError("manifest question set is invalid") from None
        if canonical_questions.sha256 != self.question_set.sha256:
            raise ConvergenceError("manifest question set is not canonical")
        if not self.expected_draws:
            raise ConvergenceError("manifest must contain expected draws")
        seen: set[tuple[str, int]] = set()
        for item in self.expected_draws:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ConvergenceError("expected draw membership must be (work_item_ref, draw_number)")
            ref, draw = item
            _validate_text(ref, "work_item_ref", maximum=256)
            if type(draw) is not int or draw <= 0 or item in seen:
                raise ConvergenceError("expected draw membership is invalid or duplicated")
            seen.add(item)
        if self.contradiction_policy is not None:
            self.contradiction_policy.validate(self.question_set)


@dataclass(frozen=True)
class Stage1Observation:
    work_item_ref: str
    draw_number: int
    profile_sha256: str
    model_identity: str
    request_identity: str
    assessment_from_cache: bool
    native_payload: Mapping[str, Any]


def _native_value(answer: Any) -> str | int | float:
    value = answer.value
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ConvergenceError("validated native answer contains an unsupported value")
    if isinstance(value, float) and not (value == value and abs(value) != float("inf")):
        raise ConvergenceError("validated native answer contains a non-finite value")
    return value


def _metric(values: list[str | int | float]) -> dict[str, Any]:
    counts: dict[tuple[type, str], int] = {}
    value_by_key: dict[tuple[type, str], str | int | float] = {}
    for value in values:
        key = (type(value), json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))
        counts[key] = counts.get(key, 0) + 1
        value_by_key[key] = value
    ordered = sorted(counts, key=lambda key: (key[1], key[0].__name__))
    top = max(counts.values(), default=0)
    modes = [value_by_key[key] for key in ordered if counts[key] == top]
    pair_total = len(values) * (len(values) - 1) // 2
    pair_agree = sum(count * (count - 1) // 2 for count in counts.values())
    return {
        "draw_count": len(values),
        "value_counts": [{"value": value_by_key[key], "count": counts[key]} for key in ordered],
        "modal_values": modes,
        "modal_count": top,
        "modal_agreement": (top / len(values)) if values else None,
        "pairwise_agreement": (pair_agree / pair_total) if pair_total else None,
        "pairwise_agreeing_pairs": pair_agree,
        "pairwise_total_pairs": pair_total,
    }


def build_stage1_report(
    manifest: Stage1Manifest,
    observations: Iterable[Stage1Observation],
) -> dict[str, Any]:
    """Validate and summarize repeated native answers without labels or quality scores."""
    manifest.validate()
    expected = set(manifest.expected_draws)
    indexed: dict[tuple[str, int], ValidatedNativeAssessment] = {}
    request_identities: set[str] = set()
    for observation in observations:
        if not isinstance(observation, Stage1Observation):
            raise ConvergenceError("stage-one observations must use Stage1Observation")
        ref = _validate_text(observation.work_item_ref, "work_item_ref", maximum=256)
        if type(observation.draw_number) is not int or observation.draw_number <= 0:
            raise ConvergenceError("observation draw number must be positive")
        key = (ref, observation.draw_number)
        if key not in expected:
            raise ConvergenceError("observation is outside explicit expected membership")
        if key in indexed:
            raise ConvergenceError("duplicate draw observation")
        if observation.profile_sha256 != manifest.profile_sha256:
            raise ConvergenceError("observation profile differs from the frozen manifest")
        if observation.model_identity != manifest.model_identity:
            raise ConvergenceError("observation model differs from the frozen manifest")
        request_identity = _sha256(observation.request_identity, "request_identity")
        if request_identity in request_identities:
            raise ConvergenceError("request identity was reused across stage-one draws")
        request_identities.add(request_identity)
        if observation.assessment_from_cache is not False:
            raise ConvergenceError("cached assessments do not count as independent draws")
        try:
            assessment = validate_native_jev_journal_payload(
                observation.native_payload,
                expected_question_set=manifest.question_set,
                expected_question_set_sha256=manifest.question_set.sha256,
                expected_model=manifest.model_identity,
            )
        except JevContractError as exc:
            raise ConvergenceError("native observation failed contract validation") from exc
        indexed[key] = assessment

    missing = sorted(expected - set(indexed), key=lambda item: (item[0], item[1]))
    per_job: dict[str, list[tuple[int, ValidatedNativeAssessment]]] = {}
    for (ref, draw), assessment in indexed.items():
        per_job.setdefault(ref, []).append((draw, assessment))
    question_ids = [question.id for question in manifest.question_set.questions]
    values_by_job: dict[str, dict[int, dict[str, str | int | float]]] = {}
    for ref, draws in per_job.items():
        values_by_job[ref] = {}
        for draw, assessment in draws:
            values_by_job[ref][draw] = {
                answer.question_id: _native_value(answer) for answer in assessment.answers
            }
    field_metrics: dict[str, Any] = {}
    for question_id in question_ids:
        pooled: list[str | int | float] = []
        modal_agreeing_draws = 0
        modal_compared_draws = 0
        pairwise_agreeing = 0
        pairwise_total = 0
        repeated_jobs = 0
        for draws in values_by_job.values():
            values = [draws[draw][question_id] for draw in sorted(draws)]
            pooled.extend(values)
            if len(values) >= 2:
                repeated_jobs += 1
                metric = _metric(values)
                modal_agreeing_draws += metric["modal_count"]
                modal_compared_draws += len(values)
                pairwise_agreeing += metric["pairwise_agreeing_pairs"]
                pairwise_total += metric["pairwise_total_pairs"]
        field_metrics[question_id] = {
            "observed": _metric(pooled),
            "repeated_jobs": repeated_jobs,
            "modal_agreeing_draws": modal_agreeing_draws,
            "modal_compared_draws": modal_compared_draws,
            "modal_agreement": (modal_agreeing_draws / modal_compared_draws) if modal_compared_draws else None,
            "pairwise_agreeing_pairs": pairwise_agreeing,
            "pairwise_total_pairs": pairwise_total,
            "pairwise_agreement": (pairwise_agreeing / pairwise_total) if pairwise_total else None,
        }

    contradictions: list[dict[str, Any]] = []
    if manifest.contradiction_policy is not None:
        policy = manifest.contradiction_policy
        for ref, draws in sorted(values_by_job.items()):
            preference_values: list[tuple[int, str | int | float]] = []
            for draw, values in sorted(draws.items()):
                preference = values[policy.preference_question_id]
                preference_values.append((draw, preference))
                supported_roles = [
                    role_id for role_id in policy.first_target_role_ids
                    if values[role_id] == policy.supported_value
                ]
                if preference == policy.adjacent_value and supported_roles:
                    contradictions.append({
                        "work_item_ref": ref, "draw_number": draw,
                        "kind": "first_target_supported_with_adjacent_preference",
                        "role_question_ids": supported_roles,
                    })
                if preference == policy.primary_value and not supported_roles:
                    contradictions.append({
                        "work_item_ref": ref, "draw_number": draw,
                        "kind": "primary_preference_without_first_target_support",
                        "role_question_ids": list(policy.first_target_role_ids),
                    })
            if any(value == policy.primary_value for _, value in preference_values) and any(
                value == policy.avoided_value for _, value in preference_values
            ):
                contradictions.append({
                    "work_item_ref": ref,
                    "kind": "primary_vs_avoided_repeat_flip",
                    "draw_numbers": [draw for draw, _ in preference_values],
                })

    return {
        "schema_version": STAGE1_REPORT_SCHEMA_VERSION,
        "campaign_id": manifest.campaign_id,
        "profile_sha256": manifest.profile_sha256,
        "question_set_sha256": manifest.question_set.sha256,
        "model_identity": manifest.model_identity,
        "planned_draws": len(expected),
        "completed_draws": len(indexed),
        "missing_draws": [{"work_item_ref": ref, "draw_number": draw} for ref, draw in missing],
        "field_metrics": field_metrics,
        "contradiction_policy_applied": manifest.contradiction_policy is not None,
        "contradictions": contradictions,
        "quality_evaluation": "not_measured",
        "labels_used": False,
        "scores_or_ranks_created": False,
    }
