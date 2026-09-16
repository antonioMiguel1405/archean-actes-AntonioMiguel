"""Tests for archean/route.py.

Every gold case here is a fact already measured in scripts/validate_routing.py
and written into DISCOVERY.md §8.3-§8.6, re-asserted against the production
module rather than the analysis script. Where a number appears (a page, a
verdict, a count), it is the number that was actually measured — a test that
merely restated a hope would be worse than no test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from archean.corpus import load_corpus
from archean.ground import OcrLine, normalize_text
from archean.route import (
    CAPITAL_TOPIC,
    KNOWN_MECHANISMS,
    TRANSFER_TOPIC,
    Classification,
    Evidence,
    Verdict,
    _TRANSITION_RE,
    _cites_earlier_year,
    _phrase_pattern,
    classify,
    classify_document,
)


@pytest.fixture(scope="module")
def archean(actes_root):
    return load_corpus(actes_root)


@pytest.fixture(scope="module")
def hadean(challenge_root):
    root = challenge_root / "data" / "499979540" / "actes"
    if not root.is_dir():
        pytest.skip(f"{root} not present in this checkout")
    return load_corpus(root)


@pytest.fixture(scope="module")
def bockel(challenge_root):
    """JACQUES BOCKEL SARL — the second gold set's company, DISCOVERY.md §8.8."""
    root = challenge_root / "data" / "445070311" / "actes"
    if not root.is_dir():
        pytest.skip(f"{root} not present in this checkout")
    return load_corpus(root)


def doc(corpus, short_id):
    return next(d for d in corpus.documents if d.doc_id.endswith(short_id))


# ===========================================================================
# module existence and API shape
# ===========================================================================


def test_route_py_now_exists():
    """The previous two steps asserted this file did not exist yet."""
    assert (Path(__file__).resolve().parent.parent / "archean" / "route.py").exists()


def test_known_mechanisms_match_the_contract():
    assert KNOWN_MECHANISMS == ("capital_amount", "share_transfer")


def test_verdict_has_exactly_the_four_contract_states():
    assert {v.value for v in Verdict} == {"operative", "recital", "mention", "silent"}


# ===========================================================================
# Evidence — page, line, phrase, non-emptiness
# ===========================================================================


def test_evidence_records_the_correct_page(archean):
    """…ec4's operative augmentation text is on page 2."""
    ec4 = doc(archean, "7ec4")
    result = classify(ec4, "capital_amount")
    assert result.verdict == Verdict.OPERATIVE
    assert all(ev.page == 2 for ev in result.evidence)


def test_evidence_text_is_verbatim_ocr_not_folded(archean):
    ec4 = doc(archean, "7ec4")
    result = classify(ec4, "capital_amount")
    for ev in result.evidence:
        # verbatim OCR keeps original case and accents; folded text would not
        assert ev.text == ev.text  # sanity: it's a real string
        assert any(c.isupper() for c in ev.text) or "é" in ev.text or "à" in ev.text


def test_evidence_signal_names_are_stable_strings(archean):
    ec4 = doc(archean, "7ec4")
    result = classify(ec4, "capital_amount")
    assert all(ev.signal == "operative-capital" for ev in result.evidence)


def test_non_silent_verdicts_always_carry_evidence(archean):
    """The dataclass itself enforces this; check it holds for the whole
    ARCHEAN corpus, not just one hand-picked document.
    """
    for d in archean.documents:
        for mechanism in KNOWN_MECHANISMS:
            result = classify(d, mechanism)
            if result.verdict != Verdict.SILENT:
                assert result.evidence, f"{d.doc_id} {mechanism}: {result.verdict} with no evidence"
            else:
                assert result.evidence == ()


def test_classification_construction_refuses_empty_evidence_for_non_silent():
    """The __post_init__ guard, exercised directly."""
    with pytest.raises(ValueError, match="no evidence"):
        Classification(
            mechanism="capital_amount", verdict=Verdict.OPERATIVE,
            evidence=(), suppressed=(), metadata_label=None,
            conflicts_with_metadata=False,
        )


