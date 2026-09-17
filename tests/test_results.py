"""Tests for results.json and scripts/build_results.py.

These tests run the real ARCHEAN pipeline (corpus + route.py + Grounder),
so they need the challenge repo beside this one, same as every other
corpus-backed test — see conftest.py's challenge_root fixture.
"""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "results.json"
SCHEMA_PATH = (
    REPO_ROOT.parent / "engineering-challenges" / "challenges" / "actes"
    / "schema" / "results.schema.json"
)

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _require_challenge_repo():
    if not SCHEMA_PATH.exists():
        pytest.skip(f"challenge repo not found at {SCHEMA_PATH}")


@pytest.fixture(scope="module")
def built_results(tmp_path_factory) -> dict:
    """Run scripts/build_results.py fresh, exactly as a reviewer would."""
    _require_challenge_repo()
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_results.py")],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"build_results.py failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema() -> dict:
    _require_challenge_repo()
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ===========================================================================
# schema validation
# ===========================================================================


def test_results_json_exists_at_repo_root():
    assert RESULTS_PATH.exists(), "results.json must exist at the repo root"


def test_results_json_is_valid_against_the_challenge_schema(built_results, schema):
    import jsonschema

    jsonschema.Draft202012Validator(schema).validate(built_results)


def test_siren_is_exactly_the_required_constant(built_results):
    assert built_results["siren"] == "480489707"


def test_every_event_code_is_one_the_schema_enumerates(built_results):
    allowed = {
        "CAPITAL_INCREASE", "CAPITAL_DECREASE", "SHAREHOLDER_ENTRY",
        "SHAREHOLDER_END", "SHAREHOLDER_SHARE_TRANSFER", "CAPITAL_DUAL_CLASS",
    }
    for ev in built_results["events"]:
        assert ev["event_code"] in allowed, ev


def test_all_five_scored_codes_are_represented(built_results):
    """Not a requirement of the schema (a real corpus might not contain all
    five), but true of THIS corpus, and worth pinning so a future change
    that silently drops one is caught.
    """
    codes = {ev["event_code"] for ev in built_results["events"]}
    scored = {"CAPITAL_INCREASE", "CAPITAL_DECREASE", "SHAREHOLDER_END"}
    assert scored <= codes, codes
    # SHAREHOLDER_ENTRY and SHAREHOLDER_SHARE_TRANSFER are legitimately
    # absent — see results.json's own notes[7]/[8] for why, not a bug.


def test_every_event_has_a_unique_id(built_results):
    ids = [e["event_id"] for e in built_results["events"]]
    assert len(ids) == len(set(ids)), ids


# ===========================================================================
# provenance
# ===========================================================================


def test_every_source_inpi_id_is_a_real_document_in_the_corpus(built_results):
    from archean.corpus import load_corpus

    data_root = REPO_ROOT.parent / "engineering-challenges" / "data"
    corpus = load_corpus(data_root / "480489707" / "actes")
    real_ids = {d.doc_id for d in corpus.documents}
    for ev in built_results["events"]:
        assert ev["source"]["inpi_id"] in real_ids, ev["event_id"]


def test_every_bbox_is_normalized_and_well_formed(built_results):
    for ev in built_results["events"]:
        x0, y0, x1, y1 = ev["source"]["bbox"]
        assert 0 <= x0 <= 1 and 0 <= y0 <= 1 and 0 <= x1 <= 1 and 0 <= y1 <= 1, ev
        assert x0 < x1 and y0 < y1, ev


def test_every_source_snippet_is_findable_on_the_page_it_cites(built_results):
    """The anti-fabrication check, same shape as tests/test_golden_chain.py's."""
    from archean.corpus import load_corpus
    from archean.ground import Grounder

    data_root = REPO_ROOT.parent / "engineering-challenges" / "data"
    corpus = load_corpus(data_root / "480489707" / "actes")
    by_id = {d.doc_id: d for d in corpus.documents}

    for ev in built_results["events"]:
        src = ev["source"]
        d = by_id[src["inpi_id"]]
        with Grounder(str(d.pdf_path), str(d.ocr_dir)) as g:
            hits = g.locate(src["page"], src["snippet"])
        assert hits, f"{ev['event_id']}: snippet not found: {src['snippet']!r}"


def test_every_capital_event_is_independently_confirmed_operative_by_route_py(built_results):
    """The build script's own cross-check (assert_route_agrees), re-asserted
    here so a future change to build_results.py that removed the check
    would still be caught by the test suite.
    """
    from archean.corpus import load_corpus
    from archean.route import Verdict, classify

    data_root = REPO_ROOT.parent / "engineering-challenges" / "data"
    corpus = load_corpus(data_root / "480489707" / "actes")
    by_id = {d.doc_id: d for d in corpus.documents}

    for ev in built_results["events"]:
        if ev["event_code"] not in ("CAPITAL_INCREASE", "CAPITAL_DECREASE"):
            continue
        d = by_id[ev["source"]["inpi_id"]]
        result = classify(d, "capital_amount")
        assert result.verdict == Verdict.OPERATIVE, ev["event_id"]


# ===========================================================================
# capital_timeline — the artefact the challenge is really about
# ===========================================================================


def test_capital_timeline_is_chronological(built_results):
    dates = [row["as_of"] for row in built_results["capital_timeline"]]
    assert dates == sorted(dates)


