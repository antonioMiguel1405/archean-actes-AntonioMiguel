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

## Commands

All verified to run from this directory.

```bash
# run the test suite
python -m pytest -q

# regenerate the reproducible half of DISCOVERY.md §4.1 from the corpus
python scripts/inventory.py
python scripts/inventory.py --root path/to/data/<siren>/actes --format json

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
