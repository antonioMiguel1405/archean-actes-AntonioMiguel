"""Tests for the OCR-pixel -> normalized-bbox conversion.

The conversion is the graded artefact: a number without a provenance is not
something Takeovers can sell or defend. So it is tested against synthetic cases
with hand-computable answers, against the challenge's own reference
implementation, and against real evidence in the corpus whose boxes were
eyeballed on rendered pages.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from archean.ground import (
    EXACT,
    REFERENCE_FLOAT,
    BBox,
    Grounder,
    GroundingError,
    normalize_text,
    overflows_page,
    polygon_to_bbox,
    union,
    validate_bbox,
)
from conftest import ocr_for, pdf_for

# An A4 page: 595 x 842 pt. At 300 dpi that is 595*300/72 = 2479.166.. px wide
# and 842*300/72 = 3508.333.. px tall.
A4_W_PT, A4_H_PT = 595.0, 842.0
A4_W_PX = A4_W_PT * 300 / 72
A4_H_PX = A4_H_PT * 300 / 72

# One of the older ARCHEAN scans, which are not A4.
OLD_W_PT, OLD_H_PT = 1654.0, 2353.0


def rect(x0: float, y0: float, x1: float, y1: float):
    """A polygon in the shape the OCR ships: four corner points."""
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


# ---------------------------------------------------------------------------
# Case 1 - a simple conversion whose answer can be computed by hand
# ---------------------------------------------------------------------------


def test_case1_simple_known_conversion():
    """A box over the exact middle quarter of an A4 page."""
    poly = rect(A4_W_PX / 4, A4_H_PX / 4, A4_W_PX / 2, A4_H_PX / 2)
    box = polygon_to_bbox(poly, A4_W_PT, A4_H_PT)
    assert box.as_list() == pytest.approx([0.25, 0.25, 0.5, 0.5], abs=1e-12)


def test_case1_half_page_width():
    poly = rect(0.0, 0.0, A4_W_PX / 2, A4_H_PX)
    box = polygon_to_bbox(poly, A4_W_PT, A4_H_PT)
    assert box.as_list() == pytest.approx([0.0, 0.0, 0.5, 1.0], abs=1e-12)


# ---------------------------------------------------------------------------
# Case 2 - top-left corner. Origin is top-left, so this is (0, 0).
# ---------------------------------------------------------------------------


def test_case2_top_left_corner_is_origin():
    poly = rect(0.0, 0.0, 1.0, 1.0)
    box = polygon_to_bbox(poly, A4_W_PT, A4_H_PT)
    assert box.x0 == 0.0
    assert box.y0 == 0.0
    assert box.x1 < 0.001 and box.y1 < 0.001


def test_case2_origin_is_top_left_not_bottom_left():
    """A box near the top of the page must have a SMALL y, not a large one.

    PDF-native coordinates put the origin bottom-left; the submission format
    puts it top-left. Getting this backwards flips every box vertically and is
    the single easiest way to produce boxes that look plausible and point at
    the wrong text.
    """
    near_top = polygon_to_bbox(rect(0, 0, 100, 100), A4_W_PT, A4_H_PT)
    near_bottom = polygon_to_bbox(
        rect(0, A4_H_PX - 100, 100, A4_H_PX), A4_W_PT, A4_H_PT
    )
    assert near_top.y0 < near_bottom.y0
    assert near_top.y1 < 0.05
    assert near_bottom.y0 > 0.95


# ---------------------------------------------------------------------------
# Case 3 - bottom-right corner
# ---------------------------------------------------------------------------


def test_case3_bottom_right_corner_is_one():
    poly = rect(A4_W_PX - 1, A4_H_PX - 1, A4_W_PX, A4_H_PX)
    box = polygon_to_bbox(poly, A4_W_PT, A4_H_PT)
    assert box.x1 == pytest.approx(1.0, abs=1e-12)
    assert box.y1 == pytest.approx(1.0, abs=1e-12)
    assert box.x0 > 0.999 and box.y0 > 0.999


def test_case3_full_page():
    poly = rect(0.0, 0.0, A4_W_PX, A4_H_PX)
    box = polygon_to_bbox(poly, A4_W_PT, A4_H_PT)
    assert box.as_list() == pytest.approx([0.0, 0.0, 1.0, 1.0], abs=1e-12)


def test_case3_beyond_the_page_is_refused():
    """Coordinates well off the page mean the wrong page size was used."""
    poly = rect(0.0, 0.0, A4_W_PX * 1.5, A4_H_PX)
    with pytest.raises(GroundingError, match=r"outside \[0, 1\]"):
        polygon_to_bbox(poly, A4_W_PT, A4_H_PT)


def test_case3_marginal_overflow_is_clamped_not_refused():
    """OCR at the page edge overflows by a hair; that must not be fatal.

    results.schema.json constrains bbox values to [0, 1], so a raw 1.00008
    would make the whole submission invalid. Clamping keeps it submittable.
    """
    # shaped like the real cases: a small mark in the bottom-right margin
    poly = rect(A4_W_PX * 0.82, A4_H_PX * 0.89, A4_W_PX * 1.00005, A4_H_PX * 0.98)
    box = polygon_to_bbox(poly, A4_W_PT, A4_H_PT)
    assert box.x1 == 1.0
    assert validate_bbox(box.as_list()) == []


def test_case3_overflow_beyond_tolerance_still_raises():
    """The tolerance must not become a licence to accept anything."""
    poly = rect(0.0, 0.0, A4_W_PX * 1.02, A4_H_PX)
    with pytest.raises(GroundingError, match="beyond the"):
        polygon_to_bbox(poly, A4_W_PT, A4_H_PT)


def test_case3_clamping_can_be_switched_off_for_reference_comparison():
    poly = rect(0.0, 0.0, A4_W_PX * 1.00005, A4_H_PX)
    raw = polygon_to_bbox(poly, A4_W_PT, A4_H_PT, clamp=False)
    assert raw.x1 > 1.0


# ---------------------------------------------------------------------------
# Case 4 - a page of a different size
# ---------------------------------------------------------------------------


def test_case4_different_page_size_changes_the_answer():
    """The same pixel polygon must normalize differently on a bigger page.

    The 2005-2008 ARCHEAN scans are ~1654x2353 pt, the 2010+ ones are A4.
    Hard-coding A4 would corrupt every box in the older half of the corpus.
    """
    poly = rect(1000, 1000, 2000, 2000)
    a4 = polygon_to_bbox(poly, A4_W_PT, A4_H_PT)
    old = polygon_to_bbox(poly, OLD_W_PT, OLD_H_PT)
    assert a4.as_list() != old.as_list()
    # the same pixels cover proportionally less of the larger page
    assert old.x1 < a4.x1
    assert old.area < a4.area


def test_case4_midpoint_on_old_page_size():
    poly = rect(0, 0, OLD_W_PT * 300 / 72 / 2, OLD_H_PT * 300 / 72 / 2)
    box = polygon_to_bbox(poly, OLD_W_PT, OLD_H_PT)
    assert box.as_list() == pytest.approx([0.0, 0.0, 0.5, 0.5], abs=1e-12)


@pytest.mark.parametrize("w_pt,h_pt", [(595.0, 842.0), (1654.0, 2353.0),
                                       (578.0, 825.0), (1592.0, 2373.0)])
def test_case4_all_real_page_geometries_round_trip(w_pt, h_pt):
    """Every page geometry actually present in the ARCHEAN corpus."""
    w_px, h_px = w_pt * 300 / 72, h_pt * 300 / 72
    box = polygon_to_bbox(rect(0, 0, w_px, h_px), w_pt, h_pt)
    assert box.as_list() == pytest.approx([0.0, 0.0, 1.0, 1.0], abs=1e-12)


# ---------------------------------------------------------------------------
# Case 5 - agreement with the challenge's own bbox_viewer.py
# ---------------------------------------------------------------------------


def test_case5_matches_reference_implementation_exactly(
    reference_polygon_to_norm,
):
    """REFERENCE_FLOAT must reproduce bbox_viewer bit for bit."""
    poly = rect(123.0, 456.0, 789.0, 1011.0)
    ours = polygon_to_bbox(poly, A4_W_PT, A4_H_PT, mode=REFERENCE_FLOAT)
    theirs = reference_polygon_to_norm(poly, A4_W_PT, A4_H_PT)
    assert ours.as_list() == theirs


def test_case5_exact_mode_agrees_with_reference_within_tolerance(
    reference_polygon_to_norm,
):
    """EXACT avoids bbox_viewer's double rounding; they must still agree.

    300/72 = 25/6 is not representable in binary, so computing
    ``w_pt * scale`` and then dividing rounds twice. EXACT rounds once. The
    difference is bounded by one ulp.
    """
    poly = rect(123.0, 456.0, 789.0, 1011.0)
    ours = polygon_to_bbox(poly, A4_W_PT, A4_H_PT, mode=EXACT)
    theirs = reference_polygon_to_norm(poly, A4_W_PT, A4_H_PT)
    assert ours.as_list() == pytest.approx(theirs, abs=1e-12)


def test_case5_agreement_holds_across_the_whole_corpus(
    actes_root, reference_polygon_to_norm
):
    """Both modes, against the reference, on every OCR line of every acte.

    This is the test that would catch a conversion regression. It reads all
    17 actes; there are ~11k OCR lines.
    """
    import pymupdf

    compared = 0
    worst = 0.0
    for pdf_path in sorted((actes_root / "pdf").glob("*.pdf")):
        inpi_id = pdf_path.stem.split("_")[-1]
        ocr_dir = ocr_for(actes_root, inpi_id)
        if not ocr_dir.is_dir():
            continue
        doc = pymupdf.open(pdf_path)
        try:
            with Grounder(str(pdf_path), str(ocr_dir)) as g:
                for page_file in sorted(ocr_dir.glob("page_*.json")):
                    page = int(page_file.stem.split("_")[1])
                    w, h = g.page_size_pt(page)
                    data = json.loads(page_file.read_text(encoding="utf-8"))
                    for raw in data.get("ocr") or []:
                        poly = raw.get("polygon")
                        if not poly:
                            continue
                        theirs = reference_polygon_to_norm(poly, w, h)
                        # clamp=False: bbox_viewer does not clamp, so the
                        # comparison has to be against the raw value.
                        ref = polygon_to_bbox(
                            poly, w, h, mode=REFERENCE_FLOAT, clamp=False
                        ).as_list()
                        exact = polygon_to_bbox(
                            poly, w, h, mode=EXACT, clamp=False
                        ).as_list()
                        assert ref == theirs, (
                            f"REFERENCE_FLOAT diverged from bbox_viewer on "
                            f"{inpi_id} p{page}"
                        )
                        worst = max(
                            worst,
                            max(abs(a - b) for a, b in zip(exact, theirs)),
                        )
                        compared += 1
        finally:
            doc.close()

    assert compared > 10_000, f"expected the whole corpus, compared {compared}"
    assert worst < 1e-12, f"EXACT drifted from the reference by {worst:.2e}"


def test_case5_matches_bbox_viewer_cli_output(
    actes_root, bbox_viewer_path, challenge_root
):
    """End-to-end: run the challenge's CLI and match the box it prints.

    Guards against the reference being imported differently from how it is
    actually invoked.
    """
    inpi_id = "63e9593a8be6eb9f9d257ebe"  # 2017 president's decision
    pdf_path = pdf_for(actes_root, inpi_id)
    ocr_dir = ocr_for(actes_root, inpi_id)
    needle = "FPCI SECURITE"

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, str(bbox_viewer_path),
         "--pdf", str(pdf_path), "--page", "3",
         "--ocr", str(ocr_dir), "--grep", needle],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    printed = [
        ln for ln in proc.stdout.splitlines() if needle.lower() in ln.lower()
    ]
    assert printed, f"bbox_viewer printed nothing for {needle!r}:\n{proc.stdout}"

    # "  [0.1847, 0.2696, 0.3586, 0.2856]  - à FPCI SECURITE"
    cli_box = [
        float(v) for v in printed[0].split("]")[0].strip().lstrip("[").split(",")
    ]

    with Grounder(str(pdf_path), str(ocr_dir)) as g:
        hits = g.locate(3, needle)
    assert len(hits) == 1
    ours = hits[0][1].rounded(4)

    assert ours == pytest.approx(cli_box, abs=1e-4)


# ---------------------------------------------------------------------------
# Case 6 - every value within [0, 1]
# ---------------------------------------------------------------------------


def test_case6_every_corpus_box_is_submittable_after_clamping(actes_root):
    """Every box we could ever emit must satisfy the schema's [0, 1] bound.

    results.schema.json applies ``minimum: 0, maximum: 1`` to each value, so a
    single out-of-range box makes the whole submission invalid.
    """
    checked = 0
    for pdf_path in sorted((actes_root / "pdf").glob("*.pdf")):
        inpi_id = pdf_path.stem.split("_")[-1]
        ocr_dir = ocr_for(actes_root, inpi_id)
        if not ocr_dir.is_dir():
            continue
        with Grounder(str(pdf_path), str(ocr_dir)) as g:
            for page_file in sorted(ocr_dir.glob("page_*.json")):
                page = int(page_file.stem.split("_")[1])
                data = json.loads(page_file.read_text(encoding="utf-8"))
                w, h = g.page_size_pt(page)
                for raw in data.get("ocr") or []:
                    poly = raw.get("polygon")
                    if not poly:
                        continue
                    box = polygon_to_bbox(poly, w, h)  # clamped by default
                    assert all(0.0 <= v <= 1.0 for v in box.as_list()), (
                        f"{inpi_id} p{page}: {box.as_list()}"
                    )
                    checked += 1
    assert checked > 10_000


def test_case6_the_eight_overflowing_lines_are_known_and_tiny(actes_root):
    """Document the OCR lines that spill off the page, rather than hide them.

    8 of 11 254 lines overflow, by at most 8.5e-5 of a page dimension (about
    0.02 mm). All are marginalia — initials and paraphs in the margins.
    If this count changes, the corpus or the conversion changed.
    """
    overflows = []
    for pdf_path in sorted((actes_root / "pdf").glob("*.pdf")):
        inpi_id = pdf_path.stem.split("_")[-1]
        ocr_dir = ocr_for(actes_root, inpi_id)
        if not ocr_dir.is_dir():
            continue
        with Grounder(str(pdf_path), str(ocr_dir)) as g:
            for page_file in sorted(ocr_dir.glob("page_*.json")):
                page = int(page_file.stem.split("_")[1])
                data = json.loads(page_file.read_text(encoding="utf-8"))
                w, h = g.page_size_pt(page)
                for raw in data.get("ocr") or []:
                    poly = raw.get("polygon")
                    if not poly:
                        continue
                    over = overflows_page(poly, w, h)
                    if over > 0:
                        overflows.append((over, inpi_id, page, raw.get("text")))

    assert len(overflows) == 8, (
        f"expected 8 known overflowing lines, found {len(overflows)}: "
        f"{[(o[1][-4:], o[2], o[3]) for o in overflows]}"
    )
    assert max(o[0] for o in overflows) < 1e-4, (
        "an overflow grew beyond OCR jitter; investigate before clamping it"
    )


def test_case6_negative_coordinates_are_refused():
    with pytest.raises(GroundingError):
        polygon_to_bbox(rect(-5.0, 0.0, 100.0, 100.0), A4_W_PT, A4_H_PT)


def test_case6_validate_bbox_flags_out_of_range():
    assert validate_bbox([0.1, 0.2, 1.4, 0.3])
    assert "outside [0, 1]" in " ".join(validate_bbox([0.1, 0.2, 1.4, 0.3]))
    assert validate_bbox([0.1, 0.2, 0.3, 0.25]) == []


# ---------------------------------------------------------------------------
# Case 7 - ordering: x0 <= x1 and y0 <= y1
# ---------------------------------------------------------------------------


def test_case7_ordering_holds_for_unsorted_polygons():
    """Corner order in the polygon must not matter."""
    forwards = rect(100.0, 200.0, 300.0, 400.0)
    backwards = [[300.0, 400.0], [100.0, 400.0], [100.0, 200.0], [300.0, 200.0]]
    a = polygon_to_bbox(forwards, A4_W_PT, A4_H_PT)
    b = polygon_to_bbox(backwards, A4_W_PT, A4_H_PT)
    assert a.as_list() == b.as_list()
    assert a.x0 <= a.x1 and a.y0 <= a.y1


def test_case7_degenerate_box_is_refused():
    with pytest.raises(GroundingError, match="degenerate"):
        BBox(0.5, 0.2, 0.4, 0.3)


def test_case7_skewed_polygon_uses_the_extremes():
    """Scans are crooked; the polygon is not always axis-aligned."""
    skewed = [[100.0, 200.0], [300.0, 190.0], [305.0, 400.0], [95.0, 410.0]]
    box = polygon_to_bbox(skewed, A4_W_PT, A4_H_PT)
    assert box.x0 == pytest.approx(95.0 / A4_W_PX, abs=1e-12)
    assert box.y0 == pytest.approx(190.0 / A4_H_PX, abs=1e-12)
    assert box.x1 == pytest.approx(305.0 / A4_W_PX, abs=1e-12)
    assert box.y1 == pytest.approx(410.0 / A4_H_PX, abs=1e-12)


def test_case7_union_contains_every_input():
    a = polygon_to_bbox(rect(100, 200, 300, 250), A4_W_PT, A4_H_PT)
    b = polygon_to_bbox(rect(150, 400, 500, 450), A4_W_PT, A4_H_PT)
    u = union([a, b])
    assert u.x0 == min(a.x0, b.x0)
    assert u.y0 == min(a.y0, b.y0)
    assert u.x1 == max(a.x1, b.x1)
    assert u.y1 == max(a.y1, b.y1)
    assert u.area >= a.area and u.area >= b.area


def test_case7_union_of_nothing_is_refused():
    with pytest.raises(GroundingError):
        union([])


# ---------------------------------------------------------------------------
# Case 8 - pages are 1-indexed
# ---------------------------------------------------------------------------


def test_case8_page_zero_is_refused(actes_root):
    inpi_id = "63e9593b8be6eb9f9d257ebf"
    with Grounder(
        str(pdf_for(actes_root, inpi_id)), str(ocr_for(actes_root, inpi_id))
    ) as g:
        with pytest.raises(GroundingError, match="1-indexed"):
            g.page_size_pt(0)


def test_case8_negative_page_is_refused(actes_root):
    inpi_id = "63e9593b8be6eb9f9d257ebf"
    with Grounder(
        str(pdf_for(actes_root, inpi_id)), str(ocr_for(actes_root, inpi_id))
    ) as g:
        with pytest.raises(GroundingError, match="1-indexed"):
            g.page_size_pt(-1)


def test_case8_page_past_the_end_is_refused(actes_root):
    """The 2017-01-20 filing has exactly 4 pages."""
    inpi_id = "63e9593b8be6eb9f9d257ebf"
    with Grounder(
        str(pdf_for(actes_root, inpi_id)), str(ocr_for(actes_root, inpi_id))
    ) as g:
        assert g.page_count == 4
        g.page_size_pt(4)  # last page is valid
        with pytest.raises(GroundingError, match="out of range"):
            g.page_size_pt(5)


def test_case8_page_one_maps_to_the_first_pdf_page(actes_root):
    """Page 1 must be doc[0], not doc[1]."""
    import pymupdf

    inpi_id = "63e9593b8be6eb9f9d257ebf"
    pdf_path = pdf_for(actes_root, inpi_id)
    doc = pymupdf.open(pdf_path)
    try:
        expected = (doc[0].rect.width, doc[0].rect.height)
    finally:
        doc.close()
    with Grounder(str(pdf_path), str(ocr_for(actes_root, inpi_id))) as g:
        assert g.page_size_pt(1) == expected


def test_case8_ocr_filenames_are_one_indexed_and_aligned(actes_root):
    """page_001.json must correspond to PDF page 1, for every acte.

    If OCR page numbering were 0-indexed or offset, every box would land on
    the wrong page while still looking valid.
    """
    import pymupdf

    for pdf_path in sorted((actes_root / "pdf").glob("*.pdf")):
        inpi_id = pdf_path.stem.split("_")[-1]
        ocr_dir = ocr_for(actes_root, inpi_id)
        if not ocr_dir.is_dir():
            continue
        pages = sorted(
            int(p.stem.split("_")[1]) for p in ocr_dir.glob("page_*.json")
        )
        assert pages[0] == 1, f"{inpi_id} OCR starts at page {pages[0]}"
        doc = pymupdf.open(pdf_path)
        try:
            assert pages[-1] <= len(doc), (
                f"{inpi_id} has OCR for page {pages[-1]} but only "
                f"{len(doc)} PDF pages"
            )
            assert pages == list(range(1, len(pages) + 1)), (
                f"{inpi_id} OCR page numbering has gaps: {pages}"
            )
        finally:
            doc.close()


# ---------------------------------------------------------------------------
# Real evidence from the corpus
#
# Each of these was located with the challenge's own bbox_viewer --grep and
# then rendered to a PNG and inspected by eye; the rendered proofs are in
# docs/box_checks/. These are the three claims the capital chain leans on
# hardest.
# ---------------------------------------------------------------------------

REAL_EVIDENCE = [
    pytest.param(
        "63e9593b8be6eb9f9d257ec5", 3,
        "Il est divisé en trois cent soixante dix (370) actions",
        [0.1209, 0.415, 0.839, 0.4283],
        id="2005-constitution-370-shares",
    ),
    pytest.param(
        "63e9593a8be6eb9f9d257ebe", 3,
        "être ramené de 368 102 euros à 217 241 euros",
        [0.1137, 0.3993, 0.8801, 0.4176],
        id="2017-reduction-368102-to-217241",
    ),
    pytest.param(
        "63e9593b8be6eb9f9d257ec0", 2,
        "augmenter le capital social d",
        [0.1061, 0.7043, 0.8781, 0.7243],
        id="2018-increase-182759",
    ),
]


@pytest.mark.parametrize("inpi_id,page,needle,expected", REAL_EVIDENCE)
def test_real_evidence_grounds_to_the_expected_box(
    actes_root, inpi_id, page, needle, expected
):
    with Grounder(
        str(pdf_for(actes_root, inpi_id)), str(ocr_for(actes_root, inpi_id))
    ) as g:
        hits = g.locate(page, needle)
    assert len(hits) == 1, (
        f"expected exactly one line matching {needle!r} on page {page} of "
        f"{inpi_id}, found {len(hits)}: {[h[0].text for h in hits]}"
    )
    line, box = hits[0]
    assert box.rounded(4) == pytest.approx(expected, abs=1e-4)
    assert validate_bbox(box.as_list()) == []
    # a single line of body text is a thin horizontal strip
    assert 0.003 < (box.y1 - box.y0) < 0.05
    assert box.x1 - box.x0 > 0.1


@pytest.mark.parametrize("inpi_id,page,needle,expected", REAL_EVIDENCE)
def test_real_evidence_agrees_with_bbox_viewer(
    actes_root, reference_polygon_to_norm, inpi_id, page, needle, expected
):
    with Grounder(
        str(pdf_for(actes_root, inpi_id)), str(ocr_for(actes_root, inpi_id))
    ) as g:
        w, h = g.page_size_pt(page)
        line, box = g.locate(page, needle)[0]
    theirs = reference_polygon_to_norm(list(line.polygon), w, h)
    assert box.as_list() == pytest.approx(theirs, abs=1e-12)


def test_real_evidence_snippet_is_verbatim_ocr(actes_root):
    """A snippet must be quotable from the OCR, not paraphrased.

    This is the check that makes an invented quotation impossible: the text we
    publish has to be findable in the page we cite.
    """
    inpi_id, page = "63e9593a8be6eb9f9d257ebe", 3
    snippet = (
        "être ramené de 368 102 euros à 217 241 euros et divisé en "
        "217 241 actions de 1 euro de valeur"
    )
    with Grounder(
        str(pdf_for(actes_root, inpi_id)), str(ocr_for(actes_root, inpi_id))
    ) as g:
        hits = g.locate(page, snippet)
    assert len(hits) == 1
    assert normalize_text(hits[0][0].text) == normalize_text(snippet)


def test_multi_line_quotation_unions_into_one_box(actes_root):
    """The 2017 buyback names four funds on four consecutive lines."""
    inpi_id, page = "63e9593a8be6eb9f9d257ebe", 3
    with Grounder(
        str(pdf_for(actes_root, inpi_id)), str(ocr_for(actes_root, inpi_id))
    ) as g:
        funds = ["FPCI SECURITE", "FIP GALIA PME 4", "GALIA VENTURE",
                 "FPCI FINANCIERE DE BRIENNE"]
        boxes = []
        for fund in funds:
            hits = g.locate(page, fund)
            assert len(hits) == 1, f"{fund}: {len(hits)} hits"
            boxes.append(hits[0][1])
        combined = union(boxes)

    for b in boxes:
        assert combined.x0 <= b.x0 and combined.y0 <= b.y0
        assert combined.x1 >= b.x1 and combined.y1 >= b.y1
    assert validate_bbox(combined.as_list()) == []
    # four consecutive lines: taller than one line, still a small part of a page
    assert combined.y1 - combined.y0 > 0.04
    assert combined.area < 0.2


def test_line_ids_are_stable_and_out_of_range_ids_are_refused(actes_root):
    inpi_id, page = "63e9593a8be6eb9f9d257ebe", 3
    with Grounder(
        str(pdf_for(actes_root, inpi_id)), str(ocr_for(actes_root, inpi_id))
    ) as g:
        line, box = g.locate(page, "FPCI SECURITE")[0]
        assert g.bbox_for_line_ids(page, [line.index]).as_list() == box.as_list()
        with pytest.raises(GroundingError, match="do not exist"):
            g.bbox_for_line_ids(page, [line.index, 99_999])


# ---------------------------------------------------------------------------
# text normalization
# ---------------------------------------------------------------------------


def test_normalize_text_folds_accents_case_and_whitespace():
    assert normalize_text("Société  par\nActions") == "societe par actions"
    assert normalize_text("RÉDUCTION") == "reduction"
    assert normalize_text("  d'un  ") == "d'un"


def test_normalize_text_folds_typographic_apostrophes():
    """OCR emits both ' and U+2019; they must match each other."""
    assert normalize_text("l’augmentation") == normalize_text("l'augmentation")
