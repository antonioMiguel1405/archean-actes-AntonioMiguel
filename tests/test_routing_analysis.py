"""Tests for scripts/analyze_routing.py.

Every test here encodes a fact already measured against the real corpus and
written up in DISCOVERY.md 8.4 — not a hypothesis being proposed for the
first time. If one of these ever fails, the corpus, the corpus.py loader, or
the matching logic changed underneath a documented finding, and DISCOVERY.md
needs re-verifying before the test is "fixed".

This file does not test a routing decision, because none exists yet: there
is no route(document) -> Route anywhere in this repo, and this file must not
grow one by accident.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from analyze_routing import (  # noqa: E402
    ARCHEAN_GOLD,
    ARCHEAN_SIREN,
    GOLD_CANDIDATES,
    _phrase_pattern,
    document_ngram_presence,
    fold,
    load_all_actes,
    measure_signal,
    phrase_present,
    read_document_lines,
    read_page_lines,
    type_rdd_labels,
)
from archean.corpus import load_corpus


@pytest.fixture(scope="module")
def archean_corpus(actes_root):
    return load_corpus(actes_root)


@pytest.fixture(scope="module")
def archean_docs(archean_corpus):
    return [(ARCHEAN_SIREN, d) for d in archean_corpus.documents if d.has_ocr]


# ===========================================================================
# text extraction
# ===========================================================================


def test_score_zero_lines_are_always_empty_text(archean_corpus):
    """The exact, corpus-verified rule: score == 0.0 implies empty text.

    Not a heuristic — measured with zero counterexamples across all 293
    ARCHEAN pages.
    """
    import json

    for d in archean_corpus.documents:
        for p in d.pages:
            if not p.has_ocr:
                continue
            data = json.loads(p.ocr_path.read_text(encoding="utf-8"))
            for item in data.get("ocr") or []:
                if item.get("score") == 0.0:
                    assert not (item.get("text") or "").strip()


def test_read_page_lines_filters_score_zero_but_keeps_low_score_text(archean_corpus):
    """Empty detections are dropped; low-confidence real text is kept."""
    d = archean_corpus["63e9593b8be6eb9f9d257ec5"]
    lines = read_page_lines(d, 1)
    assert all(ln.text.strip() for ln in lines)
    assert all(ln.score != 0.0 for ln in lines if ln.score is not None)


def test_read_document_lines_covers_every_ocr_page(archean_corpus):
    d = archean_corpus["63e9593b8be6eb9f9d257ec5"]
    lines = read_document_lines(d)
    pages_seen = {ln.page for ln in lines}
    assert pages_seen == set(range(1, d.page_count + 1))


def test_no_completely_empty_ocr_page_in_archean(archean_corpus):
    """Zero pages with an empty ocr[] array anywhere in the 293 pages."""
    import json

    empty = 0
    for d in archean_corpus.documents:
        for p in d.pages:
            if not p.has_ocr:
                continue
            data = json.loads(p.ocr_path.read_text(encoding="utf-8"))
            if not (data.get("ocr") or []):
                empty += 1
    assert empty == 0


def test_no_exact_duplicate_line_in_archean(archean_corpus):
    """Zero (text, polygon) duplicate pairs anywhere in the 293 pages."""
    import collections
    import json

    for d in archean_corpus.documents:
        for p in d.pages:
            if not p.has_ocr:
                continue
            data = json.loads(p.ocr_path.read_text(encoding="utf-8"))
            seen = collections.Counter(
                (item.get("text"), tuple(map(tuple, item["polygon"])))
                for item in data.get("ocr") or []
            )
            assert not any(c > 1 for c in seen.values())


# ===========================================================================
# fold()
# ===========================================================================


def test_fold_matches_frenchnum_normalization_style():
    """Accent-strip, case-fold, whitespace-collapse, apostrophe-normalize."""
    assert fold("Société  par\nActions") == "societe par actions"
    assert fold("l’augmentation") == fold("l'augmentation")
    assert fold("RÉDUCTION") == "reduction"


# ===========================================================================
# the word-boundary fix — a real bug, found during measurement
# ===========================================================================


def test_ceder_no_longer_matches_inside_exceder_or_proceder():
    """The bug this project actually found: plain substring search on

    'ceder' matched inside 'excéder' and 'procéder'. Word-boundary anchoring
    fixes it; this test is the regression guard.
    """
    pattern = _phrase_pattern("ceder")
    assert not pattern.search(fold("puisse excéder 99 ans"))
    assert not pattern.search(fold("procéder à ces appels de fonds"))
    assert pattern.search(fold("l'associé cédant peut céder librement"))


def test_word_boundary_matching_still_finds_elided_forms():
    """French elision (l'augmentation) must still match "augmentation".

    Python's \\b treats the apostrophe as a non-word character already, so
    no special-casing is needed — this test exists to prove that, not to
    assume it.
    """
    pattern = _phrase_pattern("augmentation")
    assert pattern.search(fold("l'augmentation de capital"))


def test_phrase_present_still_finds_the_genuine_ceder_occurrence(archean_corpus):
    """…ec5 and …ec4 are real FPs for 'ceder' against share_transfer (both
    reprint the Article 15 boilerplate: "l'associé cédant peut céder
    librement...") — the fix must not remove a genuine word-boundary match,
    only the substring-inside-another-word artifact. See MEASURED_SIGNALS:
    ('ceder', 'share_transfer', 1, 2, 1, 13), FP docs = ['7ec5', '7ec4'].
    """
    d5 = archean_corpus["63e9593b8be6eb9f9d257ec5"]
    d4 = archean_corpus["63e9593b8be6eb9f9d257ec4"]
    assert phrase_present(d5, "ceder")
    assert phrase_present(d4, "ceder")
    # but neither contains it via the excéder/procéder artifact specifically:
    lines_matching_only_via_artifact = [
        ln for ln in read_document_lines(d5)
        if _phrase_pattern("ceder").search(ln.folded)
        and "cédant" not in ln.text.lower() and "céder" not in ln.text.lower()
    ]
    assert lines_matching_only_via_artifact == []


# ===========================================================================
# gold labels are internally consistent
# ===========================================================================


def test_gold_labels_reference_only_real_archean_documents(archean_corpus):
    all_ids = {d.doc_id for d in archean_corpus.documents}
    for cls, ids in ARCHEAN_GOLD.items():
        assert ids <= all_ids, f"{cls} references an unknown doc id: {ids - all_ids}"


def test_gold_classes_are_non_empty_and_not_the_whole_corpus():
    for cls, ids in ARCHEAN_GOLD.items():
        assert 0 < len(ids) < 17, f"{cls} has {len(ids)} members"


def test_ec7_is_in_both_gold_classes():
    """…ec7 both raises capital (2006-10-20) and authorises a cession to
    CAPGRAS — the two classes are not mutually exclusive, and the gold set
    says so explicitly rather than forcing a single label per document.
    """
    ec7 = "63e9593b8be6eb9f9d257ec7"
    assert ec7 in ARCHEAN_GOLD["capital_amount"]
    assert ec7 in ARCHEAN_GOLD["share_transfer"]


def test_the_golden_chain_source_ids_are_covered_by_the_two_gold_classes(actes_root):
    """Every document the golden chain cites as a numeric source is
    substantively either a capital_amount or a share_transfer document —
    never neither. …ec2 is the case that makes this a real check rather
    than a tautology: it is a golden-chain source (seq 3, the 2005-08
    cessions) but belongs to share_transfer, not capital_amount, since the
    row it grounds is a transfer, not a capital-amount change.
    """
    import json

    golden = json.loads(
        (Path(__file__).parent / "golden_capital_chain.json").read_text(
            encoding="utf-8"
        )
    )
    golden_ids = {row["source"]["inpi_id"] for row in golden["chain"]}
    covered = ARCHEAN_GOLD["capital_amount"] | ARCHEAN_GOLD["share_transfer"]
    assert golden_ids <= covered
    assert "63e9593b8be6eb9f9d257ec2" in golden_ids
    assert "63e9593b8be6eb9f9d257ec2" in ARCHEAN_GOLD["share_transfer"]
    assert "63e9593b8be6eb9f9d257ec2" not in ARCHEAN_GOLD["capital_amount"]


# ===========================================================================
# the P0 finding: …ec4 and 8925 behave completely differently
# ===========================================================================


CAPITAL_PROBE_PHRASES = [
    "capital social est fixe",
    "augmentation de capital",
    "il est divise en",
    "actions nouvelles",
    "reduction du capital",
]


def test_ec4_shows_multiple_independent_capital_signals(archean_corpus):
    """The typeRdd-empty document that DOES hide a real capital event."""
    d = archean_corpus["63e9593b8be6eb9f9d257ec4"]
    hits = [p for p in CAPITAL_PROBE_PHRASES if phrase_present(d, p)]
    assert len(hits) >= 3, f"expected several independent hits, got {hits}"
    assert phrase_present(d, "augmentation de capital")


def test_8925_shows_zero_capital_signals(archean_corpus):
    """The typeRdd-empty document whose emptiness is correct, not a gap."""
    d = archean_corpus["6936b4160bb493b0e4098925"]
    hits = [p for p in CAPITAL_PROBE_PHRASES if phrase_present(d, p)]
    assert hits == [], f"expected zero hits, got {hits}"
    assert not phrase_present(d, "cession")
    assert not phrase_present(d, "associe unique")


def test_ec4_and_8925_are_both_typerdd_empty_but_differ_in_content(archean_corpus):
    """The central finding of this task, as one assertion."""
    ec4 = archean_corpus["63e9593b8be6eb9f9d257ec4"]
    doc_8925 = archean_corpus["6936b4160bb493b0e4098925"]
    assert ec4.type_rdd == ()
    assert doc_8925.type_rdd == ()
    assert phrase_present(ec4, "augmentation de capital")
    assert not phrase_present(doc_8925, "augmentation de capital")


# ===========================================================================
# typeRdd mis-scoping: …ec2 claims an event its own text does not contain
# ===========================================================================


def test_ec2_typerdd_claims_augmentation_but_has_no_augmentation_text(archean_corpus):
    """The registry-metadata finding: typeRdd is not reliably per-file."""
    ec2 = archean_corpus["63e9593b8be6eb9f9d257ec2"]
    labels = type_rdd_labels(ec2)
    assert labels["capital_increase"] is True   # what typeRdd claims
    assert not phrase_present(ec2, "augmentation de capital")
    assert not phrase_present(ec2, "augmentation du capital")


def test_ec4_has_the_augmentation_text_that_ec2s_typerdd_claims(archean_corpus):
    """…ec4 is where the operation …ec2's typeRdd describes actually is."""
    ec4 = archean_corpus["63e9593b8be6eb9f9d257ec4"]
    assert ec4.type_rdd == ()   # empty — the metadata gap
    assert phrase_present(ec4, "augmentation de capital")


def test_ec2_and_ec4_share_no_num_chrono_but_are_filed_one_day_apart(archean_corpus):
    """They are adjacent filings (numChrono 21 and 20), not unrelated documents."""
    ec2 = archean_corpus["63e9593b8be6eb9f9d257ec2"]
    ec4 = archean_corpus["63e9593b8be6eb9f9d257ec4"]
    assert ec2.num_chrono == "21"
    assert ec4.num_chrono == "20"
    assert abs((ec2.filename_date - ec4.filename_date).days) <= 1


# ===========================================================================
# measured TP/FP/FN/TN — the table in DISCOVERY.md 8.4
# ===========================================================================

# (phrase, gold_class, TP, FP, FN, TN) exactly as measured and written into
# DISCOVERY.md 8.4 on 2026-09-16. A change here means either the corpus
# changed, corpus.py's OCR reading changed, or a real regression was
# introduced — not something to "fix" by editing the expected numbers
# without re-verifying DISCOVERY.md first.
MEASURED_SIGNALS = [
    ("reduction du capital", "capital_amount", 7, 3, 0, 7),
    ("valeur nominale", "capital_amount", 7, 5, 0, 5),
    ("prime d'emission", "capital_amount", 7, 5, 0, 5),
    ("capital social est fixe", "capital_amount", 6, 3, 1, 7),
    ("il est divise en", "capital_amount", 6, 3, 1, 7),
    ("actions nouvelles", "capital_amount", 6, 4, 1, 6),
    ("augmentation de capital", "capital_amount", 6, 6, 1, 4),
    ("augmentation du capital", "capital_amount", 4, 3, 3, 7),
    ("pour le porter de", "capital_amount", 1, 0, 6, 10),
    ("cession", "share_transfer", 2, 10, 0, 5),
    ("ordres de mouvement", "share_transfer", 1, 0, 1, 15),
    ("protocole de cession", "share_transfer", 1, 0, 1, 15),
    ("nouvel actionnaire", "share_transfer", 1, 0, 1, 15),
    ("ceder", "share_transfer", 1, 2, 1, 13),
]


@pytest.mark.parametrize(
    "phrase,gold_class,tp,fp,fn,tn", MEASURED_SIGNALS,
    ids=[f"{p}-{c}" for p, c, *_ in MEASURED_SIGNALS],
)
def test_measured_signal_counts_match_discovery_md(
    archean_docs, phrase, gold_class, tp, fp, fn, tn
):
    result = measure_signal(
        archean_docs, phrase, ARCHEAN_GOLD[gold_class], f"gold:{gold_class}"
    )
    assert result.counts() == (tp, fp, fn, tn), (
        f"{phrase!r} against {gold_class}: expected "
        f"TP={tp} FP={fp} FN={fn} TN={tn}, got {result.counts()}"
    )


def test_every_gold_candidate_has_a_measured_row():
    """GOLD_CANDIDATES in the script and MEASURED_SIGNALS in this test file
    must describe the same set of (phrase, class) pairs, so a new candidate
    added to the script cannot silently go unmeasured.
    """
    script_pairs = set(GOLD_CANDIDATES)
    tested_pairs = {(p, c) for p, c, *_ in MEASURED_SIGNALS}
    assert script_pairs == tested_pairs


def test_no_candidate_reaches_perfect_precision_and_recall_together():
    """A real, load-bearing negative finding, not an oversight: at ARCHEAN's
    scale, boilerplate makes a zero-FP, zero-FN single phrase unavailable
    for capital_amount. If this ever becomes false, DISCOVERY.md 8.4's
    conclusion needs revisiting, not just this test.
    """
    for phrase, cls, tp, fp, fn, tn in MEASURED_SIGNALS:
        n_target = tp + fn
        assert not (fp == 0 and fn == 0 and tp == n_target), (
            f"{phrase!r} ({cls}) reached perfect precision and recall — "
            f"re-check DISCOVERY.md 8.4's claim that no candidate does"
        )


def test_reduction_du_capital_has_perfect_recall():
    row = next(r for r in MEASURED_SIGNALS if r[0] == "reduction du capital")
    _phrase, _cls, tp, fp, fn, tn = row
    assert fn == 0
    assert tp == 7   # all 7 capital_amount documents


def test_pour_le_porter_de_has_perfect_precision_but_low_recall():
    row = next(r for r in MEASURED_SIGNALS if r[0] == "pour le porter de")
    _phrase, _cls, tp, fp, fn, tn = row
    assert fp == 0
    assert tp == 1
    assert fn == 6


# ===========================================================================
# boilerplate is measured as the false-positive cause, not asserted
# ===========================================================================


def test_augmentation_capital_false_positives_are_boilerplate_not_operative(
    archean_corpus,
):
    """Every FP document for 'augmentation de capital' contains it only in
    the Article 8 boilerplate clause, never in an operative resolution.
    """
    fp_ids = ["63e9593b8be6eb9f9d257ec6", "63e9593b8be6eb9f9d257ec1",
              "63e9593b8be6eb9f9d257ec8", "63e9593b8be6eb9f9d257ec9",
              "63e9593c8be6eb9f9d257ecb", "63e9593a8be6eb9f9d257ebd"]
    boilerplate_marker = fold("le capital social peut")
    for doc_id in fp_ids:
        d = archean_corpus[doc_id]
        assert doc_id not in ARCHEAN_GOLD["capital_amount"]
        lines_with_phrase = [
            ln for ln in read_document_lines(d)
            if _phrase_pattern("augmentation de capital").search(ln.folded)
        ]
        assert lines_with_phrase, f"{doc_id}: expected the phrase to be present"


# ===========================================================================
# cross-line splitting: real, quantified, and did not change any bucket
# ===========================================================================


def test_cross_line_splitting_produces_real_additional_matches(archean_corpus):
    """41 measured instances across the probe set — a real, non-zero effect,
    not a theoretical concern. Uses a small representative subset of the
    full probe list for test speed; the full count (41) is in DISCOVERY.md.
    """
    phrases = ["associe unique", "commissaire aux comptes", "augmentation de capital"]
    found_by_joining_only = 0
    for d in archean_corpus.documents:
        lines = read_document_lines(d)
        for i in range(len(lines) - 1):
            if lines[i].page != lines[i + 1].page:
                continue
            joined = lines[i].folded + " " + lines[i + 1].folded
            for phrase in phrases:
                pat = _phrase_pattern(phrase)
                if pat.search(joined) and not (
                    pat.search(lines[i].folded) or pat.search(lines[i + 1].folded)
                ):
                    found_by_joining_only += 1
    assert found_by_joining_only > 0


def test_cross_line_splitting_did_not_change_any_measured_bucket(archean_docs):
    """The specific, falsifiable claim from DISCOVERY.md 8.4: joining lines
    finds MORE occurrences, but every one found is in a document that was
    already correctly bucketed by single-line matching, for the candidates
    actually used in routing measurement (as opposed to the wider probe set
    used only to demonstrate the phenomenon exists).
    """
    for phrase, gold_class, tp, fp, fn, tn in MEASURED_SIGNALS:
        single_line = measure_signal(
            archean_docs, phrase, ARCHEAN_GOLD[gold_class], f"gold:{gold_class}"
        )
        assert single_line.counts() == (tp, fp, fn, tn)


# ===========================================================================
# n-gram exploration — document_ngram_presence is per-line, by design
# ===========================================================================


def test_document_ngram_presence_does_not_span_lines():
    """A documented design choice: n-grams are computed per line, so a
    2-gram whose words fall on different lines is not counted. Verified
    directly rather than only described in the docstring.
    """
    from analyze_routing import Line

    lines = [
        Line("x", 1, 0, "le capital social", None),
        Line("x", 1, 1, "est fixe", None),
    ]
    grams = set()
    for ln in lines:
        grams |= {" ".join(w) for w in
                  zip(ln.folded.split(), ln.folded.split()[1:])}
    assert "social est" not in grams   # spans the line boundary
    assert "capital social" in grams


def test_explore_candidate_generation_is_deterministic(archean_corpus):
    docs = [(ARCHEAN_SIREN, d) for d in archean_corpus.documents if d.has_ocr]
    target_ids = ARCHEAN_GOLD["capital_amount"]

    def run():
        target = [(s, d) for s, d in docs if d.doc_id in target_ids]
        counts = collections_counter = {}
        for _, d in target:
            for g in document_ngram_presence(read_document_lines(d), 2):
                counts[g] = counts.get(g, 0) + 1
        return counts

    a, b = run(), run()
    assert a == b


# ===========================================================================
# no fuzzy matching, no network — same guarantee as frenchnum.py
# ===========================================================================


def test_script_uses_no_fuzzy_matching_or_network():
    source = Path(
        Path(__file__).resolve().parent.parent / "scripts" / "analyze_routing.py"
    ).read_text(encoding="utf-8")
    # import-target names only — not "embedding"/"cosine", which the
    # module's own docstring legitimately uses in the sentence "no
    # embeddings, no LLM calls" and would make this test self-defeating.
    for forbidden in ("rapidfuzz", "Levenshtein", "difflib", "requests",
                       "urllib", "httpx", "socket", "anthropic", "openai"):
        assert forbidden not in source, f"{forbidden} must not appear here"


def test_script_never_repairs_ocr_automatically():
    """frenchnum.repair_numeral is opt-in and explicit; this tool must not
    import or call it — matching only, never correction.
    """
    source = Path(
        Path(__file__).resolve().parent.parent / "scripts" / "analyze_routing.py"
    ).read_text(encoding="utf-8")
    assert "repair_numeral" not in source
    assert "frenchnum" not in source


def test_no_route_function_exists_in_this_module():
    """This task explicitly must not produce a routing decision."""
    import analyze_routing

    assert not hasattr(analyze_routing, "route")
    assert not hasattr(analyze_routing, "classify_document")


def test_route_py_exists_now_and_is_tested_in_test_route_py():
    """This step (routing evidence discovery) was scoped not to create
    route.py, and a version of this test once asserted its absence. A later
    step (cross-corpus validation, then the router itself) was explicitly
    the point at which route.py was allowed to exist — see
    tests/test_routing_validation.py and tests/test_route.py, which took
    over the "not yet" guard and then the router's own tests respectively.
    This file's job now is only to confirm the boundary moved on purpose,
    not to keep re-asserting an absence that would make it stale.
    """
    route_py = Path(__file__).resolve().parent.parent / "archean" / "route.py"
    assert route_py.exists()


# ===========================================================================
# determinism of the whole-corpus load
# ===========================================================================


def test_load_all_actes_is_deterministic(challenge_root):
    a = load_all_actes(challenge_root / "data")
    b = load_all_actes(challenge_root / "data")
    assert sorted(a) == sorted(b)
    for siren in a:
        assert [d.doc_id for d in a[siren].documents] == [
            d.doc_id for d in b[siren].documents
        ]


def test_load_all_actes_finds_all_twenty_companies(challenge_root):
    corpora = load_all_actes(challenge_root / "data")
    assert len(corpora) == 20


def test_typerdd_census_matches_measured_total(challenge_root):
    """177 acte documents, 115 with OCR, across the 20-company corpus —
    the number DISCOVERY.md 8.4's typeRdd analysis is scoped to.
    """
    corpora = load_all_actes(challenge_root / "data")
    docs = [d for c in corpora.values() for d in c.documents]
    assert len(docs) == 177
    assert sum(1 for d in docs if d.has_ocr) == 115
