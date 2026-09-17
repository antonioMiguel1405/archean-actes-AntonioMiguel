# ARCHEAN TECHNOLOGIES — capital reconstruction

Reconstructs the capital composition of **ARCHEAN TECHNOLOGIES** (SIREN `480489707`) from
its 17 filed *actes* (2005–2025), for the Takeovers Engineering Challenge — Actes.

`results.json` at the repository root is the deliverable: `events[]` (the movements found,
each grounded in a real document/page/bbox) and `capital_timeline[]` (the cap-table state
after each one — the artefact the challenge is actually about).

**Screen recording (~3 min walkthrough):** https://youtu.be/Gxq2BCALPMQ

## 1. Problem

French companies deposit the minutes of every capital or shareholder change with the
registry, in the legal French of the year it happened, each assuming the reader already
knows the ones before it. Nowhere is there a statement of who owns the company today —
that has to be reconstructed from two decades of scattered filings. The brief scores five
event codes (`CAPITAL_INCREASE`, `CAPITAL_DECREASE`, `SHAREHOLDER_ENTRY`, `SHAREHOLDER_END`,
`SHAREHOLDER_SHARE_TRANSFER`; `CAPITAL_DUAL_CLASS` is bonus, unscored) and explicitly warns
that a share transfer and a shareholder entry can describe the same movement from two
sides — deciding what that means for the timeline is part of the problem.

## 2. Approach

Nine sessions, each closing with its own audit and a written record in `DISCOVERY.md`:

1. **Corpus audit** — what the shipped `{pdf, meta, ocr}` folders actually contain, measured
   directly rather than assumed (`archean/corpus.py`, `scripts/inventory.py`).
2. **Deterministic French number/date parsing** (`archean/frenchnum.py`) — spelled and
   digit-written numbers, three date shapes, OCR-corruption repairs — built against real
   corpus strings, not invented grammar.
3. **Evidence-based routing** (`archean/route.py`) — a deterministic classifier that answers
   *"what does the observable text support?"* for `capital_amount` and `share_transfer`,
   never *"what really happened historically"*. Every signal (a transition verb + an amount,
   a recital marker, a topic phrase) was measured cross-corpus (all 20 companies) before
   being trusted, with the false-positive rate reported, not assumed away
   (`scripts/analyze_routing.py`, `scripts/validate_routing.py`).
4. **Two independent gold sets** — ARCHEAN's own 17 hand-read documents, and a second,
   structurally-selected company (JACQUES BOCKEL SARL) read completely independently and
   compared against the router blind (`tests/data/gold_non_archean.json`,
   `scripts/gold_compare.py`). The second gold set found two real router bugs (a four-digit
   share count misread as a year; a boilerplate sentence matching the transition regex) —
   both fixed, both regression-tested, both written up (`DISCOVERY.md` §8.9, §8.10).
5. **This closing session**: the event-extraction and cap-table state-machine layer
   (`archean/timeline.py`, `scripts/build_results.py`) that turns the router's evidence, plus
   a small set of individually-cited facts read directly for the shareholder side, into
   `results.json`.

## 3. Architecture

```
data/480489707/actes/{pdf,meta,ocr}/
        │
        ▼
archean/corpus.py        structural indexing — files, pages, metadata. No content interpretation.
        │
        ▼
archean/ground.py        OCR line reading, text folding, bbox computation (px @ 300dpi → normalized 0-1)
        │
        ▼
archean/frenchnum.py     lexical number/date parsing — no semantic decisions, no document context
        │
        ▼
archean/route.py         evidence-based classification: OPERATIVE / RECITAL / MENTION / SILENT,
        │                 per (document, mechanism) — deterministic, no LLM, no fuzzy match, no
        │                 document-ID branching (AST-verified)
        ▼
scripts/build_results.py  cites the capital deltas + shareholder facts this project has read
        │                 directly (cross-checked live against route.py's own OPERATIVE
        │                 evidence, and against tests/golden_capital_chain.json), re-grounds
        │                 every citation against the real PDF/OCR at build time
        ▼
archean/timeline.py       Decimal/int cap-table arithmetic, chronological folding, invariant
        │                 checking — no OCR, no French, testable with synthetic events alone
        ▼
results.json               events[] + capital_timeline[], schema-validated
```

