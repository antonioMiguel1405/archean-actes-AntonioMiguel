"""Deterministic, evidence-based routing over ARCHEAN's actes.

Answers one question per (document, mechanism) pair: *what verdict do the
observable signals in this document's OCR text support?* Never: *what really
happened, historically, in this company?* The second question needs a human
reading every page; this module answers only the first, and says exactly
which lines it looked at to get there.

This module implements the contract proposed in DISCOVERY.md §8.6, built
from the measurements in §8.3-§8.5. Two places where that contract was
ambiguous were resolved here, against evidence, not intuition — both
documented below and in DISCOVERY.md's implementation note:

1. §8.6 sketched a single ``Classification`` per document, but ARCHEAN's own
   gold set has a document (…ec7) that is positive for *both*
   ``capital_amount`` and ``share_transfer``. `classify` takes a mechanism
   and returns one `Classification`; `classify_document` calls it once per
   known mechanism and returns a tuple.
2. §8.6's `Verdict.MENTION` comment read "topic present, no transition and
   no amount", but its own policy table described MENTION as "topic +
   amount, no transition" and cited the two gold false negatives as the
   motivating cases. Reading those two documents directly (…ec5's
   constitution states its capital as "37 000 euros" with no transition
   verb nearby; …7ebf authorises "un montant maximum de 150 861 euros" with
   no transition verb either) confirmed the *table*, not the inline
   comment. This module classifies a document MENTION whenever the topic
   phrase appears anywhere and the document is not OPERATIVE — amount is
   not required as a strict precondition, because forcing SILENT on a
   topic-only boilerplate document (the CAC reports on preference-share
   economics, ...7ec6/...7ec1) would contradict the "do not force SILENT
   when relevant evidence exists" instruction this step was built under.
   This is an engineering choice, not a corpus discovery — recorded as
   such.

What this module reuses, unmodified
------------------------------------
``archean.ground.normalize_text``, ``archean.ground.OcrLine`` and
``archean.ground.load_ocr_lines`` are the already-tested primitives for
folding text and reading OCR lines; nothing here reimplements them.
``archean.frenchnum.parse_french_date_parts`` is reused for the date-based
recital check, exactly as validated in ``scripts/validate_routing.py``.

Word-boundary phrase matching is redefined locally (a three-line regex) —
`route.py` cannot import from `scripts/`, which is a tool tree, not a
dependency of production code. The regex is the same fix validated there:
plain substring search on "ceder" matches inside "excéder"/"procéder";
``\\b``-anchoring does not, and the case is kept as a regression test here.

What is NOT here
-----------------
No fuzzy matching, no embeddings, no LLM call, no score, no confidence
float, no `if doc.doc_id == "...":` special case. `typeRdd` is read as
`metadata_label` and compared, never substituted for content evidence.
`share_transfer` never reaches OPERATIVE — DISCOVERY.md §8.5 found no
signal for it that survives cross-corpus measurement, so its ceiling is
MENTION, and that ceiling is enforced here, not worked around.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import Literal

from archean.corpus import Document
from archean.frenchnum import FrenchDateError, parse_french_date_parts
from archean.ground import OcrLine, load_ocr_lines, normalize_text

__all__ = [
    "Mechanism",
    "Verdict",
    "Evidence",
    "Classification",
    "classify",
    "classify_document",
    "KNOWN_MECHANISMS",
]

Mechanism = Literal["capital_amount", "share_transfer"]
KNOWN_MECHANISMS: tuple[Mechanism, ...] = ("capital_amount", "share_transfer")

#: §8.6 allowed "line" or "page" ("document" was measured strictly worse for
#: co-occurrence, DISCOVERY.md §8.5). Every rule actually implemented here is
#: a single-line phrase or construction match — MENTION does not require
#: amount co-occurrence (see the module docstring's resolution #2), so no
#: rule here tests page-level co-occurrence, and every Evidence carries
#: scope="line" honestly rather than claiming a page-level test that was not
#: performed. The type still allows "page" for a future rule that does.
Scope = Literal["line", "page"]


# ---------------------------------------------------------------------------
# matching primitives — mirrors scripts/analyze_routing.py's validated fix,
# redefined locally because route.py must not import from scripts/.
# ---------------------------------------------------------------------------


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Word-boundary-anchored exact match on folded text.

    Regression case (DISCOVERY.md §8.4): plain substring search on "ceder"
    matched inside "excéder" and "procéder" — 12 of 17 ARCHEAN documents,
    all wrong. ``\\b`` fixes it; French elision ("l'augmentation") still
    matches "augmentation" because the apostrophe is already a non-word
    character to Python's regex engine.
    """
    return re.compile(r"\b" + re.escape(normalize_text(phrase)) + r"\b")


