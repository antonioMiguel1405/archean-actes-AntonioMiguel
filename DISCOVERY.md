# Discovery — Takeovers · Data/ML Engineer · Challenge ACTES
### ARCHEAN TECHNOLOGIES · SIREN 480489707

> **Status:** discovery + provenance groundwork. No extraction pipeline, no `results.json` yet.

## How to read the labels in this document

Every substantive claim below carries one of four markers. They mean different things and
must not be collapsed into each other.

| marker | meaning | how far you may trust it |
|---|---|---|
| **`[F]` FACT** | Read directly in a document in this corpus, or observed directly in the repository. Cited with document, page and — where it matters — bbox. | Trust it. It was re-read during the verification pass of §4.2-V. |
| **`[I]` INFERENCE** | Our conclusion, derived from facts. Sound reasoning, but nobody wrote it down. | Treat as provisional. Never promote to a number in `results.json` without saying it is derived. |
| **`[H]` HYPOTHESIS** | Plausible, not yet checked against a document. | Do not act on it. Check it first. |
| **`[R]` RECOMMENDATION** | An engineering decision **we** propose. | These are **our** choices, not requirements from Takeovers. Where the challenge actually mandates something, it is quoted and marked `[F]`. |

**Nothing marked `[R]` is an official requirement of the challenge.** The only binding
requirements are those in `BRIEF.md`, `README.md` and the two schema files, which are quoted
verbatim wherever relied on.

---

## 1. Executive Summary

**What must be built.** One `results.json` at the root of *our own* repo containing
(a) `events[]` — capital/shareholder movements typed with 5 scored codes, each carrying
`{inpi_id, page, bbox, snippet}`; (b) `capital_timeline[]` — the cap-table state after each
event. Plus `README.md` (incl. "How I used AI"), `.env.example`, and a ~3 min recording.

**Where the real difficulty is.** *Not* OCR, and *not* the capital amounts. The 17 actes are
fully OCR'd, the OCR is good, and the capital chain (37 000 → 150 000 → 200 000 → 368 102 →
217 241 → 400 000 €) is legible and internally cross-checked by the statutes themselves.
The difficulty is **holder attribution**: French statutes stop listing shareholders after
incorporation, so who held what must be reconstructed from PV feuilles de présence,
subscription resolutions and diffing. Three specific pain points, all already located:

1. **A missing decision.** The AGE of 2005-03-04 that decided the +113 000 € increase is
   *not* in the corpus. Three shareholders (GUELLATI, LEROUX, ROUJEAN) appear out of nowhere,
   hold shares for ~3 months, and leave — with no document stating how many shares each held.
2. **Two documents that disagree.** 2005-08-08 states BLANCO 823 / AUMONT 617 / GICQUEL 60.
   The feuille de présence of 2006-10-20 states BLANCO 803 / AUMONT 637 / GICQUEL 60.
   Both total 1 500. 20 shares moved with no acte. (And the 2005 doc itself computes
   60/1500 = "6,00 %", which is wrong — it is 4 %.)
3. **The biggest ownership change is not in this folder.** Between 2007 and 2008-06-27,
   ARCHEAN goes from 4 individuals to a single corporate owner, **HADEAN SAS
   (SIREN 499 979 540)**. ARCHEAN's own actes never document that transfer. HADEAN's actes
   — `data/499979540/` — do, in detail. This directly qualifies the brief's statement that
   "the capital timeline of 480489707 is reconstructable from its own folder".

**Recommended strategy (Strategy C+, detailed in §5/§13).** OCR index → deterministic
candidate-page retrieval by French legal lexicon → LLM structured extraction *restricted to
those pages* under a strict JSON schema → **grounding done by code, never by the LLM**
(the LLM returns a verbatim snippet; code fuzzy-matches it back into the OCR lines and
computes the bbox) → deterministic timeline folder → invariant validator that fails loudly.
The LLM reads French; the code owns every number, every bbox, and every arithmetic step.

---

## 2. Repository Findings

**Layout is not what the brief's prose implies.** The brief says `schema/results.schema.json`;
the actual paths are scoped per challenge.

```
D:\projeto takeovers\
└── engineering-challenges\            ← the clone (a git repo; the parent dir is not)
    ├── README.md                      ← ground rules, submitting, grounding, AI declaration
    ├── NOTICE.md                      ← data provenance / licence
    ├── challenges/
    │   ├── actes/BRIEF.md             ← our brief
    │   ├── actes/schema/event_codes.json
    │   ├── actes/schema/results.schema.json
    │   ├── bilan/…  fullstack/…       ← not ours
    ├── tools/bbox_viewer.py           ← the only code shipped (203 lines)
    └── data/<20 sirens>/{actes,bilans}/{pdf,meta,ocr}/
```

`[F]` **There is no starter code, no tests, no CI, no requirements.txt, no example of a
filled `results.json`.** `bbox_viewer.py` is the entire codebase. We build from zero.

`[R]` **Do not commit our solution inside this clone.** Submission is "a PR to your own
repository". Create a sibling repo, e.g. `D:\projeto takeovers\archean-actes\`, and make the
data root a config value (`DATA_ROOT`, default `../engineering-challenges/data`), documented
in the README. That keeps the corpus unduplicated and the provenance obvious.

`[F]` Environment verified working: Python 3.14, **PyMuPDF 1.27.2.2** already installed.
`bbox_viewer.py --grep` runs correctly on this corpus.

---

## 3. Schema Analysis — the exact output contract

### 3.1 Top level (`challenges/actes/schema/results.schema.json`)

| field | required | notes |
|---|---|---|
| `siren` | yes | `const: "480489707"` — a literal constant, must match exactly |
| `events[]` | yes | see below |
| `capital_timeline[]` | yes | see below |
| `group` | no | bonus: `{nodes[], edges[]}` |
| `notes` | no | free text — **this is where the contradictions go** |

`additionalProperties: true` **everywhere**. That is a deliberate opening: we may add
`confidence`, `derivation`, `conflicts`, `assumptions`, `mechanism` fields without breaking
the schema. `[R]` Use it — it is how we show reasoning without abandoning the contract.

### 3.2 `events[]` item

