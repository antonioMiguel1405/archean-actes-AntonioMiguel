#!/usr/bin/env python
"""Regenerate the reproducible half of DISCOVERY.md §4.1 from the corpus.

    python scripts/inventory.py
    python scripts/inventory.py --root path/to/data/<siren>/actes
    python scripts/inventory.py --format json

This script contains no discovery logic of its own — every fact it prints
comes from :func:`archean.corpus.load_corpus`. It formats and counts; it does
not open a PDF, read an OCR file, or touch the filesystem beyond what
``load_corpus`` already did:

    filesystem -> archean.corpus.load_corpus -> Document / Page -> this script

What this script deliberately does NOT reproduce
    DISCOVERY.md §4.1 has two columns this script cannot regenerate:
    "capital in header" and "priority". Both require reading what a page
    *says* (grepping page headers for "au capital de ...", judging which
    documents matter for the scored event codes) — interpretation that
    belongs to a later, content-aware layer, not to a filesystem index. This
    script prints every column that is a structural fact, and says so.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from archean.corpus import Corpus, Document, load_corpus  # noqa: E402

DEFAULT_SIREN = "480489707"
DEFAULT_SUBDIR = "actes"


def default_root() -> Path:
    """The ARCHEAN actes folder, next to this repo, unless overridden.

    Honours ARCHEAN_CHALLENGE_ROOT for consistency with conftest.py, which
    every test in this repo already uses to find the reference clone.
    """
    challenge_root = Path(
        os.environ.get(
            "ARCHEAN_CHALLENGE_ROOT",
            Path(__file__).resolve().parent.parent.parent / "engineering-challenges",
        )
    )
    return challenge_root / "data" / DEFAULT_SIREN / DEFAULT_SUBDIR


def _short_id(doc_id: str) -> str:
    """Matches DISCOVERY.md's prose convention of citing the last 4 hex chars.

    Display only. Every machine-readable field elsewhere carries the full id.
    """
    return f"…{doc_id[-4:]}" if len(doc_id) > 4 else doc_id


def render_markdown(corpus: Corpus) -> str:
    lines: list[str] = []
    complete = sum(1 for d in corpus.documents if d.ocr_coverage_complete)
    lines.append(f"# Corpus inventory — `{corpus.root}`\n")
    lines.append(
        f"**{len(corpus)} documents, {corpus.total_pages} PDF pages, "
        f"OCR coverage {corpus.total_ocr_pages}/{corpus.total_pages} pages "
        f"across {complete}/{len(corpus)} fully-OCR'd documents.**\n"
    )
    lines.append(
        "Columns `capital in header` and `priority` from DISCOVERY.md §4.1 "
        "are not reproduced here: both require reading document content, "
        "which this script — built only on `archean.corpus` — never does. "
        "See DISCOVERY.md for the hand-verified values.\n"
    )
    lines.append(
        "| # | deposit | inpi_id | pages | OCR | numChrono | meta typeRdd |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for i, d in enumerate(corpus.documents, start=1):
        ocr = (
            f"{d.ocr_page_count}/{d.page_count}"
            if d.has_ocr
            else "none"
        )
        nc = d.num_chrono or "—"
        summary = d.type_rdd_summary().replace("|", "\\|")
        lines.append(
            f"| {i} | {d.filename_date} | `{_short_id(d.doc_id)}` | "
            f"{d.page_count} | {ocr} | {nc} | {summary} |"
        )

    if corpus.findings:
        lines.append("\n## Findings (structural facts, not errors)\n")
        lines.append("| severity | code | inpi_id | message |")
        lines.append("|---|---|---|---|")
        for f in corpus.findings:
            lines.append(
                f"| {f.severity} | {f.code} | `{_short_id(f.doc_id)}` | "
                f"{f.message} |"
            )

    return "\n".join(lines) + "\n"


def render_json(corpus: Corpus) -> str:
    """A machine-readable equivalent, for diffing against a previous run."""

    def doc_to_dict(d: Document) -> dict:
        return {
            "doc_id": d.doc_id,
            "filename_date": d.filename_date.isoformat(),
            "deposit_date": d.deposit_date.isoformat() if d.deposit_date else None,
            "num_chrono": d.num_chrono,
            "page_count": d.page_count,
            "ocr_page_count": d.ocr_page_count,
            "ocr_coverage_complete": d.ocr_coverage_complete,
            "type_rdd_summary": d.type_rdd_summary(),
        }

    payload = {
        "root": str(corpus.root),
        "document_count": len(corpus),
        "total_pages": corpus.total_pages,
        "total_ocr_pages": corpus.total_ocr_pages,
        "documents": [doc_to_dict(d) for d in corpus.documents],
        "findings": [
            {
                "severity": f.severity,
                "code": f.code,
                "doc_id": f.doc_id,
                "message": f.message,
            }
            for f in corpus.findings
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=None,
        help="corpus folder to index (default: ARCHEAN's actes, "
             "resolved via ARCHEAN_CHALLENGE_ROOT)",
    )
    parser.add_argument(
        "--format", choices=("markdown", "json"), default="markdown",
    )
    args = parser.parse_args(argv)

    root = args.root or default_root()
    if not root.is_dir():
        print(
            f"no corpus at {root}\n"
            f"clone github.com/takeovers-ai/engineering-challenges beside "
            f"this repo, or pass --root, or set ARCHEAN_CHALLENGE_ROOT",
            file=sys.stderr,
        )
        return 2

    corpus = load_corpus(root)

    if args.format == "json":
        sys.stdout.write(render_json(corpus))
    else:
        sys.stdout.write(render_markdown(corpus))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