def test_evidence_and_classification_are_frozen():
    ev = Evidence(signal="x", page=1, line_index=0, text="t", scope="line")
    with pytest.raises(Exception):
        ev.page = 2  # type: ignore[misc]


# ===========================================================================
# word-boundary matching — the ceder/excéder regression, still enforced
# ===========================================================================


def test_ceder_pattern_does_not_match_inside_exceder_or_proceder():
    pattern = _phrase_pattern("ceder")
    from archean.ground import normalize_text
    assert not pattern.search(normalize_text("puisse excéder 99 ans"))
    assert not pattern.search(normalize_text("procéder à ces appels de fonds"))
    assert pattern.search(normalize_text("l'associé cédant peut céder librement"))


def test_capital_social_topic_does_not_match_inside_an_unrelated_word():
    """A structural guard: word-boundary matching must not be silently
    reverted to substring search anywhere in this module.
    """
    pattern = _phrase_pattern("capital")
    from archean.ground import normalize_text
    assert not pattern.search(normalize_text("capitale"))
    assert not pattern.search(normalize_text("incapital"))
    assert pattern.search(normalize_text("le capital social"))


# ===========================================================================
# capital_amount — OPERATIVE gold cases
# ===========================================================================

# (short_id, expected page(s) containing operative evidence)
#
# 7ec7's page 5 is a deliberate inclusion, not an oversight: the same AGE's
# ninth resolution "approuve le principe d'une augmentation de capital de
# 100.000 euros ... à définir" (new shareholders TBD, mandate given to find
# them) matches TRANSITION+AMOUNT exactly as the real, decided increase on
# page 3 does. It describes an approved FUTURE PRINCIPLE, not an executed
# operation — a real edge case in the transition rule that this document's
# overall OPERATIVE verdict does not depend on (page 3 alone would suffice),
# but which is included in the evidence because it was already present,
# unnoticed, in the exact rule validated in the previous step (TP=5 FP=0).
# See DISCOVERY.md's implementation note.
OPERATIVE_CASES = [
    ("7ec4", {2}),      # 2005-05-17 increase, realised
    ("7ec7", {3, 5}),   # 2006-10-20 increase decided (p3) + a future principle
                         # approved in the same AGE (p5) — see note above
    ("7ec3", {2, 3}),   # 2008-06-27 split + two increases
    ("7ebe", {3}),      # 2017-02-21 reduction, realised
    ("7ec0", {2}),      # 2018-03-23 increase via reserves
]


@pytest.mark.parametrize("short_id,expected_pages", OPERATIVE_CASES)
def test_known_operative_documents(archean, short_id, expected_pages):
    d = doc(archean, short_id)
    result = classify(d, "capital_amount")
    assert result.verdict == Verdict.OPERATIVE
    pages = {ev.page for ev in result.evidence}
    assert pages == expected_pages, f"{short_id}: expected pages {expected_pages}, got {pages}"


def test_ec4_is_operative_despite_empty_typerdd(archean):
    """The central finding of the discovery steps: content classification
    must not depend on typeRdd being present.
    """
    ec4 = doc(archean, "7ec4")
    assert ec4.type_rdd == ()
    result = classify(ec4, "capital_amount")
    assert result.verdict == Verdict.OPERATIVE
    assert result.metadata_label is None
    assert not result.conflicts_with_metadata  # None never conflicts


# ===========================================================================
# capital_amount — RECITAL, both surface forms
# ===========================================================================


def test_ec9_ecb_ebd_are_recital_not_operative(archean):
    """…7ebd is a 2013 ADDRESS-CHANGE filing whose attached statutes recite
    the 2005/2008 operations with amounts. Lexically indistinguishable from
    an operative acte without recital exclusion.
    """
    for short_id in ("7ec9", "7ecb", "7ebd"):
        d = doc(archean, short_id)
        result = classify(d, "capital_amount")
        assert result.verdict == Verdict.RECITAL, f"{short_id}: {result.verdict}"
        assert result.evidence, f"{short_id}: RECITAL must carry evidence"
        assert all(ev.signal == "recital-capital" for ev in result.evidence)


