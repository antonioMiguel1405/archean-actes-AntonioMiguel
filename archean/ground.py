"""Turn OCR coordinates into submittable bounding boxes.

This module is the *only* place a bbox is ever produced. Nothing else in the
pipeline — and in particular no language model — may write into a ``bbox``
field. A model may say which OCR lines it read; this module turns those lines
into coordinates.

Coordinate systems
------------------
The shipped OCR gives ``polygon`` as four ``[x, y]`` points in **pixels at
300 dpi**. A PDF page is measured in **points** (1/72 inch). What the challenge
wants submitted is ``[x0, y0, x1, y1]`` normalized 0-1 against that page's own
width and height, origin top-left, page 1-indexed::

    scale  = 300 / 72
    x_norm = x_px / (page_width_pt  * scale)
    y_norm = y_px / (page_height_pt * scale)

Page size varies across this corpus — the 2005-2008 scans are roughly
1654x2353 pt and the 2010+ filings are A4 595x842 pt — so the rect of the
*specific page* is always read. Assuming A4 silently corrupts every box in the
older half of the corpus.

On rounding order
-----------------
``tools/bbox_viewer.py`` in the challenge repo is the reference implementation.
It computes ``w_px = page_w_pt * scale`` first and then divides, which rounds
twice, because 300/72 = 25/6 is not representable in binary floating point.

This module computes the same quantity in exact rational arithmetic and rounds
once, at the boundary. Measured across all 11 254 OCR lines of the ARCHEAN
corpus (45 016 coordinate values), the two paths differ by at most 2.22e-16.
After rounding to four decimals they disagree on 20 values out of 45 016
(0.04%), all of them exact ties such as a true value of 0.70125, where the
reference path yields 0.7012499999999999 and rounds down. The difference is
about 0.02 mm on an A4 page.

``REFERENCE_FLOAT`` reproduces ``bbox_viewer`` bit for bit and exists so the
compatibility can be asserted in tests rather than assumed. ``EXACT`` is the
default because it avoids the double rounding; the two are proven equivalent to
within 1e-12 in ``tests/test_bbox.py``.

On boxes that overflow the page
-------------------------------
8 of the 11 254 OCR lines in this corpus (0.07%) have polygons that extend just
past the page edge — at most 8.5e-5 of a page dimension, roughly 0.02 mm. They
are all marginalia: initials, paraphs and signature strokes in the margins.

This matters because ``results.schema.json`` constrains every bbox value with
``minimum: 0, maximum: 1``. A box of 1.00008 makes the submission invalid
against the schema, and the brief is explicit that a file they cannot parse
cannot be scored. ``bbox_viewer.py`` does not clamp, so the reference tool can
print a box that cannot legally be submitted.

So clamping is on by default, but only within ``CLAMP_TOLERANCE``. A polygon
that lands further outside the page than that is not OCR jitter — it means the
wrong page size was used, or the coordinates were not 300-dpi pixels — and is
still refused. Pass ``clamp=False`` to get the raw reference behaviour.
"""

from __future__ import annotations

import glob
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Literal, Sequence

DPI_OF_OCR = 300
POINTS_PER_INCH = 72
SCALE = Fraction(DPI_OF_OCR, POINTS_PER_INCH)

Mode = Literal["exact", "reference_float"]
EXACT: Mode = "exact"
REFERENCE_FLOAT: Mode = "reference_float"

#: How far outside [0, 1] a coordinate may land before it is treated as an
#: error rather than as OCR jitter at the page edge. The worst real overflow in
#: this corpus is 8.5e-5; a wrong page size is out by percent, not by 0.001.
CLAMP_TOLERANCE = 0.001

Polygon = Sequence[Sequence[float]]


class GroundingError(ValueError):
    """Raised when a box cannot be produced honestly from the inputs given."""