def _read_document_lines(document: Document) -> list[OcrLine]:
    """Every OCR line of every OCR'd page, filtering empty detections.

    DISCOVERY.md §8.3: every line with ``score == 0.0`` has empty text, with
    zero counterexamples across 293 ARCHEAN pages — an exact rule, not a
    threshold. ``archean.ground.load_ocr_lines`` does not apply this filter
    itself (it is a general-purpose reader used by provenance code that may
    want every detection); routing wants only lines that carry text.
    """
    out: list[OcrLine] = []
    if document.ocr_dir is None:
        return out
    for page in document.pages:
        if not page.has_ocr:
            continue
        for ln in load_ocr_lines(str(document.ocr_dir), page.number):
            if ln.score == 0.0:
                continue
            if not ln.text.strip():
                continue
            out.append(ln)
    return out


# ---------------------------------------------------------------------------
# capital_amount: topic, transition, amount, recital
# ---------------------------------------------------------------------------

#: Bare mention of the capital topic. Fires on boilerplate (Article 8) as
#: readily as on an operative resolution — that is expected; this is the
#: MENTION-level signal, not the OPERATIVE one.
CAPITAL_TOPIC: tuple[str, ...] = (
    "augmentation de capital",
    "augmentation du capital",
    "reduction du capital",
    "capital social",
)

#: A euro amount. Operative capital text states one; the permissive
#: boilerplate ("le capital social peut être augmenté...") does not.
_AMOUNT_RE = re.compile(r"\d[\d .,]*(euros?|eur\b|€)")

#: A capital-change construction, as opposed to a bare topic mention.
_TRANSITION_RE = re.compile(
    r"\b(augmente(?:e|es|s)? de|reduit(?:e|s)? de|porter le capital"
    r"|pour le porter|ramene(?:e)? de|augmenter le capital|reduire le capital"
    r"|augmentation de capital de|reduction du capital de)\b"
)

#: The historical back-reference that opens a statutes recital of a past
#: operation: "Aux termes de l'assemblée générale extraordinaire du
#: 17/05/2005, le capital social a été augmenté de 113.000 euros...".
#: DISCOVERY.md §8.5: this catches ARCHEAN's recital form but not HADEAN's
#: ("Lors de ... décidée par ... du 30 avril 2008 :"), which is why it is
#: combined with the date-based check below, not used alone.
_BACKREF_RE = re.compile(r"\baux termes (de|des)\b")

#: How many lines around a transition+amount line to search for a recital
#: signal. DISCOVERY.md §8.6 implementation note: widening this to the whole
#: page was measured and found WORSE (ARCHEAN gold: TP=3 FP=0 FN=4 TN=10,
#: vs TP=5 FP=0 FN=2 TN=10 at this line-local window) — a page-wide search
#: suppresses genuinely operative lines that merely share a page with an
#: unrelated older date (a registration stamp, a signature block). Recital
#: detection stays line-local; MENTION's topic+amount check (measured
#: separately, see _topic_amount_present) is the one place page-scope was
#: validated as correct.
_RECITAL_WINDOW = 3


def _cites_earlier_year(lines: list[OcrLine], index: int, document_year: int) -> bool:
    """True if a line within ``_RECITAL_WINDOW`` of ``lines[index]`` (same
    page only) states a year earlier than the document's own filing year.

    Catches ``ValueError`` alongside ``FrenchDateError``: an OCR-split
    registration stamp such as ``"3 0 MAI 2012"`` (the day digits "3" and "0"
    separated by a space) lets ``_DAY_MONTH_YEAR`` match day=0, which
    ``DateParts.to_date()`` rejects with a plain ``ValueError``, not the
    ``FrenchDateError`` this function otherwise expects — found by running
    this exact call over the whole corpus during the audit for the
    numeral-as-year fix (DISCOVERY.md 8.9), not by design. This function's
    contract is best-effort — "no parseable date here" and "a malformed one
    here" both mean the same thing to a recital check: skip this line.
    """
    target_page = lines[index].page
    lo = max(0, index - _RECITAL_WINDOW)
    hi = min(len(lines), index + 2)
    for j in range(lo, hi):
        if lines[j].page != target_page:
            continue
        try:
            parts = parse_french_date_parts(lines[j].text)
        except (FrenchDateError, ValueError):
            continue
        if parts.year is not None and parts.year < document_year:
            return True
    return False


