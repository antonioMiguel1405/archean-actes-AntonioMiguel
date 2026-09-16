#!/usr/bin/env python
"""Measure candidate routing signals against the corpus. Not route.py.

This is a discovery tool, not a classifier. It answers one question at a
time — "how often does this phrase appear in documents labelled X, versus
documents not labelled X?" — and prints raw counts. It never computes a score
or a ranking, and it never decides that a signal is "good enough": that
judgement belongs to whoever reads the numbers and to `route.py`, once it
exists.

Two label sources are used, and they are never conflated:

  gold      A small (17-document), hand-verified label set for ARCHEAN's own
            actes, built from facts already established elsewhere in this
            project: `tests/golden_capital_chain.json` (which documents
            ground a real capital-amount change, with page+bbox+snippet) and
            content this conversation has read directly (which documents
            discuss a share transfer). This is the only label source in this
            script that is actually trustworthy.

  typerdd   A weak label built from `meta['typeRdd']`, across all 20
            companies' actes. Large (115 OCR'd documents) but demonstrably
            noisy: see `p0` / DISCOVERY.md 4.1-W for a document (…ec2) whose
            typeRdd claims "Augmentation du capital social" while its OCR
            text contains no such text at all — the real augmentation text
            lives in a different, adjacently-filed document whose own
            typeRdd is empty. typerdd labels are useful for generating
            candidates over a bigger sample; they are not a ground truth and
            every count computed against them says so.

Commands
--------
    census    typeRdd decision-string frequency across the whole corpus
    explore   line/word n-gram frequency, target class vs the rest
    signal    TP/FP/FN/TN for one phrase against one label source
    p0        dedicated investigation of ARCHEAN's two typeRdd-empty P0 docs
    gold      TP/FP/FN/TN for a batch of candidates against the ARCHEAN gold set

No fuzzy matching, no edit distance, no embeddings, no LLM calls. Phrase
matching is exact substring, on accent-and-case-folded text. Word-level
`_reocr_*` repair is never applied — see DISCOVERY.md's OCR-structure section
for why (this file quotes, it never corrects).
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from archean.corpus import Corpus, Document, load_corpus  # noqa: E402

# ---------------------------------------------------------------------------
# text extraction — thin, and it says what it does not do
# ---------------------------------------------------------------------------


def fold(s: str) -> str:
    """Lower-case, strip accents, collapse whitespace. Matching only.

    The returned string is never displayed or stored as a "corrected" value;
    every report below prints the original OCR text alongside any folded
    form it used for matching.
    """
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", s).strip().lower()


@dataclass(frozen=True)
class Line:
    """One OCR line, with enough context to say where it came from."""

    doc_id: str
    page: int
    index: int          # position in that page's ocr[] array
    text: str            # verbatim
    score: float | None

    @property
    def folded(self) -> str:
        return fold(self.text)


def read_page_lines(doc: Document, page_number: int) -> list[Line]:
    """Lines of one page, in the order the OCR JSON emits them.

    Filters lines with score == 0.0, which measurement showed are always
    empty-text detections (a region flagged but never transcribed) — 62 of
    them in the ARCHEAN corpus, none carrying any text. Nothing else is
    filtered: low-but-nonzero-confidence fragments are kept, since they are
    rare and phrase-level substring matching is not sensitive to an isolated
    garbage token elsewhere on the page.
    """
    page = doc.page(page_number)
    if not page.has_ocr:
        return []
    data = json.loads(page.ocr_path.read_text(encoding="utf-8"))
    out = []
    for i, item in enumerate(data.get("ocr") or []):
        if item.get("score") == 0.0:
            continue
        text = item.get("text") or ""
        if not text.strip():
            continue
        out.append(Line(doc.doc_id, page_number, i, text, item.get("score")))
    return out


def read_document_lines(doc: Document) -> list[Line]:
    """Every line of every OCR'd page of one document, page order, line order."""
    out: list[Line] = []
    for p in doc.pages:
        if p.has_ocr:
            out.extend(read_page_lines(doc, p.number))
    return out


# ---------------------------------------------------------------------------
# labels
# ---------------------------------------------------------------------------

ARCHEAN_SIREN = "480489707"

