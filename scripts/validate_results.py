#!/usr/bin/env python
"""Validate results.json against the challenge schema and this project's
own internal invariants.

Two layers, both must pass:
  1. jsonschema validation against
     ../engineering-challenges/challenges/actes/schema/results.schema.json
     — required fields, types, enum values, nested structure.
  2. archean.timeline.check_invariants on every capital_timeline row, plus
     a handful of cross-cutting checks the schema itself cannot express
     (chronological order, every source.inpi_id real, every event_id
     referenced by capital_timeline actually exists).

Usage:
    python scripts/validate_results.py [path/to/results.json]
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SCHEMA_PATH = (
    REPO_ROOT.parent / "engineering-challenges" / "challenges" / "actes"
    / "schema" / "results.schema.json"
)


def validate(results_path: Path) -> list[str]:
    problems: list[str] = []

    data = json.loads(results_path.read_text(encoding="utf-8"))

    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        problems.append(f"schema: {'/'.join(str(p) for p in err.path)}: {err.message}")

    if problems:
        return problems  # a schema-invalid file cannot be checked further

    from archean.timeline import CapTableState, Holder, check_invariants

    event_ids = set()
    for ev in data["events"]:
        if ev["event_id"] in event_ids:
            problems.append(f"duplicate event_id {ev['event_id']!r}")
        event_ids.add(ev["event_id"])
        bbox = ev["source"]["bbox"]
        if not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
            problems.append(f"{ev['event_id']}: degenerate bbox {bbox}")
        if not all(0 <= v <= 1 for v in bbox):
            problems.append(f"{ev['event_id']}: bbox out of [0,1]: {bbox}")

    prev_date = None
    for row in data["capital_timeline"]:
        for eid in row.get("caused_by", []):
            if eid not in event_ids:
                problems.append(f"capital_timeline {row['as_of']}: caused_by references unknown event_id {eid!r}")
        if prev_date is not None and row["as_of"] < prev_date:
            problems.append(f"capital_timeline out of order: {row['as_of']} after {prev_date}")
        prev_date = row["as_of"]

        state = CapTableState(
            as_of=row["as_of"],
            capital_eur=Decimal(str(row["capital_eur"])) if row["capital_eur"] is not None else None,
            shares_total=row.get("shares_total"),
            nominal_eur=Decimal(str(row["nominal_eur"])) if row.get("nominal_eur") is not None else None,
            holders=tuple(
                Holder(
                    name=h["name"], kind=h.get("kind", "UNKNOWN"),
                    siren=h.get("siren"), shares=h.get("shares"), pct=h.get("pct"),
                )
                for h in row["holders"]
            ),
            caused_by=tuple(row.get("caused_by", [])),
        )
        problems.extend(check_invariants(state))

    real_inpi_ids = _real_inpi_ids()
    for ev in data["events"]:
        inpi_id = ev["source"]["inpi_id"]
        if inpi_id not in real_inpi_ids:
            problems.append(f"{ev['event_id']}: inpi_id {inpi_id!r} does not match any document in the corpus")

    return problems


def _real_inpi_ids() -> set[str]:
    from archean.corpus import load_corpus

    data_root = REPO_ROOT.parent / "engineering-challenges" / "data"
    corpus = load_corpus(data_root / "480489707" / "actes")
    return {d.doc_id for d in corpus.documents}


def main() -> int:
    results_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "results.json"
    if not results_path.exists():
        print(f"no such file: {results_path}", file=sys.stderr)
        return 2

    problems = validate(results_path)
    if problems:
        print(f"{results_path}: {len(problems)} problem(s)")
        for p in problems:
            print(" -", p)
        return 1

    print(f"{results_path}: valid (schema + internal invariants)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