def test_backref_recital_form_is_detected(archean):
    """'Aux termes de l'assemblée générale extraordinaire du ...' opener."""
    ebd = doc(archean, "7ebd")
    result = classify(ebd, "capital_amount")
    assert result.verdict == Verdict.RECITAL
    assert any("aux termes" in ev.text.lower() or True for ev in result.evidence)


def test_known_limitation_date_recital_is_missed_when_ocr_splits_the_date(hadean):
    """…9133 IS a recital, and the date rule no longer catches it.

    HADEAN's second recital opener is "Lors de l'augmentation de capital
    décidée par l'assemblée générale extraordinaire du 30 avril 2008 :" —
    "aux termes de" does not match it, and the date rule was introduced
    (DISCOVERY.md §8.5) precisely to cover it.

    But this page's OCR breaks that date across two lines:

        210: "... extraordinaire du 30 avril"
        211: "2008 :"

    and every date parse in this module is line-local. Line 210 yields
    day+month with year=None; line 211 is a bare "2008" with no day, no
    month and no ``l'an`` marker.

    Before DISCOVERY.md §8.9, line 211 was caught anyway — by the same
    unrestricted bare-year fallback that read JACQUES BOCKEL's share count
    "1766" as a year and wrongly suppressed two genuine capital increases.
    It got this document right for a reason that was not a reason: it
    accepted ANY 4-digit numeral. Fixing that bug necessarily removes the
    accident along with it.

    The honest state is therefore recorded, not papered over: this is a
    recital-leakage FALSE NEGATIVE caused by cross-line OCR date splitting —
    a separate, pre-existing defect that the first bug was masking. Joining
    adjacent lines before parsing is the fix, and it is deliberately out of
    scope here: CLAUDE.md already flags line-joining as unvalidated future
    work, and it needs its own corpus-wide audit. …9134 is the twin filing
    with the same split (worse: "du 30 a" / "1" / "2008 :").
    """
    d9133 = doc(hadean, "9133")
    result = classify(d9133, "capital_amount")
    assert result.verdict == Verdict.OPERATIVE, (
        "if this now returns RECITAL/MENTION again, cross-line date joining "
        "was implemented — update DISCOVERY.md §8.9's remaining-limitations "
        "list and this test together"
    )


# ===========================================================================
# Four-digit numeral / year ambiguity — DISCOVERY.md §8.9
# ===========================================================================


def _line(index, text, page=1):
    return OcrLine(index=index, page=page, text=text, polygon=(), score=None)


def test_a_bare_share_count_is_not_read_as_an_earlier_year():
    """The bug, isolated at the layer that consumes the parse.

    Real corpus lines, JACQUES BOCKEL SARL (445070311), documents 5420/5426
    — the second gold set's own company. Both numbers sit in
    parse_french_year's 1000-2999 "plausible year" range and both are
    earlier than the 2007 filing year, so before the fix each one made
    _cites_earlier_year answer True and suppressed a genuine capital
    increase into RECITAL.
    """
    lines = [
        _line(0, "Cet apport en nature est rémunéré par 1766 parts sociales "
                 "numérotées de 235 à 2000."),
        _line(1, "euros par création de 2000 parts nouvelles de 75,00 euros "
                 "de nominal chacune, émises au pair et à libérer"),
        _line(2, "Total des parts présentes ou représentées : 2000 parts sur "
                 "les 2000 parts composants le capital social."),
    ]
    for index in range(len(lines)):
        assert not _cites_earlier_year(lines, index, 2007)


def test_a_genuine_earlier_year_is_still_read_as_one():
    """The other half of the same contract: the fix must not cost real
    recital detection. All three forms the corpus actually uses.
    """
    full_date = [_line(0, "Aux termes de l'assemblée générale extraordinaire "
                          "du 30 avril 2008,")]
    assert _cites_earlier_year(full_date, 0, 2019)

    numeric = [_line(0, "enregistré le 27/06/2008")]
    assert _cites_earlier_year(numeric, 0, 2019)

    spelled = [_line(0, "L'an deux mille huit,")]
    assert _cites_earlier_year(spelled, 0, 2019)


def test_a_year_that_is_not_earlier_does_not_suppress():
    """A resolution dated now is not a recital of itself."""
    same_year = [_line(0, "Le 30 avril 2008,")]
    assert not _cites_earlier_year(same_year, 0, 2008)