#: ARCHEAN's own hand-verified labels. Every entry cites where the fact came
#: from, so this is not a guess dressed up as ground truth.
#:
#: capital_amount:  documents that ground a real capital-amount change in
#:   tests/golden_capital_chain.json (source.inpi_id), plus …ebf, which
#:   AUTHORISES the 2017 reduction that …ebe REALISES — golden_capital_chain
#:   cites only …ebe as the numeric source (that is where the delta and the
#:   after-capital are stated), but …ebf is the document that decides the
#:   reduction happens at all. Both are capital-amount documents; the golden
#:   chain's source field alone under-counts them, by design (it records the
#:   number's origin, not "everything relevant").
#: share_transfer:  documents this conversation has read directly and found
#:   discussing a transfer of shares between named parties: …ec2 (the 2005-08
#:   cession ratification and its ordres de mouvement) and …ec7 (which
#:   authorises AUMONT to cede 225 shares to CAPGRAS, in addition to being a
#:   capital-amount document).
#: neither: every other ARCHEAN acte.
ARCHEAN_GOLD: dict[str, set[str]] = {
    "capital_amount": {
        "63e9593b8be6eb9f9d257ec5",  # constitution — states the initial capital
        "63e9593b8be6eb9f9d257ec4",  # 2005-05-17 increase, realised
        "63e9593b8be6eb9f9d257ec7",  # 2006-10-20 increase, decided
        "63e9593b8be6eb9f9d257ec3",  # 2008-06-27 split + two increases
        "63e9593b8be6eb9f9d257ebf",  # 2017-01-19 reduction, authorised
        "63e9593a8be6eb9f9d257ebe",  # 2017-02-21 reduction, realised
        "63e9593b8be6eb9f9d257ec0",  # 2018-03-23 increase via reserves
    },
    "share_transfer": {
        "63e9593b8be6eb9f9d257ec2",  # 2005-08 cessions ratified
        "63e9593b8be6eb9f9d257ec7",  # AUMONT -> CAPGRAS, 225 shares
    },
}


def type_rdd_labels(doc: Document) -> dict[str, bool]:
    """Weak, noisy labels from meta['typeRdd']. See the module docstring.

    A document is labelled True for a class if any typeRdd decision string
    (folded) contains all of that class's required substrings.
    """
    decisions = " | ".join(fold(e.decision or e.type_acte) for e in doc.type_rdd)
    return {
        "capital_increase": "augmentation" in decisions and "capital" in decisions,
        "capital_decrease": "reduction" in decisions and "capital" in decisions,
        "constitution": "constitution" in decisions,
        "share_transfer": "cession" in decisions or "donation" in decisions,
    }


# ---------------------------------------------------------------------------
# corpus-wide loading
# ---------------------------------------------------------------------------


def load_all_actes(data_root: Path) -> dict[str, Corpus]:
    """Every company's actes/ folder that loads cleanly. Order: sorted siren."""
    out: dict[str, Corpus] = {}
    for company_dir in sorted(data_root.iterdir()):
        actes = company_dir / "actes"
        if not actes.is_dir():
            continue
        try:
            out[company_dir.name] = load_corpus(actes)
        except Exception as exc:  # pragma: no cover - defensive, not expected
            print(f"skipping {actes}: {exc}", file=sys.stderr)
    return out


def all_documents(corpora: dict[str, Corpus]) -> list[tuple[str, Document]]:
    """(siren, Document) for every document, sorted for determinism."""
    out = []
    for siren in sorted(corpora):
        for doc in corpora[siren].documents:
            out.append((siren, doc))
    return out


# ---------------------------------------------------------------------------
# command: census
# ---------------------------------------------------------------------------


def cmd_census(args: argparse.Namespace) -> int:
    corpora = load_all_actes(args.data_root)
    docs = all_documents(corpora)
    with_ocr = [d for _, d in docs if d.has_ocr]

    print(f"companies with an actes/ folder: {len(corpora)}")
    print(f"total acte documents: {len(docs)}   with OCR: {len(with_ocr)}")
    print()

    decisions = collections.Counter()
    for _, d in docs:
        for e in d.type_rdd:
            key = fold(e.decision) if e.decision else f"[no-decision] {fold(e.type_acte)}"
            decisions[key] += 1

    print(f"distinct typeRdd decision strings: {len(decisions)}")
    print()
    print(f"{'count':>6}  decision (folded)")
    for k, v in decisions.most_common(args.top):
        print(f"{v:6d}  {k}")
    return 0