# --------------------------------------------------------------------------
# bounding boxes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BBox:
    """A normalized box, ``[x0, y0, x1, y1]`` with origin top-left.

    Construction refuses boxes that are *implausible* — grossly off the page,
    or with the corners crossed. It tolerates the sub-0.001 overflow that real
    OCR produces at page edges, because refusing that would mean refusing eight
    genuine lines of this corpus. Whether a box is *legal to submit* is a
    stricter question, answered by :func:`validate_bbox`.
    """

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        for name, v in zip(("x0", "y0", "x1", "y1"), self.as_list()):
            if v < -CLAMP_TOLERANCE or v > 1.0 + CLAMP_TOLERANCE:
                raise GroundingError(
                    f"{name}={v!r} is outside [0, 1]. A normalized box cannot "
                    f"leave the page; this usually means the page size was "
                    f"wrong or the coordinates were not in 300-dpi pixels."
                )
        if self.x0 > self.x1 or self.y0 > self.y1:
            raise GroundingError(
                f"degenerate box {self.as_list()}: requires x0 <= x1 and y0 <= y1"
            )

    @property
    def is_submittable(self) -> bool:
        """True when every coordinate is within [0, 1], as the schema requires."""
        return not validate_bbox(self.as_list())

    def as_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]

    def rounded(self, ndigits: int = 4) -> list[float]:
        """Round once, for emitting. Never round during computation."""
        return [round(v, ndigits) for v in self.as_list()]

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)


def _clamp_unit(
    values: Sequence[float], *, tolerance: float, context: str
) -> list[float]:
    """Pull values marginally outside [0, 1] back onto the page.

    Anything further out than ``tolerance`` is an error, not jitter.
    """
    out = []
    for name, v in zip(("x0", "y0", "x1", "y1"), values):
        if v < -tolerance or v > 1 + tolerance:
            raise GroundingError(
                f"{name}={v!r} is {max(-v, v - 1):.4g} outside [0, 1], beyond "
                f"the {tolerance:g} tolerance{context}. A normalized box cannot "
                f"leave the page by this much; the page size is probably wrong, "
                f"or the coordinates were not in 300-dpi pixels."
            )
        out.append(min(1.0, max(0.0, v)))
    return out


def polygon_to_bbox(
    polygon: Polygon,
    page_w_pt: float,
    page_h_pt: float,
    *,
    mode: Mode = EXACT,
    clamp: bool = True,
    clamp_tolerance: float = CLAMP_TOLERANCE,
) -> BBox:
    """One OCR polygon (300-dpi pixels) -> one normalized :class:`BBox`.

    ``mode=REFERENCE_FLOAT`` reproduces ``tools/bbox_viewer.polygon_to_norm``
    exactly, including its double rounding. ``mode=EXACT`` (the default) does
    the same arithmetic over rationals and rounds once.

    ``clamp=True`` (the default) pulls coordinates that overflow the page by
    less than ``clamp_tolerance`` back onto it, so the result can legally be
    submitted. ``clamp=False`` gives the raw value, which is what
    ``bbox_viewer`` prints and which may fall outside [0, 1].
    """
    if not polygon:
        raise GroundingError("empty polygon")
    if page_w_pt <= 0 or page_h_pt <= 0:
        raise GroundingError(f"bad page size {page_w_pt}x{page_h_pt} pt")

    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]

    if mode == REFERENCE_FLOAT:
        scale = DPI_OF_OCR / POINTS_PER_INCH
        w_px, h_px = page_w_pt * scale, page_h_pt * scale
        raw = [
            min(xs) / w_px, min(ys) / h_px, max(xs) / w_px, max(ys) / h_px
        ]
    elif mode == EXACT:
        w_px = Fraction(page_w_pt) * SCALE
        h_px = Fraction(page_h_pt) * SCALE
        raw = [
            float(Fraction(min(xs)) / w_px),
            float(Fraction(min(ys)) / h_px),
            float(Fraction(max(xs)) / w_px),
            float(Fraction(max(ys)) / h_px),
        ]
    else:
        raise GroundingError(f"unknown mode {mode!r}")

    if clamp:
        raw = _clamp_unit(
            raw,
            tolerance=clamp_tolerance,
            context=f" on a {page_w_pt:.0f}x{page_h_pt:.0f} pt page",
        )
    return BBox(*raw)


