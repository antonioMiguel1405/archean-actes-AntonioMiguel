"""Tests for scripts/validate_routing.py — cross-corpus validation facts.

Everything asserted here was measured first and written into DISCOVERY.md
8.5. The distinction this file exists to protect is between:

  - facts about ARCHEAN, where a hand-verified gold label exists and real
    TP/FP/FN/TN can be computed; and
  - facts about the other 19 companies, where the only label is typeRdd and
    the honest measurement is AGREEMENT between two imperfect sources.

A test that blurred those two would be worse than no test, so several below
assert the separation itself rather than a number.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from analyze_routing import ARCHEAN_GOLD, ARCHEAN_SIREN  # noqa: E402
from validate_routing import (  # noqa: E402
    ALL_SIGNALS,
    AMOUNT,
    BACKREF,
    TRANSITION,
    Contingency,
    _operative_hits,
    _topic_amount_at_scope,
    contingency,
    find_hits,
    fires,
    has_operative_capital_text,
    has_operative_capital_text_by_date,
    has_typerdd,
    ocr_documents,
    operative_hits_by_date,
    split_archean,
    typerdd_capital,
)


@pytest.fixture(scope="module")
def docs(challenge_root):
    return ocr_documents(challenge_root / "data")


@pytest.fixture(scope="module")
def archean(docs):
    return split_archean(docs)[0]


@pytest.fixture(scope="module")
def others(docs):
    return split_archean(docs)[1]


@pytest.fixture(scope="module")
def by_short_id(docs):
    return {d.doc_id[-4:]: d for _s, d in docs}


# ===========================================================================
# the measurable universe
# ===========================================================================


def test_corpus_scale(docs, archean, others):
    """115 OCR'd acte documents: 17 ARCHEAN, 98 across 16 other sirens."""
    assert len(docs) == 115
    assert len(archean) == 17
    assert len(others) == 98
    assert len({s for s, _ in others}) == 16


def test_only_a_minority_of_ocr_documents_carry_a_typerdd(docs):
    """79 of 115 have typeRdd; 36 have none.

    This is the number that decides whether typeRdd can be a primary routing
    input. ARCHEAN contributed 2 of the 36 — it is a corpus-wide population,
    not an ARCHEAN quirk.
    """
    labelled = [d for _s, d in docs if has_typerdd(d)]
    unlabelled = [d for _s, d in docs if not has_typerdd(d)]
    assert len(labelled) == 79
    assert len(unlabelled) == 36


def test_archean_contributes_only_two_of_the_unlabelled_documents(docs):
    unlabelled = [(s, d) for s, d in docs if not has_typerdd(d)]
    archean_unlabelled = [d for s, d in unlabelled if s == ARCHEAN_SIREN]
    assert len(archean_unlabelled) == 2
    assert {d.doc_id[-4:] for d in archean_unlabelled} == {"7ec4", "8925"}


# ===========================================================================
# what did NOT generalize — the point of cross-corpus validation
# ===========================================================================


@pytest.mark.parametrize("signal", ["protocole de cession", "nouvel actionnaire"])
def test_archean_only_signals_fire_in_zero_other_companies(others, signal):
    """Both had FP=0 in ARCHEAN and looked like clean share_transfer signals.

    Neither fires in a single one of the other 16 companies: they describe
    ARCHEAN's drafting, not a corpus-wide pattern. This is the finding that
    justified doing cross-corpus validation before writing route.py.
    """
    assert not any(fires(d, signal) for _s, d in others)


def test_ordres_de_mouvement_is_near_archean_specific(others):
    """Fires in exactly one other company — too thin to call validated."""
    companies = {s for s, d in others if fires(d, "ordres de mouvement")}
    assert len(companies) == 1


def test_singular_ordre_de_mouvement_generalises_but_as_boilerplate(others, archean):
    """It fires widely — because it is the statutory transmission clause.

    "la cession s'opère par un ordre de mouvement signé du cédant" appears in
    the statutes of most companies regardless of whether any transfer took
    place. Broad firing is not validation; this test pins the distinction so
    the singular form is never mistaken for an operative signal.
    """
    companies = {s for s, d in others if fires(d, "ordre de mouvement")}
    assert len(companies) >= 5
    # in ARCHEAN it fires only inside the transmission article, never in the
    # document that actually records the 2005 cessions (…ec2)
    ec2 = next(d for _s, d in archean if d.doc_id.endswith("ec2"))
    assert not fires(ec2, "ordre de mouvement")
    assert fires(ec2, "ordres de mouvement")