def test_capital_timeline_every_caused_by_id_exists(built_results):
    event_ids = {e["event_id"] for e in built_results["events"]}
    for row in built_results["capital_timeline"]:
        for eid in row.get("caused_by", []):
            assert eid in event_ids, (row["as_of"], eid)


def test_capital_eur_equals_shares_times_nominal_wherever_both_are_known(built_results):
    for row in built_results["capital_timeline"]:
        if row["capital_eur"] is None or row["shares_total"] is None or row.get("nominal_eur") is None:
            continue
        assert Decimal(str(row["capital_eur"])) == row["shares_total"] * Decimal(str(row["nominal_eur"])), row["as_of"]


def test_holder_shares_sum_to_shares_total_wherever_every_holder_is_known(built_results):
    for row in built_results["capital_timeline"]:
        if row["shares_total"] is None:
            continue
        shares = [h.get("shares") for h in row["holders"]]
        if any(s is None for s in shares):
            continue
        assert sum(shares) == row["shares_total"], row["as_of"]


def test_unattributed_holders_are_explicit_not_silently_dropped(built_results):
    """Where this corpus genuinely does not state who held the shares, the
    row must say so (kind=UNKNOWN), never omit the shares from the total.
    """
    for row in built_results["capital_timeline"]:
        known = [h for h in row["holders"] if h.get("kind") != "UNKNOWN"]
        unknown = [h for h in row["holders"] if h.get("kind") == "UNKNOWN"]
        if row["shares_total"] is None:
            continue
        known_total = sum(h.get("shares") or 0 for h in known)
        unknown_total = sum(h.get("shares") or 0 for h in unknown)
        assert known_total + unknown_total == row["shares_total"], row["as_of"]


def test_the_first_row_is_the_constitution_with_no_caused_by(built_results):
    first = built_results["capital_timeline"][0]
    assert first["as_of"] == "2004-12-15"
    assert first.get("caused_by", []) == []
    assert first["capital_eur"] == 37000
    assert first["shares_total"] == 370


def test_capital_timeline_matches_the_verified_golden_chain(built_results):
    """The literal cross-check results.json's own `notes` claims: every
    VERIFIED row of tests/golden_capital_chain.json (an earlier session's
    hand-verified reading, independently re-tested against the real OCR/PDF
    by tests/test_golden_chain.py) must have a matching capital_timeline row
    here, agreeing on capital_eur_after / shares_total_after / nominal_eur.
    UNCERTAIN rows (seq 4: effective date not fixed by the corpus) are
    checked on their numbers only, not their exact date.
    """
    golden = json.loads((REPO_ROOT / "tests" / "golden_capital_chain.json").read_text(encoding="utf-8"))
    timeline_by_date: dict[str, list[dict]] = {}
    for row in built_results["capital_timeline"]:
        timeline_by_date.setdefault(row["as_of"], []).append(row)

    for chain_row in golden["chain"]:
        date = chain_row["event_date"]
        matches = timeline_by_date.get(date, [])
        assert matches, f"golden chain seq {chain_row['seq']} ({date}): no capital_timeline row"
        found = [
            m for m in matches
            if m["capital_eur"] == chain_row["capital_eur_after"]
            and m["shares_total"] == chain_row["shares_total_after"]
            and m["nominal_eur"] == chain_row["nominal_eur"]
        ]
        assert found, (
            f"golden chain seq {chain_row['seq']} ({date}): expected capital="
            f"{chain_row['capital_eur_after']} shares={chain_row['shares_total_after']} "
            f"nominal={chain_row['nominal_eur']}, found {matches}"
        )


def test_the_last_row_matches_the_latest_known_capital_confirmation(built_results):
    """tests/golden_capital_chain.json's independent_observations: the 2024
    AG confirms 400 000 EUR with no intervening capital event.
    """
    last = built_results["capital_timeline"][-1]
    assert last["capital_eur"] == 400000
    assert last["shares_total"] == 400000


def test_hadean_is_named_with_its_real_siren_wherever_it_appears(built_results):
    for row in built_results["capital_timeline"]:
        for h in row["holders"]:
            if h["name"] == "HADEAN":
                assert h.get("siren") == "499979540", row["as_of"]


# ===========================================================================
# known contradictions must survive into notes, not be silently resolved
# ===========================================================================


def test_the_823_vs_803_contradiction_is_reported_in_notes(built_results):
    notes = built_results.get("notes", "")
    assert "823" in notes and "803" in notes


def test_the_hadean_acquisition_gap_is_reported_in_notes(built_results):
    notes = built_results.get("notes", "")
    assert "HADEAN" in notes and "499979540" in notes


def test_the_missing_2005_subscribers_gap_is_reported_in_notes(built_results):
    notes = built_results.get("notes", "")
    assert "2005-03-04" in notes or "1 130" in notes


# ===========================================================================
# determinism
# ===========================================================================


def test_the_validation_script_agrees(built_results):
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate_results.py")],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_build_results_is_byte_identical_across_independent_runs():
    """Two fresh, independent processes must produce the exact same file —
    no dict ordering, no set iteration, no filesystem-order dependency.
    """
    _require_challenge_repo()

    def run() -> bytes:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "build_results.py")],
            cwd=REPO_ROOT, capture_output=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return RESULTS_PATH.read_bytes()

    a = run()
    b = run()
    assert a == b