def _is_recital_line(lines: list[OcrLine], index: int, document_year: int) -> bool:
    """A transition+amount line is a recital if either discovered surface
    form is present nearby: an "aux termes de" opener (on this line or the
    previous one, same page), or a cited year earlier than the document's.
    """
    ln = lines[index]
    if _BACKREF_RE.search(normalize_text(ln.text)):
        return True
    if index > 0 and lines[index - 1].page == ln.page:
        if _BACKREF_RE.search(normalize_text(lines[index - 1].text)):
            return True
    return _cites_earlier_year(lines, index, document_year)


def _capital_evidence(
    document: Document, lines: list[OcrLine]
) -> tuple[list["Evidence"], list["Evidence"]]:
    """(operative, suppressed-as-recital) evidence for capital_amount."""
    operative: list[Evidence] = []
    suppressed: list[Evidence] = []
    year = document.filename_date.year
    for i, ln in enumerate(lines):
        folded = normalize_text(ln.text)
        if not (_TRANSITION_RE.search(folded) and _AMOUNT_RE.search(folded)):
            continue
        ev = Evidence(
            signal="operative-capital", page=ln.page, line_index=ln.index,
            text=ln.text, scope="line",
        )
        if _is_recital_line(lines, i, year):
            suppressed.append(Evidence(
                signal="recital-capital", page=ln.page, line_index=ln.index,
                text=ln.text, scope="line",
            ))
        else:
            operative.append(ev)
    return operative, suppressed


def _topic_evidence(lines: list[OcrLine], topics: tuple[str, ...], signal: str) -> list["Evidence"]:
    out: list[Evidence] = []
    patterns = [_phrase_pattern(t) for t in topics]
    for ln in lines:
        folded = normalize_text(ln.text)
        if any(p.search(folded) for p in patterns):
            out.append(Evidence(
                signal=signal, page=ln.page, line_index=ln.index,
                text=ln.text, scope="line",
            ))
    return out


# ---------------------------------------------------------------------------
# share_transfer: topic only. DISCOVERY.md §8.5: no signal here survives
# cross-corpus measurement (protocole de cession / nouvel actionnaire fire
# in zero other companies; ordres de mouvement in one; cession alone is
# FP=10/15 in ARCHEAN). No transition-level rule is implemented for this
# mechanism — OPERATIVE is therefore structurally unreachable for
# share_transfer until a second gold-labelled company justifies one.
# ---------------------------------------------------------------------------

#: SAS ("actions") and SARL ("parts") vocabulary, both measured in §8.5.
TRANSFER_TOPIC: tuple[str, ...] = (
    "cession",
    "cession de parts",
    "cession d'actions",
)


# ---------------------------------------------------------------------------
# metadata label — typeRdd, read but never substituted for content
# ---------------------------------------------------------------------------


def _metadata_label(document: Document, mechanism: Mechanism) -> bool | None:
    """What typeRdd says about this mechanism. None if typeRdd is absent.

    Mirrors scripts/analyze_routing.py's type_rdd_labels / validate_routing's
    typerdd_capital, redefined locally for the same import-direction reason
    as _phrase_pattern above.
    """
    if not document.type_rdd:
        return None
    decisions = " | ".join(
        normalize_text(e.decision or e.type_acte) for e in document.type_rdd
    )
    if mechanism == "capital_amount":
        return ("augmentation" in decisions or "reduction" in decisions) and \
            "capital" in decisions
    return "cession" in decisions or "donation" in decisions


# ---------------------------------------------------------------------------
# the contract — DISCOVERY.md §8.6, with the two resolutions noted above
# ---------------------------------------------------------------------------


class Verdict(enum.Enum):
    """What the observable evidence supports — never a historical claim."""

    #: A transition construction and an amount, on one line, not identified
    #: as a recital. DISCOVERY.md gold: TP=5 FP=0 FN=2 TN=10.
    OPERATIVE = "operative"
    #: Every transition+amount line found was identified as a recital of a
    #: past operation (a statutes reprint), not this act's own decision.
    RECITAL = "recital"
    #: The topic is present but the document is not OPERATIVE — a
    #: constitution stating its capital, an authorisation of a ceiling, a
    #: CAC report discussing capital mechanics, or a bare "cession" mention
    #: too imprecise to call executed.
    MENTION = "mention"
    #: No signal for this mechanism anywhere in the document.
    SILENT = "silent"


