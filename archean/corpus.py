"""Deterministic discovery of one acte/bilan corpus folder.

This module answers exactly one question: *what exists on disk, and how do
the files relate to each other?* It does not read what a document says.

Given a folder shaped like ``data/<siren>/actes/`` — a ``pdf/`` directory, a
``meta/`` directory, and optionally an ``ocr/`` directory — :func:`load_corpus`
returns a :class:`Corpus`: an ordered, typed index of :class:`Document` and
:class:`Page` objects, plus a list of non-fatal :class:`Finding` objects for
structural facts worth knowing about (a document with no OCR, two documents
sharing a registry batch number) that are not errors.

What belongs here
    Identifying documents and pages, associating a PDF with its metadata and
    its OCR directory, counting pages, detecting when the pdf/meta/ocr
    contract is violated.

What does not belong here
    Reading what a page says, classifying a document by its content, scoring
    which documents matter, resolving names, correcting OCR text, guessing at
    missing data. See :mod:`archean.ground` for provenance (turning OCR
    coordinates into boxes) and :mod:`archean.frenchnum` for reading numbers
    and dates out of text — both operate on text this module only locates.

Determinism
    The same directory tree always produces the same :class:`Corpus`, field
    for field, in the same order. Documents are sorted by
    ``(filename_date, doc_id)`` — never by filesystem iteration order — and
    every list this module returns is a tuple, built by explicit sort.

What was verified before writing this module
    Every claim below was checked against the full 20-company, both-doctype
    corpus, not just ARCHEAN's actes; see DISCOVERY.md's corpus.py section for
    the audit. In summary: filenames are always
    ``<prefix>_<yyyy-mm-dd>_<24-hex-id>.<ext>``; ``meta['id']`` always equals
    the filename id; a document's OCR is either complete (one page file per
    PDF page, matching page numbers) or entirely absent (no ``ocr/<id>/``
    directory at all) — partial per-document OCR does not occur anywhere in
    the shipped corpus, though this module tolerates it if it ever does; and
    there are zero orphaned files anywhere in the shipped corpus, so orphan
    handling here is exercised only by test fixtures, not by real data.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

__all__ = [
    "CorpusError",
    "MalformedFilenameError",
    "UnexpectedFileError",
    "OrphanFileError",
    "InvalidMetadataError",
    "PageNumberingError",
    "Finding",
    "TypeRddEntry",
    "Page",
    "Document",
    "Corpus",
    "load_corpus",
]


# ---------------------------------------------------------------------------
# errors — reserved for violations of the pdf/meta/ocr contract itself.
# Never raised by anything this module has observed in the real corpus; each
# one exists because DISCOVERY.md's audit asked "what if this happened?" and
# the answer needs to be a loud, specific failure rather than silent skipping.
# ---------------------------------------------------------------------------


class CorpusError(Exception):
    """Base class: the corpus folder does not honour its own contract."""


class MalformedFilenameError(CorpusError):
    """A filename in pdf/ or meta/ does not match ``<prefix>_<date>_<id>``."""


class UnexpectedFileError(CorpusError):
    """A file exists in pdf/, meta/ or ocr/ that does not belong there."""


class OrphanFileError(CorpusError):
    """A pdf, meta, or ocr entry has no counterpart in the other two."""


class InvalidMetadataError(CorpusError):
    """A meta/*.json file is unreadable, or contradicts its own filename."""


class PageNumberingError(CorpusError):
    """Two OCR files disagree about which page they are."""


# ---------------------------------------------------------------------------
# non-fatal findings — real structural facts, not errors.
# ---------------------------------------------------------------------------

Severity = Literal["info", "warning"]


@dataclass(frozen=True, order=True)
class Finding:
    """A structural fact worth surfacing, that is not a contract violation.

    Ordered so that a list of findings sorts deterministically regardless of
    discovery order.
    """

    severity: Severity
    code: str
    doc_id: str
    message: str


# ---------------------------------------------------------------------------
# the domain model
# ---------------------------------------------------------------------------

#: <prefix>_<yyyy-mm-dd>_<24 lowercase hex chars>.<ext>
#: Observed prefixes: "acte", "bilan". The prefix itself is not constrained,
#: since corpus.py indexes one folder at a time and does not need to know
#: which kind of folder it was handed.
_FILENAME_RE = re.compile(
    r"^(?P<prefix>[a-z]+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<id>[0-9a-f]{24})"
    r"\.(?P<ext>[a-z]+)$"
)
_OCR_PAGE_RE = re.compile(r"^page_(?P<num>\d{3,})\.json$")


@dataclass(frozen=True)
class TypeRddEntry:
    """One item of ``meta['typeRdd']``, verbatim.

    ``decision`` is absent on some entries in the real data (a handful of
    ``typeRdd`` items carry only ``typeActe``), so it is optional here rather
    than defaulted to an empty string — an absent decision and an empty one
    are different facts and this module does not collapse them.
    """

    type_acte: str
    decision: str | None = None


@dataclass(frozen=True)
class Page:
    """One page of one document.

    ``number`` is always in ``1..Document.page_count``; this module never
    constructs a ``Page`` for a number the PDF does not have. ``ocr_path`` is
    ``None`` when this specific page has no OCR — which in the shipped corpus
    only ever happens for every page of a document at once, but is modelled
    per page because nothing here should assume that continues to hold.
    """

    number: int
    ocr_path: Path | None

    @property
    def has_ocr(self) -> bool:
        return self.ocr_path is not None


@dataclass(frozen=True)
class Document:
    """One filed act or bilan: a PDF, its registry metadata, and its OCR.

    ``doc_id`` is the 24-character id from the filename — the same id the
    challenge's ``results.schema.json`` asks for in ``source.inpi_id``, and
    the same string used as the OCR subdirectory name.

    ``meta`` is the parsed ``meta/*.json`` file, verbatim and unmodified. The
    typed properties below are direct pass-throughs of specific meta fields —
    formatting, not interpretation — kept because looking them up by raw key
    everywhere they are used would scatter the same ``.get(...)`` calls
    through every caller.
    """

    doc_id: str
    filename_date: _dt.date
    prefix: str
    pdf_path: Path
    meta_path: Path
    ocr_dir: Path | None
    page_count: int
    pages: tuple[Page, ...]
    meta: Mapping[str, object]

    # -- typed pass-throughs of meta fields, no interpretation -------------

    @property
    def siren(self) -> str | None:
        v = self.meta.get("siren")
        return v if isinstance(v, str) else None

    @property
    def denomination(self) -> str | None:
        v = self.meta.get("denomination")
        return v if isinstance(v, str) else None

    @property
    def deposit_date(self) -> _dt.date | None:
        """``meta['dateDepot']``, parsed. ``None`` if the field is absent."""
        raw = self.meta.get("dateDepot")
        if not isinstance(raw, str):
            return None
        return _dt.date.fromisoformat(raw)

    @property
    def num_chrono(self) -> str | None:
        v = self.meta.get("numChrono")
        return v if isinstance(v, str) else None

    @property
    def type_document(self) -> str | None:
        """``meta['typeDocument']`` — only the 2025-12-02 filing carries this."""
        v = self.meta.get("typeDocument")
        return v if isinstance(v, str) else None

    @property
    def type_rdd(self) -> tuple[TypeRddEntry, ...]:
        raw = self.meta.get("typeRdd")
        if not isinstance(raw, list):
            return ()
        return tuple(
            TypeRddEntry(
                type_acte=str(item.get("typeActe", "")).strip(),
                decision=(
                    str(item["decision"]).strip()
                    if item.get("decision") is not None
                    else None
                ),
            )
            for item in raw
            if isinstance(item, dict)
        )

    def type_rdd_summary(self) -> str:
        """The registry's own index entries, joined for display.

        Pure formatting of ``type_rdd``: no judgement about what any entry
        means. Returns ``"(none)"`` when the field is absent or empty, which
        is itself a real, observed state — two documents in the ARCHEAN
        corpus have no ``typeRdd`` at all.
        """
        entries = self.type_rdd
        if not entries:
            return "(none)"
        parts = []
        for e in entries:
            parts.append(f"{e.type_acte} — {e.decision}" if e.decision else e.type_acte)
        return " · ".join(parts)

    # -- OCR facts -----------------------------------------------------

    @property
    def has_ocr(self) -> bool:
        return self.ocr_dir is not None

    @property
    def ocr_page_count(self) -> int:
        return sum(1 for p in self.pages if p.has_ocr)

    @property
    def ocr_coverage_complete(self) -> bool:
        """Every page of this document has OCR."""
        return self.has_ocr and self.ocr_page_count == self.page_count

    def page(self, number: int) -> Page:
        """The :class:`Page` for a 1-indexed page number.

        Raises ``KeyError`` rather than returning ``None``, since asking for a
        page number the document does not have is a caller error, not a
        structural fact about the corpus.
        """
        if not 1 <= number <= self.page_count:
            raise KeyError(
                f"{self.doc_id} has {self.page_count} pages; no page {number}"
            )
        return self.pages[number - 1]


@dataclass(frozen=True)
class Corpus:
    """One indexed corpus folder: every document, in deterministic order."""

    root: Path
    documents: tuple[Document, ...]
    findings: tuple[Finding, ...]

    def __len__(self) -> int:
        return len(self.documents)

    def __iter__(self):
        return iter(self.documents)

    def get(self, doc_id: str) -> Document | None:
        for d in self.documents:
            if d.doc_id == doc_id:
                return d
        return None

    def __getitem__(self, doc_id: str) -> Document:
        doc = self.get(doc_id)
        if doc is None:
            raise KeyError(f"no document {doc_id!r} in corpus at {self.root}")
        return doc

    @property
    def total_pages(self) -> int:
        return sum(d.page_count for d in self.documents)

    @property
    def total_ocr_pages(self) -> int:
        return sum(d.ocr_page_count for d in self.documents)

    def findings_for(self, doc_id: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.doc_id == doc_id)


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def _open_pdf_page_count(pdf_path: Path) -> int:
    """The PDF's own page count — the ground truth, since meta/ carries none."""
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - environment issue
        import fitz as pymupdf  # type: ignore
    doc = pymupdf.open(str(pdf_path))
    try:
        return len(doc)
    finally:
        doc.close()


def _parse_filename(path: Path, expected_ext: str) -> tuple[str, str, _dt.date]:
    """(prefix, doc_id, filename_date), or raise :class:`MalformedFilenameError`."""
    m = _FILENAME_RE.match(path.name)
    if not m:
        raise MalformedFilenameError(
            f"{path}: filename does not match "
            f"'<prefix>_<yyyy-mm-dd>_<24-hex-id>.{expected_ext}'"
        )
    if m.group("ext") != expected_ext:
        raise MalformedFilenameError(
            f"{path}: expected .{expected_ext}, found .{m.group('ext')}"
        )
    try:
        filename_date = _dt.date.fromisoformat(m.group("date"))
    except ValueError as exc:
        raise MalformedFilenameError(f"{path}: invalid date in filename") from exc
    return m.group("prefix"), m.group("id"), filename_date


def _scan_dir(dir_path: Path, expected_ext: str) -> dict[str, tuple[Path, str, _dt.date]]:
    """doc_id -> (path, prefix, filename_date), for every file in a directory.

    Raises :class:`UnexpectedFileError` for anything that is not a plain file
    with the expected extension, and :class:`MalformedFilenameError` for a
    same-extension file whose name does not fit the convention.
    """
    out: dict[str, tuple[Path, str, _dt.date]] = {}
    for entry in sorted(dir_path.iterdir()):
        if not entry.is_file():
            raise UnexpectedFileError(f"{entry}: not a plain file")
        if entry.suffix != f".{expected_ext}":
            raise UnexpectedFileError(
                f"{entry}: unexpected file in {dir_path.name}/ "
                f"(expected only .{expected_ext} files)"
            )
        prefix, doc_id, filename_date = _parse_filename(entry, expected_ext)
        if doc_id in out:
            raise OrphanFileError(  # pragma: no cover - two files, same id, same dir
                f"{doc_id}: two {expected_ext} files claim the same id: "
                f"{out[doc_id][0]} and {entry}"
            )
        out[doc_id] = (entry, prefix, filename_date)
    return out


def _load_meta(meta_path: Path, expected_doc_id: str) -> Mapping[str, object]:
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidMetadataError(f"{meta_path}: cannot read or parse") from exc
    if not isinstance(raw, dict):
        raise InvalidMetadataError(f"{meta_path}: top level is not an object")
    meta_id = raw.get("id")
    if meta_id != expected_doc_id:
        raise InvalidMetadataError(
            f"{meta_path}: meta['id'] is {meta_id!r}, filename says "
            f"{expected_doc_id!r}"
        )
    return raw


def _load_pages(
    doc_id: str, page_count: int, ocr_dir: Path | None, findings: list[Finding]
) -> tuple[Page, ...]:
    if ocr_dir is None or not ocr_dir.is_dir():
        return tuple(Page(number=i, ocr_path=None) for i in range(1, page_count + 1))

    by_number: dict[int, Path] = {}
    for entry in sorted(ocr_dir.iterdir()):
        if not entry.is_file():
            raise UnexpectedFileError(f"{entry}: not a plain file in ocr/{doc_id}/")
        m = _OCR_PAGE_RE.match(entry.name)
        if not m:
            raise UnexpectedFileError(
                f"{entry}: expected 'page_NNN.json' in ocr/{doc_id}/"
            )
        num = int(m.group("num"))
        try:
            declared = json.loads(entry.read_text(encoding="utf-8")).get("page")
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidMetadataError(f"{entry}: cannot read or parse") from exc
        if declared != num:
            raise PageNumberingError(
                f"{entry}: filename says page {num}, the file's own 'page' "
                f"field says {declared!r}"
            )
        if num in by_number:
            raise PageNumberingError(
                f"ocr/{doc_id}/: two files both declare page {num}: "
                f"{by_number[num]} and {entry}"
            )
        by_number[num] = entry

    if by_number and max(by_number) > page_count:
        findings.append(Finding(
            "warning", "ocr_page_out_of_range", doc_id,
            f"OCR has a page {max(by_number)} but the PDF only has "
            f"{page_count} pages",
        ))

    pages = tuple(
        Page(number=i, ocr_path=by_number.get(i))
        for i in range(1, page_count + 1)
    )
    n_ocr = sum(1 for p in pages if p.has_ocr)
    if 0 < n_ocr < page_count:
        findings.append(Finding(
            "warning", "partial_ocr_coverage", doc_id,
            f"{n_ocr} of {page_count} pages have OCR; the rest do not",
        ))
    return pages


def load_corpus(root: Path | str) -> Corpus:
    """Index one ``{pdf,meta,ocr}`` folder into a :class:`Corpus`.

    ``root`` is a single company/document-kind folder, e.g.
    ``data/480489707/actes`` — not the ``data/`` tree of all companies. This
    module indexes one such folder at a time; composing several is a caller's
    decision, not something corpus.py imposes an opinion about.

    Raises a :class:`CorpusError` subclass if the pdf/meta/ocr contract is
    violated. Returns a :class:`Corpus` with populated ``findings`` for real
    but non-fatal facts (a document with no OCR, a shared registry batch
    number) otherwise. Never returns partial results after raising.
    """
    root = Path(root)
    pdf_dir, meta_dir, ocr_dir = root / "pdf", root / "meta", root / "ocr"

    if not pdf_dir.is_dir():
        raise CorpusError(f"{root}: no pdf/ directory")
    if not meta_dir.is_dir():
        raise CorpusError(f"{root}: no meta/ directory")

    pdfs = _scan_dir(pdf_dir, "pdf")
    metas = _scan_dir(meta_dir, "json")

    pdf_only = sorted(set(pdfs) - set(metas))
    meta_only = sorted(set(metas) - set(pdfs))
    if pdf_only:
        raise OrphanFileError(f"{root}: pdf with no meta counterpart: {pdf_only}")
    if meta_only:
        raise OrphanFileError(f"{root}: meta with no pdf counterpart: {meta_only}")

    # ocr/ is optional at the folder level (some companies have none at all,
    # per the brief); when present, every subdirectory must be a real document.
    ocr_subdirs: dict[str, Path] = {}
    if ocr_dir.is_dir():
        for entry in sorted(ocr_dir.iterdir()):
            if not entry.is_dir():
                raise UnexpectedFileError(
                    f"{entry}: expected only per-document subdirectories in ocr/"
                )
            if not re.fullmatch(r"[0-9a-f]{24}", entry.name):
                raise MalformedFilenameError(
                    f"{entry}: ocr/ subdirectory name is not a 24-hex document id"
                )
            if entry.name not in pdfs:
                raise OrphanFileError(
                    f"{entry}: ocr/ subdirectory has no pdf/meta counterpart"
                )
            ocr_subdirs[entry.name] = entry

    findings: list[Finding] = []
    documents: list[Document] = []

    for doc_id in sorted(pdfs):
        pdf_path, prefix, filename_date = pdfs[doc_id]
        meta_path, meta_prefix, meta_filename_date = metas[doc_id]

        if meta_prefix != prefix or meta_filename_date != filename_date:
            raise InvalidMetadataError(
                f"{doc_id}: pdf filename says ({prefix}, {filename_date}), "
                f"meta filename says ({meta_prefix}, {meta_filename_date})"
            )

        meta = _load_meta(meta_path, doc_id)

        deposit_raw = meta.get("dateDepot")
        if isinstance(deposit_raw, str):
            try:
                deposit_date = _dt.date.fromisoformat(deposit_raw)
            except ValueError as exc:
                raise InvalidMetadataError(
                    f"{doc_id}: meta['dateDepot'] = {deposit_raw!r} is not "
                    f"a valid ISO date"
                ) from exc
            if deposit_date != filename_date:
                findings.append(Finding(
                    "warning", "deposit_date_differs_from_filename", doc_id,
                    f"filename says {filename_date}, meta['dateDepot'] says "
                    f"{deposit_date}",
                ))

        page_count = _open_pdf_page_count(pdf_path)
        doc_ocr_dir = ocr_subdirs.get(doc_id)
        pages = _load_pages(doc_id, page_count, doc_ocr_dir, findings)

        if doc_ocr_dir is None:
            findings.append(Finding(
                "info", "no_ocr", doc_id,
                "this document has no OCR at all",
            ))
        if "typeRdd" not in meta:
            findings.append(Finding(
                "info", "no_type_rdd", doc_id,
                "meta has no typeRdd field",
            ))

        documents.append(Document(
            doc_id=doc_id,
            filename_date=filename_date,
            prefix=prefix,
            pdf_path=pdf_path,
            meta_path=meta_path,
            ocr_dir=doc_ocr_dir,
            page_count=page_count,
            pages=pages,
            meta=meta,
        ))

    documents.sort(key=lambda d: (d.filename_date, d.doc_id))

    # numChrono grouping is a cross-document fact, computed after every
    # document is loaded.
    by_num_chrono: dict[str, list[str]] = {}
    for d in documents:
        nc = d.num_chrono
        if nc is not None:
            by_num_chrono.setdefault(nc, []).append(d.doc_id)
    for nc, ids in sorted(by_num_chrono.items()):
        if len(ids) > 1:
            for doc_id in ids:
                others = [i for i in ids if i != doc_id]
                findings.append(Finding(
                    "info", "shared_num_chrono", doc_id,
                    f"numChrono {nc!r} is shared with {others}",
                ))

    findings.sort(key=lambda f: (f.severity, f.code, f.doc_id))

    return Corpus(root=root, documents=tuple(documents), findings=tuple(findings))