# ---------------------------------------------------------------------------
# command: explore — n-gram frequency, target class vs the rest
# ---------------------------------------------------------------------------


def line_ngrams(text: str, n: int) -> set[str]:
    """Word n-grams within one folded line. A set: presence, not count."""
    words = text.split()
    if len(words) < n:
        return set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def document_ngram_presence(lines: Sequence[Line], n: int) -> set[str]:
    """Every distinct n-gram that appears anywhere in this document.

    Computed per line, not on the whole document joined together — an
    n-gram spanning two OCR lines is not counted. Whether that matters is
    exactly what `explore --cross-line` and the "page-level vs document-level"
    findings in DISCOVERY.md address; this function deliberately does the
    simpler, more conservative thing by default.
    """
    out: set[str] = set()
    for ln in lines:
        out |= line_ngrams(ln.folded, n)
    return out


def cmd_explore(args: argparse.Namespace) -> int:
    corpora = load_all_actes(args.data_root)
    docs = [(s, d) for s, d in all_documents(corpora) if d.has_ocr]

    target_ids: set[str] = set()
    label_source = "typerdd"
    if args.gold_class:
        target_ids = ARCHEAN_GOLD.get(args.gold_class, set())
        label_source = f"gold:{args.gold_class}"
    elif args.label:
        for _, d in docs:
            if type_rdd_labels(d).get(args.label):
                target_ids.add(d.doc_id)
        label_source = f"typerdd:{args.label}"
    else:
        print("pass --label or --gold-class", file=sys.stderr)
        return 2

    target_docs = [(s, d) for s, d in docs if d.doc_id in target_ids]
    other_docs = [(s, d) for s, d in docs if d.doc_id not in target_ids]
    print(f"label source: {label_source}")
    print(f"target documents: {len(target_docs)}   other documents: {len(other_docs)}")
    print()

    target_presence: collections.Counter = collections.Counter()
    other_presence: collections.Counter = collections.Counter()
    for _, d in target_docs:
        for gram in document_ngram_presence(read_document_lines(d), args.n):
            target_presence[gram] += 1
    for _, d in other_docs:
        for gram in document_ngram_presence(read_document_lines(d), args.n):
            other_presence[gram] += 1

    n_target = len(target_docs) or 1
    n_other = len(other_docs) or 1

    # Candidate generation only: ranked by how much more of the target class
    # contains the n-gram than the rest does. This ranking exists to pick
    # what to look at next during exploration; it is not a validated signal
    # and nothing downstream may cite this ordering as evidence.
    rows = []
    for gram, tcount in target_presence.items():
        ocount = other_presence.get(gram, 0)
        target_rate = tcount / n_target
        other_rate = ocount / n_other
        rows.append((target_rate - other_rate, gram, tcount, ocount))
    rows.sort(key=lambda r: (-r[0], r[1]))

    print(f"top {args.top} {args.n}-grams by (target coverage - other coverage), "
          f"for CANDIDATE GENERATION ONLY:")
    print(f"{'target':>8}  {'other':>8}  n-gram")
    for _, gram, tcount, ocount in rows[:args.top]:
        print(f"{tcount:3d}/{n_target:<4d}  {ocount:3d}/{n_other:<4d}  {gram!r}")
    return 0