@dataclass(frozen=True)
class Evidence:
    """One place a signal fired. Enough to go and look at it."""

    signal: str
    page: int
    line_index: int
    text: str
    scope: Scope


@dataclass(frozen=True)
class Classification:
    """The verdict for one (document, mechanism) pair, with its evidence.

    ``evidence`` is non-empty for every verdict except SILENT — an
    OPERATIVE, RECITAL or MENTION verdict with no evidence would be
    unauditable, which the whole point of this module is to avoid.
    """

    mechanism: Mechanism
    verdict: Verdict
    evidence: tuple[Evidence, ...]
    suppressed: tuple[Evidence, ...]
    metadata_label: bool | None
    conflicts_with_metadata: bool

    def __post_init__(self) -> None:
        if self.verdict != Verdict.SILENT and not self.evidence:
            raise ValueError(
                f"{self.verdict} classification with no evidence — every "
                f"non-SILENT verdict must be auditable"
            )


def _conflicts(metadata_label: bool | None, verdict: Verdict) -> bool:
    """Compares typeRdd against OPERATIVE only, matching the definition
    already established and measured in scripts/validate_routing.py's
    conflicts command: "typeRdd says X" is compared to "content shows an
    operative X", not to MENTION-level evidence. Never resolved here — only
    reported.
    """
    if metadata_label is None:
        return False
    return metadata_label != (verdict == Verdict.OPERATIVE)


def classify(document: Document, mechanism: Mechanism) -> Classification:
    """Classify one document for one mechanism, from OCR content alone.

    Deterministic: the same document and mechanism always produce the same
    Classification. Never reads ``document.doc_id`` to special-case a
    result — only ``document.pages`` (via OCR text) and ``document.type_rdd``
    (as a separately-reported label) are consulted.
    """
    if mechanism not in KNOWN_MECHANISMS:
        raise ValueError(f"unknown mechanism {mechanism!r}, expected one of {KNOWN_MECHANISMS}")

    lines = _read_document_lines(document)
    metadata_label = _metadata_label(document, mechanism)

    if mechanism == "capital_amount":
        operative, suppressed = _capital_evidence(document, lines)
        if operative:
            verdict = Verdict.OPERATIVE
            evidence = tuple(operative)
        elif suppressed:
            # every transition+amount line found was a recital — the RECITAL
            # verdict itself is evidenced by the suppressed lines that
            # caused it, so they are also surfaced as evidence here.
            verdict = Verdict.RECITAL
            evidence = tuple(suppressed)
        else:
            topic_hits = _topic_evidence(lines, CAPITAL_TOPIC, "topic-capital")
            if topic_hits:
                verdict = Verdict.MENTION
                evidence = tuple(topic_hits)
            else:
                verdict = Verdict.SILENT
                evidence = ()
        return Classification(
            mechanism=mechanism, verdict=verdict, evidence=evidence,
            suppressed=tuple(suppressed) if verdict != Verdict.RECITAL else (),
            metadata_label=metadata_label,
            conflicts_with_metadata=_conflicts(metadata_label, verdict),
        )

    # share_transfer: topic-only, per the module docstring and DISCOVERY.md
    # §8.5 — OPERATIVE and RECITAL are not reachable, since no transition-
    # level or recital-level rule has been validated for this mechanism.
    topic_hits = _topic_evidence(lines, TRANSFER_TOPIC, "topic-transfer")
    if topic_hits:
        verdict = Verdict.MENTION
        evidence = tuple(topic_hits)
    else:
        verdict = Verdict.SILENT
        evidence = ()
    return Classification(
        mechanism=mechanism, verdict=verdict, evidence=evidence,
        suppressed=(), metadata_label=metadata_label,
        conflicts_with_metadata=_conflicts(metadata_label, verdict),
    )


def classify_document(document: Document) -> tuple[Classification, ...]:
    """One Classification per known mechanism.

    §8.6 sketched a single Classification per document; ARCHEAN's own gold
    set has a document (…ec7) positive for both capital_amount and
    share_transfer, so a single verdict per document cannot represent the
    corpus. This returns one Classification per mechanism, in the fixed
    order of KNOWN_MECHANISMS, so the output is always the same shape.
    """
    return tuple(classify(document, m) for m in KNOWN_MECHANISMS)