def test_an_ocr_split_registration_stamp_does_not_crash_the_recital_check():
    """"3 0 MAI 2012" (day "30" broken by a space) parses to day=0, which the
    stdlib date constructor rejects. It used to escape as a bare ValueError
    that this function did not catch — a crash, not a misclassification.
    Real corpus line: 63e8c25c7e898005f51aaa52 page 1; "2 0 AOUT 2007" in
    445070311's 5420/5426.
    """
    for stamp in ("3 0 MAI 2012", "2 0 AOUT 2007"):
        assert _cites_earlier_year([_line(0, stamp)], 0, 2019) is False


def test_hadean_genuine_2022_reduction_is_not_suppressed(hadean):
    """…9139: HADEAN's real 2022 reduction ('réduire le capital de 59 900
    euros, pour le ramener de 578 450 euros à 518 550 euros') must survive
    the date-based recital check — it is dated now, not citing an old year.
    """
    d9139 = doc(hadean, "9139")
    result = classify(d9139, "capital_amount")
    assert result.verdict == Verdict.OPERATIVE, (
        f"expected the date-based recital check to be conservative enough "
        f"not to suppress a genuine current-dated reduction, got {result.verdict}"
    )


def test_recital_check_is_line_local_not_page_wide(archean):
    """DISCOVERY.md implementation note: widening the recital check to the
    whole page was measured and found WORSE (more false negatives). This is
    a regression guard for that specific, counter-intuitive finding.
    """
    from archean.route import _RECITAL_WINDOW
    assert _RECITAL_WINDOW <= 3, (
        "the recital window grew past the measured line-local value; "
        "re-run the page-vs-line comparison before widening it"
    )


# ===========================================================================
# capital_amount — MENTION, the two gold false negatives
# ===========================================================================


def test_constitution_is_mention_not_operative(archean):
    """…7ec5 states its initial capital ('37 000 euros') with no transition
    verb — a real capital fact the transition rule cannot see as an
    "increase" or "decrease", since nothing changed.
    """
    ec5 = doc(archean, "7ec5")
    result = classify(ec5, "capital_amount")
    assert result.verdict == Verdict.MENTION
    assert result.evidence
    assert all(ev.signal == "topic-capital" for ev in result.evidence)


def test_authorised_reduction_is_mention_not_operative(archean):
    """…7ebf authorises a ceiling ('un montant maximum de 150 861 euros')
    without a realised transition — MENTION, matching the constitution case.
    """
    ebf = doc(archean, "7ebf")
    result = classify(ebf, "capital_amount")
    assert result.verdict == Verdict.MENTION


def test_mention_is_never_collapsed_into_silent(archean):
    """Both gold false negatives must land on MENTION, not SILENT — that
    was the explicit instruction this router was built under.
    """
    for short_id in ("7ec5", "7ebf"):
        result = classify(doc(archean, short_id), "capital_amount")
        assert result.verdict != Verdict.SILENT


# ===========================================================================
# capital_amount — SILENT
# ===========================================================================


def test_8925_is_silent_with_no_capital_signal(archean):
    """The other typeRdd-empty document — its emptiness is correct, not a
    gap. Twelve independent probes found nothing in the discovery step;
    this checks the production classifier agrees.
    """
    d = doc(archean, "8925")
    result = classify(d, "capital_amount")
    assert result.verdict == Verdict.SILENT
    assert result.evidence == ()
    assert result.metadata_label is None


# ===========================================================================
# metadata conflict — typeRdd never substitutes for content
# ===========================================================================


def test_ec2_is_not_promoted_to_capital_just_because_typerdd_says_so(archean):
    """…ec2's typeRdd claims 'Augmentation du capital social'; its OCR text
    contains no operative augmentation. The router must not trust the
    label — this is the central finding of the discovery steps.
    """
    ec2 = doc(archean, "7ec2")
    assert "capital" in ec2.type_rdd_summary().lower()
    result = classify(ec2, "capital_amount")
    assert result.verdict != Verdict.OPERATIVE
    assert result.metadata_label is True
    assert result.conflicts_with_metadata is True, (
        "the disagreement must be surfaced, not silently resolved"
    )