Required: `event_id` (any unique string), `event_code` (enum of 6), `event_date`
(string, `YYYY-MM-DD`, **not regex-validated** — but "the date the decision took effect,
which is usually not the date the acte was deposited"), `payload` (free object),
`source` (required: `inpi_id`, `page`, `bbox`; optional: `snippet`).

- `source.inpi_id` — "the 24-character document id **from the filename**". So for
  `acte_2017-03-28_63e9593a8be6eb9f9d257ebe.pdf` → `63e9593a8be6eb9f9d257ebe`. This is also
  the `id` field in `meta/*.json` and the OCR subdirectory name. `[F]` verified: all three agree.
- `source.page` — integer ≥ 1, 1-indexed, relative to the **PDF**; `[F]` verified that the OCR
  `page_NNN.json` numbering matches PDF page numbering 1:1 for all 17 actes.
- `source.bbox` — `[x0,y0,x1,y1]`, each `0 ≤ v ≤ 1`. **Schema-enforced.** A value > 1 makes
  the file invalid → unscoreable. Our validator must assert this.

### 3.3 `capital_timeline[]` item

Required: `as_of`, `capital_eur` (number **or null**), `holders[]` (each requires `name` only).
Optional: `shares_total`, `nominal_eur`, `holders[].siren|kind|shares|pct`, `caused_by[]`.

`[I]` The nullability of `capital_eur`, `shares`, `pct`, `siren` is an invitation: **it is
schema-legal to say "I know the capital but not the split"**. That is exactly the honest
answer for 2005-05-17 → 2005-08-08, and for the 2008–2017 B-share holders. Use `null` plus an
extra `"holders_known": false` / `"note"` field rather than fabricating a split.

`holders[].kind` enum: `PERSON | COMPANY | UNKNOWN`.

### 3.4 Event codes (`event_codes.json`) — meaning, trigger, effect, ambiguity

| code | scored | payload | when to emit | effect on timeline |
|---|---|---|---|---|
| `CAPITAL_INCREASE` | yes | `amount_eur`, `capital_after_eur`, `method` ∈ {`numeraire`, `incorporation de reserves`, `apport en nature`, `autre`} | nominal capital goes **up** | `capital += amount`; `shares += amount/nominal`; new shares allocated to subscribers |
| `CAPITAL_DECREASE` | yes | same shape | nominal capital goes **down** | `capital -= amount`; shares cancelled and **removed from the seller's line** |
| `SHAREHOLDER_ENTRY` | yes | `holder_name`, `holder_siren?`, `shares?` | a party joins the cap table **for the first time** | creates a holder line |
| `SHAREHOLDER_END` | yes | same shape | a party holds **zero** shares afterwards | removes a holder line |
| `SHAREHOLDER_SHARE_TRANSFER` | yes | `from_name`, `to_name`, `shares`, `price_eur?` | shares move between two parties | moves N shares, `shares_total` unchanged |
| `CAPITAL_DUAL_CLASS` | **no** | `class_name`, `description` | creation of a new class of *actions de préférence* | none on totals; annotates classes |

**The critical sentence in the schema file** (SHAREHOLDER_SHARE_TRANSFER description):

> "The downstream cap-table consequences — a new actor entering, an exiting actor leaving —
> are derived by the snapshot folder (Phase 4) and emitted as SHAREHOLDER_ENTRY /
> SHAREHOLDER_END events **at projection time, not here**."

And symmetrically, SHAREHOLDER_ENTRY: *"this event captures the **consequence**; the
**mechanism** is its own co-firing event […] recorded here only as the `mechanism` enum"*,
and SHAREHOLDER_END: *"Most often **reconstructed** by diffing the pre- and post-act capital
allocation article rather than stated by an explicit phrase."*

`[I]` **This is Takeovers' own answer to the trap they warn about in the brief.** Their model
is two-layer: *mechanism events* (TRANSFER / INCREASE / DECREASE) are extracted from documents;
*consequence events* (ENTRY / END) are **derived by the timeline folder**. We should implement
exactly that, and say so in the README — it is the single highest-signal design decision
available in this challenge. See §10.

`[R]` Add a non-schema `mechanism` field to ENTRY/END events naming the co-firing event id
(the schema's own description asks for a `mechanism` enum). It costs nothing and proves we
read the taxonomy rather than the summary table in the brief.

---

## 4. Corpus Analysis — ARCHEAN TECHNOLOGIES actes

### 4.1 Hard inventory (all verified)

`[F]` **17 actes, 293 PDF pages, OCR coverage 17/17 documents and 293/293 pages.** There is
**no OCR gap at all** for the subject company. `[F]` **No PDF has a text layer**
(`get_text()` returns 0 chars on every page of every acte) — these are pure scans; OCR or
vision is the only route to text.

| # | deposit | inpi_id | pages | meta `typeRdd` (registry's own index) | capital in header | priority |
|---|---|---|---|---|---|---|
| 1 | 2005-01-25 | `…257ec5` | 24 | Acte sous seing privé · **Constitution** | 37 000 | **P0** |
| 2 | 2006-01-03 | `…257ec4` | 27 | *(meta empty)* — PV AGE 17/05/2005 + statuts | 37 000→150 000 | **P0** |
| 3 | 2006-01-04 | `…257ec2` | 7 | PV d'assemblée · **Augmentation du capital** + président changes + statuts | 150 000 | **P0** |
| 4 | 2007-02-20 | `…257ec7` | 31 | PV d'assemblée · **Augmentation du capital** + statuts | 150 000→200 000 | **P0** |
| 5 | 2008-06-23 | `…257ec6` | 9 | Rapport du CAC · **avantages particuliers** | 200 000 | P2 |
| 6 | 2008-07-15 | `…257ec3` | 31 | Extrait décisions **associé unique** · **Augmentation du capital** + statuts | 200 000→368 102 | **P0** |
| 7 | 2008-09-08 | `…257ec1` | 9 | Rapport CAC complémentaire | 200 000 | P2 |
| 8 | 2010-12-08 | `…257ec8` | 5 | objet social / activité + statuts | 368 102 | P3 |
| 9 | 2010-12-08 | `…257ec9` | 26 | *(same dépôt, part 2: the statuts)* | 368 102 | P2 |
| 10 | 2011-07-11 | `…257eca` | 1 | date de clôture + statuts | 368 102 | P3 |
| 11 | 2011-07-11 | `…257ecb` | 27 | *(same dépôt, part 2: the statuts)* | 368 102 | P2 |
| 12 | 2013-02-12 | `…257ebd` | 28 | Décision du président (adresse) + statuts | 368 102 | P2 |
| 13 | 2017-01-20 | `…257ebf` | 4 | PV AG mixte · **Réduction du capital** | 368 102 | **P0** |
| 14 | 2017-03-28 | `…257ebe` | 32 | Décision du président · **Réduction du capital** + CAC + statuts | →217 241 | **P0** |
| 15 | 2018-05-30 | `…257ec0` | 28 | Décisions **associé unique** · **Augmentation du capital** + statuts | →400 000 | **P0** |
| 16 | 2018-11-02 | `…257ecc` | 2 | CAC démission/nomination | 400 000 | P3 (out of scope) |
| 17 | 2025-12-02 | `6936b416…` | 2 | PJ_52 · PV AG 24/06/2024 (comptes 2023) | 400 000 | P1 (confirms end state) |

`[R]` **`meta/*.json` `typeRdd[].decision` is a free, high-precision router.** The strings
"Augmentation du capital social" / "Réduction du capital social" / "Constitution" flag
documents 1, 3, 4, 6, 13, 14, 15. Two caveats `[F]`: doc #2 (the 17/05/2005 AGE, the single
largest increase) has **empty meta** — so meta alone is *not* sufficient; and the 2025 doc uses
a different metadata shape entirely (`typeDocument: PJ_52`, `numNat`, no `typeRdd`).

`[F]` **Page size varies across documents** — the 2005–2008 scans are ~1655×2360 pt, the 2010+
ones are A4 595×842 pt. So the px→normalized conversion **must read each page's own
`page.rect`**, never a hard-coded A4. (`bbox_viewer.polygon_to_norm` does this correctly.)

`[F]` `skew_angle: 0.0` and `layout: []` on the pages inspected — the shipped `layout` array is
empty, so there is **no reading-order / table structure** to lean on. Consequence: OCR lines
come in raster order and **two-column tables interleave**. Real example from the constitution
(doc 1, p.3), which is the répartition table:

```
Monsieur Xavier AUMONT
155 actions
155 actions
Monsieur Antonio BLANCO MARINA
=
60 actions
Monsieur Franck GICQUEL
```

The name→count pairing is *off by one line*. A naive regex pairing adjacent lines gets
AUMONT/155 right by luck and BLANCO/60 wrong. `[R]` This is precisely where an LLM earns its
place, and precisely why we must re-ground its answer geometrically (§7).

### 4.2 The reconstructed capital chain (all `[F]` unless marked)

Cross-checked twice: once from the PVs, once from **Article 6 (APPORTS) of the 2008 statuts**,
which recites the whole history — a free internal audit trail the company wrote for us.

| effective date | operation | Δ capital | capital after | shares after | nominal |
|---|---|---|---|---|---|
| 2004-12-15 / 2005-01 | constitution | — | 37 000 | 370 | 100 € |
| **decided 2005-03-04**, **constatée 2005-05-17** | augmentation numéraire, 1 130 new shares | +113 000 | 150 000 | 1 500 | 100 € |
| 2005-08-16 (ordres de mouvement) | cessions — capital unchanged | 0 | 150 000 | 1 500 | 100 € |
| 2006-10-20 | augmentation par **compensation de créance**, 500 new shares, DPS supprimé | +50 000 | 200 000 | 2 000 | 100 € |
| 2008-06-27 | **division du nominal ×100** — capital unchanged | 0 | 200 000 | 200 000 | **1 €** |
| 2008-06-27 (Augm. I) | émission 17 241 **Actions A** @ 5,80 € (prime 82 756,80) | +17 241 | 217 241 | 217 241 | 1 € |
| 2008-06-27 (Augm. II) | émission 150 861 **Actions B** (ABSOC) @ 5,80 € (prime 724 132,80) | +150 861 | 368 102 | 368 102 | 1 € |
| authorised 2017-01-19, **realised 2017-02-21** | **rachat + annulation** de 150 861 actions @ 2,72 € | −150 861 | 217 241 | 217 241 | 1 € |
| 2018-03-23 | augmentation par **incorporation de réserves**, attribution gratuite | +182 759 | 400 000 | 400 000 | 1 € |
| 2024-06-24 | no capital event (comptes 2023) | 0 | 400 000 | 400 000 | 1 € |

Every line closes arithmetically. `[R]` This table is the **golden reference** for the
validator: the pipeline output must reproduce it exactly, or the pipeline is wrong.

### 4.2-V Verification pass on §4.2 — and four corrections to it

§4.2 above is **our own reconstruction**, produced during discovery. It is not supplied by
the challenge: `BRIEF.md` states there is no answer key, and a grep of the whole reference
clone returns nothing resembling a capital chain. So before it could be used as a test
oracle, every row was re-opened in the OCR, re-read, and given a bbox by the same conversion
the pipeline will use. The result is `tests/golden_capital_chain.json`.

The pass **confirmed the capital numbers on every row** and forced four corrections:

**Correction 1 — it is a 9-row chain, not 10.** `[F]` The 2024-06-24 row records *no capital
movement*; the AG approves the 2023 accounts and the capital is unchanged at 400 000 since
2018. It is a confirmation of the end state, not an event, and it has been moved out of the
chain into `independent_observations`. Describing it as a chain row overstated how many
movements the corpus actually documents.

**Correction 2 — the interleaved répartition tables do not need an LLM.** `[F]` §4.1 and §9
both claimed the name↔count pairing is "precisely where an LLM earns its place". That is
wrong. The columns separate cleanly in geometry: on the constitution page the names sit at
`x0 ≈ 0.18` and the counts at `x0 ≈ 0.51`, and each pair shares a y-band to within 0.001:

```
y0=0.4444 x0=0.1820 | Monsieur Xavier AUMONT          y0=0.4439 x0=0.5083 | 155 actions
y0=0.4576 x0=0.1805 | Monsieur Antonio BLANCO MARINA  y0=0.4569 x0=0.5076 | 155 actions
y0=0.4727 x0=0.1820 | Monsieur Franck GICQUEL         y0=0.4716 x0=0.5173 | 60 actions
```

The same holds for the 2005-08 table and the 2006 feuille de présence. `[R]` Pair them by
sorting on y and bucketing, deterministically, and keep the LLM for genuinely linguistic
work. This moves a task out of the "LLM" column of §9 and into "code" — cheaper, reproducible,
and it removes a hallucination surface.

**Correction 3 — the 2006-10-20 date is `UNCERTAIN`, not `[F]`.** `[F]` The AGE decided the
increase on 2006-10-20 but gave beneficiaries **until 2006-11-16** to subscribe and libérer
par compensation, and **no constatation/réalisation act appears in the corpus**. So the
operation completed somewhere in that window. §4.2 presented 2006-10-20 as settled; it is
the decision date and the date the 2008 statutes attribute the operation to, which is a
defensible choice but is a choice. Recorded as `UNCERTAIN` in the golden file. This also
makes it the one row that must never be used to fail a build.

**Correction 4 — the 2018 "185 759" is confirmed as the document's error, not OCR noise.**
`[F]` Discovery listed this as a probable typo. It has now been checked properly: the string
appears on **both** p.3 and p.7 (the clause is copied into the updated statutes), and p.3 was
rendered at 130 dpi and read directly — the PDF genuinely prints `185 759`. The operative
decision on p.2 says `182 759` twice, and 217 241 + 182 759 = 400 000 exactly. So it is the
drafter's error, propagated. Promoted from `[H]` to `[F]`.

**What the pass could *not* promote.** These stay `[I]` or unsupported and are `null` in the
golden file — no document in this corpus states them:

- who subscribed the 1 130 shares of 2005-05-17, and what GUELLATI / LEROUX / ROUJEAN held;
- the cap table resulting from the 2006-10-20 increase (the updated statutes give only
  "deux mille (2000) actions", with no holder list);
- who held the 150 861 category-B shares between 2008 and 2017;
- whether BLANCO held 823 or 803 — see §4.4/C1, unchanged and still unadjudicated.

`[F]` Verification status of the 9 chain rows: **8 `VERIFIED`, 1 `UNCERTAIN`, 0 unsupported**
on the capital numbers. On holders: 5 `VERIFIED`, 1 `VERIFIED_BUT_CONTRADICTED`, 1 `PARTIAL`,
2 `UNSUPPORTED`. Seven distinct source documents carry the chain.

### 4.3 The shareholder chain

| as of | holders | total | source |
|---|---|---|---|
| 2005-01 | AUMONT 155 · BLANCO MARINA 155 · GICQUEL 60 | 370 | `…ec5` p.3 art.7 |
| 2005-05-17 | AUMONT ? · BLANCO ? · GICQUEL ? · **GUELLATI ?** · **LEROUX ?** · **ROUJEAN ?** | 1 500 | **split undocumented** `[F]` |
| 2005-08-16 | BLANCO **823** · AUMONT **617** · GICQUEL 60 | 1 500 | `…ec2` p.6 |
| 2006-10-20 | BLANCO **803** · AUMONT **637** · GICQUEL 60 | 1 500 | `…ec7` p.6 feuille de présence — **contradicts the line above** |
| after the 2006-10-20 AGE | AUMONT 967 · BLANCO 953 · GICQUEL 80 `[I]` | 2 000 | `…ec7` p.3 (+330/+150/+20) |
| after cession to CAPGRAS | AUMONT **742** · BLANCO 953 · GICQUEL **80** · **CAPGRAS 225** `[I]` | 2 000 | `…ec7` p.5 authorises it; **confirmed** by HADEAN statuts reciting AUMONT 742 / GICQUEL 80 / CAPGRAS 225 |
| 2008-06-27 | **HADEAN SAS (499 979 540) — associée unique**, 200 000 → 217 241 (A) | 217 241 | `…ec3` p.1 |
| 2008-06-27 → 2017 | HADEAN 217 241 (A) + **4 funds** 150 861 (B) | 368 102 | classes in `…ec3` p.8; fund names **only** in `…ebe` p.3 (2017) |
| 2017-02-21 | **HADEAN 217 241 — sole holder** ("intégralement détenues par la société HADEAN") | 217 241 | `…ebe` p.3 |
| 2018-03-23 → today | **HADEAN 400 000** | 400 000 | `…ec0` p.3, `6936…` p.1 |

The B-share holders, named only retroactively in the 2017 buyback `[F]`:
FPCI SECURITE 64 655 · FIP GALIA PME 4 12 931 · GALIA VENTURE 30 172 ·
FPCI FINANCIERE DE BRIENNE 43 103 = **150 861** ✓.
`[I]` They almost certainly subscribed those exact B shares in 2008; the 2008 acte is an
*extrait* and the resolutions naming the subscribers (10, 12–15) are **omitted from it**.

### 4.4 Documented contradictions and gaps (the scored deliverable of the brief's §"What we are actually reading")

| # | what | evidence | proposed handling |
|---|---|---|---|
| C1 | **823/617 (2005-08) vs 803/637 (2006-10)** — 20 shares move with no acte | `…ec2` p.6 vs `…ec7` p.6 | report both states; emit a `SHAREHOLDER_SHARE_TRANSFER` with `confidence: low`, `derivation: "diff"`, `note: "no acte; inferred from feuille de présence"`. Do **not** silently pick one. |
| C2 | **"60 actions = 6,00 %"** — arithmetically 4,00 % | `…ec2` p.6 | note it; trust the share count (it closes to 1 500), not the % |
| C3 | **"augmenté de 185 759 euros"** vs "182 759 euros" in the **same document** | `…ec0` p.3 | 217 241 + 182 759 = 400 000 ✓ → 185 759 is the document's own typo; record in `notes` |
| C4 | **The 2005-03-04 AGE is absent from the corpus** — the decision behind the largest relative increase | referenced in `…ec4` p.2 | flag as missing; date the CAPITAL_INCREASE on the **constatation** (2005-05-17) with a note |
| C5 | **Who subscribed the 1 130 shares of 2005** is nowhere stated | — | `holders_known: false` / `shares: null` for that snapshot |
| C6 | **Who subscribed the 150 861 B shares in 2008** is not in the extrait | `…ec3` | attribute by back-inference from 2017, marked `[I]`, `confidence: medium` |
| C7 | **The transfer of ~100 % of the capital to HADEAN is not in this folder** | absent | resolve from `data/499979540/` and say so explicitly |
| C8 | 2010-12-08 and 2011-07-11 each appear **twice** (same `numChrono`, two `inpi_id`s) | meta | not a contradiction — one dépôt split into two files. Deduplicate by `numChrono` to avoid double-counting. |

### 4.5 Cross-corpus (relevant to the main task, not only the bonus)

`[F]` `data/499979540/actes/…069135` (dépôt 2007-09-18) — **HADEAN's constitutive statutes** are
an *apport en nature* of ARCHEAN shares:

- art. 6.2 — Xavier AUMONT contributes **742** ARCHEAN shares @ 100 € nominal, valued 575 €/share = 426 650 €, remunerated by 17 066 HADEAN shares.
- art. 6.3 — Franck GICQUEL contributes **80** shares, 46 000 €, remunerated by 1 840 HADEAN shares.
- art. 6.6 — "Le présent apport de titres porte sur une **participation minoritaire**".
- AUMONT's *origine de propriété* explicitly recites: constitution + subscriptions of
  **17 mai 2005** and **20 octobre 2006** + an **acquisition du 16 août 2005**.
  → independent confirmation of our entire 2005–2007 reconstruction.

`[F]` `…069136` (2008-04-30) and `…069137` (2008-05-29) — apport by **Michel CAPGRAS of 225
ARCHEAN shares** to HADEAN. `[F]` `…069138/9` (2022) — HADEAN buys back CAPGRAS's shares after
his death. `[H]` BLANCO's 953 shares reach HADEAN by the same route in 2008 — to verify in
`…069137` before asserting it.

**Twenty-company inventory** (for the bonus; OCR coverage measured):

| siren | name | actes (ocr) | bilans (ocr) |
|---|---|---|---|
| 480489707 | **ARCHEAN TECHNOLOGIES** | 17 (17) | 9 (9) |
| 499979540 | **HADEAN** | 9 (8) | 6 (5) |
| 843071218 | **ARCHEAN LABS** | 3 (2) | 5 (5) |
| 026980508 | LES IMPRESSIONS DUMAS | 12 (**0**) | 3 (**0**) |
| 352890354 | AIR SYSTEM SERVICE | 12 (**0**) | 6 (**0**) |
| 846650141 | ETABLISSEMENTS E PECOU | 12 (**0**) | 6 (**0**) |
| + 14 others | LUNA, BERNACHON SA, SEM de Niort, LESUEUR, CREAMANDE, CEROV, JACQUES BOCKEL, SO ME PROD, DEDIEU, PAUTET, CONSEIL ET AUDIT MAYOTTE, 015551401, 016850919, 035550318 | varies | varies |

`[F]` A corpus-wide grep for `archean|hadean` returns hits **only** in 480489707 and 499979540.
`[I]` ARCHEAN LABS is a name-similarity candidate, not yet an evidenced edge. `[F]`
"ARCHEAN INTERNATIONAL" is named in `…ec2` p.6–7 (a ratified agreement) with **no ownership
claim** — a strong candidate for the brief's "at least one is named in another's filings
without owning anything", and for `resolved: false`.

---

## 5. Event Extraction Strategy

### 5.1 Architecture comparison

| | **A** LLM reads whole docs | **B** OCR→regex→LLM on snippets | **C** OCR→classify→structured extract→deterministic fold | **D** Hand-curated ledger + code |
|---|---|---|---|---|
| accuracy on numbers | medium (drift, invented totals) | high | **high** | highest |
| accuracy on French legal nuance | high | medium (regex misses paraphrase) | **high** | highest |
| cost | 293 pages × 17 docs, high | very low | **low** (~25–35 pages sent) | zero |
| speed | slow | fast | **fast** | slow (human) |
| complexity | low | medium | **medium** | low |
| auditability | poor | good | **excellent** (every stage inspectable) | excellent |
| debuggability | poor | good | **excellent** | n/a |
| hallucination risk | **high** | low | **low** (schema + snippet-must-exist check) | none |
| provenance generation | **cannot** (no coordinates) | good | **excellent** | manual |
| fits 6–8 h | yes | yes | **yes** | no — doesn't scale, and reads as "no pipeline" |

**Chosen: C**, with two hardening rules borrowed from B and D:

- **R1 — the LLM never emits a bbox and never emits a number that is not also present verbatim
  in a `snippet` it quotes from the OCR.** Code verifies `snippet ⊆ OCR text of that page`
  (normalized, fuzzy ≥ 0.90) and *rejects* the extraction otherwise.
- **R2 — a hand-built golden file** (`tests/golden_capital_chain.json`, the table in §4.2) that
  the pipeline output is diffed against. This is D used as a *test oracle*, not as the
  deliverable. It is cheap (we already have it) and it converts "I think it's right" into
  "here is the assertion that proves it".

Rejected A because provenance is the graded artefact and a full-document LLM read cannot
produce coordinates. Rejected pure B because the répartition tables (§4.1) defeat regex.

### 5.2 Pipeline stages

```
Stage 0  index      meta/*.json + ocr/*/page_*.json  →  documents.jsonl (id, date, pages, typeRdd, text/page)
Stage 1  route      (a) typeRdd decision strings  ∪  (b) lexicon hit-scoring per page   →  candidate pages
Stage 2  extract    LLM, one call per candidate PAGE-GROUP, strict JSON schema out      →  raw_events.jsonl
Stage 3  ground     snippet → OCR line match → polygon union → normalized bbox          →  grounded_events.jsonl
Stage 4  fold       events sorted by (effective_date, seq) → CapitalState[]             →  capital_timeline
Stage 5  validate   invariants + golden diff + jsonschema                               →  report.txt (fails loud)
Stage 6  emit       results.json + notes (contradictions, gaps, confidence)
```

### 5.3 How to recognise each code (lexicon derived from *this* corpus — §11)

- `CAPITAL_INCREASE` ← `augmenter le capital`, `augmentation de capital`,
  `pour le porter de X euros à Y euros`, `par création de N actions nouvelles`,
  `émission de N Actions`, `par incorporation de réserves`, `par compensation avec des créances`.
  Anchor on **`pour le porter de X à Y`** — it gives `amount`, `capital_before` and
  `capital_after` in one line, which is self-validating. Set `method` from: `numéraire` /
  `compensation de créance` (→ `numeraire`, note the sub-mechanism) / `incorporation de réserves` /
  `apport en nature`.
- `CAPITAL_DECREASE` ← `réduction du capital`, `ramener de X à Y`,
  `rachat de N actions … en vue de leur annulation`, `les actions rachetées sont annulées`.
  **Emit on the realisation act, not the authorisation** (§5.4).
- `SHAREHOLDER_SHARE_TRANSFER` ← `cession`, `céder N actions à`, `protocole de cession`,
  `ordres de mouvement`, `apport de N actions de la SAS X par M. Y`, `registre des mouvements de titres`.
- `SHAREHOLDER_ENTRY` / `SHAREHOLDER_END` ← **derived** (§10), plus explicit signals
  `agrée à devenir actionnaire`, `nouvel actionnaire`, `associé unique`,
  `totalité des actions détenues par`.
- `CAPITAL_DUAL_CLASS` ← `création d'actions de préférence de catégorie A/B/B'` (`…ec3` p.2).
  Unscored but free credit — emit it.

### 5.4 `event_date` — the single most common way to get this wrong

`[F]` In this corpus the **deposit date in the filename is never the effective date**, and the
gap runs from 3 weeks to **17 months**:

| filename date | actual decision date | gap |
|---|---|---|
| 2006-01-03 | AGE **2005-05-17** | 7.5 months |
| 2006-01-04 | AGE **2005-08-08** (movements **2005-08-16**) | 5 months |
| 2007-02-20 | AGE **2006-10-20** | 4 months |
| 2008-07-15 | décisions **2008-06-27** | 3 weeks |
| 2017-03-28 | décision du président **2017-02-21** | 5 weeks |
| 2018-05-30 | décisions associé unique **2018-03-23** | 2 months |
| 2025-12-02 | AG **2024-06-24** | 17 months |

`[R]` Rule: `event_date` = the date **in the body** of the decision (`"L'an deux mille dix-sept,
le vingt-et-un février"` / `"EN DATE DU 27 JUIN 2008"`). Parse French date words. Where an
operation is *authorised* on date A and *realised* on date B (2017: 19 Jan → 21 Feb), emit the
capital movement on **B**, because that is when the capital actually changed, and reference A in
the payload (`authorised_on`). Use the deposit date **only** as a sanity bound
(`event_date ≤ dateDepot`) — a cheap, powerful validator.

---

## 6. Timeline Reconstruction Strategy

### 6.1 Intermediate model

```python
@dataclass(frozen=True)
class Holding:
    name: str                       # canonicalised
    kind: Literal["PERSON","COMPANY","UNKNOWN"]
    siren: str | None
    shares: int | None              # None = "is a holder, count unknown"
    share_class: str | None         # "A" / "B" / "B'" / None

@dataclass(frozen=True)
class CapitalState:
    as_of: date
    capital_eur: Decimal | None
    shares_total: int | None
    nominal_eur: Decimal | None
    holders: tuple[Holding, ...]
    caused_by: tuple[str, ...]      # event_ids
    confidence: Literal["high","medium","low"]
    warnings: tuple[str, ...]       # invariant violations recorded, not swallowed
```

Use `Decimal` for money and `int` for shares. Never floats. `pct` is **computed at emit time**
(`shares / shares_total`), never parsed from the document — C2 shows why.

### 6.2 Fold semantics (`apply(state, event) -> state`)

1. **Initial state** = the constitution: capital 37 000, 370 shares, nominal 100, three named
   holders. This is the only state read wholesale from a single article `[F]`.
2. `CAPITAL_INCREASE` → `capital += amount`; `shares_total += amount / nominal`; allocate new
   shares per the subscription resolution. If subscribers are unknown → `shares_total` updates
   but each holder's `shares` becomes `None` and `confidence = low`.
3. `CAPITAL_DECREASE` (buyback+cancel) → `capital -= amount`; `shares_total -= n`; subtract from
   the **named sellers' lines**; any line reaching 0 is dropped → this **fires
   `SHAREHOLDER_END`** at projection time. A "réduction motivée par les pertes" or a
   "diminution de la valeur nominale" would instead change `nominal` with `shares_total`
   unchanged — not present in this corpus, but the fold should distinguish them.
4. `SHAREHOLDER_SHARE_TRANSFER` → `from.shares -= n`, `to.shares += n`. **`capital` and
   `shares_total` MUST be unchanged.** Assert it.
5. **Nominal change (split)** — `…ec3` divides the nominal by 100: `nominal /= 100`,
   `shares_total *= 100`, every holder's `shares *= 100`, `capital` unchanged.
   `[R]` Do **not** invent an out-of-enum `event_code` for it — the enum is closed and an
   unknown value makes `results.json` invalid. Model it as an internal fold op, record
   `nominal_before` / `nominal_after` in the payload of the same-session `CAPITAL_INCREASE`,
   and describe it in `notes`. Losing it silently would make the 2008 numbers unexplainable.
6. **New holder appears** in a transfer/subscription target and is not in `state` → derive
   `SHAREHOLDER_ENTRY`. **Existing holder reaches 0** → derive `SHAREHOLDER_END`. This is the
   projection-time derivation the schema prescribes (§3.4).

### 6.3 Ordering

Sort by `(event_date, doc_deposit_date, intra_document_resolution_index)`. `[F]` Intra-day
ordering matters here: on 2008-06-27 the split, Augmentation I and Augmentation II all occur,
and applying them out of order yields the wrong share count. Keep an explicit `seq` field.

### 6.4 Snapshot emission

Emit one `capital_timeline` entry per **event date** (not per event) — coalesce same-day events
into one snapshot whose `caused_by` lists every contributing `event_id`. That matches "the state
of the cap table after each of those events" while staying readable, and keeps the 2008-06-27
triple from producing three near-identical rows. `[R]` State this choice in the README; it is a
judgement call a reviewer will want to see named.

---

## 7. Provenance Strategy

### 7.1 The conversion — verified end-to-end

`[F]` OCR polygons are **pixels at 300 dpi**; PDF pages are in **points**; page size varies per
document (§4.1). The conversion is:

```python
SCALE = 300 / 72                       # px per point
w_px, h_px = page.rect.width * SCALE, page.rect.height * SCALE
x0 = min(p[0] for p in polygon) / w_px
y0 = min(p[1] for p in polygon) / h_px
x1 = max(p[0] for p in polygon) / w_px
y1 = max(p[1] for p in polygon) / h_px
```

`[F]` **Verified against the shipped tool**: for `"- à FPCI SECURITE"` on page 3 of
`acte_2017-03-28_…257ebe.pdf`, `bbox_viewer.py --grep` prints
`[0.1847, 0.2696, 0.3586, 0.2856]` and an independent implementation returns the identical four
values. The conversion is settled; no guesswork remains here.

Page height/width must come from **that page's** `page.rect` (`doc[page-1]`), because
`polygon_to_norm` is page-relative and sizes differ across documents.

#### Two findings from implementing this (`archean/ground.py`)

**`[F]` The reference tool can emit a box that the schema rejects.** 8 of the 11 254 OCR
lines in this corpus (0.07%) have polygons that extend just past the page edge — at most
`8.5e-5` of a page dimension, roughly 0.02 mm. They are all marginalia: initials, paraphs
and signature strokes written in the margins. `results.schema.json` constrains every bbox
value with `minimum: 0, maximum: 1`, so a raw value of `1.00008` makes the **whole
submission invalid**, and the brief says a file they cannot parse cannot be scored.
`bbox_viewer.py` does not clamp.

`[R]` So `polygon_to_bbox` clamps by default, but only within a `0.001` tolerance — enough
to absorb OCR jitter at a page edge, far too little to hide a wrong page size, which is out
by percent. Beyond the tolerance it still raises. `clamp=False` reproduces the raw reference
behaviour and is what the compatibility tests compare against. `tests/test_bbox.py` pins the
count at exactly 8, so if the corpus or the conversion changes, that is noticed rather than
absorbed silently.

**`[F]` Rounding order changes the fourth decimal on 20 coordinates.** `300/72 = 25/6` is
not representable in binary. `bbox_viewer` computes `w_px = page_w_pt * scale` and *then*
divides, which rounds twice. Computing the same quantity over rationals and rounding once
differs by at most `2.22e-16` — but on 20 of the 45 016 coordinate values in the corpus
(0.04%) the true value lands on an exact 4-decimal tie, e.g. `0.70125`, where the
double-rounded path yields `0.7012499999999999` and rounds *down* to `0.7012`, while the
exact path gives `0.7013`.

`[R]` The module computes in exact rational arithmetic and rounds once, at emit time, and
keeps a `REFERENCE_FLOAT` mode that reproduces `bbox_viewer` bit-for-bit so compatibility is
asserted over all 11 254 lines rather than assumed. The practical difference is ~0.02 mm and
matters to nobody; documenting it costs nothing and means the discrepancy was understood now
rather than discovered later as a mystery.

### 7.2 Preventing invented boxes — the LLM must not produce coordinates

`[R]` **Strongly endorse the approach you proposed**, tightened into a hard contract:

1. The LLM receives, for a candidate page, the OCR lines **with stable integer ids**:
   `[{"i": 0, "t": "…"}, {"i": 1, "t": "…"}, …]`.
2. The LLM's JSON output must include, per extracted fact, `evidence_line_ids: [int]` **and**
   `snippet: str` copied verbatim.
3. Code then:
   - asserts every `i` is in range for that page → else reject;
   - asserts `normalize(snippet)` fuzzy-matches (`difflib` ratio ≥ 0.90) the concatenation of
     those lines' texts → else reject and retry once with the failure quoted;
   - asserts every numeral in the payload appears in the cited lines → else flag
     `grounded_numbers: false` and downgrade confidence;
   - computes the bbox as the **union of those lines' polygons**, converted as §7.1;
   - clamps to `[0,1]` and asserts `x0 < x1`, `y0 < y1`.

This makes an invented bbox structurally impossible: the model's only lever is *which lines*,
and a wrong line is caught by the snippet check. It also makes the bbox reproducible —
re-running the grounding stage on the same extraction yields byte-identical boxes.

### 7.3 Visual verification

`[R]` A `scripts/verify_boxes.py` that loops over `results.json` and shells out to
`bbox_viewer.py --bbox … -o out/<event_id>.png` for **every** event, producing a contact sheet.
With ~15–25 events this is a 2-minute eyeball check and it is *exactly* what the brief says they
grade ("whether the boxes point where you say they do"). Commit a handful of the PNGs
(`docs/box_checks/`) and show one in the recording. High effort-to-signal ratio.

`[R]` Prefer **tight, line-level boxes over the operative sentence**, not whole paragraphs. The
example in the brief (`[0.116, 0.610, 0.920, 0.626]`, height 1.6 % of the page) is a single
line. Match that granularity.

---

## 8. OCR Strategy

### 8.1 Observed quality

`[F]` Quality is **good** — `score` ≥ 0.95 on most lines. But the failure modes are the ones
that matter most:

| failure | real example | risk |
|---|---|---|
| **digits corrupted inside numbers** | `"trente sept mille (37.0o0) euros"`, `"capital de 400/o0o euros"`, `"217 241 euøs"`, `"368 102 euròs"` | **critical** — wrong capital |
| **year corrupted** | `"augmentation de capital intervenue le 17 mai 200s"` | **critical** — wrong `event_date` |
| **name corrupted** | `GUELLATTI`/`GUELLATI`, `GICOUEL`/`GICQUEL`, `AUMANT`/`AUMONT`, `BLANcO` | holder identity splits in two |
| **column interleaving** | §4.1 répartition table | wrong holder→count pairing |
| **handwriting** | `…ec7` p.7 is a handwritten annotation, almost entirely garbled | ignorable (out of scope) |
| **stamp/marginal text mixed into body** | registration stamps interleaved on p.1 of most docs | noise in retrieval |

`[R]` Mitigations, all deterministic:

- **Never trust a single numeric OCR read.** Every capital figure appears 2–25× (page headers
  repeat `au capital de X euros` on every page of the statutes). Take the **mode across
  occurrences**, cross-checked against the arithmetic (`before + amount == after`). `37.0o0`
  loses instantly to 24 copies of `37.000`.
- **Prefer the French words over the digits** where both are present: the corpus systematically
  writes `"trente sept mille (37.000)"`, `"deux cent mille (200.000)"`. A French number-word
  parser is ~40 lines and is far more OCR-robust than digit groups. Use words/digits agreement
  as a confidence signal.
- **Canonicalise names**: strip accents, uppercase, drop honorifics, then fuzzy-cluster
  (`rapidfuzz` ≥ 88) within the document set. Keep a hand-checked alias map
  (`GUELLATTI→GUELLATI`, `GICOUEL→GICQUEL`, `AUMANT→AUMONT`) committed as data, not hidden in code.

### 8.2 Fallback hierarchy — and when each applies here

| level | tool | when | needed for 480489707? |
|---|---|---|---|
| 1 | shipped OCR JSON | default | **yes** — 17/17 docs, 293/293 pages |
| 2 | multi-occurrence voting + word/digit cross-check | any number feeding capital or a date | **yes** |
| 3 | render page and read it myself (`bbox_viewer -o`) | a number the validator flags | **yes**, expect 2–4 pages |
| 4 | multimodal LLM on the rendered page image | a table whose line order defeats both | **likely** — 2005 répartition + 2006 feuille de présence |
| 5 | run our own OCR (tesseract/paddle) | only where level 1 is **missing** | **no** — no gaps for the subject |
| 6 | external sources (INPI, BODACC) | a fact absent from the entire corpus | only for C4/C5 (§12) |

`[R]` **Do not build a local OCR fallback for this challenge.** It is the most expensive
component and buys literally nothing for 480489707. Mention in the README that the design has a
slot for it and that three companies in the wider corpus (IMPRESSIONS DUMAS, AIR SYSTEM SERVICE,
E PECOU) have zero OCR — that shows we saw the problem without paying for it.

---

## 9. LLM Strategy — the division of labour

| task | code | LLM | human (you) |
|---|---|---|---|
| enumerate documents, pages, meta | yes | | |
| route to candidate pages (`typeRdd` + lexicon scoring) | yes | | |
| **read a French legal resolution and say what it decides** | | yes | |
| ~~pair a name with a share count in an interleaved table~~ → **moved to code**, see §4.2-V correction 2 | **yes** (y-band geometry) | | spot-check |
| parse French date words → ISO | yes | | |
| parse French number words → int | yes | | |
| decide `event_code` for an unambiguous resolution | | yes | |
| decide `event_code` for an ambiguous one (entry vs transfer) | rule (§10) | propose | **adjudicate** |
| **compute bbox** | **only** | **never** | |
| verify `snippet` exists in the OCR | yes | | |
| arithmetic: `before + Δ = after`, share sums, % | **only** | **never** | |
| apply the fold, build snapshots | yes | | |
| detect invariant violations | yes | | |
| **decide what a violation means** | | propose | **decide** |
| name canonicalisation / alias clustering | propose | | **approve the map** |
| resolve a name → SIREN (bonus) | lookup | **never guess** | confirm |
| write the `notes` contradiction narrative | | draft | **rewrite** |
| visual bbox check | render | | **eyeball** |

**Model choice `[R]`:** Claude Sonnet 5 for extraction (cheap, ~30 page-group calls, strict
JSON), Opus only if a page defeats it. Temperature 0. `.env.example` should therefore name
`ANTHROPIC_API_KEY` and `LLM_MODEL` (default `claude-sonnet-5`), and — since a reviewer must be
able to run this — **cache every LLM response to `cache/llm/<sha256(prompt)>.json` and commit
the cache**, so `python -m archean.pipeline` reproduces `results.json` byte-for-byte **with no
API key at all**. The repo README explicitly says "If your submission needs no keys at all, say
so in the README — that is a legitimate and interesting answer." A committed cache gets us both:
a real LLM pipeline *and* a zero-key reproduction. `[R]` High value, cheap; do it.

---

## 10. The ENTRY vs TRANSFER problem

### 10.1 The rule (derived from `event_codes.json`, §3.4)

> **Mechanism events are extracted. Consequence events are derived.**
> Extract only `CAPITAL_INCREASE`, `CAPITAL_DECREASE`, `SHAREHOLDER_SHARE_TRANSFER` from
> documents. Emit `SHAREHOLDER_ENTRY` / `SHAREHOLDER_END` **exclusively** from the fold, by
> diffing `state_before` and `state_after`.

Decision procedure for any observed movement:

```
Does shares_total change?
├── YES → the shares are NEW or CANCELLED   → CAPITAL_INCREASE / CAPITAL_DECREASE
│         └── did a name appear/disappear?  → derive ENTRY / END  (mechanism = the capital event)
└── NO  → the shares MOVED between parties  → SHAREHOLDER_SHARE_TRANSFER
          └── did a name appear/disappear?  → derive ENTRY / END  (mechanism = the transfer)
```

The invariant that makes it safe: **a TRANSFER never changes `shares_total`; an
INCREASE/DECREASE always does.** Assert both in the validator.

### 10.2 Worked examples from this corpus

**(a) Double-count trap — CAPGRAS, 2006-10-20.** The AGE both *agrées* CAPGRAS as a new
shareholder (7th res.) **and** authorises AUMONT to cede him 225 shares (8th res.). Two
resolutions, **one** movement.

- Wrong: `SHAREHOLDER_ENTRY(CAPGRAS, 225)` **plus**
  `SHAREHOLDER_SHARE_TRANSFER(AUMONT→CAPGRAS, 225)` both applied to the fold → CAPGRAS ends with
  450, `shares_total` inflated to 2 225.
- Right: extract **one** `SHAREHOLDER_SHARE_TRANSFER(AUMONT→CAPGRAS, 225)`. The fold sees
  CAPGRAS is new → emits `SHAREHOLDER_ENTRY(CAPGRAS, shares=225, mechanism=TRANSFER)`.
  `shares_total` stays 2 000.
- Extra subtlety `[F]`: the resolution *authorises* — it does not record execution. Independent
  confirmation that it happened comes from HADEAN's statutes reciting AUMONT's 742 (= 967 − 225)
  and CAPGRAS's 225. Without that cross-check the honest answer would be `confidence: medium`
  with a note. **Use the cross-check and say where it came from.**

**(b) Artificial-share-creation trap — 2008-06-27.** HADEAN is already the sole holder with
200 000 shares and subscribes 17 241 new A shares.

- Wrong: `SHAREHOLDER_ENTRY(HADEAN, 17 241)` — HADEAN is not entering, and an ENTRY event for an
  existing holder invites a fold bug that adds a second HADEAN line.
- Right: `CAPITAL_INCREASE(+17 241, capital_after=217 241, method=numeraire)` with the allocation
  in the payload. No ENTRY — the fold sees HADEAN already present.

**(c) Artificial-disappearance trap — 2017-02-21.** Four funds sell 150 861 shares *to the
company*, which cancels them.

- Wrong: `SHAREHOLDER_SHARE_TRANSFER(FPCI SECURITE → ARCHEAN TECHNOLOGIES, 64 655)`. A transfer
  preserves `shares_total`; this would leave ARCHEAN holding its own shares and the capital
  would not fall.
- Right: **one** `CAPITAL_DECREASE(−150 861, capital_after=217 241, method=autre,
  mechanism="rachat et annulation")` naming the four sellers in the payload; the fold then
  derives **four** `SHAREHOLDER_END` events. This is the case where transfer-shaped language
  ("rachat", "offres d'achat") must *not* become a transfer event.

**(d) The genuinely ambiguous one — 2005-08-16.** Three holders sell everything to two holders,
`shares_total` unchanged at 1 500.

- `SHAREHOLDER_SHARE_TRANSFER` × N, `SHAREHOLDER_END` × 3 derived.
- But **we do not know how many shares each of the three held**, so we cannot write per-pair
  `shares`. The defensible output is a `SHAREHOLDER_SHARE_TRANSFER` per *cédant* with
  `shares: null` + a note, plus the *resulting* snapshot (823/617/60) which **is** documented.
  `[R]` Anchor the snapshot on the stated result, not on arithmetic we cannot perform.

### 10.3 Anti-double-count guards (as validator rules)

- Two events with the same `(event_date, from, to, shares)` → duplicate, fail.
- An `ENTRY` whose holder already exists in `state_before` → fail.
- An `END` whose holder is absent from `state_before` → fail.
- A `TRANSFER` whose `from` holds fewer shares than transferred → fail ("impossible transfer").
- Any `ENTRY`/`END` in `events[]` that the fold did **not** derive → fail (it means we extracted
  a consequence event by hand, violating §10.1).

---

## 11. French legal vocabulary — grounded in *this* corpus

Every term below was **observed in the ARCHEAN OCR**, with the document it came from. This is
the retrieval lexicon, not a textbook list.

| French (as it appears) | meaning | seen in | signals |
|---|---|---|---|
| `Constitution` / `acte sous seing privé` | incorporation | meta, `…ec5` | initial state |
| `ARTICLE 6 - APPORTS` | contributions article — **recites the full capital history** | `…ec3` p.7–8 | audit trail |
| `ARTICLE 7 - CAPITAL SOCIAL` | the operative capital clause | all statutes | capital, shares, nominal |
| `le capital social est fixé à la somme de …` | capital is set at | all statutes | `capital_after` |
| `il est divisé en N actions de X euros` | divided into N shares of X | all statutes | `shares_total`, `nominal` |
| `valeur nominale` / `de nominal chacune` | par value | all | `nominal_eur` |
| `répartition` / `attribuées aux actionnaires suivant la répartition suivante` | allocation table | `…ec5` p.3, `…ec2` p.6 | holders |
| `augmentation de capital` / `augmenter le capital social` | capital increase | `…ec4`, `…ec7`, `…ec3`, `…ec0` | `CAPITAL_INCREASE` |
| `pour le porter de X euros à Y euros` | to raise it from X to Y | `…ec7` p.3 | before **and** after in one line |
| `par création de N actions nouvelles` | by creating N new shares | `…ec4` p.2, `…ec7` p.3 | Δ shares |
| `émises au pair` | issued at par (no premium) | `…ec7` p.3 | premium = 0 |
| `prime d'émission` | issue premium | `…ec3` p.3 | **not** part of capital — do not add |
| `par compensation avec des créances certaines, liquides et exigibles` | debt-to-equity offset | `…ec7` p.3 | `method` sub-type |
| `par incorporation de réserves` / `prélèvement sur le poste « Autres Réserves »` | capitalisation of reserves | `…ec0` p.2 | `method = incorporation de reserves` |
| `attribuées gratuitement à l'Associé Unique` | free attribution | `…ec0` p.2 | no cash, pro-rata |
| `apport en numéraire` / `apport en nature` | cash / in-kind contribution | `…ec5` p.3; HADEAN `…9135` | method |
| `réduction du capital social` / `ramener de X à Y` | capital decrease | `…ebf` p.3, `…ebe` p.3 | `CAPITAL_DECREASE` |
| `rachat d'actions … en vue de leur annulation` | buyback for cancellation | `…ebf` p.3 | decrease, not transfer |
| `les actions rachetées sont annulées` | cancelled | `…ebe` p.3 | effective date |
| `associés minoritaires` | minority shareholders | `…ebf` p.3 | unnamed sellers |
| `division de la valeur nominale des actions` | share split | `…ec3` p.1 | nominal ÷ 100, shares × 100 |
| `cession d'actions` / `protocole de cession` / `céder N actions à` | share transfer | `…ec2` p.6, `…ec7` p.5 | `SHAREHOLDER_SHARE_TRANSFER` |
| `ordres de mouvement` / `registre des mouvements de titres` | transfer orders / share register | `…ec2` p.6 | **effective date of a transfer** |
| `agrée à devenir actionnaire` / `agrément d'un nouvel actionnaire` | approval of a new shareholder | `…ec7` p.2, p.4 | entry signal (mechanism elsewhere) |
| `droit de préemption` / `droit préférentiel de souscription` (DPS) | pre-emption / preferential subscription right | `…ec7`, `…ec3` | its *suppression* implies reserved subscribers |
| `réservée à des bénéficiaires dénommés` / `au profit de personnes dénommées` | reserved to named beneficiaries | `…ec7` p.2–3 | **the subscriber list follows** |
| `actions de préférence de catégorie A / B / B'` | preference share classes | `…ec3` p.2, p.8 | `CAPITAL_DUAL_CLASS` |
| `BSA` / `BSOC` / `ABSOC` / `obligations convertibles` | warrants / convertible instruments | `…ec3` p.3 | future dilution, not capital yet |
| `associé` / `actionnaire` / `Associé(e) Unique` | shareholder / sole shareholder | throughout | **"associé unique" implies holders == 1** |
| `feuille de présence` (`Nombre de Parts`) | attendance sheet with share counts | `…ec7` p.6 | **independent cap-table snapshot** |
| `assemblée générale ordinaire / extraordinaire / mixte` (AGO/AGE) | shareholder meeting types | throughout | AGE implies statutory change |
| `procès-verbal` (PV) / `décisions du président` | minutes / presidential decisions | throughout | doc type |
| `extrait de procès-verbal` | **excerpt** — resolutions may be omitted | `…ec3` | absence ≠ non-existence |
| `commissaire aux apports / aux avantages particuliers` | valuation / special-advantage auditor | `…ec6`, `…ec1` | out of scope, but corroborates |
| `déposé au greffe le` | filed at the registry on | p.1 stamps | **deposit date ≠ event date** |

`[R]` Two operational uses: (1) a **weighted page-scoring** function for Stage 1 retrieval —
`pour le porter de` and `il est divisé en` score far higher than `capital` alone; (2) a **README
glossary**, the cheapest possible way to show the reviewer we closed the French gap deliberately
rather than by luck. They said explicitly they find *how* we close it interesting.

---

## 12. External Sources

`[R]` **The corpus is sufficient for the capital chain. It is not sufficient for two holder
questions.** Be precise about which:

| missing | where it should have been | why it matters | external source that would settle it |
|---|---|---|---|
| **Per-holder allocation of the 1 130 shares of 2005** | the **AGE of 2005-03-04**, referenced in `…ec4` p.2 but absent | the only unknown split in the whole timeline; also fixes what GUELLATI/LEROUX/ROUJEAN held | INPI: pull all 2005 dépôts for 480489707. Secondarily BODACC 2005. |
| **Subscribers of the 150 861 B shares (2008)** | resolutions 10 & 12–15 of the 2008-06-27 decisions — omitted because the filed document is an ***extrait*** | 41 % of the capital for 9 years | INPI: the full PV rather than the extrait, if deposited. Otherwise the 2017 buyback list is the best available evidence. |
| **Transfer of BLANCO's 953 shares to HADEAN** | not in ARCHEAN's folder | completes the 2007→2008 handover | **already in the local corpus** — `data/499979540/actes/…069137` (2008-05-29). Check before going external. |
| SIREN of FPCI SECURITE / GALIA VENTURE / FINANCIERE DE BRIENNE / FIP GALIA PME 4 | never given | bonus only | `resolved: false` is the correct answer unless confirmed. FPCI/FIP are *fonds*, which frequently have **no SIREN of their own** — the management company does. Do not guess. |

`[R]` Time-box external lookups to **30 minutes, after the timeline is complete**, and record in
the README exactly what was looked up and what it changed. Do not start there.

---

## 13. Architecture

```
archean-actes/                        ← our own repo (sibling of the clone)
├── results.json                      ← THE deliverable
├── README.md                         ← how to run · trade-offs · How I used AI · what I left · recording
├── .env.example                      ← ANTHROPIC_API_KEY= / LLM_MODEL=claude-sonnet-5
├── .gitignore                        ← .env, out/, __pycache__
├── pyproject.toml                    ← pymupdf, pydantic, rapidfuzz, jsonschema, anthropic
├── src/archean/
│   ├── config.py          DATA_ROOT, SIREN, model name
│   ├── corpus.py          index meta+ocr+pdf → Document/Page objects   [deterministic]
│   ├── lexicon.py         the §11 terms, weighted                      [deterministic]
│   ├── route.py           typeRdd + lexicon → candidate page groups    [deterministic]
│   ├── extract.py         LLM call, strict schema, disk cache          [LLM]
│   ├── ground.py          snippet → line ids → polygon union → bbox    [deterministic]
│   ├── frenchnum.py       number-words & date-words → int / ISO date   [deterministic]
│   ├── names.py           canonicalise + alias map                     [deterministic + human]
│   ├── fold.py            CapitalState, apply(), derive ENTRY/END      [deterministic]
│   ├── validate.py        invariants + golden diff + jsonschema        [deterministic]
│   └── emit.py            results.json + notes                         [deterministic]
├── data_overrides/
│   ├── aliases.yaml       hand-approved name equivalences
│   └── adjudications.yaml ← contradictions we resolved, with the reason. Human, versioned, cited.
├── cache/llm/             committed → zero-key reproduction
├── tests/
│   ├── golden_capital_chain.json   ← §4.2, hand-built oracle
│   ├── test_bbox.py       conversion == bbox_viewer on known lines, BOTH page geometries
│   ├── test_frenchnum.py  "trois cent soixante dix" → 370; "37.0o0" → flagged
│   ├── test_fold.py       each event type; the four §10.2 traps as regression tests
│   └── test_schema.py     results.json validates against results.schema.json
├── scripts/
│   ├── inventory.py       regenerates the §4.1 table
│   ├── dump_ocr.py        dump a document's OCR text by page   (promoted from discovery)
│   ├── grep_ocr.py        accent-insensitive line grep         (promoted from discovery)
│   └── verify_boxes.py    renders every event's bbox → docs/box_checks/
└── docs/box_checks/*.png
```

`adjudications.yaml` is the piece I would most want a reviewer to see: it is where "we noticed
the documents disagree" becomes a reviewable artefact rather than a sentence in a README.

---

## 14. Implementation Plan (ordered)

1. `corpus.py` + `scripts/inventory.py` — reproduce §4.1 from the data. *(proves the plumbing)*
2. `tests/golden_capital_chain.json` — commit §4.2 **first**, so everything after has an oracle.
3. `ground.py` + `test_bbox.py` — the conversion, tested against `bbox_viewer --grep` output on
   3 known lines across both page geometries. *(de-risks the graded artefact early)*
4. `frenchnum.py` + tests.
5. `route.py` — `typeRdd` + lexicon → candidate pages. Print the shortlist; **eyeball it**
   against §4.1 before spending a token.
6. `extract.py` — Pydantic-typed output, cached, `evidence_line_ids` mandatory.
7. `fold.py` + `test_fold.py` — with the four §10.2 traps as named regression tests.
8. `validate.py` — invariants (§16), then golden diff, then jsonschema.
9. `emit.py` → `results.json`; run `scripts/verify_boxes.py`; eyeball the contact sheet.
10. README + `.env.example` + recording.
11. *(only if time remains)* `group.nodes/edges` from HADEAN + ARCHEAN LABS + bilans.

---

## 15. 6–8 Hour Prioritisation

The discovery above (~1 h) is already done and is a real asset — the capital chain, the
contradictions and the HADEAN link are found. Budget from here:

```
0:00–0:30  repo scaffold, config, corpus.py, inventory.py, golden file committed
0:30–1:15  ground.py + frenchnum.py + their tests   (provenance de-risked first)
1:15–2:00  route.py; shortlist reviewed by hand against §4.1
2:00–3:30  extract.py; run over the 7 P0 documents only; inspect every extraction
3:30–5:00  fold.py + derived ENTRY/END + the four trap tests
5:00–5:45  validate.py; fix what it catches; golden diff must be clean
5:45–6:15  emit results.json; verify_boxes.py; eyeball the contact sheet
6:15–7:15  README (glossary, contradictions, gaps, How I used AI, trade-offs) + .env.example
7:15–7:45  recording
7:45–8:00  final audit: schema validation, no .env committed, links work
```

### MUST HAVE

- `results.json` that **validates against the schema** (a file they cannot parse scores zero).
- The full capital chain 37 000 → 400 000 with correct `capital_after` at every step.
- Correct `event_date`s taken from document bodies, never filenames.
- Every event grounded: real `inpi_id`, real page, **code-computed** bbox, verbatim snippet.
- The **derived** ENTRY/END model (§10.1), stated and implemented.
- `README.md` naming C1–C8: the 20-share discrepancy, the 6 %/4 % error, the 185 759/182 759
  typo, the missing 2005-03-04 AGE, the unnamed 2005 subscribers, the unnamed 2008 B holders,
  and the fact that the HADEAN handover is **not** in this folder.
- `.env.example`, `.gitignore` with `.env`, no committed key.

### SHOULD HAVE

- Validator with hard invariants + the golden-chain diff, run in `make check` or CI.
- `docs/box_checks/` contact sheet.
- Committed LLM cache → reproduction with no API key.
- French glossary in the README.
- `confidence` + `derivation` on every event and snapshot.
- HADEAN cross-reference used to close the 2007→2008 gap, explicitly sourced.

### NICE TO HAVE

- `CAPITAL_DUAL_CLASS` events for the A/B/B' classes (free, unscored).
- Per-class share tracking (A vs B) inside snapshots.
- `group.nodes/edges`: ARCHEAN ← HADEAN (evidenced), ARCHEAN LABS (?), ARCHEAN INTERNATIONAL
  (`resolved: false`), plus a second hop (who owns HADEAN) from HADEAN's own statutes.
- Bilans used as an independent capital cross-check.

### CUT FIRST

1. **Local OCR fallback** — zero value here (§8.2). Cut immediately.
2. **The group bonus beyond HADEAN** — the brief says "do the timeline first". If the timeline
   is not clean by 6:00, emit only the HADEAN edge (or none) and say so.
3. **Generalising the pipeline to all 20 companies.** Tempting, scores nothing.
4. **A web UI / notebook dashboard.** Scores nothing.
5. **Per-class (A/B) tracking** if the fold gets fiddly — collapse to one class and note it.
6. **External INPI lookups** — strictly after everything else.

---

## 16. Validation Strategy

### 16.1 Invariants (assert, and on failure **record**, never silently repair)

**Arithmetic**

- `I1` `capital_after == capital_before + amount` for every INCREASE/DECREASE.
- `I2` `capital_eur == shares_total × nominal_eur` at every snapshot. *(Holds at every step of §4.2.)*
- `I3` `sum(h.shares for h in holders) == shares_total`, when all holder shares are known.
- `I4` `sum(pct) ∈ [99.5, 100.5]`; `pct` is computed, never parsed.
- `I5` a TRANSFER leaves `shares_total` and `capital_eur` **unchanged**.
- `I6` an INCREASE/DECREASE **changes** `capital_eur`.
- `I7` a nominal split leaves `capital_eur` unchanged and scales `shares_total` inversely.
- `I8` `shares` are integers ≥ 0; no fractional shares anywhere.

**Cap-table integrity**

- `I9` no duplicate holder name within one snapshot (post-canonicalisation).
- `I10` a holder present in `state[n]` and absent from `state[n+1]` **must** have a
  `SHAREHOLDER_END` in `state[n+1].caused_by`. *(catches silent disappearance)*
- `I11` a holder absent from `state[n]` and present in `state[n+1]` must have a
  `SHAREHOLDER_ENTRY`. *(catches silent appearance)*
- `I12` `transfer.shares <= state_before[from].shares`. *(impossible transfer)*
- `I13` if any document says `associé unique` at date D, `len(holders) == 1` at D.
  *(free, very strong — it fires on 2008, 2017 and 2018)*

**Temporal**

- `I14` `capital_timeline` is non-decreasing in `as_of`.
- `I15` `event_date <= meta.dateDepot` for every event. *(the deposit is never before the decision)*
- `I16` no two events share `(event_code, event_date, payload_signature)`. *(duplicates)*
- `I17` same-day events have an explicit `seq`.

**Provenance**

- `I18` every event has a `source`; `inpi_id` exists in `meta/`; `page <= pdf.page_count`.
- `I19` `0 <= bbox[i] <= 1`, `x0 < x1`, `y0 < y1`, and area is neither ~0 nor > 0.5 of the page.
- `I20` `snippet` fuzzy-matches (≥ 0.90) the concatenated OCR text of the cited lines **on that
  page of that document**. *(the anti-hallucination check)*
- `I21` every numeral in `payload` appears in the cited snippet, or `grounded_numbers: false`.

**Oracle**

- `I22` the emitted `(date, capital_eur, shares_total, nominal_eur)` sequence equals
  `tests/golden_capital_chain.json` exactly.
- `I23` `results.json` validates against
  `challenges/actes/schema/results.schema.json` (`jsonschema` draft 2020-12).

### 16.2 What "failure" means

`[R]` The validator should have **three outcomes**, not two: `PASS`, `WARN` (a known,
adjudicated contradiction listed in `adjudications.yaml` — e.g. C1's 20 shares), and `FAIL`
(anything else). A `WARN` must carry the adjudication reference. That way the 823/803 conflict
shows up as a *documented, intentional* warning rather than either a crash or a silence — and
`notes` can be generated from the WARN list automatically, guaranteeing the README and the JSON
tell the same story.

---

## 17. Main Risks

| # | risk | likelihood | impact | mitigation |
|---|---|---|---|---|
| R1 | **Over-engineering the pipeline and running out of time before `results.json` exists** | **high** | fatal | build the golden file and `emit.py` early; a hand-seeded but validated `results.json` at 4:00 beats a beautiful half-pipeline at 8:00 |
| R2 | LLM invents a share count that OCR never contained | medium | high | I20/I21; `evidence_line_ids`; temperature 0 |
| R3 | bbox off-by-scale (A4 assumed for the 1655×2360 pt scans) | medium | high | read `page.rect` per page; `test_bbox.py` covers **both** geometries |
| R4 | wrong `event_date` (deposit vs decision) | medium | high | I15 + French date-word parser + the §5.4 table as test fixtures |
| R5 | double-counting ENTRY + TRANSFER (the brief's own warning) | medium | high | §10.1 rule + the four trap regression tests |
| R6 | the 2010/2011 duplicate dépôts produce duplicate events | medium | medium | deduplicate by `numChrono`; I16 |
| R7 | name variants split one holder into two (`GICQUEL`/`GICOUEL`) | high | medium | canonicalise + committed alias map + I9 |
| R8 | asserting the HADEAN handover without reading `…069137` | medium | medium | read it, or mark `[H]` explicitly |
| R9 | committing a real key | low | **very high** (explicitly "counts against you") | `.gitignore` `.env` from commit #1; grep the diff before the PR |
| R10 | schema violation (bbox > 1, wrong `siren`) makes the file unscoreable | low | fatal | I19/I23 in `make check`, run last |
| R11 | scope creep into the group bonus | medium | medium | hard gate at 6:00 |

---

## 18. Expected Weak Points

Where I expect our submission to be genuinely weak, and where the README must say so plainly:

1. **The 2005-05-17 cap table.** We will know capital (150 000) and share count (1 500) but
   **not the split**, and not what GUELLATI/LEROUX/ROUJEAN held. Best output: a snapshot with
   `shares: null` per holder and `holders_known: false`. Any specific split we write would be
   invented. This is the largest genuine hole and it is unavoidable from this corpus.
2. **The 2008 B-share attribution.** Back-inferred from a 2017 document. Defensible, but it is an
   inference across nine years during which those funds could have traded among themselves.
   Mark `confidence: medium` and say why.
3. **The 20-share discrepancy (C1).** We can detect it; we cannot adjudicate it. Two documents,
   both official, both internally consistent. The right answer is to report both and decline to
   pick — which is also what the brief says they look for.
4. **BLANCO's exit.** Until `…069137` is read, "BLANCO's 953 shares went to HADEAN in 2008" is
   `[H]`, not `[F]`. If time runs out, it stays a hypothesis and must be labelled one.
5. **Preference-class tracking.** A/B/B' with conversion rights and BSOC/OCA instruments are
   genuinely complex; we will likely track class as a label only and ignore conversion mechanics.
   Acceptable — no conversion appears to have occurred — but say it.
6. **SIREN resolution for the four funds.** Almost certainly unresolved. `resolved: false`.
7. **The 2025 document.** Metadata shape differs (`PJ_52`, `numNat`, no `typeRdd`); our router
   may need a special case. Low impact (no capital event) but it will look like a gap if unhandled.
8. **Bilans unused.** Nine annual filings for ARCHEAN sit unread in the main plan. They could
   cross-check capital and reveal the group. Realistically out of budget.

---

## 19. Claude Code / VS Code Workflow

Assessed against what this environment **actually** offers (verified, not assumed):

| capability | available here | use it? | why, for *this* challenge |
|---|---|---|---|
| **Bash + Python one-liners** | yes | **heavily** | The entire discovery above was ~12 Bash/Python calls. Ad-hoc OCR greps are the highest-bandwidth tool in this task. |
| **Grep tool (ripgrep)** | yes | limited | Accents and the per-line JSON structure mean a small Python grep beats raw ripgrep here. Keep the Python one. |
| **Read / Edit / Write** | yes | yes | Normal editing. |
| `tools/bbox_viewer.py` | yes | **critical** | It is the *reference implementation* of the graded conversion. Test against it. |
| **PyMuPDF (installed)** | yes | yes | Page geometry; page rendering for visual checks. |
| **Git / GitHub (`gh`)** | yes | yes | Submission is a PR with `@YassineBouderbala` and `@AleBastos25` invited as reviewers. |
| **pytest** | yes | yes | The golden file + trap tests are the cheapest credibility we can buy. |
| **JSON Schema validation** | yes (`jsonschema`) | **must** | "A submission we cannot parse is a submission we cannot score." |
| **`CLAUDE.md`** | yes | yes | §20 — it is what stops a long session drifting into invention. |
| **Subagents (`Agent` tool)** | yes | **sparingly** | §21. |
| **MCP servers** | a Google Drive connector is listed but **unauthenticated in this session** | no | Not usable here and not needed. Don't design around it. |
| **WebSearch / WebFetch** | yes (deferred tools) | late only | Only for §12, time-boxed to 30 min *after* the timeline. |
| **VS Code split view** | yes | yes | Render a page to PNG and open it beside the OCR JSON — this is how you resolve the interleaved-table problem by eye in seconds. |
| **Scratchpad dir** | yes | yes | Keep throwaway greps out of the deliverable repo. |

**Concrete working loop `[R]`:**

1. Keep `DISCOVERY.md` (this file) open as the working spec; update it as facts change.
2. One terminal running `pytest -q` on save; one running `python -m archean.validate`.
3. For any disputed number:
   `python tools/bbox_viewer.py --pdf … --page N --ocr … --grep "…"` → copy the printed box →
   that *is* the submittable bbox. Fast, and it is the graders' own tool.
4. Commit per stage with messages that name the finding (e.g. *"fold: derive ENTRY/END at
   projection time per event_codes.json"*). The git log becomes evidence of reasoning for the
   recording.

**Investigation artefacts created during this discovery** (throwaway, in the session scratchpad,
**not** part of the deliverable): `dump.py` (dump a document's OCR text by page),
`grep_corpus.py` (accent-insensitive line grep over 480489707), `grep_any.py` (same across all
20 companies). `[R]` Promote `dump.py` and `grep_corpus.py` into `scripts/` — they are genuinely
useful and they show the reviewer how the corpus was explored.

---

## 20. `CLAUDE.md` Proposal

`[R]` **Yes, create one** — in our solution repo, not in the clone. The specific failure it
prevents is the one the challenge punishes hardest: a long session quietly inventing a share
count or a bbox to make the timeline close. Proposed content:

```markdown
# ARCHEAN TECHNOLOGIES — actes challenge

## What this repo is
Reconstruct the capital composition of ARCHEAN TECHNOLOGIES (SIREN 480489707), 2005–2025,
from its filed actes. Output: `results.json` at the repo root, matching
`../engineering-challenges/challenges/actes/schema/results.schema.json`.
Budget: 6–8 hours total. Partial and auditable beats complete and unverifiable.

## Rules that are never broken
1. **Never invent a number.** Every figure in `results.json` traces to OCR text we can quote.
   If it is unknown, it is `null` plus a note. "Unknown" is a correct answer.
2. **Never invent a bounding box.** Boxes are computed by `ground.py` from OCR polygons.
   No LLM output is ever written into a `bbox` field.
3. **`event_date` is the date in the body of the decision.** Never the filename, never
   `dateDepot`. Where a decision is authorised then realised, the capital event is dated at
   realisation, with `authorised_on` in the payload.
4. **Extract mechanisms; derive consequences.** Only CAPITAL_INCREASE, CAPITAL_DECREASE and
   SHAREHOLDER_SHARE_TRANSFER come from documents. SHAREHOLDER_ENTRY and SHAREHOLDER_END are
   emitted by `fold.py` from a state diff. (Per `event_codes.json`.)
5. **Scope is capital composition only.** Auditors, presidents, addresses, objet social, name
   changes: ignore, even when they sit in the same resolution.
6. **Contradictions are reported, not resolved silently.** Anything adjudicated goes in
   `data_overrides/adjudications.yaml` with the reason and both citations, and is surfaced in
   `results.json > notes`.
7. **Never commit `.env`, a key or a token.**

## Output contract
- `siren` is the literal string `"480489707"`.
- `bbox` = `[x0,y0,x1,y1]`, normalized 0–1, origin top-left, page 1-indexed.
  Conversion: `px / (page.rect.<dim> * 300/72)`, using **that page's** rect.
- `source.inpi_id` = the 24-hex id in the PDF filename (== `meta.id` == the OCR dir name).
- Money as `Decimal`; shares as `int`. Never float.

## Commands
    python -m archean.pipeline          # full run (uses cache/, no API key needed)
    python -m archean.validate          # invariants + golden diff + jsonschema
    python scripts/inventory.py         # regenerate the document table
    python scripts/verify_boxes.py      # render every event bbox to docs/box_checks/
    pytest -q
    python ../engineering-challenges/tools/bbox_viewer.py --pdf <pdf> --page N --ocr <dir> --grep "<text>"

## Definition of done
`pytest` green · `validate` reports PASS or only adjudicated WARNs · `results.json` validates
against the schema · every event's box rendered and eyeballed · README covers how to run it,
trade-offs, "How I used AI", what is unresolved, and the recording link · `.env.example` present,
`.env` absent.

## LLM policy
LLM reads French and pairs names to counts on a *given page*, returning `evidence_line_ids`
plus a verbatim `snippet`. Code does all arithmetic, all dates, all boxes, all folding, all
validation. Temperature 0. Every response cached to `cache/llm/` and committed.

## When a document is ambiguous
Emit the event with `confidence: low` and a `note`, record it in `adjudications.yaml`, and
surface it in `notes`. Do not pick the most recent document just because it is the most recent.
```

---

## 21. Subagent Strategy

`[R]` **Two, at most — and not the five-agent split.** Honest reasoning:

- The corpus is **17 documents / 293 pages / one company**. Five cold-started agents would each
  re-derive the same context (schema, conversion, capital chain) and then need reconciling —
  which costs more than doing it inline, and risks five slightly different capital chains.
- The task is also **deeply sequential**: routing depends on the lexicon, extraction on routing,
  the fold on extraction, validation on the fold. There is little genuine parallelism.
- The parts that *are* independent are the ones where a fresh, uncontaminated reading is actually
  valuable — i.e. auditing, not producing.

**Where a subagent genuinely pays:**

| agent | when | why it beats doing it inline |
|---|---|---|
| **A — Group/bonus investigator** | after 6:00, only if the timeline is done | Truly independent (different sirens, different folders), read-only, and its context (20 companies × bilans) would otherwise pollute the main session. Runs in the background while the README is written. |
| **B — Adversarial timeline auditor** | once at ~5:30, on the finished `results.json` | The single highest-value use: give it *only* the schema, `results.json` and the corpus path, and ask it to break the timeline — find an unsourced holder change, a box pointing at the wrong line, an arithmetic gap. A cold reader catches what the author cannot. |

**Not worth a subagent:** repository analysis (done, inline), document analysis (17 docs — the
main session reads them faster than it can brief an agent), French legal analysis (a lexicon
file, not an agent), provenance audit (that is `scripts/verify_boxes.py` plus your eyes —
deterministic code beats a model here).

`[R]` Run A and B **in the background**, both read-only, and never let a subagent write to
`results.json`. Per this environment's standing guidance, I will only spawn them if you ask.

---

## 22. Recommended Next Step

**One concrete action, before any pipeline code:**

> **Create the solution repo skeleton and commit `tests/golden_capital_chain.json` — the §4.2
> capital chain — as the very first commit.**
>
> ```
> D:\projeto takeovers\archean-actes\
>   ├── tests/golden_capital_chain.json    ← the 10-row table of §4.2, with the inpi_id + page
>   │                                        that proves each row
>   ├── CLAUDE.md                          ← §20
>   ├── .gitignore                         ← .env
>   └── DISCOVERY.md                       ← this file, moved in
> ```

Why this first, and not `corpus.py`: it converts an hour of reading into a **machine-checkable
oracle**. From that commit onward, every later stage has something to be wrong against, and the
risk that most often kills this kind of submission — a plausible-looking pipeline whose numbers
silently drift — is closed before a single line of extraction code exists.

Immediately after, in order: `ground.py` + `test_bbox.py` (provenance de-risked second, because
it is the graded artefact), then routing, then extraction.

**Awaiting your approval before implementing anything.**
