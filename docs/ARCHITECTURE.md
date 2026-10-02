# Architecture, as built

`BUILD-PLAN.md` is the specification. This document describes what exists,
where it lives, and **every deviation from the plan, with its reason**
(the last section). When the two disagree, this one describes the code and
the plan describes the intent.

---

## 1. One request, end to end

```
 statement parse x.pdf
        │
        ▼
 cli/main.py ──► cli/composition.py   builds: PdfplumberReader, DirectoryProfiles,
        │                             CachedLlm(AnthropicLlm | OllamaLlm | none)
        ▼
 pipeline/run.py  Pipeline.parse(bytes)
        │
        ├─ ① ingest      size cap, %PDF- magic                    ─► REJECTED
        ├─ ② text layer  adapters/pdf_reader.py: words+boxes → lines (p{n}-l{m})
        │                page cap, encrypted, no text              ─► REJECTED
        ├─ ③ classify    extract/tier1.classify: fingerprint tokens + header line
        ├─ ④ tier 1      extract/tier1.extract: header-anchored columns → RawRow
        │                → domain/assemble.assemble → Statement
        ├─ ⑤ verify      domain/verify.verify ── ok & no doubts ──────────► ACCEPTED
        │
        ├─ ⑥ tier 2      rescue/tier2.rescue: prompt → LLM → schema → grounding
        │                → rule inference → domain/assemble.assemble
        ├─ ⑦ verify      same verifier, same thresholds ──────────────────► ACCEPTED
        │
        └─ ⑧ degrade     best available statement + every reason ─────► NEEDS_REVIEW
```

`ParseResult` carries the verdict, the statement (or none), all reasons,
the per-check outcomes, token usage, and a trace of every stage with timings.
`statement explain` prints that trace.

## 2. Rings and contracts

```
 ring 3  statement.cli               typer CLI; the composition root
 ring 2  statement.adapters          pdfplumber, reportlab, httpx, fs cache, yaml
 ring 1  statement.evaluate | forge  scorer, corruption harness, reports, canary, generator
         statement.pipeline          the trust ladder
         statement.rescue | extract  tier 2 | tier 1   (independent siblings)
         statement.ports             protocols + the Extraction type both tiers return
 ring 0  statement.domain            money, model, parsing, assemble, verify, profile schema
```

Four import-linter contracts (`pyproject.toml`), run by `make imports`:

1. **Rings**: the layer order above, inward only.
2. **Domain is pure**: no pdfplumber, reportlab, httpx, yaml or typer.
3. **INV-05**: `statement.rescue` may not import `statement.domain.verify`.
4. **Scorer off the product path**: pipeline, extract and rescue may not
   import evaluate or forge.

## 3. The domain, file by file

| File | Owns |
|---|---|
| `money.py` | `Money` (Decimal), minor units per currency, float refusal (INV-09), precision check |
| `model.py` | `Txn`, `Statement`, `Provenance`, `BalancePolicy`; INV-03 in the `Txn` validator |
| `parsing.py` | amounts (5 sign spellings, lakh/western/EU grouping), dates (year rollover), locale and date-format **inference by evidence** |
| `assemble.py` | `RawDoc` + `ReadingRules` → `Statement`. The single interpretation path for both tiers (INV-07) |
| `verify.py` | INV-01 totals, INV-02 chain with resync, balance presence (INV-10), INV-04 dates |
| `profile.py` | the profile schema: `extra="forbid"`, coherence checks, column alignment |
| `reasons.py`, `outcome.py`, `text.py` | reason codes, `Ok`/`Fail`, the text-layer data types |

## 4. Tier 1 geometry

Column regions come from the header row on each page, using each column's
**alignment**, not header midpoints:

- **Before a left-aligned column**, the boundary sits 2pt left of its header.
  A wide narration may run up to the next column.
- **Before a right-aligned column**, the boundary sits one header-width
  (minimum 40pt) left of its header, and never left of the previous header's
  end. Wide amounts may start left of a short `Amount` header.

A word belongs to the region containing its centre.

Each line is then classified as one of:
- a **row**: it has a parseable date;
- a **carry-forward row**: it has amounts but no date, and the profile allows
  carry-forward;
- a **continuation**: description only, appended to the previous row;
- **skipped**: it matches a skip pattern;
- **end of the page's table**: it matches a stop pattern;
- **`ROW_UNPARSED`**: it has amounts but no rule covers it. Such a line is
  never dropped silently.

A page without a repeated header reuses the previous page's geometry. On such
a page, lines before the first dated row are ignored.

## 5. Tier 2 contract

- **One request per document.** All lines go in as `<line_id>\t<text>`. The
  prompt contains no arithmetic rules (§C3).
- **Reply validation.** The reply is validated against `rescue/schema.py`.
  Extra keys are ignored; missing or mistyped keys fail as
  `RESCUE_UNPARSEABLE`.