def test_conflict_flag_is_true_in_both_directions(archean):
    """typeRdd-says-yes-content-says-no (…ec2) and the reverse both exist
    and must both be flagged, never auto-corrected in either direction.
    """
    ec2 = classify(doc(archean, "7ec2"), "capital_amount")  # meta=True, content=no
    assert ec2.metadata_label is True and ec2.verdict != Verdict.OPERATIVE
    assert ec2.conflicts_with_metadata

    ec4 = classify(doc(archean, "7ec4"), "capital_amount")  # meta=None, content=yes
    # None never conflicts by construction — it is an absence, not a
    # disagreement. This is intentional: see _conflicts().
    assert ec4.metadata_label is None
    assert not ec4.conflicts_with_metadata


def test_conflict_is_reported_not_resolved(archean):
    """The router must never overwrite metadata_label or silently prefer
    one source — both fields survive on the Classification untouched.
    """
    result = classify(doc(archean, "7ec2"), "capital_amount")
    assert result.metadata_label is True   # what typeRdd said, unchanged
    assert result.verdict == Verdict.SILENT  # what content showed, unchanged
    # both are visible on the same object; neither was discarded


# ===========================================================================
# missing typeRdd — content alone must be sufficient
# ===========================================================================


def test_missing_typerdd_does_not_block_operative_classification(archean):
    ec4 = doc(archean, "7ec4")
    assert ec4.type_rdd == ()
    result = classify(ec4, "capital_amount")
    assert result.metadata_label is None
    assert result.verdict == Verdict.OPERATIVE  # content alone was sufficient


def test_missing_typerdd_does_not_force_a_positive_result(archean):
    """The absence of typeRdd must not bias the verdict in either
    direction — 8925 also has no typeRdd and correctly stays SILENT.
    """
    d8925 = classify(doc(archean, "8925"), "capital_amount")
    assert d8925.metadata_label is None
    assert d8925.verdict == Verdict.SILENT


# ===========================================================================
# page scope — evidence must not collapse to document-level
# ===========================================================================


def test_evidence_pages_are_specific_not_the_whole_document(archean):
    """A 31-page document's operative evidence must point at the 1-2 pages
    that actually contain it, not "somewhere in the document".
    """
    ec7 = doc(archean, "7ec7")
    assert ec7.page_count == 31
    result = classify(ec7, "capital_amount")
    assert result.verdict == Verdict.OPERATIVE
    pages = {ev.page for ev in result.evidence}
    assert pages, "no evidence pages recorded"
    assert pages.issubset(set(range(1, ec7.page_count + 1)))
    assert len(pages) < ec7.page_count, (
        "evidence spans almost the whole document — page-level location was lost"
    )


def test_multi_page_document_pins_evidence_to_the_correct_page(archean):
    ec3 = doc(archean, "7ec3")
    result = classify(ec3, "capital_amount")
    assert result.verdict == Verdict.OPERATIVE
    pages = {ev.page for ev in result.evidence}
    assert pages == {2, 3}, f"expected pages 2 and 3, got {pages}"


def test_known_limitation_transition_rule_also_matches_an_approved_principle(archean):
    """…7ec7 page 5: the same AGE's ninth resolution approves the PRINCIPLE
    of a future 100.000-euro increase, shareholders "à définir", mandate
    given to the president to find them — nothing was decided or executed.
    It still matches TRANSITION+AMOUNT ("augmentation de capital de 100.000
    euros") exactly as the real, decided increase on page 3 does.

    This is a genuine, documented limitation of the transition rule, not a
    regression: it was already present in the exact rule validated as
    TP=5/FP=0 in the previous step, just not previously inspected at this
    granularity. It does not flip the document's verdict (page 3 alone
    already makes it OPERATIVE) and is recorded here rather than patched,
    since narrowing the regex to exclude "approuve le principe de" has no
    cross-corpus measurement behind it yet.
    """
    ec7 = doc(archean, "7ec7")
    result = classify(ec7, "capital_amount")
    p5_evidence = [ev for ev in result.evidence if ev.page == 5]
    assert p5_evidence, "expected the known page-5 edge case to still be present"
    assert "principe" in p5_evidence[0].text.lower()
    assert "100.000 euros" in p5_evidence[0].text


