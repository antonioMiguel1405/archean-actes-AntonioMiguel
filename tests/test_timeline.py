"""Tests for archean/timeline.py — the cap-table state machine.

Synthetic scenarios only (no corpus dependency): this module is tested in
isolation from OCR/routing, exactly as its own docstring describes. ARCHEAN's
real chain is exercised end-to-end by tests/test_results.py instead, via
scripts/build_results.py's own output.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from archean.timeline import (
    CapTableState,
    Event,
    Holder,
    InitialState,
    Source,
    StateOnlyTransition,
    TimelineError,
    build_timeline,
    check_invariants,
)


def src(page: int = 1, line_index: int = 0, date: str = "x") -> Source:
    return Source(inpi_id="a" * 24, page=page, bbox=(0.1, 0.1, 0.2, 0.2), snippet="s", line_index=line_index)


def initial() -> InitialState:
    return InitialState(
        as_of="2000-01-01", capital_eur=Decimal(1000), shares_total=10, nominal_eur=Decimal(100),
        holders=(Holder("A", "PERSON", shares=6), Holder("B", "PERSON", shares=4)),
    )


# ===========================================================================
# capital arithmetic
# ===========================================================================


def test_capital_increase_adds_the_delta_and_recomputes_shares():
    ev = Event("e1", "CAPITAL_INCREASE", "2001-01-01", {"amount_eur": 500}, src())
    rows, problems = build_timeline(initial(), [ev])
    assert rows[-1].capital_eur == Decimal(1500)
    assert rows[-1].shares_total == 15
    assert rows[-1].caused_by == ("e1",)
    assert problems  # holders were not updated -> sum(6+4)=10 != 15, correctly flagged


def test_capital_decrease_subtracts_the_delta():
    ev = Event("e1", "CAPITAL_DECREASE", "2001-01-01", {"amount_eur": 200}, src())
    rows, _ = build_timeline(initial(), [ev])
    assert rows[-1].capital_eur == Decimal(800)
    assert rows[-1].shares_total == 8


def test_stated_capital_after_must_match_the_running_total():
    ev = Event("e1", "CAPITAL_INCREASE", "2001-01-01", {"amount_eur": 500, "capital_after_eur": 9999}, src())
    with pytest.raises(TimelineError, match="capital_after_eur"):
        build_timeline(initial(), [ev])


def test_non_exact_division_raises_rather_than_truncating():
    """500 EUR increase with a 3-EUR nominal does not divide evenly — the
    module must refuse to invent a rounded share count.
    """
    weird_initial = InitialState(
        as_of="2000-01-01", capital_eur=Decimal(999), shares_total=333, nominal_eur=Decimal(3),
    )
    ev = Event("e1", "CAPITAL_INCREASE", "2001-01-01", {"amount_eur": 500}, src())
    with pytest.raises(TimelineError, match="not an exact multiple"):
        build_timeline(weird_initial, [ev])


# ===========================================================================
# holder projection
# ===========================================================================


def test_shareholder_end_removes_the_holder():
    """shares_total is unchanged (SHAREHOLDER_END alone does not touch
    capital) so holders now correctly sum to less than shares_total — a
    real, expected invariant gap check_invariants must report, not hide.
    """
    ev = Event("e1", "SHAREHOLDER_END", "2001-01-01", {"holder_name": "B"}, src())
    rows, problems = build_timeline(initial(), [ev])
    names = {h.name for h in rows[-1].holders}
    assert names == {"A"}
    assert sum(h.shares for h in rows[-1].holders if h.shares is not None) == 6
    assert problems and "sum to 6" in problems[0]


def test_shareholder_entry_adds_a_new_holder():
    ev = Event("e1", "SHAREHOLDER_ENTRY", "2001-01-01", {"holder_name": "C", "shares": 3}, src())
    rows, _ = build_timeline(initial(), [ev])
    c = next(h for h in rows[-1].holders if h.name == "C")
    assert c.shares == 3
    assert c.kind == "PERSON"


def test_shareholder_entry_replaces_an_existing_holder_of_the_same_name():
    """Re-entering under the same name updates the share count rather than
    duplicating the row.
    """
    ev = Event("e1", "SHAREHOLDER_ENTRY", "2001-01-01", {"holder_name": "A", "shares": 99}, src())
    rows, _ = build_timeline(initial(), [ev])
    names = [h.name for h in rows[-1].holders]
    assert names.count("A") == 1
    assert next(h for h in rows[-1].holders if h.name == "A").shares == 99


def test_share_transfer_does_not_fold_state_on_its_own():
    """BRIEF.md's explicit warning: a transfer and an entry/end can describe
    the same movement — this event contributes only its own row to
    events[]/caused_by, never a silent state change of its own.
    """
    ev = Event(
        "e1", "SHAREHOLDER_SHARE_TRANSFER", "2001-01-01",
        {"from_name": "A", "to_name": "B", "shares": 2}, src(),
    )
    rows, _ = build_timeline(initial(), [ev])
    assert rows[-1].holders == initial().holders
    assert rows[-1].caused_by == ("e1",)


# ===========================================================================
# ordering and determinism
# ===========================================================================


def test_events_fold_in_event_date_order_not_list_order():
    early = Event("e-early", "CAPITAL_INCREASE", "2001-01-01", {"amount_eur": 100}, src())
    late = Event("e-late", "CAPITAL_INCREASE", "2002-01-01", {"amount_eur": 200}, src())
    rows_forward, _ = build_timeline(initial(), [late, early])
    rows_backward, _ = build_timeline(initial(), [early, late])
    assert [r.as_of for r in rows_forward] == [r.as_of for r in rows_backward]
    assert [r.capital_eur for r in rows_forward] == [r.capital_eur for r in rows_backward]


def test_same_day_events_are_ordered_by_source_not_list_order():
    """Two events on the same date, different (inpi_id, page, line_index) —
    the fold must be deterministic and independent of input list order.
    """
    first = Event("e1", "CAPITAL_INCREASE", "2001-01-01", {"amount_eur": 100}, src(page=1, line_index=5))
    second = Event("e2", "CAPITAL_INCREASE", "2001-01-01", {"amount_eur": 200}, src(page=1, line_index=9))
    a, _ = build_timeline(initial(), [first, second])
    b, _ = build_timeline(initial(), [second, first])
    assert [r.capital_eur for r in a] == [r.capital_eur for r in b]
    assert a[-2].caused_by == ("e1",)
    assert a[-1].caused_by == ("e2",)


def test_state_only_transition_produces_a_row_with_no_caused_by():
    t = StateOnlyTransition(
        as_of="2001-06-01", capital_eur=Decimal(1000), shares_total=1000, nominal_eur=Decimal(1),
        holders=initial().holders, sort_key=("2001-06-01", "z", 1, 0), reason="nominal split",
    )
    rows, _ = build_timeline(initial(), [], extra_transitions=[t])
    assert rows[-1].caused_by == ()
    assert rows[-1].nominal_eur == Decimal(1)


def test_build_timeline_never_raises_on_a_real_invariant_gap():
    """A documented, real corpus gap (unknown holders after an increase) is
    a fact to report via check_invariants, not a crash.
    """
    ev = Event("e1", "CAPITAL_INCREASE", "2001-01-01", {"amount_eur": 500}, src())
    rows, problems = build_timeline(initial(), [ev])
    assert rows  # did not raise
    assert problems  # and the gap was reported


# ===========================================================================
# check_invariants directly
# ===========================================================================


def test_check_invariants_catches_holder_sum_mismatch():
    state = CapTableState(
        as_of="x", capital_eur=Decimal(100), shares_total=10, nominal_eur=Decimal(10),
        holders=(Holder("A", shares=3), Holder("B", shares=3)),
    )
    problems = check_invariants(state)
    assert any("sum to 6" in p for p in problems)


def test_check_invariants_catches_capital_mismatch():
    state = CapTableState(
        as_of="x", capital_eur=Decimal(999), shares_total=10, nominal_eur=Decimal(10),
        holders=(),
    )
    problems = check_invariants(state)
    assert any("!=" in p for p in problems)


def test_check_invariants_is_silent_on_a_fully_unknown_state():
    """Nothing to check is not a violation — only a stated, wrong claim is."""
    state = CapTableState(as_of="x", capital_eur=None, shares_total=None, nominal_eur=None, holders=())
    assert check_invariants(state) == []


def test_check_invariants_skips_partially_unknown_holders():
    """One UNKNOWN bucket with no shares plus a real holder: only the known
    portion is checked, an explicit unattributed holder with shares=None is
    simply not summed.
    """
    state = CapTableState(
        as_of="x", capital_eur=Decimal(100), shares_total=10, nominal_eur=Decimal(10),
        holders=(Holder("A", shares=10), Holder("unattributed", "UNKNOWN", shares=None)),
    )
    assert check_invariants(state) == []
