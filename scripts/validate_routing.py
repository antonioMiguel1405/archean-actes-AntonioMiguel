#!/usr/bin/env python
"""Cross-corpus validation of the routing signals measured in ARCHEAN.

`scripts/analyze_routing.py` measured candidate phrases against ARCHEAN's 17
documents. This script asks the next question: do those measurements hold
anywhere else, or did they describe one company's drafting habits?

It reuses analyze_routing's primitives (folding, word-boundary matching, line
reading, corpus loading) rather than restating them, so a fix there cannot
silently diverge from the validation here.

What can and cannot be measured cross-corpus
--------------------------------------------
This is the central methodological constraint and it shapes every command
below. ARCHEAN has a hand-verified label set (ARCHEAN_GOLD, built from
tests/golden_capital_chain.json plus content read directly). **The other 19
companies have no such thing.** Their only label is `typeRdd`, which the
previous step proved is not reliably scoped to its own PDF (…ec2 claims an
augmentation its own text does not contain; the real one is in …ec4, whose
typeRdd is empty).

So this script never reports "accuracy" outside ARCHEAN. It reports:

  prevalence   how often a signal fires, per company. No label needed, so
               this is a fact about the corpus, not about a label.
  agreement    signal vs typeRdd, as AGREEMENT, not accuracy. A disagreement
               is not a signal error — it is a disagreement between two
               imperfect sources, and `conflicts` enumerates them without
               picking a winner.
  gold         true TP/FP/FN/TN, ARCHEAN only, where a trustworthy label exists.

Deliberately absent: any composite score, any weighting, any confidence
number. Rules here are boolean and their inputs are printed.

Commands
--------
    prevalence   per-signal, per-company firing counts (no label)
    agreement    signal vs typeRdd, split ARCHEAN / OTHERS / ALL
    conflicts    documents where typeRdd and content disagree, both recorded
    unlabeled    every OCR'd document with no typeRdd, and what fires in it
    scope        same-line vs adjacent vs page vs document, against gold
    rules        composite boolean rules, against gold, with the evidence
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_routing import (  # noqa: E402
    ARCHEAN_GOLD,
    ARCHEAN_SIREN,
    Line,
    _phrase_pattern,
    default_data_root,
    fold,
    load_all_actes,
    read_document_lines,
    type_rdd_labels,
)
from archean.corpus import Document  # noqa: E402
from archean.frenchnum import FrenchParseError, parse_french_date_parts  # noqa: E402

# ---------------------------------------------------------------------------
# the signals carried over from analyze_routing, plus the vocabulary variants
# that only became visible once the other 19 companies were looked at
# ---------------------------------------------------------------------------

#: Measured in ARCHEAN by the previous step. Re-measured here everywhere else.
CARRIED_OVER = [
    "reduction du capital",
    "augmentation de capital",
    "augmentation du capital",
    "pour le porter de",
    "valeur nominale",
    "prime d'emission",
    "cession",
    "ordres de mouvement",
    "protocole de cession",
    "nouvel actionnaire",
    "ceder",
]

#: ARCHEAN is a SAS and speaks of `actions`; much of the rest of the corpus is
#: SARL and speaks of `parts sociales`. A signal set derived from ARCHEAN alone
#: cannot see that split, which is exactly why these are measured separately.
LEGAL_FORM_VARIANTS = [
    "parts sociales",
    "cession de parts",
    "cession d'actions",
    "ordre de mouvement",
]

ALL_SIGNALS = CARRIED_OVER + LEGAL_FORM_VARIANTS

#: A euro amount. Operative capital text states amounts; the permissive
#: Article 8 boilerplate ("le capital social peut être augmenté...") does not.
AMOUNT = re.compile(r"\d[\d .,]*(euros?|eur\b|€)")

#: Capital-change constructions, as opposed to a bare mention of the topic.
TRANSITION = re.compile(
    r"\b(augmente(?:e|es|s)? de|reduit(?:e|s)? de|porter le capital"
    r"|pour le porter|ramene(?:e)? de|augmenter le capital|reduire le capital"
    r"|augmentation de capital de|reduction du capital de)\b"
)

#: The historical back-reference that opens a statutes recital:
#: "Aux termes de l'assemblée générale extraordinaire du 17/05/2005, le capital
#: social a été augmenté de 113.000 euros...". Article 6 of every updated
#: statutes reprints the company's whole capital history in this form, which is
#: why a bare transition+amount match cannot tell an operative resolution from
#: a recital of one that happened years earlier.
BACKREF = re.compile(r"\baux termes (de|des)\b")


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    """One place a signal fired, with enough to go look at it."""

    doc_id: str
    page: int
    line_index: int
    signal: str
    text: str


def find_hits(doc: Document, signal: str) -> list[Hit]:
    pattern = _phrase_pattern(signal)
    return [
        Hit(doc.doc_id, ln.page, ln.index, signal, ln.text)
        for ln in read_document_lines(doc)
        if pattern.search(ln.folded)
    ]


def fires(doc: Document, signal: str) -> bool:
    return bool(find_hits(doc, signal))


# ---------------------------------------------------------------------------
# contingency counting — used for both gold (accuracy) and typeRdd (agreement)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Contingency:
    tp: list[str]
    fp: list[str]
    fn: list[str]
    tn: list[str]

    @property
    def counts(self) -> tuple[int, int, int, int]:
        return len(self.tp), len(self.fp), len(self.fn), len(self.tn)

    def __str__(self) -> str:
        t, f, n, x = self.counts
        return f"TP={t:<3} FP={f:<3} FN={n:<3} TN={x:<3}"


def contingency(
    docs: Sequence[tuple[str, Document]],
    predicate: Callable[[Document], bool],
    target: Callable[[Document], bool],
) -> Contingency:
    tp: list[str] = []
    fp: list[str] = []
    fn: list[str] = []
    tn: list[str] = []
    for _siren, doc in docs:
        p, t = predicate(doc), target(doc)
        (tp if (p and t) else fp if (p and not t) else fn if t else tn).append(doc.doc_id)
    return Contingency(tp, fp, fn, tn)


# ---------------------------------------------------------------------------
# document sets
# ---------------------------------------------------------------------------


def ocr_documents(data_root: Path) -> list[tuple[str, Document]]:
    corpora = load_all_actes(data_root)
    return [
        (siren, doc)
        for siren in sorted(corpora)
        for doc in corpora[siren].documents
        if doc.has_ocr
    ]


def split_archean(
    docs: Sequence[tuple[str, Document]]
) -> tuple[list[tuple[str, Document]], list[tuple[str, Document]]]:
    archean = [(s, d) for s, d in docs if s == ARCHEAN_SIREN]
    others = [(s, d) for s, d in docs if s != ARCHEAN_SIREN]
    return archean, others


# --- typeRdd-derived weak labels, spanning legal forms ---------------------


def typerdd_capital(doc: Document) -> bool:
    lab = type_rdd_labels(doc)
    if lab["capital_increase"] or lab["capital_decrease"]:
        return True
    decisions = " | ".join(fold(e.decision or e.type_acte) for e in doc.type_rdd)
    return "capital" in decisions and (
        "modification" in decisions or "conversion" in decisions
    )


def typerdd_transfer(doc: Document) -> bool:
    return type_rdd_labels(doc)["share_transfer"]


def has_typerdd(doc: Document) -> bool:
    return bool(doc.type_rdd)


# ---------------------------------------------------------------------------
# command: prevalence
# ---------------------------------------------------------------------------


def cmd_prevalence(args: argparse.Namespace) -> int:
    docs = ocr_documents(args.data_root)
    archean, others = split_archean(docs)
    other_companies = sorted({s for s, _ in others})

    print(f"OCR'd acte documents: {len(docs)}  "
          f"(ARCHEAN {len(archean)}, other companies {len(others)} "
          f"across {len(other_companies)} sirens)")
    print()
    print("Signal firing counts. No label involved — these are facts about the")
    print("corpus, not claims about correctness.")
    print()
    header = (f"{'signal':<24} {'ARCHEAN':>10} {'OTHERS':>10} "
              f"{'ALL':>10} {'companies':>11}")
    print(header)
    print("-" * len(header))
    for signal in ALL_SIGNALS:
        a = sum(1 for _, d in archean if fires(d, signal))
        o = sum(1 for _, d in others if fires(d, signal))
        comps = len({s for s, d in others if fires(d, signal)})
        print(f"{signal:<24} {a:>4}/{len(archean):<5} {o:>4}/{len(others):<5} "
              f"{a + o:>4}/{len(docs):<5} {comps:>5}/{len(other_companies):<5}")

    print()
    print("A signal firing in 0 other companies is ARCHEAN-specific drafting,")
    print("not a validated cross-corpus signal, however clean it looked before.")
    return 0


# ---------------------------------------------------------------------------
# command: agreement
# ---------------------------------------------------------------------------


def cmd_agreement(args: argparse.Namespace) -> int:
    docs = [(s, d) for s, d in ocr_documents(args.data_root) if has_typerdd(d)]
    archean, others = split_archean(docs)

    target = typerdd_transfer if args.klass == "transfer" else typerdd_capital
    print(f"AGREEMENT with typeRdd:{args.klass} — NOT accuracy.")
    print("typeRdd is a weak label of known-unreliable per-document scope; a")
    print("disagreement here is a disagreement between two imperfect sources.")
    print()
    print(f"documents with OCR and a typeRdd: {len(docs)} "
          f"(ARCHEAN {len(archean)}, others {len(others)})")
    print(f"labelled positive by typeRdd: "
          f"{sum(1 for _, d in docs if target(d))}")
    print()
    print(f"{'signal':<24} {'scope':<8} {'agreement':<30}")
    print("-" * 64)
    for signal in ALL_SIGNALS:
        for name, subset in (("ARCHEAN", archean), ("OTHERS", others), ("ALL", docs)):
            if not subset:
                continue
            c = contingency(subset, lambda d, s=signal: fires(d, s), target)
            print(f"{signal if name == 'ARCHEAN' else '':<24} {name:<8} {c}")
        print()
    return 0


# ---------------------------------------------------------------------------
# command: conflicts
# ---------------------------------------------------------------------------


def cmd_conflicts(args: argparse.Namespace) -> int:
    docs = [(s, d) for s, d in ocr_documents(args.data_root) if has_typerdd(d)]

    print("Documents where typeRdd and content disagree about a capital event.")
    print("Both readings are recorded. Neither is declared correct: without")
    print("reading each document there is no basis to say which source is wrong,")
    print("and reading them to fix the label would make the label circular.")
    print()

    strong = _strong_capital_predicate()
    rows_a: list[tuple[str, Document]] = []
    rows_b: list[tuple[str, Document]] = []
    for siren, doc in docs:
        meta = typerdd_capital(doc)
        content = strong(doc)
        if meta and not content:
            rows_a.append((siren, doc))
        elif content and not meta:
            rows_b.append((siren, doc))

    print(f"=== typeRdd says capital, content shows no operative capital text "
          f"({len(rows_a)}) ===")
    for siren, doc in rows_a:
        print(f"  {siren}/{doc.doc_id[-4:]}  {doc.filename_date}  "
              f"numChrono={doc.num_chrono}")
        print(f"      typeRdd: {doc.type_rdd_summary()[:90]}")

    print()
    print(f"=== content shows operative capital text, typeRdd does not say "
          f"capital ({len(rows_b)}) ===")
    for siren, doc in rows_b:
        print(f"  {siren}/{doc.doc_id[-4:]}  {doc.filename_date}  "
              f"numChrono={doc.num_chrono}")
        print(f"      typeRdd: {doc.type_rdd_summary()[:90]}")
        for hit in _operative_hits(doc)[:2]:
            print(f"      p{hit.page}: {hit.text[:88]}")

    print()
    print("numChrono neighbours — the …ec2/…ec4 pattern was a decision tag")
    print("landing on the wrong file within one filing batch. Same-batch groups:")
    by_batch: dict[tuple[str, str], list[Document]] = collections.defaultdict(list)
    for siren, doc in ocr_documents(args.data_root):
        if doc.num_chrono:
            by_batch[(siren, doc.num_chrono)].append(doc)
    shared = {k: v for k, v in by_batch.items() if len(v) > 1}
    for (siren, chrono), group in sorted(shared.items()):
        labels = [f"{d.doc_id[-4:]}({'T' if typerdd_capital(d) else '-'}"
                  f"{'C' if strong(d) else '-'})" for d in group]
        print(f"  {siren} numChrono={chrono}: {' '.join(labels)}   "
              f"[T=typeRdd says capital, C=content shows it]")
    return 0


# ---------------------------------------------------------------------------
# command: unlabeled
# ---------------------------------------------------------------------------


def cmd_unlabeled(args: argparse.Namespace) -> int:
    docs = ocr_documents(args.data_root)
    unlabeled = [(s, d) for s, d in docs if not has_typerdd(d)]

    print(f"OCR'd documents with NO typeRdd: {len(unlabeled)} of {len(docs)} "
          f"({100 * len(unlabeled) / len(docs):.0f}%)")
    print("ARCHEAN contributed 2 of these; the population is corpus-wide, which")
    print("is what decides whether typeRdd can be a primary routing input.")
    print()

    strong = _strong_capital_predicate()
    by_company: dict[str, list[Document]] = collections.defaultdict(list)
    for siren, doc in unlabeled:
        by_company[siren].append(doc)

    n_capital = 0
    n_transfer = 0
    n_silent = 0
    for siren in sorted(by_company):
        print(f"--- {siren} ({len(by_company[siren])}) ---")
        for doc in by_company[siren]:
            cap = strong(doc)
            tr = fires(doc, "cession") or fires(doc, "cession de parts")
            flags = []
            if cap:
                flags.append("capital-operative")
                n_capital += 1
            if tr:
                flags.append("cession-mention")
                n_transfer += 1
            if not flags:
                flags.append("no capital/transfer signal")
                n_silent += 1
            print(f"  {doc.doc_id[-4:]}  {doc.filename_date}  "
                  f"{doc.page_count:>3}p  {', '.join(flags)}")
            if cap:
                for hit in _operative_hits(doc)[:1]:
                    print(f"        p{hit.page}: {hit.text[:84]}")

    print()
    print(f"of {len(unlabeled)} unlabelled documents: {n_capital} show operative "
          f"capital text, {n_transfer} mention a cession, {n_silent} show neither")
    return 0


# ---------------------------------------------------------------------------
# command: scope
# ---------------------------------------------------------------------------

CAPITAL_TOPIC = [
    "augmentation de capital",
    "augmentation du capital",
    "reduction du capital",
    "capital social",
]


def _page_groups(lines: Sequence[Line]) -> dict[int, list[Line]]:
    groups: dict[int, list[Line]] = collections.defaultdict(list)
    for ln in lines:
        groups[ln.page].append(ln)
    return groups


def _topic_amount_at_scope(doc: Document, scope: str) -> bool:
    """Capital topic co-occurring with a euro amount, at a given scope."""
    lines = read_document_lines(doc)
    patterns = [_phrase_pattern(p) for p in CAPITAL_TOPIC]

    def topic(ln: Line) -> bool:
        return any(p.search(ln.folded) for p in patterns)

    if scope == "line":
        return any(topic(ln) and AMOUNT.search(ln.folded) for ln in lines)
    if scope == "adjacent":
        for i, ln in enumerate(lines):
            if not topic(ln):
                continue
            for j in (i - 1, i, i + 1):
                if 0 <= j < len(lines) and lines[j].page == ln.page:
                    if AMOUNT.search(lines[j].folded):
                        return True
        return False
    if scope == "page":
        return any(
            any(topic(ln) for ln in group) and any(AMOUNT.search(ln.folded) for ln in group)
            for group in _page_groups(lines).values()
        )
    if scope == "document":
        return any(topic(ln) for ln in lines) and any(
            AMOUNT.search(ln.folded) for ln in lines
        )
    raise ValueError(scope)


def cmd_scope(args: argparse.Namespace) -> int:
    docs = ocr_documents(args.data_root)
    archean, _ = split_archean(docs)
    gold = ARCHEAN_GOLD["capital_amount"]

    print("Does routing need page-level location, or is document-level presence")
    print("enough? Rule under test: a capital topic phrase co-occurring with a")
    print("euro amount, at four scopes. ARCHEAN only — the only gold labels.")
    print()
    print(f"{'scope':<12} {'contingency':<34} false positives")
    print("-" * 78)
    for scope in ("line", "adjacent", "page", "document"):
        c = contingency(
            archean,
            lambda d, s=scope: _topic_amount_at_scope(d, s),
            lambda d: d.doc_id in gold,
        )
        print(f"{scope:<12} {str(c):<34} {[i[-4:] for i in c.fp]}")
    return 0


# ---------------------------------------------------------------------------
# command: rules — composite boolean rules, no weights, no score
# ---------------------------------------------------------------------------


def _operative_hits(doc: Document) -> list[Hit]:
    """Transition+amount lines that are NOT a statutes historical recital.

    Article 6 of updated statutes recites the company's entire capital history
    ("Aux termes de l'AGE du 17/05/2005, le capital social a été augmenté de
    113.000 euros afin d'être porté à 150.000 euros."). That text is lexically
    identical to an operative resolution, so a transition+amount match alone
    cannot tell them apart. The back-reference opener is what distinguishes
    them, and it is checked on the matching line and the line before it.
    """
    lines = read_document_lines(doc)
    out: list[Hit] = []
    for i, ln in enumerate(lines):
        if not (TRANSITION.search(ln.folded) and AMOUNT.search(ln.folded)):
            continue
        prev = lines[i - 1] if i > 0 and lines[i - 1].page == ln.page else None
        recital = BACKREF.search(ln.folded) or (prev and BACKREF.search(prev.folded))
        if not recital:
            out.append(Hit(doc.doc_id, ln.page, ln.index, "operative-capital", ln.text))
    return out


def _past_date_near(lines: Sequence[Line], i: int, doc_year: int, window: int = 3) -> int | None:
    """A year earlier than the document's own, stated near line ``i``.

    Uses archean.frenchnum, which already parses every date form this corpus
    contains, rather than a second date regex that could drift from it.
    """
    for j in range(max(0, i - window), min(len(lines), i + 2)):
        if lines[j].page != lines[i].page:
            continue
        try:
            parts = parse_french_date_parts(lines[j].text)
        except FrenchParseError:
            continue
        if parts.year and parts.year < doc_year:
            return parts.year
    return None


def operative_hits_by_date(doc: Document) -> list[Hit]:
    """Transition+amount lines with no earlier year stated nearby.

    A generalisation of :func:`_operative_hits`. That function excludes
    recitals by their opening words ("aux termes de"), which was measured to
    work on ARCHEAN but was then found to miss a second construction used
    elsewhere in the corpus: HADEAN writes "Lors de l'augmentation de capital
    décidée par l'assemblée générale extraordinaire du 30 avril 2008 :"
    followed by a bulleted history. Enumerating recital openers is open-ended;
    what both forms share is that they *cite a date earlier than the document
    itself*, while an operative resolution is dated now. That is what this
    checks.
    """
    lines = read_document_lines(doc)
    year = doc.filename_date.year
    out: list[Hit] = []
    for i, ln in enumerate(lines):
        if not (TRANSITION.search(ln.folded) and AMOUNT.search(ln.folded)):
            continue
        if _past_date_near(lines, i, year) is None:
            out.append(Hit(doc.doc_id, ln.page, ln.index, "operative-capital-date", ln.text))
    return out


def has_operative_capital_text(doc: Document) -> bool:
    """True when the document contains at least one non-recital transition."""
    return bool(_operative_hits(doc))


def has_operative_capital_text_by_date(doc: Document) -> bool:
    return bool(operative_hits_by_date(doc))


def _strong_capital_predicate() -> Callable[[Document], bool]:
    """Factory kept for call sites that pass a predicate around."""
    return has_operative_capital_text


def _rule_topic_amount_page(doc: Document) -> bool:
    return _topic_amount_at_scope(doc, "page")


def _rule_transition_amount(doc: Document) -> bool:
    lines = read_document_lines(doc)
    return any(TRANSITION.search(ln.folded) and AMOUNT.search(ln.folded) for ln in lines)


RULES: list[tuple[str, Callable[[Document], bool], str]] = [
    ("topic + amount (page)", _rule_topic_amount_page,
     "capital topic and a euro amount on the same page"),
    ("transition + amount", _rule_transition_amount,
     "a capital-change construction and an amount on the same line"),
    ("transition + amount, not recital", has_operative_capital_text,
     "as above, excluding lines opened by 'aux termes de' (statutes recital)"),
    ("transition + amount, no earlier date nearby", has_operative_capital_text_by_date,
     "as above, but recitals identified by citing a year earlier than the "
     "document's own — generalises past 'aux termes de' to the bulleted "
     "'Lors de ... du <date>' form used elsewhere in the corpus"),
]


def cmd_rules(args: argparse.Namespace) -> int:
    docs = ocr_documents(args.data_root)
    archean, _ = split_archean(docs)
    gold = ARCHEAN_GOLD["capital_amount"]

    print("Composite boolean rules against ARCHEAN's gold labels. No weights,")
    print("no score: each rule is a conjunction whose inputs are printed below.")
    print()
    for name, rule, description in RULES:
        c = contingency(archean, rule, lambda d: d.doc_id in gold)
        print(f"{name}")
        print(f"    {description}")
        print(f"    {c}")
        if c.fp:
            print(f"    FP: {[i[-4:] for i in c.fp]}")
        if c.fn:
            print(f"    FN: {[i[-4:] for i in c.fn]}")
        print()

    print("Evidence for the last rule, per ARCHEAN document — this is what an")
    print("auditable router would have to be able to show:")
    print()
    for _siren, doc in archean:
        hits = _operative_hits(doc)
        if not hits:
            continue
        mark = "gold" if doc.doc_id in gold else "NOT-gold"
        print(f"  {doc.doc_id[-4:]} ({doc.filename_date}, {mark})")
        for hit in hits[:3]:
            print(f"      p{hit.page} line{hit.line_index}: {hit.text[:82]}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-root", type=Path, default=None)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("prevalence").set_defaults(func=cmd_prevalence)

    p_agree = sub.add_parser("agreement")
    p_agree.add_argument("--class", dest="klass",
                          choices=["capital", "transfer"], default="capital")
    p_agree.set_defaults(func=cmd_agreement)

    sub.add_parser("conflicts").set_defaults(func=cmd_conflicts)
    sub.add_parser("unlabeled").set_defaults(func=cmd_unlabeled)
    sub.add_parser("scope").set_defaults(func=cmd_scope)
    sub.add_parser("rules").set_defaults(func=cmd_rules)

    args = parser.parse_args(argv)
    args.data_root = args.data_root or default_data_root()
    if not args.data_root.is_dir():
        print(f"no data/ at {args.data_root}", file=sys.stderr)
        return 2

    if not getattr(args, "func", None):
        # No subcommand: run the overview that answers "did it generalize?"
        return cmd_prevalence(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