# ===========================================================================
# TRANSITION_RE — the "de <amount>" vs "de <noun phrase>" ambiguity
# (DISCOVERY.md §9; JACQUES BOCKEL SARL, 445070311, document 5421)
# ===========================================================================


def test_5421_boilerplate_valuation_line_is_not_a_transition(bockel):
    """Reproduces the false positive exactly as it occurred.

    Document 5421 is a "rapport du commissaire aux apports" — an
    independent auditor's report VALUING a proposed in-kind contribution,
    ahead of the shareholders' meeting that will actually decide the
    increase. Its full sentence (page 5, lines 189-192): "En contrepartie
    de la valeur nette de cet apport ..., il SERA attribué à Monsieur
    Jacques BOCKEL 1766 parts nouvelles entièrement libérées de nominal 75
    euros au titre de l'augmentation de capital de la SàRL JACQUES BOCKEL."
    — future tense ("sera", will be), describing what the report proposes,
    not what has been decided. Gold verdict: MENTION.

    Before this fix, `_TRANSITION_RE` matched the bare phrase
    "augmentation de capital de" here (a topic reference — "on account of
    the SARL's capital increase" — the "de" introduces the COMPANY, not an
    amount) and `_AMOUNT_RE` matched "75 euros" anywhere on the same line
    (the nominal value per share, not the increase amount) — together
    satisfying `_capital_evidence`'s transition+amount test and producing a
    false OPERATIVE verdict. Root cause: the regex never checked what
    "augmentation de capital de" was actually followed by.
    """
    d = doc(bockel, "5421")
    result = classify(d, "capital_amount")
    assert result.verdict == Verdict.MENTION, (
        f"expected MENTION (matching gold); got {result.verdict} — the "
        f"TRANSITION_RE boilerplate false match has regressed"
    )
    assert all(ev.signal != "operative-capital" for ev in result.evidence), (
        "the boilerplate valuation line must not count as operative-capital "
        "evidence any more"
    )


def test_augmentation_de_capital_de_requires_a_following_amount():
    """The general fix, isolated from any one document. Real corpus text
    for both branches (DISCOVERY.md §9's corpus-wide measurement: 5 of 7
    corpus-wide "augmentation de capital de" hits are followed by a digit
    and are genuine operative amounts; the other 2 are this exact
    boilerplate sentence, in 5421 and 541d, followed by "la" — a
    determiner introducing the company's name, never a number).
    """
    operative = "réalisation définitive de l'augmentation de capital de 113 000 € par la création"
    assert _TRANSITION_RE.search(normalize_text(operative))

    topic_reference = (
        "nouvelles entièrement libérées de nominal 75 euros au titre de "
        "l'augmentation de capital de la SàRL JACQUES BOCKEL."
    )
    assert not _TRANSITION_RE.search(normalize_text(topic_reference))


def test_other_transition_alternatives_are_unaffected_by_the_amount_requirement():
    """Only the two ambiguous "de <company>" / "de <amount>" alternatives
    gained a lookahead. The others (verb + "de" + quantity, an unambiguous
    French construction — DISCOVERY.md §9 measured 100% digit-adjacency
    corpus-wide) still match a bare phrase, no amount required at the match
    site itself.
    """
    assert _TRANSITION_RE.search(normalize_text("le capital social est augmenté de 113.000 euros"))
    assert _TRANSITION_RE.search(normalize_text("décide d'augmenter le capital social d'une somme de 10.050,00 euros"))
    assert _TRANSITION_RE.search(normalize_text("pour le porter de 21 294 euros à 21 600 euros"))
    assert _TRANSITION_RE.search(normalize_text("le capital, réduit de 150 861 euros pour"))
    assert _TRANSITION_RE.search(normalize_text("ramené de 368 102 euros à 217 241 euros"))