def test_parts_sociales_reveals_a_legal_form_split(archean, others):
    """ARCHEAN is a SAS (actions); much of the corpus is SARL (parts).

    A signal vocabulary derived from ARCHEAN alone is structurally blind to
    the SARL half of the corpus.
    """
    assert not any(fires(d, "parts sociales") for _s, d in archean)
    companies = {s for s, d in others if fires(d, "parts sociales")}
    assert len(companies) >= 10


def test_pour_le_porter_de_generalises_with_no_typerdd_disagreement(docs):
    """Low recall in ARCHEAN, but it fires in 9 other companies and never on
    a document typeRdd does not call a capital event.
    """
    labelled = [(s, d) for s, d in docs if has_typerdd(d)]
    c = contingency(labelled, lambda d: fires(d, "pour le porter de"), typerdd_capital)
    assert c.counts[1] == 0, f"expected no disagreement, got FP={c.fp}"
    assert c.counts[0] >= 8


# ===========================================================================
# context scope — page-level matters, document-level does not suffice
# ===========================================================================


def test_line_adjacent_and_page_scopes_are_equivalent_here(archean):
    """Measured: tightening from page to line buys nothing on this corpus."""
    gold = ARCHEAN_GOLD["capital_amount"]
    results = {
        scope: contingency(
            archean,
            lambda d, s=scope: _topic_amount_at_scope(d, s),
            lambda d: d.doc_id in gold,
        ).counts
        for scope in ("line", "adjacent", "page")
    }
    assert len(set(results.values())) == 1
    assert results["line"] == (7, 3, 0, 7)


def test_document_scope_is_strictly_worse_than_page_scope(archean):
    """Document-level presence admits 3 extra false positives.

    This is the measured answer to "is document-level presence enough?" —
    no, and the cost is quantified rather than asserted.
    """
    gold = ARCHEAN_GOLD["capital_amount"]
    page = contingency(
        archean, lambda d: _topic_amount_at_scope(d, "page"), lambda d: d.doc_id in gold
    )
    document = contingency(
        archean, lambda d: _topic_amount_at_scope(d, "document"), lambda d: d.doc_id in gold
    )
    assert page.counts == (7, 3, 0, 7)
    assert document.counts == (7, 6, 0, 4)
    assert len(document.fp) > len(page.fp)


# ===========================================================================
# the recital problem — the pivotal finding of this step
# ===========================================================================


def test_statutes_recite_capital_history_with_amounts(by_short_id):
    """…7ebd is a 2013 ADDRESS-CHANGE filing whose attached statutes recite
    the 2005 and 2008 capital operations, with amounts and transitions.

    It is lexically indistinguishable from an operative capital acte, which
    is why no bare transition+amount rule can separate them.
    """
    d = by_short_id["7ebd"]
    assert "capital" not in d.type_rdd_summary().lower()
    lines = [
        ln for ln in __import__("analyze_routing").read_document_lines(d)
        if TRANSITION.search(ln.folded) and AMOUNT.search(ln.folded)
    ]
    assert len(lines) >= 3


def test_transition_plus_amount_alone_has_false_positives(archean):
    gold = ARCHEAN_GOLD["capital_amount"]
    c = contingency(
        archean,
        lambda d: any(
            TRANSITION.search(ln.folded) and AMOUNT.search(ln.folded)
            for ln in __import__("analyze_routing").read_document_lines(d)
        ),
        lambda d: d.doc_id in gold,
    )
    assert c.counts == (5, 3, 2, 7)
    assert {i[-4:] for i in c.fp} == {"7ec9", "7ecb", "7ebd"}


def test_excluding_recitals_removes_every_false_positive_in_archean(archean):
    """The measured result: TP=5 FP=0 FN=2 TN=10."""
    gold = ARCHEAN_GOLD["capital_amount"]
    c = contingency(archean, has_operative_capital_text, lambda d: d.doc_id in gold)
    assert c.counts == (5, 0, 2, 10)
    assert {i[-4:] for i in c.fn} == {"7ec5", "7ebf"}


def test_backref_recital_detection_has_a_known_gap_outside_archean(by_short_id):
    """HADEAN introduces its recital differently, and 'aux termes de' misses it.

    "Lors de l'augmentation de capital décidée par l'assemblée générale
    extraordinaire du 30 avril 2008 :" followed by a bulleted history. The
    FP=0 result above is an ARCHEAN result; it does not transfer unchanged.
    """
    d = by_short_id["9133"]
    assert has_operative_capital_text(d), "backref rule treats the recital as operative"
    assert not has_operative_capital_text_by_date(d), "date rule correctly excludes it"


