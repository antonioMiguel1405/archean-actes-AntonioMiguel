# ARCHEAN TECHNOLOGIES — Takeovers "Actes" challenge

## Context

| | |
|---|---|
| Company | ARCHEAN TECHNOLOGIES |
| SIREN | `480489707` |
| Challenge | Data / ML Engineer — **Actes** (not Bilan) |
| Period | 2005 → 2025 (17 actes, 293 pages, OCR complete) |
| Corpus | `../engineering-challenges/data/480489707/actes/` |
| Schema | `../engineering-challenges/challenges/actes/schema/results.schema.json` |
| Codes | `../engineering-challenges/challenges/actes/schema/event_codes.json` |
| Brief | `../engineering-challenges/challenges/actes/BRIEF.md` |
| Budget | 6–8 hours total |

`../engineering-challenges/` is the **reference clone**. It is read-only. Never edit,
stage or commit anything inside it. This repo is the deliverable.

## Objective

Reconstruct the capital composition of ARCHEAN TECHNOLOGIES over its whole life and emit
`results.json` at this repo's root, containing `events[]` (the movements) and
`capital_timeline[]` (the cap-table state after each). The timeline is what is graded;
events justify it.

A partial, auditable answer beats a complete, unverifiable one. The brief says outright
that a complete answer is not expected, and that what gets read is what we chose to do
first and how clearly we said what we left.

## Rules that are never broken

1. **Never invent a number.** Every figure in `results.json` traces to OCR text we can
   quote from a named document and page. If it is not stated anywhere, it is `null` plus a
   note. `null` is a correct answer; a plausible guess is not.
2. **Never invent provenance.** `inpi_id`, `page` and `bbox` describe a real location in a
   real PDF. Never cite a document to make a claim look grounded.
3. **Never invent a bbox.** Boxes are computed by `archean/ground.py` from OCR polygons.
   No model output is ever written into a `bbox` field. The LLM may say *which lines* it
   used; code turns lines into coordinates.
4. **`event_date` is the date the decision took effect** — read from the body of the act.
   It is never the filename date and never `meta.dateDepot`. In this corpus the gap runs
   from 3 weeks to 17 months. Where an operation is authorised on date A and realised on
   date B, the capital event is dated B, with `authorised_on: A` in the payload.
5. **Scope is capital composition only.** Auditors, presidents, addresses, objet social,
   name changes and fiscal-year changes are out of scope even when they sit in the same
   resolution as something in scope.
6. **Contradictions are reported, never silently resolved.** Do not prefer a document just
   because it is more recent. Where two documents disagree and neither can be shown wrong,
   record both, mark the row, and surface it in `results.json > notes`.
7. **Money is `Decimal`, shares are `int`.** Never float for either. Do not round during
   intermediate computation.
8. **The LLM does not compute the timeline.** Deterministic code owns all arithmetic, all
   date parsing, all bbox computation, all folding, all validation.
9. **Never commit `.env`, an API key or a token.**

## Provenance convention

```
bbox = [x0, y0, x1, y1]
```

- normalized **0–1** against that page's own width and height
- origin **top-left**
- page **1-indexed**

The shipped OCR uses a different convention — polygons in **pixels at 300 dpi** — so there
is a conversion:

```
scale = 300 / 72
x_norm = x_px / (page.rect.width  * scale)
y_norm = y_px / (page.rect.height * scale)
```

**Page size varies in this corpus.** The 2005–2008 scans are ~1654×2353 pt; the 2010+ ones
are A4 595×842 pt. Always read the rect of the specific page (`doc[page - 1].rect`), never
assume A4.

`archean/ground.py` is the single implementation. It is verified against the challenge's own
`tools/bbox_viewer.py`, which is the reference behaviour — if ours ever disagrees with it,
stop and investigate rather than "fixing" either side.

Two known, investigated divergences from the reference, both documented in `ground.py` and
in DISCOVERY.md §7.1:

- **Clamping.** 8 of 11 254 OCR lines have polygons that spill past the page edge by up to
  8.5e-5 (marginalia and signature strokes). `results.schema.json` requires `0 <= v <= 1`,
  so an unclamped box makes the submission invalid; `bbox_viewer` does not clamp. We clamp,
  but only within a 0.001 tolerance — beyond that it is a wrong page size and still raises.