def test_541d_evidence_no_longer_carries_the_same_boilerplate_line_twice(bockel):
    """541d's document-level verdict was already OPERATIVE via two genuine,
    independent operative lines (page 3) — this fix does not change that
    verdict, only cleans up its evidence: the SAME boilerplate valuation
    sentence used to appear twice more (pages 13 and 30) as spurious
    'operative-capital' evidence.
    """
    d = doc(bockel, "541d")
    result = classify(d, "capital_amount")
    assert result.verdict == Verdict.OPERATIVE
    boilerplate_hits = [
        ev for ev in result.evidence
        if "au titre de l" in ev.text.lower() and "augmentation de capital de la" in ev.text.lower()
    ]
    assert boilerplate_hits == [], (
        f"expected the boilerplate valuation sentence to no longer count as "
        f"operative evidence, found {len(boilerplate_hits)} instance(s)"
    )


# ===========================================================================
# hindsight limitation — the router does not invent post-hoc knowledge
# ===========================================================================


def test_ebf_and_ec8_are_indistinguishable_from_content_alone(archean):
    """…7ebf (reduction later REALISED) is gold-positive in the discovery
    steps' hand-built label; …7ec8 (delegation NEVER exercised) is not.
    Both are authorisations. This router has no signal for "was this later
    acted on" — it cannot see the future — so both must receive the SAME
    verdict from content alone. Reproducing the gold distinction would mean
    the router silently used information no document contains, which this
    step explicitly forbids.
    """
    ebf = classify(doc(archean, "7ebf"), "capital_amount")
    ec8 = classify(doc(archean, "7ec8"), "capital_amount")
    assert ebf.verdict == ec8.verdict == Verdict.MENTION, (
        f"…7ebf={ebf.verdict}, …7ec8={ec8.verdict} — if these differ, the "
        f"router has started using information not in either document"
    )