- **Grounding** (`rescue/grounding.py`):
  - amounts and balances must appear on the row's own lines;
  - dates on the row's lines or earlier on the same page;
  - document fields anywhere in the document;
  - description words on the row's lines.
  Unknown and duplicate line ids are reported. Rows are re-sorted into print
  order (INV-11).
- **Rule inference** (`rescue/tier2._infer_rules`):
  - number locale, by unanimous evidence;
  - amount mode, from which cells are filled and whether Dr/Cr markers
    appear;
  - balance policy (all, none, or mixed treated as every-row, so gaps
    surface);
  - date formats, as the unique pair that fits period, order and range.

## 6. Evaluation

| Piece | File | Notes |
|---|---|---|
| Forge | `forge/ledger.py`, `layouts.py`, `corpus.py`, `plan.py`; `adapters/pdf_renderer.py` | 6 layout families + 4 drifted templates; splits dev / unknown / drift / holdout (secret seed) / canary; refuses overlapping text |
| Scorer | `evaluate/score.py` | LCS over (date, amount, direction); then description and balance; silent-wrong; per-layout summaries |
| Corruption | `evaluate/corrupt.py` | 12 catalogue mutations on truth statements; detection rate per F-code |
| Reports | `evaluate/report.py` | static HTML scorecards, light/dark, worst documents first |
| Replay | `statement replay` | deterministic JSONL dump for byte-for-byte regression |
| Canary | `evaluate/canary.py`, `statement canary` | live readings of 30 fixed docs compared with the previous live run |

Runs are written to `runs/<UTC stamp>-<corpus>/`, which holds
`scorecard.json`, `results.jsonl` and `scorecard.html`. Every scorecard
embeds a manifest: git sha (or `not-a-git-repo`), profile versions, model,
prompt hash, cache mode, a corpus fingerprint, Python and platform.

## 7. Configuration

All configuration comes from `STATEMENT_*` environment variables, read only
in `cli/composition.py`.

| Variable | Default | Meaning |
|---|---|---|
| `STATEMENT_LLM` | `none` | `none`, `anthropic` or `ollama` |
| `STATEMENT_LLM_MODEL` | provider default | model name |
| `STATEMENT_CACHE_MODE` | `replay` | `live`, `record` or `replay` |
| `STATEMENT_CACHE_DIR` | `cache/llm` | response cache root |
| `STATEMENT_ANTHROPIC_API_KEY` | — | needed only for live/record with Anthropic |
| `STATEMENT_LLM_BASE_URL` | provider default | explicit only; the ambient `ANTHROPIC_BASE_URL` is ignored on purpose |
| `STATEMENT_PROFILES` | `profiles` | profile directory |
| `STATEMENT_HOLDOUT_SECRET` | — | required to generate the holdout |

The defaults are safe: no model, replay only. Nothing leaves the machine and
nothing costs money unless explicitly enabled.

---

## 8. Deviations from BUILD-PLAN.md

| Plan | As built | Why |
|---|---|---|
| §C3: Tier 2 receives Tier 1's failure reasons as hints | Tier 2 gets the page text only | hints depend on Tier-1/profile state, so any profile change would invalidate every cached LLM answer and break drift-proof replay (ADR-0009); revisit with hints *outside* the cache key |
| §C3: re-read single pages | one request per document | statements in scope are 1–4 pages; whole-document context keeps continuation rows intact; per-page chunking is the `RESCUE_BUDGET` follow-up |
| §B3 INV-06: values grounded on the row's lines | dates may also ground on an earlier line of the same page | carry-forward layouts print a day's date once; amounts and balances are still row-strict |
| §D1: simulator emits zero-amount rows | no zero-amount rows; zero appears as the printed empty leg (`0.00`) | a zero-amount transaction contradicts INV-03; the INV-10 trap is the zero-filled leg, which `split_zero_filled` exercises |
| §D1: dev / unknown / holdout splits | added `drift` (profiled banks after a template change) | risk R1 tripped (100% on dev); drift is the realistic way header-keyed parsers fail |
| §C2: SQLite run store | runs are directories of JSON + HTML; `eval-diff` compares them; canary history is JSON files | nothing in v1 needed queries across runs; files are diffable and committed as evidence (`docs/results/`) |
| §F4: parse in a worker with memory/time limits | size and page caps, plus a process pool for `eval`; no per-document memory or timeout limit | portable rlimits are not available on macOS; listed as an open item |
| §F4: `--redact`, `--local-only` | Ollama adapter exists (`STATEMENT_LLM=ollama`); no redaction | redaction with re-hydration by line id is designed but not built |
| §F3: cost report per tier | token counts per document and per run; no price table | no real model has been run yet, so there is nothing honest to price |
| §B4 F11 in the corruption harness | covered by Tier-2 tests with a scripted model | injection needs a model in the loop; the corruption harness is model-free |
| §F2: structlog | removed; trace events on `ParseResult` | unused dependency (ADR-0006) |
| Profile schema | added `Column.align` | needed for correct boundaries (session log #2) |