def test_date_based_recital_exclusion_matches_archean_and_generalises(
    archean, by_short_id
):
    """Same ARCHEAN contingency as the backref rule, but also excludes the
    two HADEAN recitals the backref rule admits — while keeping HADEAN's
    genuine 2022 reduction.
    """
    gold = ARCHEAN_GOLD["capital_amount"]
    c = contingency(archean, has_operative_capital_text_by_date, lambda d: d.doc_id in gold)
    assert c.counts == (5, 0, 2, 10)

    assert not has_operative_capital_text_by_date(by_short_id["9133"])
    assert not has_operative_capital_text_by_date(by_short_id["9134"])
    # 9139 is HADEAN's 2022 capital reduction — genuinely operative
    assert has_operative_capital_text_by_date(by_short_id["9139"])


def test_date_rule_reduces_cross_corpus_disagreement_with_typerdd(docs):
    """Outside ARCHEAN the date rule disagrees with typeRdd on 1 document,
    the backref rule on 4. Reported as agreement, never as accuracy.
    """
    labelled = [(s, d) for s, d in docs if has_typerdd(d) and s != ARCHEAN_SIREN]
    backref = contingency(labelled, has_operative_capital_text, typerdd_capital)
    dated = contingency(labelled, has_operative_capital_text_by_date, typerdd_capital)
    assert len(backref.fp) == 4
    assert len(dated.fp) == 1
    assert {i[-4:] for i in dated.fp} == {"9139"}


def test_the_date_rule_is_more_conservative_not_strictly_better(docs):
    """It trades recall for precision: more FN than the backref rule outside
    ARCHEAN. Recorded so the trade-off is not lost.
    """
    labelled = [(s, d) for s, d in docs if has_typerdd(d) and s != ARCHEAN_SIREN]
    backref = contingency(labelled, has_operative_capital_text, typerdd_capital)
    dated = contingency(labelled, has_operative_capital_text_by_date, typerdd_capital)
    assert len(dated.fn) > len(backref.fn)


# ===========================================================================
# gold-label limitations — honesty about our own labels
# ===========================================================================


def test_gold_labels_encode_hindsight_for_authorisation_documents(by_short_id):
    """…7ebf (2017 reduction AUTHORISED, later realised) is gold-positive.
    …7ec8 (2010 delegation to increase capital, never exercised) is not.

    Both are authorisations. The distinction is whether the authorisation was
    later acted on — which is not knowable from the document itself. No
    content-based router can reproduce this, and pretending otherwise would
    build a rule on hindsight.
    """
    assert by_short_id["7ebf"].doc_id in ARCHEAN_GOLD["capital_amount"]
    assert by_short_id["7ec8"].doc_id not in ARCHEAN_GOLD["capital_amount"]
    # and the delegation really is capital-related text, not a mismatch:
    hits = [
        ln for ln in __import__("analyze_routing").read_document_lines(by_short_id["7ec8"])
        if TRANSITION.search(ln.folded)
    ]
    assert hits


def test_the_two_gold_false_negatives_are_different_mechanisms(by_short_id):
    """…7ec5 is a constitution (states an initial capital, no transition);
    …7ebf authorises a maximum (no realised transition). Neither is a tuning
    failure — they are mechanisms the transition rule is not built to catch.
    """
    for short in ("7ec5", "7ebf"):
        assert not has_operative_capital_text_by_date(by_short_id[short])
        assert by_short_id[short].doc_id in ARCHEAN_GOLD["capital_amount"]


# ===========================================================================
# unlabelled documents — the systemic version of the …ec4 finding
# ===========================================================================


def test_unlabelled_documents_contain_operative_capital_text(docs):
    """6 of the 36 typeRdd-less documents show operative capital text.

    …ec4 was not a one-off: metadata-blind capital events exist across
    several companies, which is what makes typeRdd unusable as the primary
    routing input.
    """
    unlabelled = [(s, d) for s, d in docs if not has_typerdd(d)]
    with_capital = [
        (s, d) for s, d in unlabelled if has_operative_capital_text(d)
    ]
    assert len(with_capital) == 6
    assert len({s for s, _ in with_capital}) >= 3, "spans several companies"
    assert any(d.doc_id.endswith("7ec4") for _s, d in with_capital)