Each arrow is a real module boundary with its own tests. `corpus.py` never sees an event
code; `frenchnum.py` never sees a verdict; `route.py` never reads `document.doc_id` to
special-case an answer (`tests/test_route.py::test_no_document_id_special_casing_anywhere_in_route_py`,
an AST check, not a text scan); `timeline.py` never reads a PDF.

## 4. Event extraction

**`CAPITAL_INCREASE` / `CAPITAL_DECREASE`** — fully code-derived. For each of ARCHEAN's 17
documents, `archean.route.classify(doc, "capital_amount")` independently decides OPERATIVE
(a transition construction + an amount, on one line, not identified as a recital of a past
operation). `scripts/build_results.py` cites the exact OPERATIVE line for each of the six
real capital movements this corpus contains, asserts live (at build time) that `route.py`
still agrees, parses the amount with `frenchnum.parse_french_amount` (exact `Decimal`, never
float), and folds it through `archean.timeline`'s arithmetic.

**`SHAREHOLDER_END`** (7 instances) and **`CAPITAL_DUAL_CLASS`** (2 instances) — sourced by
direct reading, not by a generic extractor: `archean/route.py`'s `share_transfer` mechanism
is structurally capped at `MENTION`/`SILENT` (`DISCOVERY.md` §8.5/§8.7/§8.8/§8.10 — no signal
for an executed transfer survived cross-corpus measurement), so it cannot source a
shareholder event on its own. Every SHAREHOLDER_END event's citation is re-verified live
against the real OCR at build time (`scripts/build_results.py`'s `ground()`), the same
mechanism used for the capital events. **See Limitations** for exactly what this does and
does not generalise to.

**`SHAREHOLDER_ENTRY` / `SHAREHOLDER_SHARE_TRANSFER`** — not present in this results.json.
Not because the mechanism is unimplemented (`archean/timeline.py` handles both), but because
this corpus's one candidate transfer (the 2005-08-16 reallocation among three existing
holders) is documented as a *result table*, not as seller→buyer instructions — inventing a
pairwise split from an aggregate table would be exactly the kind of invented number this
project's own rules forbid. See `results.json`'s own `notes[7]`.

## 5. Timeline

`archean/timeline.py`'s `build_timeline` folds a chronological sequence of events into
`capital_timeline[]`, one row per event (or group of same-day events), ordered by
`event_date` — **never** filename or deposit order, and never dependent on filesystem
iteration order. Same-day events (ARCHEAN's 2008-06-27 nominal split plus two increases, all
in one document) are ordered by `(inpi_id, page, line_index)` — the physical order the
resolutions appear in the document, a deterministic tie-break, not an arbitrary one.

Every row is checked against two invariants (`archean.timeline.check_invariants`), reported
as facts, never silently repaired:
- `sum(known holder shares) == shares_total`
- `capital_eur == shares_total × nominal_eur`

Where this corpus does not state who held the shares (three of nine rows), the row carries
an explicit `{"kind": "UNKNOWN", "shares": N}` holder rather than guessing a split or
dropping the shares from the total.

## 6. How to run

```bash
# clone this repo and the challenge repo side by side:
#   .../archean-actes/            (this repo)
#   .../engineering-challenges/   (github.com/takeovers-ai/engineering-challenges)

pip install pymupdf pytest jsonschema

# regenerate results.json from the corpus, from scratch
python scripts/build_results.py

# validate it against the challenge's own schema + this project's own invariants
python scripts/validate_results.py

# the full test suite (includes an end-to-end build + schema + determinism check)
python -m pytest -q

# the supporting evidence tools, if you want to re-derive the routing measurements
python scripts/inventory.py
python scripts/analyze_routing.py gold
python scripts/validate_routing.py rules
python scripts/gold_compare.py
```

