"""Tests for archean.corpus.

Split in two halves. The first exercises load_corpus against the real
ARCHEAN actes corpus, which — per the audit in DISCOVERY.md — contains zero
orphans, zero malformed filenames and zero page-numbering conflicts. The
second exercises every failure path against small, synthetic fixture trees
built under tmp_path, because those failures do not occur anywhere in the
shipped corpus and the instructions are explicit that this is the correct way
to test them: build a fixture, never mutate the real corpus to manufacture a
failure.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from archean.corpus import (
    InvalidMetadataError,
    MalformedFilenameError,
    OrphanFileError,
    PageNumberingError,
    TypeRddEntry,
    UnexpectedFileError,
    load_corpus,
)

# ===========================================================================
# real corpus: discovery
# ===========================================================================


def test_loads_every_document(actes_root):
    corpus = load_corpus(actes_root)
    assert len(corpus) == 17


def test_document_ids_are_the_24_hex_ids_from_the_filenames(actes_root):
    corpus = load_corpus(actes_root)
    for d in corpus.documents:
        assert len(d.doc_id) == 24
        assert all(c in "0123456789abcdef" for c in d.doc_id)


def test_page_counts_come_from_the_pdf_not_from_meta(actes_root):
    """meta/*.json carries no page-count field at all; the PDF is the source."""
    corpus = load_corpus(actes_root)
    constitution = corpus["63e9593b8be6eb9f9d257ec5"]
    assert constitution.page_count == 24
    assert len(constitution.pages) == 24
    assert [p.number for p in constitution.pages] == list(range(1, 25))


def test_multi_page_and_single_page_documents_both_load(actes_root):
    corpus = load_corpus(actes_root)
    largest = max(corpus.documents, key=lambda d: d.page_count)
    smallest = min(corpus.documents, key=lambda d: d.page_count)
    assert largest.page_count == 32   # 2017-03-28
    assert smallest.page_count == 1   # 2011-07-11, …eca


def test_seventeen_documents_is_the_known_corpus_size(actes_root):
    """Matches DISCOVERY.md §4.1, independently reproduced from disk."""
    corpus = load_corpus(actes_root)
    assert len(corpus) == 17
    assert corpus.total_pages == 293
    assert corpus.total_ocr_pages == 293


# ===========================================================================
# real corpus: ordering
# ===========================================================================


def test_documents_are_sorted_by_filename_date_then_id(actes_root):
    corpus = load_corpus(actes_root)
    keys = [(d.filename_date, d.doc_id) for d in corpus.documents]
    assert keys == sorted(keys)


def test_the_two_same_day_deposits_sort_by_id(actes_root):
    """2010-12-08 has two documents; …ec8 must sort before …ec9."""
    corpus = load_corpus(actes_root)
    same_day = [d for d in corpus.documents if d.filename_date.isoformat() == "2010-12-08"]
    assert [d.doc_id[-4:] for d in same_day] == ["7ec8", "7ec9"]


def test_document_order_matches_discovery_section_4_1(actes_root):
    """The exact sequence hand-transcribed into DISCOVERY.md §4.1."""
    corpus = load_corpus(actes_root)
    expected = [
        "63e9593b8be6eb9f9d257ec5", "63e9593b8be6eb9f9d257ec4",
        "63e9593b8be6eb9f9d257ec2", "63e9593b8be6eb9f9d257ec7",
        "63e9593b8be6eb9f9d257ec6", "63e9593b8be6eb9f9d257ec3",
        "63e9593b8be6eb9f9d257ec1", "63e9593b8be6eb9f9d257ec8",
        "63e9593b8be6eb9f9d257ec9", "63e9593c8be6eb9f9d257eca",
        "63e9593c8be6eb9f9d257ecb", "63e9593a8be6eb9f9d257ebd",
        "63e9593b8be6eb9f9d257ebf", "63e9593a8be6eb9f9d257ebe",
        "63e9593b8be6eb9f9d257ec0", "63e9593c8be6eb9f9d257ecc",
        "6936b4160bb493b0e4098925",
    ]
    assert [d.doc_id for d in corpus.documents] == expected


# ===========================================================================
# real corpus: correspondence (meta <-> pdf <-> ocr)
# ===========================================================================


def test_every_document_has_a_pdf_and_meta_path_that_exist(actes_root):
    corpus = load_corpus(actes_root)
    for d in corpus.documents:
        assert d.pdf_path.is_file()
        assert d.meta_path.is_file()


def test_meta_is_the_raw_parsed_json_verbatim(actes_root):
    corpus = load_corpus(actes_root)
    d = corpus["63e9593b8be6eb9f9d257ec5"]
    assert d.meta["denomination"] == "ARCHEAN TECHNOLOGIES"
    assert d.meta["siren"] == "480489707"
    assert d.meta["id"] == "63e9593b8be6eb9f9d257ec5"


def test_typed_accessors_match_the_raw_meta_fields(actes_root):
    corpus = load_corpus(actes_root)
    d = corpus["63e9593b8be6eb9f9d257ec5"]
    assert d.siren == d.meta["siren"]
    assert d.denomination == d.meta["denomination"]
    assert d.deposit_date.isoformat() == d.meta["dateDepot"]
    assert d.num_chrono == d.meta["numChrono"]


def test_type_rdd_entries_are_typed_and_ordered(actes_root):
    corpus = load_corpus(actes_root)
    constitution = corpus["63e9593b8be6eb9f9d257ec5"]
    entries = constitution.type_rdd
    assert len(entries) == 1
    assert entries[0] == TypeRddEntry(
        type_acte="Acte sous seing privé", decision="Constitution"
    )


def test_type_rdd_entry_without_a_decision_keeps_decision_none(actes_root):
    """Some entries carry only typeActe. None is preserved, not "" ."""
    corpus = load_corpus(actes_root)
    d = corpus["63e9593a8be6eb9f9d257ebd"]  # "Statuts mis à jour" has no decision
    no_decision = [e for e in d.type_rdd if e.decision is None]
    assert no_decision, "expected at least one typeRdd entry without a decision"


def test_document_with_empty_meta_has_no_type_rdd(actes_root):
    """The 2006-01-03 filing: DISCOVERY.md flagged it as 'meta empty'."""
    corpus = load_corpus(actes_root)
    d = corpus["63e9593b8be6eb9f9d257ec4"]
    assert d.type_rdd == ()
    assert d.type_rdd_summary() == "(none)"


def test_ocr_path_points_at_the_real_page_file(actes_root):
    corpus = load_corpus(actes_root)
    d = corpus["63e9593b8be6eb9f9d257ec5"]
    page3 = d.page(3)
    assert page3.has_ocr
    assert page3.ocr_path.name == "page_003.json"
    assert page3.ocr_path.is_file()


def test_every_document_in_this_corpus_has_complete_ocr(actes_root):
    """17/17, per the audit. If this regresses, the corpus changed underneath us."""
    corpus = load_corpus(actes_root)
    assert all(d.ocr_coverage_complete for d in corpus.documents)
    assert all(d.has_ocr for d in corpus.documents)


def test_page_out_of_range_raises_key_error(actes_root):
    corpus = load_corpus(actes_root)
    d = corpus["63e9593c8be6eb9f9d257eca"]  # 1-page document
    assert d.page_count == 1
    with pytest.raises(KeyError):
        d.page(2)
    with pytest.raises(KeyError):
        d.page(0)


# ===========================================================================
# real corpus: findings (structural facts, not errors)
# ===========================================================================


def test_no_type_rdd_finding_fires_for_the_two_known_documents(actes_root):
    corpus = load_corpus(actes_root)
    ids = {f.doc_id for f in corpus.findings if f.code == "no_type_rdd"}
    assert ids == {"63e9593b8be6eb9f9d257ec4", "6936b4160bb493b0e4098925"}


def test_shared_num_chrono_finding_fires_for_both_known_pairs(actes_root):
    """Matches DISCOVERY.md's C8: the two 2010-12-08 and two 2011-07-11 filings."""
    corpus = load_corpus(actes_root)
    shared = {f.doc_id for f in corpus.findings if f.code == "shared_num_chrono"}
    assert shared == {
        "63e9593b8be6eb9f9d257ec8", "63e9593b8be6eb9f9d257ec9",
        "63e9593c8be6eb9f9d257eca", "63e9593c8be6eb9f9d257ecb",
    }


def test_no_ocr_finding_never_fires_for_this_corpus(actes_root):
    """ARCHEAN has complete OCR; this finding exists for other companies."""
    corpus = load_corpus(actes_root)
    assert not any(f.code == "no_ocr" for f in corpus.findings)


def test_findings_for_helper_filters_by_document(actes_root):
    corpus = load_corpus(actes_root)
    fs = corpus.findings_for("63e9593b8be6eb9f9d257ec4")
    assert all(f.doc_id == "63e9593b8be6eb9f9d257ec4" for f in fs)
    assert len(fs) >= 1


def test_deposit_date_matches_filename_date_for_every_document(actes_root):
    """No deposit_date_differs_from_filename finding anywhere in this corpus."""
    corpus = load_corpus(actes_root)
    assert not any(
        f.code == "deposit_date_differs_from_filename" for f in corpus.findings
    )
    for d in corpus.documents:
        assert d.deposit_date == d.filename_date


def test_findings_are_sorted_deterministically(actes_root):
    corpus = load_corpus(actes_root)
    keys = [(f.severity, f.code, f.doc_id) for f in corpus.findings]
    assert keys == sorted(keys)


# ===========================================================================
# real corpus: no OCR at the whole-company level (a different real company)
# ===========================================================================


def test_a_company_with_zero_ocr_loads_with_no_ocr_findings_not_errors(
    challenge_root,
):
    """data/026980508/actes/ has a pdf/ and meta/ but no ocr/ directory at all.

    This is documented as normal in the challenge brief ("a few companies
    have none at all"), so it must load cleanly with info-level findings,
    never raise.
    """
    root = challenge_root / "data" / "026980508" / "actes"
    if not root.is_dir():
        pytest.skip(f"{root} not present in this checkout")
    corpus = load_corpus(root)
    assert len(corpus) > 0
    assert all(not d.has_ocr for d in corpus.documents)
    assert all(d.ocr_page_count == 0 for d in corpus.documents)
    assert {f.code for f in corpus.findings if f.severity == "info"} >= {"no_ocr"}
    no_ocr_ids = {f.doc_id for f in corpus.findings if f.code == "no_ocr"}
    assert no_ocr_ids == {d.doc_id for d in corpus.documents}


# ===========================================================================
# determinism
# ===========================================================================


def test_loading_twice_produces_an_identical_result(actes_root):
    a = load_corpus(actes_root)
    b = load_corpus(actes_root)
    assert [d.doc_id for d in a.documents] == [d.doc_id for d in b.documents]
    assert a.findings == b.findings
    assert a.total_pages == b.total_pages == 293


def test_documents_are_tuples_not_lists_or_sets(actes_root):
    """Immutability is part of the determinism guarantee, not incidental."""
    corpus = load_corpus(actes_root)
    assert isinstance(corpus.documents, tuple)
    assert isinstance(corpus.findings, tuple)
    for d in corpus.documents:
        assert isinstance(d.pages, tuple)
        assert isinstance(d.type_rdd, tuple)


def test_corpus_and_document_are_frozen(actes_root):
    corpus = load_corpus(actes_root)
    with pytest.raises(Exception):
        corpus.documents = ()  # type: ignore[misc]
    with pytest.raises(Exception):
        corpus.documents[0].doc_id = "x"  # type: ignore[misc]


def test_loading_ten_times_is_stable(actes_root):
    """Not just twice — guard against nondeterminism that only shows up rarely."""
    results = [tuple(d.doc_id for d in load_corpus(actes_root).documents) for _ in range(10)]
    assert len(set(results)) == 1


# ===========================================================================
# synthetic fixtures: failure paths not present in the real corpus
# ===========================================================================


def _make_pdf(path: Path, n_pages: int = 1) -> None:
    """A minimal real PDF, since corpus.py opens it with pymupdf for page_count."""
    import pymupdf

    doc = pymupdf.open()
    for _ in range(n_pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()


def _make_meta(path: Path, doc_id: str, date: str = "2020-01-01", **extra) -> None:
    payload = {
        "updatedAt": "2020-01-01T00:00:00+01:00",
        "siren": "000000000",
        "denomination": "TEST CO",
        "dateDepot": date,
        "confidentiality": "Public",
        "deleted": False,
        "id": doc_id,
        **extra,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_ocr_page(path: Path, page: int, text: str = "hello") -> None:
    payload = {
        "page": page,
        "ocr": [{"polygon": [[0, 0], [10, 0], [10, 10], [0, 10]], "text": text, "score": 0.9}],
        "layout": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def empty_corpus(tmp_path) -> Path:
    root = tmp_path / "corpus"
    (root / "pdf").mkdir(parents=True)
    (root / "meta").mkdir(parents=True)
    return root


DOC_ID = "aaaaaaaaaaaaaaaaaaaaaaaa"  # 24 hex chars, valid shape


def test_orphan_pdf_without_meta_is_refused(empty_corpus):
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf")
    with pytest.raises(OrphanFileError, match="no meta counterpart"):
        load_corpus(empty_corpus)


def test_orphan_meta_without_pdf_is_refused(empty_corpus):
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json", DOC_ID)
    with pytest.raises(OrphanFileError, match="no pdf counterpart"):
        load_corpus(empty_corpus)


def test_orphan_ocr_directory_without_pdf_is_refused(empty_corpus):
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf")
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json", DOC_ID)
    other_id = "bbbbbbbbbbbbbbbbbbbbbbbb"
    ocr_dir = empty_corpus / "ocr" / other_id
    ocr_dir.mkdir(parents=True)
    _make_ocr_page(ocr_dir / "page_001.json", 1)
    with pytest.raises(OrphanFileError, match="no pdf/meta counterpart"):
        load_corpus(empty_corpus)


def test_malformed_pdf_filename_is_refused(empty_corpus):
    (empty_corpus / "pdf" / "not_a_valid_name.pdf").write_bytes(b"%PDF-1.4\n")
    with pytest.raises(MalformedFilenameError):
        load_corpus(empty_corpus)


def test_short_document_id_is_refused(empty_corpus):
    """9 hex chars instead of 24: the id shape itself is part of the contract."""
    (empty_corpus / "pdf" / "acte_2020-01-01_deadbeef9.pdf").write_bytes(b"%PDF-1.4\n")
    with pytest.raises(MalformedFilenameError):
        load_corpus(empty_corpus)


def test_unexpected_file_in_pdf_directory_is_refused(empty_corpus):
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf")
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json", DOC_ID)
    (empty_corpus / "pdf" / "Thumbs.db").write_bytes(b"junk")
    with pytest.raises(UnexpectedFileError):
        load_corpus(empty_corpus)


def test_unexpected_subdirectory_in_pdf_directory_is_refused(empty_corpus):
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf")
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json", DOC_ID)
    (empty_corpus / "pdf" / "stray_subdir").mkdir()
    with pytest.raises(UnexpectedFileError):
        load_corpus(empty_corpus)


def test_meta_id_field_contradicting_the_filename_is_refused(empty_corpus):
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf")
    wrong_id = "cccccccccccccccccccccccc"
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json", wrong_id)
    with pytest.raises(InvalidMetadataError, match="meta\\['id'\\]"):
        load_corpus(empty_corpus)


def test_unparseable_meta_json_is_refused(empty_corpus):
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf")
    (empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json").write_text(
        "{not valid json", encoding="utf-8"
    )
    with pytest.raises(InvalidMetadataError):
        load_corpus(empty_corpus)


def test_meta_that_is_a_json_array_not_an_object_is_refused(empty_corpus):
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf")
    (empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json").write_text(
        "[]", encoding="utf-8"
    )
    with pytest.raises(InvalidMetadataError, match="not an object"):
        load_corpus(empty_corpus)


def test_pdf_and_meta_filenames_disagreeing_on_date_is_refused(empty_corpus):
    """Same id, different embedded dates: which one is the real deposit date?"""
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf")
    _make_meta(
        empty_corpus / "meta" / f"acte_2020-06-15_{DOC_ID}.json", DOC_ID,
        date="2020-06-15",
    )
    with pytest.raises(InvalidMetadataError, match="pdf filename says"):
        load_corpus(empty_corpus)


def test_duplicate_page_number_inside_one_document_is_refused(empty_corpus):
    """Two OCR files both claiming to be page 1 of the same document."""
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf", n_pages=2)
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json", DOC_ID)
    ocr_dir = empty_corpus / "ocr" / DOC_ID
    ocr_dir.mkdir(parents=True)
    _make_ocr_page(ocr_dir / "page_001.json", 1)
    # a second file, differently named, whose internal "page" field also says 1
    _make_ocr_page(ocr_dir / "page_0001.json", 1)
    with pytest.raises(PageNumberingError, match="both declare page 1"):
        load_corpus(empty_corpus)


def test_ocr_filename_disagreeing_with_its_own_page_field_is_refused(empty_corpus):
    """page_002.json whose internal 'page' field says 5."""
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf", n_pages=2)
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json", DOC_ID)
    ocr_dir = empty_corpus / "ocr" / DOC_ID
    ocr_dir.mkdir(parents=True)
    _make_ocr_page(ocr_dir / "page_002.json", 5)
    with pytest.raises(PageNumberingError, match="says 5"):
        load_corpus(empty_corpus)


def test_ocr_subdirectory_name_not_a_valid_id_is_refused(empty_corpus):
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf")
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json", DOC_ID)
    (empty_corpus / "ocr" / "not-a-hex-id").mkdir(parents=True)
    with pytest.raises(MalformedFilenameError, match="not a 24-hex"):
        load_corpus(empty_corpus)


def test_missing_pdf_directory_is_refused(tmp_path):
    root = tmp_path / "corpus"
    (root / "meta").mkdir(parents=True)
    with pytest.raises(Exception, match="no pdf/ directory"):
        load_corpus(root)


def test_missing_meta_directory_is_refused(tmp_path):
    root = tmp_path / "corpus"
    (root / "pdf").mkdir(parents=True)
    with pytest.raises(Exception, match="no meta/ directory"):
        load_corpus(root)


# -- fixtures: paths this corpus does not exercise, but which must not raise ---


def test_partial_ocr_coverage_within_one_document_is_a_finding_not_an_error(
    empty_corpus,
):
    """One page has OCR, the other does not. Never observed in the shipped
    corpus (§4.1: it is all-or-nothing everywhere), but bbox_viewer.py's own
    docstring anticipates it, so load_corpus must tolerate it, not crash.
    """
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf", n_pages=2)
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json", DOC_ID)
    ocr_dir = empty_corpus / "ocr" / DOC_ID
    ocr_dir.mkdir(parents=True)
    _make_ocr_page(ocr_dir / "page_001.json", 1)
    # page 2 has no OCR file at all

    corpus = load_corpus(empty_corpus)
    doc = corpus[DOC_ID]
    assert doc.page_count == 2
    assert doc.ocr_page_count == 1
    assert doc.page(1).has_ocr
    assert not doc.page(2).has_ocr
    assert not doc.ocr_coverage_complete
    codes = {f.code for f in corpus.findings if f.doc_id == DOC_ID}
    assert "partial_ocr_coverage" in codes


def test_document_with_no_ocr_directory_at_all_loads_cleanly(empty_corpus):
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf", n_pages=3)
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json", DOC_ID)
    corpus = load_corpus(empty_corpus)
    doc = corpus[DOC_ID]
    assert doc.ocr_dir is None
    assert not doc.has_ocr
    assert all(not p.has_ocr for p in doc.pages)
    assert any(f.code == "no_ocr" and f.doc_id == DOC_ID for f in corpus.findings)


def test_deposit_date_differing_from_filename_is_a_finding_not_an_error(
    empty_corpus,
):
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf")
    _make_meta(
        empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json", DOC_ID,
        date="2020-03-15",  # differs from the filename's 2020-01-01
    )
    corpus = load_corpus(empty_corpus)
    doc = corpus[DOC_ID]
    assert doc.filename_date.isoformat() == "2020-01-01"
    assert doc.deposit_date.isoformat() == "2020-03-15"
    assert any(
        f.code == "deposit_date_differs_from_filename" and f.doc_id == DOC_ID
        for f in corpus.findings
    )


def test_document_without_a_type_rdd_field_loads_cleanly(empty_corpus):
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{DOC_ID}.pdf")
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{DOC_ID}.json", DOC_ID)
    corpus = load_corpus(empty_corpus)
    assert corpus[DOC_ID].type_rdd == ()
    assert any(f.code == "no_type_rdd" for f in corpus.findings)


def test_two_documents_sharing_num_chrono_produces_paired_findings(empty_corpus):
    id_a, id_b = "aaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbb"
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{id_a}.pdf")
    _make_pdf(empty_corpus / "pdf" / f"acte_2020-01-01_{id_b}.pdf")
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{id_a}.json", id_a, numChrono="42")
    _make_meta(empty_corpus / "meta" / f"acte_2020-01-01_{id_b}.json", id_b, numChrono="42")
    corpus = load_corpus(empty_corpus)
    shared = {f.doc_id for f in corpus.findings if f.code == "shared_num_chrono"}
    assert shared == {id_a, id_b}


def test_empty_corpus_folder_loads_to_zero_documents(empty_corpus):
    corpus = load_corpus(empty_corpus)
    assert len(corpus) == 0
    assert corpus.total_pages == 0
    assert corpus.findings == ()


def test_get_returns_none_for_an_unknown_id(empty_corpus):
    corpus = load_corpus(empty_corpus)
    assert corpus.get("does-not-exist") is None
    with pytest.raises(KeyError):
        corpus["does-not-exist"]


# ===========================================================================
# scripts/inventory.py: output is derived, not hardcoded
# ===========================================================================


def test_inventory_markdown_is_derived_from_the_corpus_not_hardcoded(actes_root):
    """Rebuild the corpus, feed it to the renderer, and check the numbers
    in the rendered text are the ones the objects actually carry - not a
    copy of a previous run's output pasted into the script.
    """
    from scripts.inventory import render_markdown

    corpus = load_corpus(actes_root)
    text = render_markdown(corpus)

    assert f"{len(corpus)} documents" in text
    assert f"{corpus.total_pages} PDF pages" in text
    for d in corpus.documents:
        assert d.doc_id[-4:] in text
        assert str(d.filename_date) in text
        assert str(d.page_count) in text


def test_inventory_markdown_omits_capital_and_priority_with_an_explanation(
    actes_root,
):
    """These two §4.1 columns require reading content; corpus.py never does."""
    from scripts.inventory import render_markdown

    text = render_markdown(load_corpus(actes_root))
    assert "capital in header" not in text.split("\n")[3]  # not a real column
    assert "priority" not in text.split("\n")[3]
    assert "never does" in text or "not reproduced" in text


def test_inventory_json_round_trips_the_same_facts_as_markdown(actes_root):
    from scripts.inventory import render_json, render_markdown

    corpus = load_corpus(actes_root)
    payload = json.loads(render_json(corpus))
    assert payload["document_count"] == len(corpus)
    assert payload["total_pages"] == corpus.total_pages
    assert len(payload["documents"]) == len(corpus)
    ids_in_json = {d["doc_id"] for d in payload["documents"]}
    assert ids_in_json == {d.doc_id for d in corpus.documents}

    md = render_markdown(corpus)
    for d in corpus.documents:
        assert d.doc_id[-4:] in md


def test_inventory_two_runs_produce_byte_identical_output(actes_root):
    from scripts.inventory import render_markdown

    a = render_markdown(load_corpus(actes_root))
    b = render_markdown(load_corpus(actes_root))
    assert a == b


def test_inventory_script_runs_end_to_end_as_a_subprocess(actes_root):
    import os
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "inventory.py"),
         "--root", str(actes_root)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "17 documents" in proc.stdout
    assert "293 PDF pages" in proc.stdout


def test_inventory_script_fails_cleanly_on_a_missing_root(tmp_path):
    import os
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "inventory.py"),
         "--root", str(tmp_path / "does-not-exist")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, env=env,
    )
    assert proc.returncode != 0
    assert "no corpus at" in proc.stderr