def overflows_page(
    polygon: Polygon, page_w_pt: float, page_h_pt: float
) -> float:
    """How far outside [0, 1] this polygon lands. 0.0 means it fits.

    Used to report, rather than hide, the OCR lines that spill off the page.
    """
    scale = DPI_OF_OCR / POINTS_PER_INCH
    w_px, h_px = page_w_pt * scale, page_h_pt * scale
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    raw = [min(xs) / w_px, min(ys) / h_px, max(xs) / w_px, max(ys) / h_px]
    return max(0.0, max(max(v - 1.0 for v in raw), max(-v for v in raw)))


def union(boxes: Iterable[BBox]) -> BBox:
    """Smallest box containing all of ``boxes``.

    This is how a multi-line quotation is grounded: each cited OCR line becomes
    a box, and the union is what gets submitted.
    """
    boxes = list(boxes)
    if not boxes:
        raise GroundingError("cannot take the union of no boxes")
    return BBox(
        min(b.x0 for b in boxes),
        min(b.y0 for b in boxes),
        max(b.x1 for b in boxes),
        max(b.y1 for b in boxes),
    )


# --------------------------------------------------------------------------
# text handling
# --------------------------------------------------------------------------


def normalize_text(s: str) -> str:
    """Fold accents, case and whitespace for matching only.

    Matching has to survive OCR that renders the same word as ``Société`` and
    ``Societe``. The *original* text is always what gets quoted in a snippet;
    this form is never emitted.
    """
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("’", "'").replace("‘", "'")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


@dataclass(frozen=True)
class OcrLine:
    """One line of shipped OCR, with its position on the page."""

    index: int          # position in the page's ocr[] array; stable id
    page: int           # 1-indexed
    text: str           # verbatim, as OCR produced it
    polygon: tuple[tuple[float, float], ...]
    score: float | None = None

    @property
    def normalized(self) -> str:
        return normalize_text(self.text)


# --------------------------------------------------------------------------
# reading the corpus
# --------------------------------------------------------------------------


def ocr_page_path(ocr_dir: str, page: int) -> str:
    if page < 1:
        raise GroundingError(f"page must be 1-indexed, got {page}")
    return os.path.join(ocr_dir, f"page_{page:03d}.json")


def available_pages(ocr_dir: str) -> list[int]:
    out = []
    for f in glob.glob(os.path.join(ocr_dir, "page_*.json")):
        m = re.search(r"page_(\d+)\.json$", os.path.basename(f))
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


def load_ocr_lines(ocr_dir: str, page: int) -> list[OcrLine]:
    """Read one page of shipped OCR into :class:`OcrLine` objects."""
    path = ocr_page_path(ocr_dir, page)
    if not os.path.exists(path):
        present = available_pages(ocr_dir)
        raise GroundingError(
            f"no OCR for page {page} in {ocr_dir}; pages present: "
            f"{present[:1]}..{present[-1:]}" if present else
            f"no OCR at all in {ocr_dir}"
        )
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    lines: list[OcrLine] = []
    for i, raw in enumerate(data.get("ocr") or []):
        poly = raw.get("polygon")
        if not poly:
            continue
        lines.append(
            OcrLine(
                index=i,
                page=page,
                text=(raw.get("text") or "").strip(),
                polygon=tuple((float(p[0]), float(p[1])) for p in poly),
                score=raw.get("score"),
            )
        )
    return lines