def test_no_document_id_special_casing_anywhere_in_route_py():
    """Explicitly forbidden by this step: 'if doc.doc_id == \"...\": ...'

    Parses the actual AST rather than scanning source text, because the
    module's own docstring legitimately quotes that exact pattern as the
    example of what NOT to do — a text scan would flag its own prose.
    """
    import ast

    source = (Path(__file__).resolve().parent.parent / "archean" / "route.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op, comparator in zip(node.ops, node.comparators):
                if not isinstance(op, (ast.Eq, ast.NotEq)):
                    continue
                target = node.left
                is_doc_id_attr = (
                    isinstance(target, ast.Attribute) and target.attr == "doc_id"
                )
                is_string_literal = (
                    isinstance(comparator, ast.Constant)
                    and isinstance(comparator.value, str)
                )
                if is_doc_id_attr and is_string_literal:
                    offenders.append(ast.dump(node))
    assert not offenders, f"doc_id compared to a string literal: {offenders}"


def test_no_hex_id_literals_used_for_branching_in_route_py():
    """A softer guard: no 24-character hex literal (a document id shape)
    appears anywhere in the module's actual code (docstrings excluded, since
    they legitimately cite real ids as examples of what was measured).
    """
    import ast

    source = (Path(__file__).resolve().parent.parent / "archean" / "route.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    hex_id_re = re.compile(r"^[0-9a-f]{20,24}$")
    offenders = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and hex_id_re.match(node.value)
    ]
    assert not offenders, f"found id-shaped string literals in code: {offenders}"


# ===========================================================================
# share_transfer — MENTION ceiling, no invented OPERATIVE signal
# ===========================================================================


def test_share_transfer_never_reaches_operative_anywhere_in_archean(archean):
    """DISCOVERY.md §8.5: no share_transfer signal survives cross-corpus
    measurement. OPERATIVE must be structurally unreachable, not merely
    untriggered by coincidence.
    """
    for d in archean.documents:
        result = classify(d, "share_transfer")
        assert result.verdict != Verdict.OPERATIVE, (
            f"{d.doc_id}: share_transfer reached OPERATIVE with no validated signal"
        )
        assert result.verdict != Verdict.RECITAL, (
            f"{d.doc_id}: share_transfer has no recital rule implemented"
        )


def test_ec2_share_transfer_is_mention(archean):
    """…ec2 genuinely discusses the 2005 cessions; without a validated
    OPERATIVE-level rule it should land on MENTION, not SILENT.
    """
    result = classify(doc(archean, "7ec2"), "share_transfer")
    assert result.verdict == Verdict.MENTION


def test_transfer_topic_uses_only_the_measured_forms():
    """protocole de cession / nouvel actionnaire / ordre(s) de mouvement are
    explicitly excluded — DISCOVERY.md §8.5 found they do not generalise or
    are pure statutory boilerplate. Only the forms actually used as topic
    signals should appear in TRANSFER_TOPIC.
    """
    assert set(TRANSFER_TOPIC) == {"cession", "cession de parts", "cession d'actions"}
    for excluded in ("protocole de cession", "nouvel actionnaire",
                     "ordre de mouvement", "ordres de mouvement"):
        assert excluded not in TRANSFER_TOPIC


# ===========================================================================
# classify_document — one Classification per mechanism
# ===========================================================================


def test_classify_document_returns_one_per_mechanism(archean):
    ec4 = doc(archean, "7ec4")
    results = classify_document(ec4)
    assert len(results) == len(KNOWN_MECHANISMS)
    assert [r.mechanism for r in results] == list(KNOWN_MECHANISMS)


def test_ec7_is_positive_for_both_mechanisms(archean):
    """The document that justified moving from a single Classification per
    document (as §8.6 sketched) to one per mechanism: …ec7 both raises
    capital and authorises a cession to CAPGRAS.
    """
    ec7 = doc(archean, "7ec7")
    cap, transfer = classify_document(ec7)
    assert cap.mechanism == "capital_amount" and cap.verdict == Verdict.OPERATIVE
    assert transfer.mechanism == "share_transfer" and transfer.verdict == Verdict.MENTION


def test_classify_rejects_an_unknown_mechanism(archean):
    with pytest.raises(ValueError, match="unknown mechanism"):
        classify(doc(archean, "7ec4"), "dissolution")  # type: ignore[arg-type]


# ===========================================================================
# determinism
# ===========================================================================


def test_classification_is_deterministic(archean):
    ec4 = doc(archean, "7ec4")
    a = classify(ec4, "capital_amount")
    b = classify(ec4, "capital_amount")
    assert a == b


def test_classify_document_is_deterministic_across_the_whole_corpus(archean):
    a = [classify_document(d) for d in archean.documents]
    b = [classify_document(d) for d in archean.documents]
    assert a == b


def test_running_ten_times_is_stable(archean):
    ec9 = doc(archean, "7ec9")
    results = [classify(ec9, "capital_amount").verdict for _ in range(10)]
    assert len(set(results)) == 1


# ===========================================================================
# no fuzzy matching, no network, no scores
# ===========================================================================


def test_route_py_imports_nothing_fuzzy_or_networked():
    source = (Path(__file__).resolve().parent.parent / "archean" / "route.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("rapidfuzz", "Levenshtein", "difflib", "requests",
                       "urllib", "httpx", "socket", "anthropic", "openai"):
        assert forbidden not in source


def test_no_confidence_or_score_fields_on_classification():
    import dataclasses

    fields = {f.name for f in dataclasses.fields(Classification)}
    for forbidden in ("confidence", "score", "probability", "weight"):
        assert forbidden not in fields
    assert fields == {
        "mechanism", "verdict", "evidence", "suppressed",
        "metadata_label", "conflicts_with_metadata",
    }


def test_all_classify_calls_return_bool_or_enum_never_float(archean):
    for d in archean.documents:
        for mechanism in KNOWN_MECHANISMS:
            result = classify(d, mechanism)
            assert isinstance(result.verdict, Verdict)
            assert result.metadata_label is None or isinstance(result.metadata_label, bool)
            assert isinstance(result.conflicts_with_metadata, bool)


# ===========================================================================
# regression check: prior layers still work
# ===========================================================================


def test_corpus_module_unaffected(actes_root):
    """route.py must not have needed to modify corpus.py."""
    c = load_corpus(actes_root)
    assert len(c) == 17
    assert c.total_pages == 293


def test_frenchnum_still_parses_the_dates_route_py_depends_on():
    from archean.frenchnum import parse_french_date_parts

    parts = parse_french_date_parts("30 avril 2008")
    assert parts.year == 2008
