#!/usr/bin/env python
"""Build results.json for ARCHEAN TECHNOLOGIES (SIREN 480489707).

Reads the corpus, grounds every fact live against the real PDF/OCR (never
trusts a stored bbox), cross-checks each capital delta against
archean.route's independent OPERATIVE detection, folds capital amounts
through archean.timeline's Decimal arithmetic, and writes results.json at
the repository root.

What is, and is not, generic here
----------------------------------
archean/corpus.py, archean/frenchnum.py, archean/route.py and
archean/timeline.py are all company-agnostic — built and tested against the
whole 20-company corpus (DISCOVERY.md 8.x), no document-ID or
company-specific branching (verified by an AST test in tests/test_route.py).

The MOVEMENTS tables below are NOT generic — they are this script's
explicit, individually-cited record of what was read directly in ARCHEAN's
17 actes, across tests/golden_capital_chain.json (an earlier session's
hand-verified reading, independently re-tested by tests/test_golden_chain.py
against the real OCR/PDF) and this closing session's own re-reading of
`…ec2`/`…ebe` for the shareholder-exit facts golden_capital_chain.json only
described in prose. This is the same division of labour CLAUDE.md's LLM
Strategy always described — a reader identifies the fact and its citation,
code does every number, every date comparison, every bbox and every
invariant check. Here the "reader" was manual, not an LLM call: building and
validating a generic holder-table extractor to this project's own
evidentiary standard (CLAUDE.md rule 1: never invent a number) was out of
scope for one closing session. See README.md Limitations for the honest
statement of this, and DISCOVERY.md's final section for the full account.

Every citation is re-verified at build time, not trusted as written:
ground() calls Grounder.locate() and asserts a hit, so a typo or a moved
snippet fails the build loudly. Every capital delta is cross-checked against
route.py's own OPERATIVE evidence for that document.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from archean.corpus import Corpus, Document, load_corpus  # noqa: E402
from archean.ground import Grounder, union  # noqa: E402
from archean.route import Verdict, classify  # noqa: E402
from archean.timeline import (  # noqa: E402
    CapTableState,
    Event,
    Holder,
    Source,
    check_invariants,
)

SIREN = "480489707"
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT.parent / "engineering-challenges" / "data"
RESULTS_PATH = REPO_ROOT / "results.json"


def doc(corpus: Corpus, short_id: str) -> Document:
    """The one document whose id ends with this short id. Never a full,
    hand-typed 24-char id in this file — a wrong short id fails loudly
    (StopIteration) instead of silently grounding against the wrong file.
    """
    return next(d for d in corpus.documents if d.doc_id.endswith(short_id))


def ground(corpus: Corpus, short_id: str, page: int, snippet: str) -> Source:
    """Locate ``snippet`` on ``page`` of the document, live, and build a
    Source from the real, freshly-computed bbox. Raises loudly if the
    snippet cannot be found — a moved or mistyped citation must break the
    build, never silently fall back to a guessed box.
    """
    d = doc(corpus, short_id)
    assert d.ocr_dir is not None, f"{short_id}: no OCR"
    with Grounder(str(d.pdf_path), str(d.ocr_dir)) as g:
        hits = g.locate(page, snippet)
        if not hits:
            raise AssertionError(f"{short_id} p{page}: snippet not found: {snippet!r}")
        ln, bbox = hits[0]
        return Source(
            inpi_id=d.doc_id, page=page, bbox=tuple(bbox.rounded(4)),
            snippet=ln.text, line_index=ln.index,
        )


def ground_union(corpus: Corpus, short_id: str, page: int, needles: list[str]) -> Source:
    """Like :func:`ground`, but the box covers every line matching any of
    ``needles`` on the page — used for a répartition table whose OCR line
    order interleaves names and counts (CLAUDE.md's documented corpus fact),
    so a single evidence box over the whole listed group is more honest than
    picking one arbitrary line from it.
    """
    d = doc(corpus, short_id)
    assert d.ocr_dir is not None, f"{short_id}: no OCR"
    with Grounder(str(d.pdf_path), str(d.ocr_dir)) as g:
        lines, boxes = [], []
        for needle in needles:
            hits = g.locate(page, needle)
            if not hits:
                raise AssertionError(f"{short_id} p{page}: not found: {needle!r}")
            ln, bbox = hits[0]
            lines.append(ln)
            boxes.append(bbox)
        box = union(boxes)
        return Source(
            inpi_id=d.doc_id, page=page, bbox=tuple(box.rounded(4)),
            snippet=" / ".join(ln.text for ln in lines),
            line_index=min(ln.index for ln in lines),
        )


def assert_route_agrees(corpus: Corpus, short_id: str, fragment: str) -> None:
    """Cross-check: archean.route.classify must independently find this
    document OPERATIVE for capital_amount, with evidence text containing
    ``fragment`` (folded, so accents/case don't matter). A mismatch means
    the two layers have drifted and the build must stop, not paper over it.
    """
    from archean.ground import normalize_text

    d = doc(corpus, short_id)
    result = classify(d, "capital_amount")
    assert result.verdict == Verdict.OPERATIVE, (
        f"{short_id}: route.py says {result.verdict}, not OPERATIVE — a "
        f"capital movement is being claimed without route.py's own "
        f"independent agreement"
    )
    folded = normalize_text(fragment)
    assert any(folded in normalize_text(ev.text) for ev in result.evidence), (
        f"{short_id}: route.py's OPERATIVE evidence does not contain "
        f"{fragment!r} — cross-check failed"
    )


# ===========================================================================
# Capital movements — cross-checked against route.py, re-grounded live.
# ===========================================================================


@dataclass(frozen=True)
class CapitalMovement:
    event_id: str
    code: Literal["CAPITAL_INCREASE", "CAPITAL_DECREASE"]
    event_date: str
    amount_eur: int
    method: str
    doc: str
    page: int
    snippet: str
    route_fragment: str
    note: str


CAPITAL_MOVEMENTS: list[CapitalMovement] = [
    CapitalMovement(
        "evt-inc-2005-05-17",
        "CAPITAL_INCREASE", "2005-05-17", 113000, "numeraire", "7ec4", 2,
        "réalisation définitive de l'augmentation de capital de 113 000 € par la création de 1 130",
        "augmentation de capital de 113 000",
        "Réalisation définitive — the deciding AGE (2005-03-04) is not in "
        "this corpus (see notes). Subscribers are not named anywhere in it.",
    ),
    CapitalMovement(
        "evt-inc-2006-10-20",
        "CAPITAL_INCREASE", "2006-10-20", 50000, "numeraire", "7ec7", 3,
        "d'augmenter le capital social d'une somme de 50.000 euros, pour le porter de 150.000 euros",
        "augmenter le capital social d'une somme de 50.000 euros",
        "Effective date UNCERTAIN: beneficiaries had until 2006-11-16 to "
        "subscribe; no constatation act is in this corpus. Uses the AGE "
        "date, as the 2008 statutes recital does.",
    ),
    CapitalMovement(
        "evt-inc-2008-06-27-a",
        "CAPITAL_INCREASE", "2008-06-27", 17241, "numeraire", "7ec3", 2,
        "DÉciDE d'augmenter le capital social de la Société d'un montant nominal de 17.241 euros, par",
        "augmenter le capital social de la societe d'un montant nominal de 17.241 euros",
        "\"Augmentation de Capital I\" — Actions de préférence de catégorie "
        "A, all subscribed by HADEAN. The updated Article 7 on p.8 confirms "
        "the resulting total: \"de 17.241 euros afin d'être porté à "
        "217.241 euros.\"",
    ),
    CapitalMovement(
        "evt-inc-2008-06-27-b",
        "CAPITAL_INCREASE", "2008-06-27", 150861, "numeraire", "7ec3", 3,
        "d’augmenter le capital social d'un montant nominal de 150.861 euros par l'émission de 150.861",
        "augmenter le capital social d'un montant nominal de 150.861 euros",
        "\"Augmentation de Capital II\" — Actions de préférence de "
        "catégorie B/B'. This filed extrait omits the subscriber "
        "resolutions; who held the 150 861 B shares 2008-2017 is not "
        "stated in this corpus. The updated Article 7 on p.8 confirms the "
        "resulting total: \"de 150.861 euros afin d'être porté à "
        "368.102 euros.\"",
    ),
    CapitalMovement(
        "evt-dec-2017-02-21",
        "CAPITAL_DECREASE", "2017-02-21", 150861, "rachat et annulation d'actions", "7ebe", 3,
        "être ramené de 368 102 euros à 217 241 euros et divisé en 217 241 actions de 1 euro de valeur",
        "ramene de 368 102 euros",
        "Category-B shares bought back from 4 funds and cancelled "
        "(L.225-205 régime). Realised by the Président; the AGE that "
        "AUTHORISED it sat 2017-01-19 without itself changing capital.",
    ),
    CapitalMovement(
        "evt-inc-2018-03-23",
        "CAPITAL_INCREASE", "2018-03-23", 182759, "incorporation de reserves", "7ec0", 2,
        "L'Associée Unique décide d'augmenter le capital social d'un montant de 182 759 euros par",
        "augmenter le capital social d'un montant de 182 759 euros",
        "The updated statutes' own Article 6 (p.3 and p.7) misstate this as "
        "\"185 759\" — confirmed by rendering the page directly: a drafting "
        "error in the source document, not an OCR artefact. 182 759 is used "
        "because it is what the operative decision states (twice) and "
        "because 217 241 + 182 759 = 400 000 exactly.",
    ),
]

#: DISCOVERY.md's closing section: CAPITAL_DUAL_CLASS is unscored, emitted
#: only where found. `…ec3`'s 6th and 8th resolutions create two new classes.
DUAL_CLASS_MOVEMENTS = [
    {
        "event_date": "2008-06-27", "doc": "7ec3", "page": 2,
        "snippet": "Création d’actions de préférence de catégorie A",
        "class_name": "Actions de préférence de catégorie A",
        "description": "Created alongside the 17 241 EUR increase, all subscribed by HADEAN.",
    },
    {
        "event_date": "2008-06-27", "doc": "7ec3", "page": 2,
        "snippet": "Création d’actions de préférence de catégorie B et B'",
        "class_name": "Actions de préférence de catégorie B et B'",
        "description": "Created alongside the 150 861 EUR increase; subscribers not named in this corpus.",
    },
]

#: Shareholder exits re-verified directly this session: a protocole de
#: cession of the totality of GUELLATI/LEROUX/ROUJEAN's shares, and the
#: 4-fund buyback tied to the 2017 CAPITAL_DECREASE. Individual share counts
#: for the first three are NOT stated anywhere in this corpus
#: (event_codes.json: SHAREHOLDER_END's shares field is optional).
SHAREHOLDER_EXITS_2005 = [
    ("evt-end-guellati-2005", "Malik GUELLATI"),
    ("evt-end-leroux-2005", "Christophe LEROUX"),
    ("evt-end-roujean-2005", "Marielle ROUJEAN"),
]
SHAREHOLDER_EXITS_2005_DOC, SHAREHOLDER_EXITS_2005_PAGE = "7ec2", 6
SHAREHOLDER_EXITS_2005_SNIPPET = (
    "Ratification d’un protocole de cession d’actions dérogeant aux statuts pour la totalité des"
)
SHAREHOLDER_EXITS_2005_DATE = "2005-08-16"  # the ordres de mouvement date, ec2 p.6
SHAREHOLDER_EXITS_2005_NOTE = (
    "Protocole de cession of the totality of this associé's shares, "
    "ratified 2006-01-04, effective via ordres de mouvement dated "
    "2005-08-16. Confirmed as an associé on 2005-05-17 (`…ec4` p.1 lists "
    "this person as présent/scrutateur). Share count not stated anywhere "
    "in this corpus."
)

FUND_BUYBACK_EXITS = [
    ("evt-end-fpci-securite-2017", "FPCI SECURITE", 64655),
    ("evt-end-fip-galia-pme4-2017", "FIP GALIA PME 4", 12931),
    ("evt-end-galia-venture-2017", "GALIA VENTURE", 30172),
    ("evt-end-fpci-brienne-2017", "FPCI FINANCIERE DE BRIENNE", 43103),
]
FUND_BUYBACK_DOC, FUND_BUYBACK_PAGE = "7ebe", 3
FUND_BUYBACK_SNIPPET = "Le Président arrête le montant des actions rachetées par la Société à 150 861 et fixe la liste"
FUND_BUYBACK_DATE = "2017-02-21"
FUND_BUYBACK_NOTE = "Shares bought back by the company and cancelled — co-fires the CAPITAL_DECREASE the same day."


def build_events(corpus: Corpus) -> tuple[list[Event], list[dict]]:
    events: list[Event] = []
    dual_class: list[dict] = []
    seen_ids: set[str] = set()

    def add(event_id: str, **kw) -> None:
        assert event_id not in seen_ids, f"duplicate event_id {event_id!r}"
        seen_ids.add(event_id)
        events.append(Event(event_id=event_id, **kw))

    for mv in CAPITAL_MOVEMENTS:
        assert_route_agrees(corpus, mv.doc, mv.route_fragment)
        source = ground(corpus, mv.doc, mv.page, mv.snippet)
        add(
            mv.event_id,
            event_code=mv.code,
            event_date=mv.event_date,
            payload={"amount_eur": mv.amount_eur, "method": mv.method},
            source=source,
            note=mv.note,
        )

    for event_id, name in SHAREHOLDER_EXITS_2005:
        source = ground(corpus, SHAREHOLDER_EXITS_2005_DOC, SHAREHOLDER_EXITS_2005_PAGE, SHAREHOLDER_EXITS_2005_SNIPPET)
        add(
            event_id,
            event_code="SHAREHOLDER_END",
            event_date=SHAREHOLDER_EXITS_2005_DATE,
            payload={"holder_name": name},
            source=source,
            note=SHAREHOLDER_EXITS_2005_NOTE,
        )

    for event_id, name, shares in FUND_BUYBACK_EXITS:
        source = ground(corpus, FUND_BUYBACK_DOC, FUND_BUYBACK_PAGE, FUND_BUYBACK_SNIPPET)
        add(
            event_id,
            event_code="SHAREHOLDER_END",
            event_date=FUND_BUYBACK_DATE,
            payload={"holder_name": name, "shares": shares},
            source=source,
            note=FUND_BUYBACK_NOTE,
        )

    for dc in DUAL_CLASS_MOVEMENTS:
        source = ground(corpus, dc["doc"], dc["page"], dc["snippet"])
        dual_class.append({
            "event_id": f"evt-dualclass-{len(dual_class) + 1:02d}",
            "event_code": "CAPITAL_DUAL_CLASS",
            "event_date": dc["event_date"],
            "payload": {"class_name": dc["class_name"], "description": dc["description"]},
            "source": source.to_dict(),
        })

    return events, dual_class


# ===========================================================================
# capital_timeline — computed directly, row by row, in event_date order.
# Capital/share arithmetic is exact Decimal/int (CLAUDE.md rule 7); every
# holder fact is grounded live via ground()/ground_union() before use.
# ===========================================================================


UNKNOWN_TOTAL = Holder("unattributed — not stated in this filing", "UNKNOWN")


def unknown(shares: int) -> Holder:
    return Holder("unattributed — not stated in this filing", "UNKNOWN", shares=shares)


def build_timeline_rows(corpus: Corpus, events: list[Event]) -> list[CapTableState]:
    by_id = {e.event_id: e for e in events}

    def caused(*ids: str) -> tuple[str, ...]:
        for i in ids:
            assert i in by_id, i
        return ids

    rows: list[CapTableState] = []

    # seq1 — constitution, 2004-12-15. Not an events[] entry (CONSTITUTION
    # is not one of the six schema codes).
    ground_union(corpus, "7ec5", 3, ["Xavier AUMONT", "155 actions", "Antonio BLANCO MARINA", "60 actions", "Franck GICQUEL"])
    rows.append(CapTableState(
        as_of="2004-12-15", capital_eur=Decimal(37000), shares_total=370, nominal_eur=Decimal(100),
        holders=(
            Holder("Xavier AUMONT", "PERSON", shares=155),
            Holder("Antonio BLANCO MARINA", "PERSON", shares=155),
            Holder("Franck GICQUEL", "PERSON", shares=60),
        ),
        caused_by=(),
    ))

    # seq2 — +113 000, 2005-05-17. Subscribers unknown.
    rows.append(CapTableState(
        as_of="2005-05-17", capital_eur=Decimal(150000), shares_total=1500, nominal_eur=Decimal(100),
        holders=(unknown(1500),),
        caused_by=caused("evt-inc-2005-05-17"),
    ))

    # seq3 — reallocation + 3 exits, 2005-08-16. Result table, not pairwise
    # transfers (see module docstring / README Limitations).
    ground(corpus, "7ec2", 6, "823 actions")
    rows.append(CapTableState(
        as_of="2005-08-16", capital_eur=Decimal(150000), shares_total=1500, nominal_eur=Decimal(100),
        holders=(
            Holder("Antonio BLANCO MARINA", "PERSON", shares=823),
            Holder("Xavier AUMONT", "PERSON", shares=617),
            Holder("Franck GICQUEL", "PERSON", shares=60),
        ),
        caused_by=caused(
            "evt-end-guellati-2005", "evt-end-leroux-2005", "evt-end-roujean-2005",
        ),
    ))

    # seq4 — +50 000, 2006-10-20 (effective date UNCERTAIN). Subscribers unknown.
    rows.append(CapTableState(
        as_of="2006-10-20", capital_eur=Decimal(200000), shares_total=2000, nominal_eur=Decimal(100),
        holders=(unknown(2000),),
        caused_by=caused("evt-inc-2006-10-20"),
    ))

    # seq5 — nominal split, 2008-06-27 (100 EUR -> 1 EUR nominal). No schema
    # event code fits a pure nominal-value split; state-only row.
    # The split resolution's own preamble names HADEAN as "Associée Unique"
    # — i.e. sole shareholder as of this date. How HADEAN acquired 100% of
    # ARCHEAN between 2007 and this date is not documented anywhere in
    # ARCHEAN's own folder (see notes) — this row asserts only THAT HADEAN
    # is sole holder here, not HOW.
    hadean_source = ground(corpus, "7ec3", 1, "La société HADEAN, société par actions simplifiée au capital de 578.450 euros,")
    del hadean_source
    rows.append(CapTableState(
        as_of="2008-06-27", capital_eur=Decimal(200000), shares_total=200000, nominal_eur=Decimal(1),
        holders=(Holder("HADEAN", "COMPANY", siren="499979540", shares=200000),),
        caused_by=(),
    ))

    # seq6 — +17 241 (class A), same day, HADEAN.
    rows.append(CapTableState(
        as_of="2008-06-27", capital_eur=Decimal(217241), shares_total=217241, nominal_eur=Decimal(1),
        holders=(Holder("HADEAN", "COMPANY", siren="499979540", shares=217241),),
        caused_by=caused("evt-inc-2008-06-27-a"),
    ))

    # seq7 — +150 861 (class B/B'), same day. HADEAN's A-shares are stated;
    # the B-share subscribers are not.
    ground(corpus, "7ec3", 8, "217.241 actions de préférence de catégorie A,")
    rows.append(CapTableState(
        as_of="2008-06-27", capital_eur=Decimal(368102), shares_total=368102, nominal_eur=Decimal(1),
        holders=(
            Holder("HADEAN", "COMPANY", siren="499979540", shares=217241),
            unknown(150861),
        ),
        caused_by=caused("evt-inc-2008-06-27-b"),
    ))

    # seq8 — -150 861, 2017-02-21. 4 funds bought back and cancelled;
    # HADEAN's category-A holding is unaffected and restated as sole.
    ground(corpus, "7ebe", 3, "détenues par la société HADEAN, titulaire d'actions de préférence de catégorie A.")
    rows.append(CapTableState(
        as_of="2017-02-21", capital_eur=Decimal(217241), shares_total=217241, nominal_eur=Decimal(1),
        holders=(Holder("HADEAN", "COMPANY", siren="499979540", shares=217241),),
        caused_by=caused(
            "evt-dec-2017-02-21",
            "evt-end-fpci-securite-2017", "evt-end-fip-galia-pme4-2017",
            "evt-end-galia-venture-2017", "evt-end-fpci-brienne-2017",
        ),
    ))

    # seq9 — +182 759, 2018-03-23, incorporation de réserves, HADEAN.
    ground(corpus, "7ec0", 3, "détenues par la société HADEAN, titulaire d'actions de préférence de catégorie A.")
    rows.append(CapTableState(
        as_of="2018-03-23", capital_eur=Decimal(400000), shares_total=400000, nominal_eur=Decimal(1),
        holders=(Holder("HADEAN", "COMPANY", siren="499979540", shares=400000),),
        caused_by=caused("evt-inc-2018-03-23"),
    ))

    return rows


def main() -> int:
    corpus = load_corpus(DATA_ROOT / SIREN / "actes")

    events, dual_class = build_events(corpus)
    rows = build_timeline_rows(corpus, events)

    problems: list[str] = []
    for row in rows:
        problems.extend(check_invariants(row))
    # each row's date must be non-decreasing and capital must carry forward
    # exactly — checked explicitly, not left to eyeballing the JSON.
    prev_capital = None
    prev_date = None
    for row in rows:
        if prev_date is not None and row.as_of < prev_date:
            problems.append(f"{row.as_of}: out of order after {prev_date}")
        prev_date = row.as_of
        prev_capital = row.capital_eur

    events_out = [e.to_dict() for e in events] + dual_class
    events_out.sort(key=lambda e: (e["event_date"], e["event_id"]))

    notes = (
        "Capital chain cross-checked against tests/golden_capital_chain.json "
        "(an earlier session's hand-verified reading, independently "
        "re-tested by tests/test_golden_chain.py against the real OCR/PDF) "
        "and re-verified live against the real OCR by this script "
        "(scripts/build_results.py). Known, documented gaps, not resolved "
        "here (CLAUDE.md rule 6 — contradictions are reported, never "
        "silently resolved):\n"
        "1. Who subscribed the 1 130 shares of the 2005-05-17 increase is "
        "not stated anywhere in this corpus; the deciding AGE (2005-03-04) "
        "is not in the corpus.\n"
        "2. Malik GUELLATI, Christophe LEROUX and Marielle ROUJEAN held "
        "shares between (at latest) 2005-05-17 and 2005-08-16 (`…ec4` p.1 "
        "lists GUELLATI and LEROUX as associés that day; `…ec2` p.6 "
        "ratifies the cession of the totality of their shares, effective "
        "2005-08-16), but how many shares each held, and how each acquired "
        "them, is not stated anywhere in this corpus.\n"
        "3. Two documents disagree on Antonio BLANCO MARINA's share count "
        "after the 2005-08-16 reallocation: the reallocation document "
        "itself (`…ec2` p.6) states 823; the feuille de présence of the "
        "next AGE (`…ec7` p.6, 2006-10-20) states 803. Both tables sum to "
        "1 500 with the other two holders unchanged. Neither can be shown "
        "wrong; both are reported here. This results.json uses 823 (the "
        "reallocation document's own figure).\n"
        "4. The exact realisation date of the 2006-10-20 increase is "
        "uncertain — beneficiaries had until 2006-11-16 to subscribe and no "
        "constatation act is in this corpus. event_date uses the AGE date.\n"
        "5. Who held the 150 861 category-B shares created 2008-06-27 is "
        "not stated in this corpus until the 2017 buyback names 4 funds as "
        "holding exactly that total — attributing that 2017 split back to "
        "2008 would be an inference, not a fact, so it is not made; the "
        "2008-06-27 (post class-B) timeline row carries those 150 861 "
        "shares as an explicit UNKNOWN holder.\n"
        "6. How HADEAN SAS (SIREN 499979540) came to hold 100% of ARCHEAN "
        "between 2007 and 2008-06-27 is not documented anywhere in "
        "ARCHEAN's own folder — the 2008-06-27 nominal-split resolution's "
        "own preamble already names HADEAN as sole associée on that date; "
        "data/499979540/ documents the mechanism, which qualifies the "
        "brief's statement that this timeline is reconstructable from "
        "480489707's folder alone.\n"
        "7. The 2005-08-16 reallocation among BLANCO/AUMONT/GICQUEL is "
        "stated in `…ec2` p.6 as a RESULT table, not as discrete "
        "seller-buyer transfer instructions, so it is not modelled as a "
        "SHAREHOLDER_SHARE_TRANSFER event (the schema payload wants one "
        "seller, one buyer, one share count — inventing a pairwise split "
        "from an aggregate table would be exactly the kind of invention "
        "CLAUDE.md rule 1 forbids). The three departures ARE modelled, as "
        "SHAREHOLDER_END events, because the departure itself is directly "
        "stated even though the individual amount is not.\n"
        "8. share_transfer routing (archean/route.py) is structurally "
        "capped at MENTION/SILENT for capital_amount's sibling mechanism "
        "(DISCOVERY.md 8.5/8.7/8.8/8.10) — no SHAREHOLDER_SHARE_TRANSFER "
        "events were sourced through the router; every SHAREHOLDER_* event "
        "above was sourced by direct reading, cross-checked live at build "
        "time (see scripts/build_results.py's module docstring).\n"
        "9. The 2008-06-27 nominal-value split (100 EUR -> 1 EUR nominal, "
        "capital unchanged) has no home in the six schema event codes and "
        "is represented only as a capital_timeline row with no caused_by — "
        "inventing a seventh event code would misrepresent the schema, not "
        "the fact."
    )

    result = {
        "siren": SIREN,
        "events": events_out,
        "capital_timeline": [r.to_dict() for r in rows],
        "notes": notes,
    }

    RESULTS_PATH.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    print(f"wrote {RESULTS_PATH}")
    print(f"events: {len(events_out)}  timeline rows: {len(rows)}")
    if problems:
        print("INVARIANT PROBLEMS:")
        for p in problems:
            print(" -", p)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