def test_8925_remains_signal_free(by_short_id):
    """The other ARCHEAN typeRdd-less document still shows nothing — its
    empty metadata is correct, unchanged by the wider measurement.
    """
    d = by_short_id["8925"]
    assert not has_operative_capital_text(d)
    assert not has_operative_capital_text_by_date(d)


# ===========================================================================
# conflicts are recorded, never silently resolved
# ===========================================================================


def test_conflicts_exist_in_both_directions(docs):
    """typeRdd says capital / content does not, and vice versa. Both happen,
    in several companies. Neither direction is treated as the error.
    """
    labelled = [(s, d) for s, d in docs if has_typerdd(d)]
    meta_only = [
        (s, d) for s, d in labelled
        if typerdd_capital(d) and not has_operative_capital_text(d)
    ]
    content_only = [
        (s, d) for s, d in labelled
        if has_operative_capital_text(d) and not typerdd_capital(d)
    ]
    assert len(meta_only) >= 3
    assert len(content_only) >= 3
    assert {s for s, _ in meta_only} != {ARCHEAN_SIREN}, "not an ARCHEAN-only problem"


def test_ec2_remains_the_documented_metadata_misattribution(by_short_id):
    """Regression guard for the previous step's central finding."""
    ec2, ec4 = by_short_id["7ec2"], by_short_id["7ec4"]
    assert typerdd_capital(ec2)
    assert not has_operative_capital_text(ec2)
    assert not ec4.type_rdd
    assert has_operative_capital_text(ec4)


# ===========================================================================
# matching discipline — regression guards carried forward
# ===========================================================================


def test_word_boundary_matching_is_still_in_force(by_short_id):
    """The excéder/procéder regression must not come back."""
    from analyze_routing import _phrase_pattern, fold

    pattern = _phrase_pattern("ceder")
    assert not pattern.search(fold("puisse excéder 99 ans"))
    assert not pattern.search(fold("procéder à ces appels de fonds"))
    assert pattern.search(fold("peut céder librement"))


def test_validator_imports_nothing_fuzzy_or_networked():
    source = (
        Path(__file__).resolve().parent.parent / "scripts" / "validate_routing.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("rapidfuzz", "Levenshtein", "difflib", "requests",
                       "urllib", "httpx", "socket", "anthropic", "openai"):
        assert forbidden not in source


def test_results_are_integer_counts_not_scores(archean):
    """The output contract is a contingency table, not a number someone can
    mistake for a confidence. Every rule is boolean; every result is a count.
    """
    gold = ARCHEAN_GOLD["capital_amount"]
    c = contingency(archean, has_operative_capital_text_by_date, lambda d: d.doc_id in gold)
    assert isinstance(c, Contingency)
    assert all(isinstance(n, int) for n in c.counts)
    assert all(isinstance(bucket, list) for bucket in (c.tp, c.fp, c.fn, c.tn))
    # and each rule returns a bool, never a float
    for _s, doc in archean[:5]:
        assert isinstance(has_operative_capital_text_by_date(doc), bool)


def test_route_py_exists_and_is_the_designated_next_step():
    """This validation step, like the discovery step before it, was scoped
    not to produce the router — cross-corpus measurement had to come first.
    That boundary has since moved on purpose: route.py now exists, built on
    exactly the contract (§8.6) and measurements (§8.3-§8.5) this file
    tests. Its own behaviour is covered in tests/test_route.py; this
    assertion only confirms the file is where the classification contract
    said it would go, not a re-litigation of whether it should exist.
    """
    route_py = Path(__file__).resolve().parent.parent / "archean" / "route.py"
    assert route_py.exists()


# ===========================================================================
# determinism
# ===========================================================================


def test_signal_measurement_is_deterministic(archean):
    gold = ARCHEAN_GOLD["capital_amount"]
    a = contingency(archean, has_operative_capital_text_by_date, lambda d: d.doc_id in gold)
    b = contingency(archean, has_operative_capital_text_by_date, lambda d: d.doc_id in gold)
    assert a == b


def test_hits_are_ordered_and_reproducible(by_short_id):
    d = by_short_id["7ec4"]
    a = operative_hits_by_date(d)
    b = operative_hits_by_date(d)
    assert a == b
    assert [h.page for h in a] == sorted(h.page for h in a)


def test_every_signal_is_measurable_without_error(docs):
    """No signal raises on any document in the corpus."""
    for signal in ALL_SIGNALS:
        for _s, doc in docs[:20]:
            find_hits(doc, signal)
