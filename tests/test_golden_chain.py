"""Structural checks on tests/golden_capital_chain.json.

The golden chain is the oracle the extraction pipeline will be measured
against. It is hand-built from documents, so nothing here regenerates it —
these tests only assert that it is internally coherent and that every claim in
it still points at a real place in a real document.

If one of these fails, the golden file is wrong and must be fixed by re-reading
the document, never by relaxing the test.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from archean.ground import Grounder, normalize_text, validate_bbox
from conftest import ocr_for, pdf_for

GOLDEN_PATH = Path(__file__).resolve().parent / "golden_capital_chain.json"

VALID_STATUS = {"VERIFIED", "UNCERTAIN", "UNSUPPORTED"}
VALID_HOLDER_STATUS = {
    "VERIFIED", "UNSUPPORTED", "PARTIAL", "VERIFIED_BUT_CONTRADICTED",
}


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def chain(golden) -> list[dict]:
    return golden["chain"]


def all_sources(golden) -> list[tuple[str, dict]]:
    """Every source block in the file, labelled by where it came from."""
    out = []
    for row in golden["chain"]:
        out.append((f"chain seq {row['seq']} source", row["source"]))
        for i, c in enumerate(row.get("corroboration", [])):
            out.append((f"chain seq {row['seq']} corroboration[{i}]", c))
    for i, obs in enumerate(golden.get("independent_observations", [])):
        out.append((f"observation[{i}] source", obs["source"]))
    return out


# ---------------------------------------------------------------------------
# it is valid, well-formed JSON with the shape we said it has
# ---------------------------------------------------------------------------


def test_golden_file_is_valid_json(golden):
    assert isinstance(golden, dict)
    assert golden["chain"], "chain is empty"


def test_golden_file_declares_it_is_not_an_answer_key(golden):
    """Guards against the file being mistaken for ground truth later."""
    about = golden["_about"]
    blob = " ".join(about["what_this_is_NOT"]).lower()
    assert "not an answer key" in blob
    assert "not results.json" in blob


def test_every_row_has_the_required_fields(chain):
    required = {
        "seq", "event_date", "event_date_basis", "operation",
        "capital_eur_after", "shares_total_after", "nominal_eur",
        "holders", "holders_status", "status", "source",
    }
    for row in chain:
        missing = required - row.keys()
        assert not missing, f"seq {row.get('seq')} missing {sorted(missing)}"


def test_status_values_are_from_the_declared_legend(golden, chain):
    legend = set(golden["_about"]["legend"])
    assert legend == VALID_STATUS
    for row in chain:
        assert row["status"] in VALID_STATUS, row["seq"]
        assert row["holders_status"] in VALID_HOLDER_STATUS, row["seq"]


def test_sequence_numbers_are_unique_and_contiguous(chain):
    seqs = [r["seq"] for r in chain]
    assert seqs == sorted(seqs), "rows are out of order"
    assert len(set(seqs)) == len(seqs), f"duplicate seq: {Counter(seqs)}"
    assert seqs == list(range(1, len(seqs) + 1))


def test_dates_are_iso_and_non_decreasing(chain):
    import datetime as dt

    dates = []
    for row in chain:
        d = dt.date.fromisoformat(row["event_date"])  # raises if malformed
        dates.append(d)
    assert dates == sorted(dates), "event dates are not chronological"


def test_no_accidental_duplicate_rows(chain):
    """Same date + same operation + same delta twice is a double-count."""
    seen = Counter(
        (r["event_date"], r["operation"], r["delta_capital_eur"])
        for r in chain
    )
    dupes = {k: n for k, n in seen.items() if n > 1}
    assert not dupes, f"duplicated rows: {dupes}"


# ---------------------------------------------------------------------------
# the arithmetic the file claims to satisfy
# ---------------------------------------------------------------------------


def test_capital_equals_shares_times_nominal(chain):
    for row in chain:
        assert row["capital_eur_after"] == row["shares_total_after"] * row["nominal_eur"], (
            f"seq {row['seq']}: {row['capital_eur_after']} != "
            f"{row['shares_total_after']} * {row['nominal_eur']}"
        )


def test_each_delta_carries_the_capital_forward(chain):
    prev = None
    for row in chain:
        if prev is not None:
            delta = row["delta_capital_eur"] or 0
            assert prev + delta == row["capital_eur_after"], (
                f"seq {row['seq']}: {prev} + {delta} != "
                f"{row['capital_eur_after']}"
            )
        prev = row["capital_eur_after"]


def test_holder_shares_sum_to_the_total_where_holders_are_known(chain):
    for row in chain:
        holders = row["holders"]
        if not holders:
            continue
        total = sum(h["shares"] for h in holders)
        assert total == row["shares_total_after"], (
            f"seq {row['seq']}: holders sum to {total}, "
            f"shares_total_after is {row['shares_total_after']}"
        )


def test_shares_are_integers_and_capital_is_exact(chain):
    for row in chain:
        assert isinstance(row["shares_total_after"], int), row["seq"]
        assert not isinstance(row["capital_eur_after"], float), (
            f"seq {row['seq']}: capital must not be a float literal"
        )
        for h in row["holders"] or []:
            assert isinstance(h["shares"], int), (row["seq"], h["name"])


def test_unsupported_holders_are_null_not_guessed(chain):
    """The whole point: absence is recorded as absence."""
    for row in chain:
        if row["holders_status"] == "UNSUPPORTED":
            assert row["holders"] is None, (
                f"seq {row['seq']} is UNSUPPORTED but carries holder data"
            )


def test_uncertain_rows_explain_themselves(chain):
    for row in chain:
        if row["status"] == "UNCERTAIN":
            assert row.get("status_note"), (
                f"seq {row['seq']} is UNCERTAIN with no status_note"
            )


def test_unresolved_questions_are_recorded(golden):
    assert len(golden["unresolved"]) >= 5, (
        "the corpus has several genuine gaps; they must stay listed"
    )


# ---------------------------------------------------------------------------
# provenance: every source is well-formed
# ---------------------------------------------------------------------------


def test_every_source_has_inpi_id_page_and_bbox(golden):
    for label, src in all_sources(golden):
        assert src.get("inpi_id"), f"{label}: no inpi_id"
        assert len(src["inpi_id"]) == 24, (
            f"{label}: inpi_id {src['inpi_id']!r} is not 24 characters"
        )
        assert isinstance(src.get("page"), int), f"{label}: page not an int"
        assert src["page"] >= 1, f"{label}: page {src['page']} is not 1-indexed"
        assert "bbox" in src, f"{label}: no bbox"
        assert src.get("snippet"), f"{label}: no snippet"


def test_every_bbox_is_structurally_valid(golden):
    for label, src in all_sources(golden):
        problems = validate_bbox(src["bbox"])
        assert not problems, f"{label}: {problems}"


# ---------------------------------------------------------------------------
# provenance: every source points at text that is really there
# ---------------------------------------------------------------------------


def test_every_cited_document_and_page_exists(golden, actes_root):
    for label, src in all_sources(golden):
        pdf_path = pdf_for(actes_root, src["inpi_id"])
        with Grounder(
            str(pdf_path), str(ocr_for(actes_root, src["inpi_id"]))
        ) as g:
            assert src["page"] <= g.page_count, (
                f"{label}: cites page {src['page']} of a "
                f"{g.page_count}-page document"
            )


def test_every_snippet_is_findable_on_the_page_it_cites(golden, actes_root):
    """The anti-fabrication check.

    Every snippet in the golden file must occur, verbatim modulo accents and
    whitespace, in the OCR of exactly the page cited. A snippet that cannot be
    found is either a typo or an invention; both are failures.
    """
    for label, src in all_sources(golden):
        with Grounder(
            str(pdf_for(actes_root, src["inpi_id"])),
            str(ocr_for(actes_root, src["inpi_id"])),
        ) as g:
            hits = g.locate(src["page"], src["snippet"])
        assert hits, (
            f"{label}: snippet not found on page {src['page']} of "
            f"{src['inpi_id']}\n  snippet: {src['snippet']!r}"
        )


def test_every_bbox_matches_the_line_its_snippet_came_from(golden, actes_root):
    """The box must point at the quoted text, not merely be on the right page."""
    for label, src in all_sources(golden):
        with Grounder(
            str(pdf_for(actes_root, src["inpi_id"])),
            str(ocr_for(actes_root, src["inpi_id"])),
        ) as g:
            hits = g.locate(src["page"], src["snippet"])
        assert hits, f"{label}: snippet not found"
        recomputed = [h[1].rounded(4) for h in hits]
        assert any(
            all(abs(a - b) <= 1e-4 for a, b in zip(src["bbox"], box))
            for box in recomputed
        ), (
            f"{label}: recorded bbox {src['bbox']} does not match any line "
            f"containing the snippet; recomputed {recomputed}"
        )


def test_event_dates_never_postdate_their_deposit(golden, actes_root):
    """A decision cannot be filed before it is taken.

    This is the cheap guard against silently using the filename date as the
    event date: in this corpus the two differ by weeks to months, and an
    event_date later than dateDepot means something was read wrong.
    """
    import datetime as dt

    meta_dir = actes_root / "meta"
    by_id = {}
    for meta_file in meta_dir.glob("*.json"):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        by_id[meta["id"]] = meta

    for row in golden["chain"]:
        inpi_id = row["source"]["inpi_id"]
        meta = by_id.get(inpi_id)
        assert meta, f"seq {row['seq']}: no meta for {inpi_id}"
        deposit = dt.date.fromisoformat(meta["dateDepot"])
        event = dt.date.fromisoformat(row["event_date"])
        assert event <= deposit, (
            f"seq {row['seq']}: event_date {event} is after dateDepot "
            f"{deposit} for {inpi_id}"
        )


def test_event_dates_are_not_just_the_deposit_dates(golden, actes_root):
    """Positive check that we did the harder thing.

    If every event_date equalled its dateDepot we would have taken the easy,
    wrong route. In this corpus the real decision dates are all earlier.
    """
    import datetime as dt

    by_id = {
        json.loads(f.read_text(encoding="utf-8"))["id"]:
        json.loads(f.read_text(encoding="utf-8"))
        for f in (actes_root / "meta").glob("*.json")
    }
    gaps = []
    for row in golden["chain"]:
        meta = by_id[row["source"]["inpi_id"]]
        gap = (
            dt.date.fromisoformat(meta["dateDepot"])
            - dt.date.fromisoformat(row["event_date"])
        ).days
        gaps.append(gap)
    assert all(g > 0 for g in gaps), (
        f"some event_date equals its deposit date, which is almost certainly "
        f"wrong for this corpus: gaps in days = {gaps}"
    )
    assert max(gaps) > 100, "expected at least one multi-month filing gap"


# ---------------------------------------------------------------------------
# the contradictions must survive
# ---------------------------------------------------------------------------


def test_the_823_vs_803_contradiction_is_preserved(golden):
    """Neither reading may be quietly dropped.

    The 2005-08 PV says BLANCO holds 823; the 2006-10 feuille de presence says
    803. Both sum to 1500 with the other holders. No acte reconciles them.
    """
    chain_row = next(r for r in golden["chain"] if r["seq"] == 3)
    blanco = next(
        h for h in chain_row["holders"] if "BLANCO" in h["name"]
    )
    assert blanco["shares"] == 823
    assert chain_row["holders_status"] == "VERIFIED_BUT_CONTRADICTED"

    obs = next(
        o for o in golden["independent_observations"]
        if o.get("observed_on") == "2006-10-20"
    )
    other = next(h for h in obs["holders"] if "BLANCO" in h["name"])
    assert other["shares"] == 803
    assert obs["sums_to"] == 1500

    assert any("823" in u and "803" in u for u in golden["unresolved"])


def test_the_2018_document_typo_is_recorded(golden):
    """185 759 vs 182 759, confirmed by reading the rendered page."""
    row = next(r for r in golden["chain"] if r["seq"] == 9)
    assert row["delta_capital_eur"] == 182759
    note = row["document_internal_error"]
    assert "185 759" in note and "182 759" in note
    assert "not an ocr artefact" in note.lower()


def test_the_percentage_error_in_the_2005_table_is_recorded(golden):
    row = next(r for r in golden["chain"] if r["seq"] == 3)
    assert "6,00" in row["document_internal_error"]
    assert "4,00" in row["document_internal_error"]
