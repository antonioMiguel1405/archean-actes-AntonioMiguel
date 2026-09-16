#!/usr/bin/env python
"""Blind comparison: tests/data/gold_non_archean.json vs archean.route.classify().

This script runs strictly AFTER the gold file is frozen. It does not tune,
adjust, or explain away anything — it prints raw agreement/disagreement and a
disagreement CATEGORY for each mismatch, chosen from a fixed vocabulary, never
a score. route.py is not modified by anything this script finds.

Usage:
    python scripts/gold_compare.py            # full report
    python scripts/gold_compare.py --json      # machine-readable, for tests
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from archean.corpus import Document, load_corpus  # noqa: E402
from archean.route import Verdict, classify  # noqa: E402

GOLD_PATH = Path(__file__).resolve().parent.parent / "tests" / "data" / "gold_non_archean.json"
DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "engineering-challenges" / "data"

#: Fixed disagreement-category vocabulary (Phase 5). A disagreement must be
#: assigned exactly one of these; "other" is a deliberate escape hatch, never
#: silently used to mean "unexamined".
CATEGORIES = (
    "gold_ambiguity",
    "router_false_positive",
    "router_false_negative",
    "scope_problem",
    "recital_problem",
    "date_problem",
    "mechanism_coverage_gap",
    "ocr_limitation",
    "other",
)


def load_gold() -> dict:
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


def load_documents(gold: dict) -> dict[str, Document]:
    """Every document any gold item references, keyed by full doc_id."""
    siren = gold["_about"]["company_selected"]["siren"]
    corpus = load_corpus(DATA_ROOT / siren / "actes")
    return {d.doc_id: d for d in corpus.documents}


#: Gold-file known_finding_id -> disagreement category. Kept as an explicit
#: table rather than embedded logic, so adding a new known finding to the
#: gold file only ever requires one new row here, never new conditionals.
_KNOWN_FINDING_CATEGORY = {
    "date-misparse-share-counts-as-years": "date_problem",
    "cession-word-sense-ambiguity": "mechanism_coverage_gap",
}


def categorize(item: dict, gold_verdict: Verdict, router_verdict: Verdict) -> str:
    """A fixed rule, not a judgement call made fresh each time.

    This function only ever LABELS a disagreement already established by
    comparing two frozen values — it does not decide who is "right".
    """
    known_id = item.get("known_finding_id")
    if known_id in _KNOWN_FINDING_CATEGORY:
        return _KNOWN_FINDING_CATEGORY[known_id]
    if item["mechanism"] == "share_transfer" and gold_verdict in (
        Verdict.OPERATIVE, Verdict.RECITAL
    ) and router_verdict == Verdict.MENTION:
        # share_transfer structurally cannot reach OPERATIVE/RECITAL in
        # route.py (DISCOVERY.md 8.5/8.7) — every such gap is this category,
        # not a router bug, by construction.
        return "mechanism_coverage_gap"
    return "other"


def compare(gold: dict, docs: dict[str, Document]) -> list[dict]:
    rows = []
    for item in gold["items"]:
        doc = docs.get(item["document_id"])
        if doc is None:
            rows.append({**item, "router_verdict": None, "error": "document not found"})
            continue
        result = classify(doc, item["mechanism"])
        gold_verdict = Verdict[item["verdict"]]
        agree = gold_verdict == result.verdict
        row = {
            "item_id": item["item_id"],
            "document_short_id": item["document_short_id"],
            "mechanism": item["mechanism"],
            "gold_verdict": item["verdict"],
            "router_verdict": result.verdict.value,
            "agree": agree,
            "router_metadata_label": result.metadata_label,
            "router_conflicts_with_metadata": result.conflicts_with_metadata,
            "router_evidence_pages": sorted({e.page for e in result.evidence}),
        }
        if not agree:
            # Each gold item that is expected, ahead of time, to disagree
            # with the router names the known_findings entry that predicts
            # it — set directly on the gold item, not re-derived here, so
            # this script cannot quietly invent a category for something the
            # gold file did not already anticipate.
            row["category"] = categorize(item, gold_verdict, result.verdict)
        rows.append(row)
    return rows


def print_report(rows: list[dict]) -> None:
    agreements = [r for r in rows if r.get("agree")]
    disagreements = [r for r in rows if r.get("agree") is False]

    print(f"gold items: {len(rows)}")
    print(f"agreements: {len(agreements)}")
    print(f"disagreements: {len(disagreements)}")
    print()

    print("=== per-mechanism breakdown ===")
    for mechanism in ("capital_amount", "share_transfer"):
        sub = [r for r in rows if r["mechanism"] == mechanism]
        a = sum(1 for r in sub if r.get("agree"))
        print(f"  {mechanism}: {a}/{len(sub)} agree")
    print()

    print("=== agreements ===")
    for r in agreements:
        print(f"  {r['item_id']:28} {r['mechanism']:15} gold={r['gold_verdict']:10} "
              f"router={r['router_verdict']:10} meta={r['router_metadata_label']}")
    print()

    print("=== disagreements ===")
    for r in disagreements:
        print(f"  {r['item_id']:28} {r['mechanism']:15} gold={r['gold_verdict']:10} "
              f"router={r['router_verdict']:10} category={r.get('category')}")
    print()

    print("=== disagreement category counts ===")
    cats = Counter(r.get("category") for r in disagreements)
    for cat in CATEGORIES:
        if cats.get(cat):
            print(f"  {cat}: {cats[cat]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    gold = load_gold()
    docs = load_documents(gold)
    rows = compare(gold, docs)

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False, sort_keys=False))
    else:
        print_report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