class Grounder:
    """Binds one PDF to its OCR directory and produces boxes for it.

    Page sizes are read from the PDF itself, per page, and cached.
    """

    def __init__(self, pdf_path: str, ocr_dir: str, *, mode: Mode = EXACT):
        if not os.path.exists(pdf_path):
            raise GroundingError(f"no PDF at {pdf_path}")
        if not os.path.isdir(ocr_dir):
            raise GroundingError(f"no OCR directory at {ocr_dir}")
        self.pdf_path = pdf_path
        self.ocr_dir = ocr_dir
        self.mode = mode
        self._doc = None
        self._sizes: dict[int, tuple[float, float]] = {}

    # -- lifecycle ------------------------------------------------------

    def _document(self):
        if self._doc is None:
            try:
                import pymupdf
            except ImportError:  # pragma: no cover - environment issue
                import fitz as pymupdf  # type: ignore
            self._doc = pymupdf.open(self.pdf_path)
        return self._doc

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    def __enter__(self) -> "Grounder":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def page_count(self) -> int:
        return len(self._document())

    # -- geometry -------------------------------------------------------

    def page_size_pt(self, page: int) -> tuple[float, float]:
        """(width, height) in points for a 1-indexed page."""
        if page < 1:
            raise GroundingError(f"page must be 1-indexed, got {page}")
        if page in self._sizes:
            return self._sizes[page]
        doc = self._document()
        if page > len(doc):
            raise GroundingError(
                f"page {page} out of range; {os.path.basename(self.pdf_path)} "
                f"has {len(doc)} pages"
            )
        rect = doc[page - 1].rect
        self._sizes[page] = (rect.width, rect.height)
        return self._sizes[page]

    def bbox_for_polygon(self, page: int, polygon: Polygon) -> BBox:
        w, h = self.page_size_pt(page)
        return polygon_to_bbox(polygon, w, h, mode=self.mode)

    def bbox_for_lines(self, page: int, lines: Iterable[OcrLine]) -> BBox:
        return union(self.bbox_for_polygon(page, ln.polygon) for ln in lines)

    def bbox_for_line_ids(self, page: int, ids: Sequence[int]) -> BBox:
        """Union of the boxes of the given OCR line indices on ``page``.

        This is the entry point a model-driven extraction uses: the model cites
        line ids, this turns them into one box. Out-of-range ids are refused
        rather than skipped, so a hallucinated citation fails loudly.
        """
        if not ids:
            raise GroundingError("no line ids given")
        lines = load_ocr_lines(self.ocr_dir, page)
        by_index = {ln.index: ln for ln in lines}
        missing = [i for i in ids if i not in by_index]
        if missing:
            raise GroundingError(
                f"line ids {missing} do not exist on page {page} of "
                f"{os.path.basename(self.pdf_path)} "
                f"(it has {len(lines)} OCR lines)"
            )
        return self.bbox_for_lines(page, [by_index[i] for i in ids])

    # -- locating text --------------------------------------------------

    def locate(self, page: int, needle: str) -> list[tuple[OcrLine, BBox]]:
        """Every OCR line on ``page`` containing ``needle``, with its box.

        Matching is accent- and case-insensitive; the returned ``OcrLine.text``
        is the verbatim OCR text, which is what a snippet must quote.
        """
        target = normalize_text(needle)
        if not target:
            raise GroundingError("empty search text")
        out = []
        for ln in load_ocr_lines(self.ocr_dir, page):
            if target in ln.normalized:
                out.append((ln, self.bbox_for_polygon(page, ln.polygon)))
        return out

    def search(self, needle: str) -> list[tuple[OcrLine, BBox]]:
        """:meth:`locate` across every page that has OCR."""
        out = []
        for page in available_pages(self.ocr_dir):
            out.extend(self.locate(page, needle))
        return out


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def validate_bbox(
    bbox: Sequence[float],
    *,
    max_area: float = 0.5,
    min_area: float = 1e-7,
) -> list[str]:
    """Return a list of problems with a box. Empty list means it is usable.

    Used by the validator rather than raised, so a whole run can be reported at
    once instead of failing on the first bad box.
    """
    problems: list[str] = []
    if len(bbox) != 4:
        return [f"expected 4 values, got {len(bbox)}"]
    x0, y0, x1, y1 = bbox
    for name, v in zip(("x0", "y0", "x1", "y1"), bbox):
        if not isinstance(v, (int, float)):
            problems.append(f"{name} is {type(v).__name__}, not a number")
        elif not 0.0 <= v <= 1.0:
            problems.append(f"{name}={v} outside [0, 1]")
    if problems:
        return problems
    if x0 > x1:
        problems.append(f"x0 ({x0}) > x1 ({x1})")
    if y0 > y1:
        problems.append(f"y0 ({y0}) > y1 ({y1})")
    area = (x1 - x0) * (y1 - y0)
    if area < min_area:
        problems.append(f"area {area:.2e} is effectively zero")
    if area > max_area:
        problems.append(
            f"area {area:.3f} covers more than {max_area:.0%} of the page; "
            f"a box should point at the operative text, not the whole page"
        )
    return problems