If the challenge repo is not a sibling directory, set `ARCHEAN_CHALLENGE_ROOT` (see
`.env.example` — it is the only environment variable this code reads, and it is a local
path, not a secret).

## 7. Validation

```
pytest:              623 passed
compileall:           OK
inventory:            OK (scripts/inventory.py)
routing validation:   OK (scripts/analyze_routing.py, scripts/validate_routing.py — cross-
                       corpus measurement against all 20 companies' OCR)
gold comparison:      11/14 agree against the independent JACQUES BOCKEL gold set — reported
                       as agreement, never as an accuracy score; the 3 remaining
                       disagreements are share_transfer's known, structural ceiling
                       (DISCOVERY.md §8.10), unrelated to this closing session
results schema:       results.json validates against results.schema.json
                       (scripts/validate_results.py, python -m jsonschema)
determinism:          results.json is byte-identical across two independent
                       `build_results.py` runs (tests/test_results.py)
```

Numbers are reported as measurements, not scores — see `DISCOVERY.md` for the full,
dated record of every one of them, including the two router bugs the independent gold set
found and how each was fixed.

## 8. How I used AI

This whole project, its tests, and every DISCOVERY.md
entry — was built in an extended pair-programming session with Claude (Anthropic), driven by
an explicit phase structure per session: audit before touching code, corpus-wide measurement
before trusting a signal, a minimal regression test before calling a bug fixed, honest
documentation of what remained unresolved before moving on.

**What was delegated**: writing the actual Python (parser, router, timeline, build/validate
scripts, tests), running the corpus-wide measurements, reading raw OCR text to locate
specific facts (e.g. finding the `…ec2` page-6 "protocole de cession" line that grounds the
three `SHAREHOLDER_END` events), and drafting `DISCOVERY.md`'s narrative.

**What was checked, not trusted**: every citation in `results.json` is re-grounded live
against the real PDF/OCR at build time (`scripts/build_results.py`'s `ground()`, backed by
`archean/ground.py`'s `Grounder`, which is itself tested against the challenge's own
`tools/bbox_viewer.py` reference behaviour) — a moved or invented snippet fails the build
loudly, not silently. Every capital delta is cross-checked against `route.py`'s own,
independently-computed `OPERATIVE` verdict before being cited. The independent gold set
(`tests/data/gold_non_archean.json`) was built and compared *blind*, specifically to catch
router bugs that self-testing against ARCHEAN's own gold would have missed — and it did
catch two, both real, both documented.

**Where it went wrong, and was caught**: an early version of the recital-detection date
parser accepted any bare 4-digit share count (e.g. `1766`) as a plausible year — found only
because the independent gold set disagreed with the router on a document neither AI nor
human had specifically checked. An early `TRANSITION_RE` alternative matched a boilerplate
valuation-report sentence as if it were an operative decision — found the same way, one layer
deeper, once the first bug's masking effect was removed. Both are written up in full in
`DISCOVERY.md` §8.9/§8.10, including the corpus-wide measurement that justified each fix and
the alternative fixes that were measured and rejected.

**No LLM call is anywhere in the shipped pipeline** (`archean/`, `scripts/`) — everything
that runs to produce `results.json` is deterministic Python, verified by
`tests/test_route.py::test_route_py_imports_nothing_fuzzy_or_networked` and a corpus-wide
grep audit for fuzzy/embedding/LLM/score/confidence terms (`DISCOVERY.md`'s closing
section). This was a deliberate choice, not a constraint of the tools available: the
project's original strategy (`DISCOVERY.md` §9) planned an LLM extraction layer with a
committed response cache; building the router and timeline to the same evidentiary standard
without one turned out to answer the challenge's own scoring criteria (traceability,
internal coherence, honesty about gaps) at least as well, for less moving-parts risk.

## 9. Limitations

Real, current, and not papered over:

- **`SHAREHOLDER_ENTRY` and `SHAREHOLDER_SHARE_TRANSFER` are not populated.** This corpus's
  one candidate (2005-08-16) is documented as a result table, not seller→buyer instructions;
  building and validating a generic pairwise-transfer extractor to this project's own
  evidentiary standard was out of scope for this closing session (see §4 above).
- **Three shareholders' entry is undocumented.** Malik GUELLATI, Christophe LEROUX and
  Marielle ROUJEAN are confirmed as associés on 2005-05-17 and confirmed to have sold all
  their shares on 2005-08-16 — but no document in this corpus states how many shares each
  held, or how they acquired them. `SHAREHOLDER_END` events are emitted with `shares` simply
  omitted; a `SHAREHOLDER_ENTRY` for them cannot be grounded at all (`results.json notes[1-2]`).
- **A live, unresolved contradiction survives into `results.json`.** Two official documents
  disagree on Antonio BLANCO MARINA's post-2005-08-16 share count (823 vs. 803) — reported in
  `notes`, not resolved by picking a winner.
- **Who held the 150 861 category-B shares between 2008 and 2017 is not stated** in the 2008
  filing (an *extrait* that omits the subscriber resolutions); the 2017 buyback names 4 funds
  holding exactly that total, but attributing that split back to 2008 would be an inference.
  The 2008-06-27 timeline row carries those shares as an explicit `UNKNOWN` holder.
- **How HADEAN SAS acquired 100% of ARCHEAN (2007→2008-06-27) is not documented anywhere in
  ARCHEAN's own folder** — confirmed as a genuine corpus gap, not a parsing failure; HADEAN's
  own folder (`data/499979540/`) has it, which is exactly the case the brief's own text
  anticipates ("the capital timeline of 480489707 is reconstructable from its own folder" —
  qualified here).
- **OCR cross-line date splitting** remains an open, documented defect (`DISCOVERY.md` §8.9's
  remaining limitations) — a real date split across two OCR lines can still evade the
  recital-date check; measured to affect one HADEAN document pair, not ARCHEAN.
- **`share_transfer` cannot reach `OPERATIVE` anywhere in `route.py`** — a structural ceiling
  from §8.5's cross-corpus measurement (no candidate signal survived), not a bug, and not
  worked around by this session.
- **Hindsight-encoded gold labels remain unresolved by design** — ARCHEAN's own gold set has
  a pair of documents (an authorisation later realised vs. one never exercised) that are
  textually indistinguishable; no heuristic was built to reproduce that distinction.
- **The bonus `group.nodes`/`group.edges`** was not attempted — the brief says do the
  timeline first, and this session's time went entirely into finishing that honestly rather
  than starting a second, lower-priority artefact.

Nothing above is claimed as solved when it is only risk-reduced, and nothing is claimed
100% resolved. The full, dated account of every finding — including two real router bugs
found and fixed by the independent gold set — is in `DISCOVERY.md`.

## 10. What I would do next

In priority order, if this were not a closing submission:

1. **A validated, generic holder-table extractor** — the OCR interleaving pattern (names in
   one column, counts in another, scrambled by reading order) recurs across this corpus; a
   geometric y-band pairing algorithm (the same technique used to hand-verify
   `tests/golden_capital_chain.json`) generalised and tested to this project's own standard
   would let `SHAREHOLDER_ENTRY` be sourced the same way `CAPITAL_INCREASE` already is.
2. **Cross-line OCR joining** for date parsing specifically — flagged since `DISCOVERY.md`
   §8.4, still not built, now confirmed to cost real recall on at least one document.
3. **A `SHAREHOLDER_SHARE_TRANSFER` model that tolerates an aggregate result table** — instead
   of requiring a single seller/buyer pair, allow a result-table-derived set of
   `SHAREHOLDER_END`+`SHAREHOLDER_ENTRY` pairs with an explicit "redistribution, not traced
   pairwise" flag, so the 2005-08-16 reallocation could be represented without inventing a
   split.
4. **The bonus group reconstruction**, once the above is stable.