# ---------------------------------------------------------------------------
# command: signal — TP/FP/FN/TN for one phrase
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalResult:
    phrase: str
    label_source: str
    tp: list[str] = field(default_factory=list)
    fp: list[str] = field(default_factory=list)
    fn: list[str] = field(default_factory=list)
    tn: list[str] = field(default_factory=list)

    def counts(self) -> tuple[int, int, int, int]:
        return len(self.tp), len(self.fp), len(self.fn), len(self.tn)


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Word-boundary-anchored exact match. Still exact matching, not fuzzy.

    Plain substring search was tried first and found to produce a real false
    positive: the bare word "ceder" matched inside "excéder" and "procéder"
    (12 of 17 ARCHEAN documents, all wrong) because Python's `in` operator
    does not respect word boundaries. `\\b` does, and does not require
    treating the apostrophe as a word character — French elision like
    "l'augmentation" still matches a search for "augmentation" because `'`
    is already a non-word character to Python's regex engine. See
    DISCOVERY.md's routing-evidence section for the measurement that found
    this and the corrected count.
    """
    return re.compile(r"\b" + re.escape(fold(phrase)) + r"\b")


def phrase_present(doc: Document, phrase: str) -> bool:
    """True if the folded phrase occurs, word-boundary-matched, in one OCR line.

    Deliberately single-line: see the module docstring and DISCOVERY.md for
    the measurement of how often a target phrase would need to span two
    lines to be found (measured, not assumed).
    """
    pattern = _phrase_pattern(phrase)
    for ln in read_document_lines(doc):
        if pattern.search(ln.folded):
            return True
    return False


def measure_signal(
    docs: Sequence[tuple[str, Document]],
    phrase: str,
    target_ids: set[str],
    label_source: str,
) -> SignalResult:
    result = SignalResult(phrase=phrase, label_source=label_source)
    for _, d in docs:
        present = phrase_present(d, phrase)
        is_target = d.doc_id in target_ids
        bucket = (
            result.tp if is_target and present else
            result.fn if is_target and not present else
            result.fp if not is_target and present else
            result.tn
        )
        bucket.append(d.doc_id)
    return result


def print_signal_result(r: SignalResult) -> None:
    tp, fp, fn, tn = r.counts()
    print(f"phrase: {r.phrase!r}   label: {r.label_source}")
    print(f"  TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    if r.tp:
        print(f"  TP docs: {[i[-4:] for i in r.tp]}")
    if r.fp:
        print(f"  FP docs: {[i[-4:] for i in r.fp]}")
    if r.fn:
        print(f"  FN docs: {[i[-4:] for i in r.fn]}")


def cmd_signal(args: argparse.Namespace) -> int:
    corpora = load_all_actes(args.data_root)
    docs = [(s, d) for s, d in all_documents(corpora) if d.has_ocr]

    if args.gold_class:
        target_ids = ARCHEAN_GOLD.get(args.gold_class, set())
        label_source = f"gold:{args.gold_class}"
        docs = [(s, d) for s, d in docs if s == ARCHEAN_SIREN]
    elif args.label:
        target_ids = {d.doc_id for _, d in docs if type_rdd_labels(d).get(args.label)}
        label_source = f"typerdd:{args.label}"
    else:
        print("pass --label or --gold-class", file=sys.stderr)
        return 2

    result = measure_signal(docs, args.phrase, target_ids, label_source)
    print_signal_result(result)
    return 0


# ---------------------------------------------------------------------------
# command: p0 — the two typeRdd-empty ARCHEAN documents
# ---------------------------------------------------------------------------

#: Candidate signals worth checking on the P0 documents, drawn from the
#: exploratory pass and from phrases already grounded elsewhere in this
#: project (DISCOVERY.md 11.1's lexicon, the golden chain's snippets).
P0_PROBE_PHRASES = [
    "capital social est fixe",
    "pour le porter de",
    "augmentation de capital",
    "augmentation du capital",
    "reduction du capital",
    "il est divise en",
    "actions nouvelles",
    "assemblee generale",
    "cession",
    "associe unique",
    "president",
    "commissaire aux comptes",
]


def cmd_p0(args: argparse.Namespace) -> int:
    corpus = load_corpus(args.data_root / ARCHEAN_SIREN / "actes")
    targets = ["63e9593b8be6eb9f9d257ec4", "6936b4160bb493b0e4098925"]

    for doc_id in targets:
        d = corpus[doc_id]
        print(f"=== {doc_id} ({d.filename_date}, {d.page_count} pages) ===")
        print(f"typeRdd: {d.type_rdd_summary()}")
        print(f"in ARCHEAN_GOLD: "
              f"{[cls for cls, ids in ARCHEAN_GOLD.items() if doc_id in ids] or ['(none)']}")
        print()
        for phrase in P0_PROBE_PHRASES:
            hits = []
            for ln in read_document_lines(d):
                if fold(phrase) in ln.folded:
                    hits.append((ln.page, ln.text))
            marker = "OBSERVED" if hits else "absent"
            print(f"  [{marker:8}] {phrase!r}: {len(hits)} line(s)")
            for page, text in hits[:2]:
                print(f"      p{page}: {text!r}")
        print()
    return 0


# ---------------------------------------------------------------------------
# command: gold — batch signal measurement against ARCHEAN's verified labels
# ---------------------------------------------------------------------------

#: Candidates carried forward from exploration, one row per (phrase, class).
#: This list is the thing DISCOVERY.md's routing-evidence table is built
#: from; nothing here is asserted to work before this command has run.
GOLD_CANDIDATES: list[tuple[str, str]] = [
    ("augmentation de capital", "capital_amount"),
    ("augmentation du capital", "capital_amount"),
    ("pour le porter de", "capital_amount"),
    ("capital social est fixe", "capital_amount"),
    ("il est divise en", "capital_amount"),
    ("actions nouvelles", "capital_amount"),
    ("reduction du capital", "capital_amount"),
    ("valeur nominale", "capital_amount"),
    ("prime d'emission", "capital_amount"),
    ("cession", "share_transfer"),
    ("ordres de mouvement", "share_transfer"),
    ("protocole de cession", "share_transfer"),
    ("ceder", "share_transfer"),
    ("nouvel actionnaire", "share_transfer"),
]


def cmd_gold(args: argparse.Namespace) -> int:
    corpus = load_corpus(args.data_root / ARCHEAN_SIREN / "actes")
    docs = [(ARCHEAN_SIREN, d) for d in corpus.documents if d.has_ocr]

    for phrase, gold_class in GOLD_CANDIDATES:
        target_ids = ARCHEAN_GOLD[gold_class]
        result = measure_signal(docs, phrase, target_ids, f"gold:{gold_class}")
        print_signal_result(result)
        print()
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def default_data_root() -> Path:
    import os

    challenge_root = Path(
        os.environ.get(
            "ARCHEAN_CHALLENGE_ROOT",
            Path(__file__).resolve().parent.parent.parent / "engineering-challenges",
        )
    )
    return challenge_root / "data"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, default=None,
                         help="the data/ folder (default: resolved via ARCHEAN_CHALLENGE_ROOT)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_census = sub.add_parser("census", help="typeRdd decision frequency, whole corpus")
    p_census.add_argument("--top", type=int, default=60)
    p_census.set_defaults(func=cmd_census)

    p_explore = sub.add_parser("explore", help="n-gram frequency, target class vs the rest")
    p_explore.add_argument("--n", type=int, default=2, help="n-gram size")
    p_explore.add_argument("--label", choices=["capital_increase", "capital_decrease",
                                                "constitution", "share_transfer"],
                            help="typeRdd-derived weak label")
    p_explore.add_argument("--gold-class", choices=sorted(ARCHEAN_GOLD),
                            help="ARCHEAN gold label (overrides --label)")
    p_explore.add_argument("--top", type=int, default=40)
    p_explore.set_defaults(func=cmd_explore)

    p_signal = sub.add_parser("signal", help="TP/FP/FN/TN for one phrase")
    p_signal.add_argument("phrase")
    p_signal.add_argument("--label", choices=["capital_increase", "capital_decrease",
                                               "constitution", "share_transfer"])
    p_signal.add_argument("--gold-class", choices=sorted(ARCHEAN_GOLD))
    p_signal.set_defaults(func=cmd_signal)

    p_p0 = sub.add_parser("p0", help="investigate ARCHEAN's two typeRdd-empty documents")
    p_p0.set_defaults(func=cmd_p0)

    p_gold = sub.add_parser("gold", help="measure every GOLD_CANDIDATES entry")
    p_gold.set_defaults(func=cmd_gold)

    args = parser.parse_args(argv)
    args.data_root = args.data_root or default_data_root()
    if not args.data_root.is_dir():
        print(f"no data/ at {args.data_root}", file=sys.stderr)
        return 2

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
