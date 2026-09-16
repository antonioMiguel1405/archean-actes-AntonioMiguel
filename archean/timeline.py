"""Deterministic cap-table state machine.

Turns a chronological sequence of :class:`Event` objects into
``capital_timeline[]`` — the state of the cap table after each one. This
module owns all the arithmetic (CLAUDE.md rule 7: money is ``Decimal``,
shares are ``int``, never float for either) and all the invariant checking.
It does not read OCR, does not parse French, and does not decide what
happened in any document — it only folds already-extracted events into
states. What produced the events (``scripts/build_results.py`` for this
project) is a different concern, kept separate on purpose: this module can
be tested with synthetic events and no corpus at all.

Ordering (BRIEF.md's own instruction): events fold in ``event_date`` order,
never filesystem or deposit order. Same-day events need a second key or the
result is not deterministic — resolved here by ``(event_date, source.inpi_id,
source.page, source.line_index)``, which is stable and matches the physical
order resolutions appear in a document when several fire on one day (see
DISCOVERY.md's account of ARCHEAN's 2008-06-27 nominal split + two
increases, all from one document, in that reading order).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Mapping, Sequence

HolderKind = Literal["PERSON", "COMPANY", "UNKNOWN"]

EventCode = Literal[
    "CAPITAL_INCREASE",
    "CAPITAL_DECREASE",
    "SHAREHOLDER_ENTRY",
    "SHAREHOLDER_END",
    "SHAREHOLDER_SHARE_TRANSFER",
    "CAPITAL_DUAL_CLASS",
]

#: The five codes results.schema.json actually scores. CAPITAL_DUAL_CLASS is
#: valid but not scored (event_codes.json's own "scored": false).
SCORED_EVENT_CODES: tuple[EventCode, ...] = (
    "CAPITAL_INCREASE",
    "CAPITAL_DECREASE",
    "SHAREHOLDER_ENTRY",
    "SHAREHOLDER_END",
    "SHAREHOLDER_SHARE_TRANSFER",
)


class TimelineError(ValueError):
    """Raised when an event cannot be folded without inventing something."""


@dataclass(frozen=True)
class Source:
    """Matches ``results.schema.json``'s ``events[].source`` exactly.

    ``line_index`` is not part of the schema (``additionalProperties`` allows
    it, but it is not required) — kept here only as this module's own
    same-day tie-break key, never emitted as part of the public payload
    beyond that ordering use.
    """

    inpi_id: str
    page: int
    bbox: tuple[float, float, float, float]
    snippet: str
    line_index: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "inpi_id": self.inpi_id,
            "page": self.page,
            "bbox": [round(v, 4) for v in self.bbox],
            "snippet": self.snippet,
        }


@dataclass(frozen=True)
class Event:
    """One row of ``events[]``."""

    event_id: str
    event_code: EventCode
    event_date: str  # ISO YYYY-MM-DD
    payload: Mapping[str, object]
    source: Source
    note: str | None = None

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "event_id": self.event_id,
            "event_code": self.event_code,
            "event_date": self.event_date,
            "payload": dict(self.payload),
            "source": self.source.to_dict(),
        }
        if self.note:
            out["note"] = self.note
        return out


@dataclass(frozen=True)
class Holder:
    """One row of ``capital_timeline[].holders``.

    ``kind="UNKNOWN"`` plus a ``shares`` count with no ``name`` beyond a
    literal placeholder is the module's way of saying "the total is known,
    the attribution is not" — used instead of either inventing a split or
    silently dropping the unattributed shares from the total.
    """

    name: str
    kind: HolderKind = "UNKNOWN"
    siren: str | None = None
    shares: int | None = None
    pct: float | None = None

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"name": self.name, "kind": self.kind}
        if self.siren is not None:
            out["siren"] = self.siren
        if self.shares is not None:
            out["shares"] = self.shares
        if self.pct is not None:
            out["pct"] = self.pct
        return out


@dataclass(frozen=True)
class CapTableState:
    """One row of ``capital_timeline[]``."""

    as_of: str
    capital_eur: Decimal | None
    shares_total: int | None
    nominal_eur: Decimal | None
    holders: tuple[Holder, ...]
    caused_by: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "capital_eur": float(self.capital_eur) if self.capital_eur is not None else None,
            "shares_total": self.shares_total,
            "nominal_eur": float(self.nominal_eur) if self.nominal_eur is not None else None,
            "holders": [h.to_dict() for h in self.holders],
            "caused_by": list(self.caused_by),
        }


# ---------------------------------------------------------------------------
# invariants — checked, never silently repaired (CLAUDE.md's "never invent")
# ---------------------------------------------------------------------------


def check_invariants(state: CapTableState) -> list[str]:
    """Structural problems with one state. Empty list means none found.

    Never raises: a documented, real corpus can and does contain rows where
    an invariant cannot be checked (unknown nominal, unknown holders) — that
    is a fact to report, not a bug to crash on. Only checks what the state
    actually claims to know; a ``None`` field is a gap, not a violation.
    """
    problems: list[str] = []
    known_holders = [h for h in state.holders if h.shares is not None]
    if known_holders and state.shares_total is not None:
        total = sum(h.shares for h in known_holders)  # type: ignore[misc]
        if total != state.shares_total:
            problems.append(
                f"{state.as_of}: holder shares sum to {total}, "
                f"shares_total is {state.shares_total}"
            )
    if (
        state.capital_eur is not None
        and state.shares_total is not None
        and state.nominal_eur is not None
    ):
        expected = Decimal(state.shares_total) * state.nominal_eur
        if expected != state.capital_eur:
            problems.append(
                f"{state.as_of}: capital_eur {state.capital_eur} != "
                f"shares_total * nominal_eur = {expected}"
            )
    return problems


# ---------------------------------------------------------------------------
# folding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InitialState:
    """The state before any scored event — a constitution, typically.

    Not itself an ``Event`` (CONSTITUTION is not one of the six schema
    codes), so it carries no ``event_id`` and produces a timeline row with
    ``caused_by=()``.
    """

    as_of: str
    capital_eur: Decimal | None
    shares_total: int | None
    nominal_eur: Decimal | None
    holders: tuple[Holder, ...] = ()


@dataclass(frozen=True)
class StateOnlyTransition:
    """A real, sourced change to the cap table that has no home in the six
    schema event codes — DISCOVERY.md's example: ARCHEAN's 2008-06-27
    nominal-value split (capital unchanged, nominal divided by 100, share
    count multiplied by 100). Recorded as a timeline row with no
    ``caused_by``, never invented as a fake event_code to force a fit.
    """

    as_of: str
    capital_eur: Decimal | None
    shares_total: int | None
    nominal_eur: Decimal | None
    holders: tuple[Holder, ...]
    sort_key: tuple[object, ...]
    reason: str


Movement = Event  # a chronological item that folds the state forward


def _sort_key(ev: Event) -> tuple[object, ...]:
    return (ev.event_date, ev.source.inpi_id, ev.source.page, ev.source.line_index)


def _divide_exact(capital: Decimal, nominal: Decimal | None, fallback: int | None, event_id: str) -> int | None:
    """``capital / nominal`` as an exact int share count, or ``fallback`` if
    the nominal value is not known. Never truncates a real remainder —
    CLAUDE.md rule 7: shares are int, computed exactly, never guessed.
    """
    if not nominal:
        return fallback
    quotient, remainder = divmod(capital, nominal)
    if remainder != 0:
        raise TimelineError(
            f"{event_id}: capital {capital} is not an exact multiple of "
            f"nominal {nominal} (remainder {remainder}) — refusing to round"
        )
    return int(quotient)


def build_timeline(
    initial: InitialState,
    events: Sequence[Event],
    extra_transitions: Sequence[StateOnlyTransition] = (),
) -> tuple[list[CapTableState], list[str]]:
    """Fold ``initial`` forward through ``events`` (and any state-only
    transitions with no scored event code), in deterministic order.

    Returns ``(timeline, problems)`` — ``problems`` collects every
    :func:`check_invariants` hit across every row, never raises, so a caller
    can decide what "not ready" means.
    """
    rows: list[CapTableState] = [
        CapTableState(
            as_of=initial.as_of,
            capital_eur=initial.capital_eur,
            shares_total=initial.shares_total,
            nominal_eur=initial.nominal_eur,
            holders=initial.holders,
            caused_by=(),
        )
    ]

    # merge scored events and state-only transitions into one chronological
    # sequence, each tagged with its own deterministic sort key.
    items: list[tuple[tuple[object, ...], str, object]] = []
    items += [(_sort_key(e), "event", e) for e in events]
    items += [(t.sort_key, "transition", t) for t in extra_transitions]
    items.sort(key=lambda t: t[0])

    current = rows[0]
    pending_ids: list[str] = []
    pending_date: str | None = None

    def flush(as_of: str, capital, shares, nominal, holders) -> None:
        nonlocal current, pending_ids, pending_date
        current = CapTableState(
            as_of=as_of,
            capital_eur=capital,
            shares_total=shares,
            nominal_eur=nominal,
            holders=holders,
            caused_by=tuple(pending_ids),
        )
        rows.append(current)
        pending_ids = []
        pending_date = None

    for _, kind, item in items:
        if kind == "transition":
            t = item
            flush(t.as_of, t.capital_eur, t.shares_total, t.nominal_eur, t.holders)
            continue
        ev = item
        if ev.event_code == "CAPITAL_INCREASE":
            amount = Decimal(str(ev.payload["amount_eur"]))
            new_capital = (current.capital_eur or Decimal(0)) + amount
            expected_after = ev.payload.get("capital_after_eur")
            if expected_after is not None and Decimal(str(expected_after)) != new_capital:
                raise TimelineError(
                    f"{ev.event_id}: stated capital_after_eur "
                    f"{expected_after} != running total {new_capital}"
                )
            new_shares = _divide_exact(new_capital, current.nominal_eur, current.shares_total, ev.event_id)
            pending_ids.append(ev.event_id)
            flush(ev.event_date, new_capital, new_shares, current.nominal_eur, current.holders)
        elif ev.event_code == "CAPITAL_DECREASE":
            amount = Decimal(str(ev.payload["amount_eur"]))
            new_capital = (current.capital_eur or Decimal(0)) - amount
            expected_after = ev.payload.get("capital_after_eur")
            if expected_after is not None and Decimal(str(expected_after)) != new_capital:
                raise TimelineError(
                    f"{ev.event_id}: stated capital_after_eur "
                    f"{expected_after} != running total {new_capital}"
                )
            new_shares = _divide_exact(new_capital, current.nominal_eur, current.shares_total, ev.event_id)
            pending_ids.append(ev.event_id)
            flush(ev.event_date, new_capital, new_shares, current.nominal_eur, current.holders)
        elif ev.event_code == "SHAREHOLDER_END":
            name = ev.payload["holder_name"]
            new_holders = tuple(h for h in current.holders if h.name != name)
            pending_ids.append(ev.event_id)
            flush(
                ev.event_date, current.capital_eur, current.shares_total,
                current.nominal_eur, new_holders,
            )
        elif ev.event_code == "SHAREHOLDER_ENTRY":
            name = ev.payload["holder_name"]
            shares = ev.payload.get("shares")
            new_holder = Holder(
                name=name,
                kind=ev.payload.get("holder_kind", "PERSON"),
                siren=ev.payload.get("holder_siren"),
                shares=shares,
            )
            new_holders = tuple(h for h in current.holders if h.name != name) + (new_holder,)
            pending_ids.append(ev.event_id)
            flush(
                ev.event_date, current.capital_eur, current.shares_total,
                current.nominal_eur, new_holders,
            )
        elif ev.event_code == "SHAREHOLDER_SHARE_TRANSFER":
            # Mechanics only (event_codes.json): the consequence for the
            # timeline is whatever SHAREHOLDER_ENTRY/END events accompany
            # it, not this event itself. Recorded in events[] but does not
            # fold the state on its own, to avoid double-counting the same
            # movement (BRIEF.md's explicit warning).
            pending_ids.append(ev.event_id)
        else:
            raise TimelineError(f"{ev.event_id}: unhandled event_code {ev.event_code!r}")

    if pending_ids:
        # trailing SHAREHOLDER_SHARE_TRANSFER-only events with no state
        # change of their own still need a row so caused_by is not lost.
        flush(current.as_of, current.capital_eur, current.shares_total, current.nominal_eur, current.holders)

    problems: list[str] = []
    for row in rows:
        problems.extend(check_invariants(row))
    return rows, problems