- **Rounding order.** `300/72` is not binary-representable, so the reference's
  multiply-then-divide rounds twice. We compute over rationals and round once. Difference:
  2.22e-16, affecting the 4th decimal of 20 of 45 016 coordinates. `REFERENCE_FLOAT` mode
  reproduces the reference exactly, and the tests assert it across the whole corpus.

Neither divergence may be widened without a documented reason.

## Corpus facts worth not re-deriving

- All 17 actes have complete OCR (293/293 pages). There are **no OCR gaps** for this company.
- **No acte has a PDF text layer.** They are pure scans; OCR or vision is the only route to text.
- `meta/*.json` → `typeRdd[].decision` is a high-precision router ("Augmentation du capital
  social", "Réduction du capital social", "Constitution") — but the 2006-01-03 filing, which
  carries the single largest increase, has **empty meta**. Never rely on it alone.
- Répartition tables put names in a left column and counts in a right column; OCR line order
  interleaves them. Pair them **geometrically by y-band**, not by line adjacency.
- Numbers are often written twice, as French words and as digits (`trente sept mille
  (37.000)`). Where OCR corrupts the digits, the words usually survive. Prefer agreement
  between the two; treat disagreement as a signal, not a nuisance.
- Two documents have no `typeRdd` field at all: `…257ec4` (2006-01-03) and `6936b416…`
  (2025-12-02, which has a different meta shape entirely — `typeDocument`/`numNat`/`libelle`
  instead). `archean/corpus.py` surfaces both as a `no_type_rdd` finding.
- `…257ec8`/`…257ec9` (2010-12-08) and `…257eca`/`…257ecb` (2011-07-11) are two pairs of
  documents sharing one `numChrono` — one registry deposit split into two files, not two
  separate events. `archean/corpus.py` flags this as `shared_num_chrono`; do not double-count.
- 10 of 293 OCR pages carry an internal `_reocr_*` diagnostic block outside the documented
  `{page, ocr, layout}` shape — always a single-character margin correction, never inside body
  text. Not used by anything; ignore it rather than parsing it.
- Zero orphaned files, zero malformed filenames, and zero partial-per-document OCR coverage
  exist anywhere in the whole shipped corpus (all 20 companies, both doctypes) — verified by
  direct comparison, not sampled. `corpus.py`'s error paths for those cases are real code with
  no real trigger; they are tested through fixtures, not through this corpus.

## Corpus indexing

`archean/corpus.py` turns a `{pdf,meta,ocr}` folder into a typed, deterministic `Corpus` of
`Document`/`Page` objects — what exists and how files relate, never what a document says. It
raises on contract violations (orphan files, id mismatches, page-numbering conflicts — none of
which occur in the real corpus) and records real-but-benign facts as non-fatal `Finding`s
(`no_ocr`, `no_type_rdd`, `shared_num_chrono`, `partial_ocr_coverage`,
`deposit_date_differs_from_filename`). `scripts/inventory.py` renders a `Corpus` into the
reproducible half of DISCOVERY.md §4.1 — everything except "capital in header" and "priority",
which need document content and stay hand-verified. See DISCOVERY.md §4.1-V.

## `archean/route.py` — the router

`classify(document, mechanism) -> Classification` and `classify_document(document) ->
tuple[Classification, ...]` (one per `KNOWN_MECHANISMS = ("capital_amount",
"share_transfer")` — `…ec7` is gold-positive for both, which is why it's a tuple, not a
single result per document). Built on DISCOVERY.md §8.6's contract; two contract
ambiguities and one new measurement from building it are in §8.7 — read that before
touching the recital window, the MENTION condition, or the mechanism list.

Rules never invented beyond what §8.3–§8.6 measured:
- `capital_amount` can reach `OPERATIVE` (transition + amount, line-scoped, recital-excluded
  via both discovered surface forms — `aux termes de` and a cited year earlier than the
  document's own, checked in a **line-local window, not page-wide** — widening it to
  page-wide was tested and made it *worse*, TP dropping from 5 to 3 on ARCHEAN gold).
- `share_transfer` can **only** reach `MENTION` or `SILENT` — no signal for it survived
  cross-corpus measurement (§8.5), so `OPERATIVE` is structurally unreachable for it, not
  merely untriggered. Don't add `protocole de cession` / `nouvel actionnaire` / `ordre(s) de
  mouvement` back as topic signals — they were excluded on evidence, not by omission.
- `typeRdd` is exposed as `metadata_label` (`None` when absent) and compared via
  `conflicts_with_metadata`, never substituted for content. A conflict is reported, never
  resolved — see `…ec2` (metadata says capital, content says no) and `…7ebf` (metadata says
  capital, content is `MENTION` not `OPERATIVE` — a known ceiling, not a bug).
- No `if doc.doc_id == "...":` anywhere — verified by an AST-based test, not a text scan
  (the module's own docstring quotes that exact forbidden pattern as an example).

## Routing evidence — not routing itself

`scripts/analyze_routing.py` measures candidate phrases against
two label sources (ARCHEAN's own 17 hand-verified documents; a noisy `typeRdd`-derived label
across all 20 companies) and prints raw TP/FP/FN/TN — never a score, never a ranking, never a
routing decision. See DISCOVERY.md §8.4 before adding a candidate phrase or trusting one already
there; the table is dated and was produced by a specific command, not asserted from memory.

`scripts/validate_routing.py` re-measures those signals across all 20 companies. It reports
prevalence (no label), agreement-with-`typeRdd` (never called accuracy), and real
TP/FP/FN/TN only for ARCHEAN, the one company with a gold label. See DISCOVERY.md §8.5 and
the proposed classification contract in §8.6.

Cross-corpus facts that overturned earlier conclusions:
- **`protocole de cession` and `nouvel actionnaire` fire in zero other companies.** They had
  FP=0 in ARCHEAN and are not cross-corpus signals at all.
- **Broad firing is not validation.** `ordre de mouvement` (singular) fires in 7 companies
  because it is the statutory transmission clause — it does not fire in `…ec2`, the one
  ARCHEAN document that records actual cessions.
- **SAS/SARL vocabulary split:** `parts sociales` fires in 38 documents, 0 of them ARCHEAN.
  Signals derived from ARCHEAN are blind to the SARL half of the corpus.
- **Updated statutes recite the whole capital history with amounts.** `…7ebd`, a 2013
  address-change filing, is lexically indistinguishable from a capital acte. Excluding
  recitals is what gets FP to 0; recitals have at least two surface forms (`aux termes de`,
  and `Lors de … du <date>`), and identifying them by *a cited year earlier than the
  document's own* covers both.
- **`typeRdd` is absent on 31% of OCR'd documents (36 of 115)**, and 6 of those 36 contain
  operative capital text. It cannot be a primary routing input; it corroborates.
- **Our own gold labels encode hindsight** — `…7ebf` (authorisation later realised) is
  gold-positive, `…7ec8` (authorisation never exercised) is not. No router can reproduce
  that distinction from the document.

Facts worth not re-discovering:
- **`typeRdd` is not reliably scoped to its own PDF.** `…ec2`'s `typeRdd` claims "Augmentation
  du capital social"; its OCR text has none. The real augmentation is in the adjacently-filed
  `…ec4`, whose `typeRdd` is empty. Never trust `typeRdd` alone; corroborate with content.
- **Word-boundary matching, not plain substring.** `"ceder"` as a plain substring matches inside
  `"excéder"`/`"procéder"` — found as a real bug during measurement, not hypothesized. Any phrase
  search must anchor on `\b`.
- **Boilerplate is the dominant false-positive source.** Article 8 (capital) and Article 15
  (cession) of the statutes are reprinted in every acte that includes updated statutes, whether
  or not that acte enacts the event. No single capital/cession phrase reaches FP=0 at recall>1.
- **Cross-line splitting is real (41 measured instances) but boilerplate-only so far** — it has
  not yet flipped a target-class bucket, but a future `extract_text` should join adjacent
  same-page lines rather than match single lines, because this was measured, not assumed safe.
- **`…ec4` and `8925` (both typeRdd-empty) are not the same kind of gap.** `…ec4` hides a real
  capital event (11 independent phrase hits, already in the golden chain). `8925` genuinely has
  none (zero hits across twelve probes) — its empty `typeRdd` is correct, not a gap.
- `_reocr_*` diagnostic pages are 18.5% of the *whole* corpus (738/3995), not the 3.4%
  (10/293) this project measured for ARCHEAN alone — both figures are real, scoped differently.
- `layout` is non-empty on 53% of all OCR pages corpus-wide (table detection, mostly on
  `bilans`) but **empty on all 293 of ARCHEAN's own actes pages**, with no exception.

## Commands

All verified to run from this directory.

```bash
# run the test suite
python -m pytest -q

# regenerate the reproducible half of DISCOVERY.md §4.1 from the corpus
python scripts/inventory.py
python scripts/inventory.py --root path/to/data/<siren>/actes --format json

# measure a routing signal — see DISCOVERY.md §8.4 before trusting a number
python scripts/analyze_routing.py p0
python scripts/analyze_routing.py gold
python scripts/analyze_routing.py signal "reduction du capital" --gold-class capital_amount

# where does a phrase sit on a page, in submittable coordinates?
python ../engineering-challenges/tools/bbox_viewer.py \
    --pdf ../engineering-challenges/data/480489707/actes/pdf/<file>.pdf \
    --page <N> \
    --ocr ../engineering-challenges/data/480489707/actes/ocr/<inpi_id> \
    --grep "<text>"

# render a page with OCR in grey and our own box in red
python ../engineering-challenges/tools/bbox_viewer.py \
    --pdf <pdf> --page <N> --ocr <ocr_dir> \
    --bbox 0.1137,0.3993,0.8801,0.4176 -o check.png
```

Dependencies installed and confirmed: `pymupdf` 1.27.2.2, `pytest` 9.0.3,
`jsonschema` 4.26.0, `rapidfuzz` 3.14.6.

## `tests/golden_capital_chain.json`

A hand-verified reference chain of the capital, used **only as a test oracle**. It is not
`results.json`, does not follow `results.schema.json`, and is **not an answer key** — the
challenge has none.

Rules for it:

- It records only what a document states. Rows whose numbers are stated but whose effective
  date is not pinned are `UNCERTAIN`; facts no document supports are `null` with
  `holders_status: UNSUPPORTED`.
- **Never edit the golden file to make the pipeline pass.** If the pipeline disagrees with
  it, one of them is wrong and that must be established from the documents. Changing the
  oracle to match the code destroys the only independent check we have.
- Contradictions live in `independent_observations` and `unresolved`, not folded away.

## Definition of done

Only requirements actually stated by the challenge, plus the checks we chose:

- `results.json` at the repo root, `siren` exactly `"480489707"`, validating against
  `results.schema.json` — the brief warns a submission they cannot parse cannot be scored.
- Every event carries `source.inpi_id`, `source.page`, `source.bbox`; ungrounded events are
  still reported, with a note saying they are ungrounded (the brief permits this explicitly).
- `README.md` covering: how to run it, trade-offs, **"How I used AI"**, what could not be
  resolved, what we would do next, and the link to a ~3-minute screen recording.
- `.env.example` naming every environment variable the code reads, with **names only, no
  values**. If the pipeline needs no keys, say so — the brief calls that a legitimate answer.
- `.env` absent from the repo and present in `.gitignore`.
- `python -m pytest -q` green.

## LLM policy

The LLM reads French and interprets resolutions on a page we hand it. It returns
`evidence_line_ids` plus a verbatim `snippet`. Code then checks the snippet really occurs in
that page's OCR and computes the bbox from the cited lines. An extraction whose snippet does
not match is rejected, not repaired.

Temperature 0. Every response cached to `cache/llm/` and **committed**, so a reviewer can
reproduce `results.json` with no API key.

## When a document is ambiguous

Emit with `confidence: low` and a `note`, record it in the unresolved list, and surface it in
`results.json > notes`. Do not resolve ambiguity by picking whichever reading makes the
arithmetic close.
