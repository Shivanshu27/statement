# Statement — Design & Delivery Specification

> **Turns any bank-statement PDF into verified transaction data, and teaches itself new layouts under supervision.**

| | |
|---|---|
| **Status** | Draft v1. Specification only; no code yet |
| **Audience** | (1) the engineer or coding agent who builds it, (2) a reviewer judging the author's engineering |
| **Reading order** | Part A → Part B, then the rest as needed. **Part B is the contract.** Nothing in Parts C–G may contradict it |
| **Name** | "Statement" is a working name. Rename in M0, before it reaches package names |

### How this document is organised

```
 Part A  THE BET            why build it, what we claim, what we refuse to build
 Part B  CORRECTNESS        what "right" means — written before any code exists
 Part C  SYSTEM             the machine that delivers Part B
 Part D  EVALUATION         how we know Part B holds, with numbers
 Part E  ONBOARDING AGENT   the AI that extends the system, and how it is fenced in
 Part F  OPERATIONS         drift, cost, security, observability
 Part G  DELIVERY           increments, risks, decisions, quality bar, exit
 Appx    TRACEABILITY       hypothesis → invariant → test → metric
```

Every claim in this document has an identifier: `H` hypothesis, `INV` invariant, `F` failure mode, `R` risk, `ADR` decision. The appendix ties them together. If something has no ID, it is commentary, not a requirement.

---

# Part A — The Bet

## A1. The problem in one paragraph

Every bank prints statements in its own layout, and changes that layout every few years. Personal-finance tools, accountants, lenders, and anyone else who needs transactions end up writing one parser per bank. Those parsers are positional ("the amount is in column 5"), so they break silently when a column moves. LLMs read layouts by meaning and can fix the brittleness, but they introduce a worse failure: **a confident, plausible, wrong number**. On financial data, a wrong number that looks right is worse than no number.

Statement is built around one observation: **a bank statement checks itself.** The running balance is a hash chain over the transactions:

```
balance[i] = balance[i-1] + credit[i] - debit[i]
opening    + Σcredits - Σdebits = closing
```

If any row is dropped, duplicated, sign-flipped, or misread, the chain breaks. This lets Statement use a fast deterministic parser first and an LLM as a fallback, and **refuse to accept any output the arithmetic cannot verify.** A third component, the onboarding agent, adds support for new layouts by writing *data* (layout profiles), scored against ground truth it cannot see or edit.

## A2. Hypotheses

These are the project's falsifiable claims. The README reports each one with a measured number, including the ones that fail.

| ID | Hypothesis | Measured by | Pass bar |
|---|---|---|---|
| **H1** | Balance-chain verification catches nearly all extraction errors that matter | share of injected corruptions (F-catalogue, §B4) detected by invariants | ≥ 99% of single-row corruptions |
| **H2** | Ordering the pipeline as "verify, then escalate" keeps the **silent-wrong rate at zero** | documents `ACCEPTED` whose rows disagree with truth, on the sealed holdout | **0**, at any coverage |
| **H3** | An LLM rescue raises coverage on unseen or changed layouts without harming H2 | coverage with vs without Tier 2 on the "unknown layout" split | ≥ +30 pp coverage, H2 still 0 |
| **H4** | A supervised agent can onboard a new layout from ≤ 10 labelled samples, writing only profile data | wall-clock time and holdout agreement for a fresh layout | < 1 h, ≥ 98% row agreement |
| **H5** | Hosted-model drift is real and detectable at low cost | canary diff rate over ≥ 4 weeks | report whatever is observed; cost < $1/week |

H2 is the product. The other four describe how much value we get without breaking it.

## A3. Scope fence

| In (v1) | Out (deliberately) | Later (designed for, not built) |
|---|---|---|
| Text-layer PDFs (digitally generated) | Credit-card statements, invoices, receipts | Scanned PDFs through vision OCR |
| Single-account statements, one currency | Multi-currency, FX legs | A second document family (receipts) to show the design generalises |
| CLI + library + static HTML scorecard | Hosted SaaS, accounts, auth | A minimal review UI for `NEEDS_REVIEW` items |
| Synthetic corpus with exact ground truth | Real customer statements in git, **ever** | Opt-in local private corpus (never committed) |
| Provider-agnostic LLM port: one hosted + one local adapter | Fine-tuning, training any model | |
| Onboarding agent as a Claude skill + scripts | Autonomous agent that merges its own PRs | Scheduled "sharpen existing profiles" job opening PRs |

**Rule:** if a reviewer asks "why does this box exist?", the answer must point to an ID in this document. Anything without one is decorative and gets deleted.

## A4. What a reviewer should come away believing

| Signal | Evidence they will find |
|---|---|
| Treats LLMs as unreliable components, not oracles | Part B verdict model; LLM output never decides acceptance (INV-05) |
| Thinks in invariants, not happy paths | §B3 with a named test per invariant |
| Measures instead of asserting | Part D harness; README numbers carry run manifests |
| Designs against reward hacking | §E3: scorer and holdout immutable to the agent, enforced by CI |
| Operates what they build | Part F drift canary with real weeks of data |
| Knows where to stop | §A3 scope fence; ADRs with real negative consequences |

---

# Part B — Correctness (the contract)

> This part was written first and changes only through an ADR. Code serves it.

## B1. Canonical output

```python
class Statement(BaseModel):          # pydantic v2, frozen
    doc_id: DocId                    # sha256 of the source bytes
    account: AccountRef              # masked number, holder name optional
    currency: CurrencyCode           # ISO 4217; one per statement in v1
    period: DateRange                # inclusive
    opening_balance: Money
    closing_balance: Money
    transactions: tuple[Txn, ...]    # in statement order — order is data
    provenance: Provenance           # tier, profile id+version, model id, prompt hash

class Txn(BaseModel):
    seq: int                         # 0-based position in statement order
    posted: date
    value_date: date | None
    description: str                 # whitespace-normalised, otherwise verbatim
    debit: Money                     # >= 0
    credit: Money                    # >= 0; exactly one of debit/credit is > 0
    balance: Money | None            # as printed; None only if the layout never prints it
    reference: str | None
    source: SourceSpan               # page index + bbox lines it was read from
```

`Money` is `Decimal` quantised to the currency's minor unit. **No float exists anywhere between the PDF and the output** (INV-09).

## B2. The verdict model

Every document ends in exactly one of three states:

```
                        ┌──────────────────────────────────────────┐
                        │  ACCEPTED       all invariants hold       │──► trusted output
 document ─► pipeline ─►│  NEEDS_REVIEW   parsed, but ≥1 invariant  │──► output + reasons,
                        │                 failed or was unprovable  │    never marked trusted
                        │  REJECTED       not a statement / unsafe  │──► reason only
                        └──────────────────────────────────────────┘
```

- `ACCEPTED` is a **claim backed by arithmetic**, not by model confidence.
- `NEEDS_REVIEW` is a normal, honest outcome. Coverage (the share `ACCEPTED`) is **reported, never optimised** (see §E1).
- A verdict carries machine-readable `reasons: list[ReasonCode]`. The CLI exits non-zero for anything other than `ACCEPTED` unless `--allow-review` is passed.

### Correctness levels

| Level | Meaning | Who checks it | When |
|---|---|---|---|
| **L1** Well-formed | schema-valid, types right, dates inside the period | pydantic + validators | every document, runtime |
| **L2** Self-consistent | balance chain and totals reconcile | invariant engine | every document, runtime |
| **L3** True | agrees with ground truth row by row | evaluation harness | offline only, where truth exists |

L2 is what we can prove at runtime. L3 is how we *measure whether L2 is enough* (H1, H2). The gap between them is documented, not hidden (§B5).

## B3. Invariants

Each invariant has one enforcement point and one test named after it. Changing an invariant requires an ADR.

| ID | Invariant | Enforced in | Test |
|---|---|---|---|
| **INV-01** | `opening + Σcredit − Σdebit == closing`, exactly | `verify/chain.py` | `test_totals_reconcile_exactly` |
| **INV-02** | For every row with a printed balance: `bal[i] == bal[i-1] + credit[i] − debit[i]` | `verify/chain.py` | `test_running_balance_chain_holds` |
| **INV-03** | Exactly one of `debit`/`credit` is non-zero per row; both are non-negative | `domain/txn.py` | `test_txn_has_single_signed_leg` |
| **INV-04** | `posted` dates are non-decreasing in statement order (or the profile declares otherwise) and lie within `period` ± profile tolerance | `verify/dates.py` | `test_dates_monotonic_and_in_period` |
| **INV-05** | Acceptance is decided only by the invariant engine. No LLM output, confidence score, or prompt text can set a verdict | `pipeline/verdict.py`, import contract | `test_llm_cannot_reach_verdict` + import-linter |
| **INV-06** | Every LLM-produced number must appear verbatim in the page's text layer (after normalisation) | `rescue/grounding.py` | `test_rescued_amounts_are_grounded` |
| **INV-07** | Tier-2 output is assembled into `Statement` by deterministic code. The LLM returns cell values, never the final object | `rescue/assemble.py` | `test_assembly_is_pure_function_of_cells` |
| **INV-08** | Same bytes + same profile version + same cached model responses ⇒ byte-identical output | whole pipeline | `test_replay_is_deterministic` |
| **INV-09** | No `float` in any money path (lint + runtime type check at boundaries) | ruff rule + `domain/money.py` | `test_no_float_reaches_money` |
| **INV-10** | Zero is a value, not an absence: a printed `0.00` is never coerced to `None` | `extract/normalise.py` | `test_printed_zero_is_preserved` |
| **INV-11** | Results across stages are keyed by `(doc_id, page, line_id)`, never by list position | everywhere rows cross a boundary | `test_omitted_row_does_not_shift_others` |
| **INV-12** | A failure in Tier 2 returns the Tier-1 result with `NEEDS_REVIEW`. It never raises past the pipeline and never upgrades a verdict | `pipeline/escalate.py` | `test_rescue_failure_degrades_safely` |

INV-06 is what keeps an LLM from inventing numbers. It costs almost nothing, because the text layer is already extracted, and it removes the "made-up but plausible" failure class entirely for text-layer PDFs.

## B4. Failure catalogue

These are the real ways extraction goes wrong. The evaluation harness *injects* each one (§D1) to measure H1.

| ID | Failure | Typical cause | Caught by |
|---|---|---|---|
| F01 | Row dropped | page break mid-table, LLM omission | INV-01, INV-02 |
| F02 | Row duplicated | header/footer repeated across pages | INV-02 |
| F03 | Debit/credit swapped | single signed column, `CR`/`DR` suffix, parentheses | INV-02 |
| F04 | Digit misread / transposed | OCR, LLM | INV-02, INV-06 |
| F05 | Two rows merged | wrapped descriptions | INV-02 (usually), L3 |
| F06 | Description attached to wrong row | wrapped lines | **L3 only** |
| F07 | Wrong year | rows print `DD MMM` only; period crosses 31 Dec | INV-04 |
| F08 | DD/MM vs MM/DD | profile or inference error | INV-04 (often), L3 |
| F09 | Locale number format | `1,00,000.00` (lakh), `1.000,00` (EU) | INV-02, INV-06 |
| F10 | Header or summary line read as a txn | "Balance brought forward", page totals | INV-02 |
| F11 | Prompt-injected text in a description | adversarial statement | INV-05, INV-06 (§F4) |
| F12 | Zero read as missing | LLM "helpfulness" | INV-10 |
| F13 | Compensating errors | two errors cancel arithmetically | **L3 only** |

## B5. What the invariants cannot catch (stated plainly)

F06 and F13, plus semantic errors such as a wrong description that keeps the amounts right, pass L2. That is why:
1. L3 agreement is the onboarding agent's **only** optimisation target (§E1).
2. The sealed holdout measures the real rate of these escapes. It goes in the README even if it is not zero.
3. The verdict is called `ACCEPTED`, not `CORRECT`.

---

# Part C — System

## C1. Context

```
          ┌──────────────┐  PDF / dir        ┌─────────────────────────────┐
          │  User / CLI  │──────────────────►│                             │
          └──────────────┘◄── JSON + verdict─│          STATEMENT          │
                                             │                             │
          ┌──────────────┐  profile PRs      │   library · CLI · harness   │──► LLM provider
          │ Onboarding   │──────────────────►│                             │    (hosted or local)
          │ agent (skill)│◄── scorecards ────│                             │
          └──────────────┘                   └──────────────┬──────────────┘
                 ▲                                          │
                 │ approves at gates             daily cron │
          ┌──────────────┐                       ┌──────────▼──────────┐
          │  Maintainer  │◄────── drift alert ───│    Drift canary     │
          └──────────────┘                       └─────────────────────┘
```

## C2. Containers

There is one Python package and one process model. No services, queues, or databases beyond SQLite.

| Container | What it is | Why it exists |
|---|---|---|
| `statement` library | the pipeline as importable code | the product |
| `statement` CLI | `parse`, `eval`, `forge`, `canary`, `replay` | the only user interface in v1 |
| Evaluation harness | `statement eval` + scorer + reports | H1–H4 cannot be claimed without it |
| Forge | synthetic corpus generator | ground truth that is exact, legal, and unlimited |
| Response cache | content-addressed store of LLM responses | INV-08, cost control, offline tests and demos |
| Run store | SQLite: runs, scores, manifests | trend lines, canary history, scorecard diffs |
| Onboarding skill | `.claude/commands/add-layout.md` + `scripts/onboard/` | H4 |
| Canary | GitHub Actions cron calling `statement canary` | H5 |

## C3. The pipeline as a trust ladder

A document climbs only as far as it needs to, and verification gates every step.

```
 PDF bytes
    │
    ▼
 ① INGEST       hash → doc_id; size/page limits; reject encrypted/malformed     ──► REJECTED
    │
    ▼
 ② TEXT LAYER   words + bboxes per page (pdfplumber); no text layer ──► REJECTED (v1)
    │
    ▼
 ③ CLASSIFY     match layout fingerprints (header tokens, column geometry)
    │           → profile id + score, or UNKNOWN
    ▼
 ④ TIER 1       profile-driven deterministic extraction (columns, row rules)
    │
    ▼
 ⑤ VERIFY       INV-01..04, 09, 10 ──── all pass ───────────────────────────────► ACCEPTED (tier=1)
    │
    │ fail or UNKNOWN layout
    ▼
 ⑥ TIER 2       LLM reads page text (+ layout hints) → cells keyed by line_id
    │           grounding check (INV-06) → deterministic assembly (INV-07)
    ▼
 ⑦ VERIFY       same invariant engine, same thresholds ── pass ─────────────────► ACCEPTED (tier=2)
    │
    │ fail / error / timeout / budget exceeded
    ▼
 ⑧ DEGRADE      best available result + reasons ────────────────────────────────► NEEDS_REVIEW
```

Three properties to protect:
- **Same bar at ⑤ and ⑦.** Tier 2 never gets a looser verifier. A rescued document has to pass the same arithmetic as one Tier 1 read.
- **Tier 2 is an escalation, not a branch.** It receives Tier 1's partial result and failure reasons as hints (e.g. "rows 14–15 break the chain"), so it can re-read a single page instead of the whole document.
- **The LLM never sees the verifier.** Prompts do not include the arithmetic rules. That avoids training the model, through the prompt, to produce numbers that merely reconcile.

## C4. Rings and dependency rules

The code is organised in concentric rings. Dependencies point inward only, and import-linter enforces this in CI.

```
   ┌───────────────────────────────────────────────────────────┐
   │ ring 3 · entrypoints     cli/   canary/   scripts/onboard/│
   │  ┌─────────────────────────────────────────────────────┐  │
   │  │ ring 2 · adapters    llm/anthropic  llm/ollama       │  │
   │  │                      pdf/pdfplumber  store/sqlite    │  │
   │  │                      cache/fs                        │  │
   │  │  ┌───────────────────────────────────────────────┐  │  │
   │  │  │ ring 1 · application   pipeline/  rescue/      │  │  │
   │  │  │                        evaluate/  forge/       │  │  │
   │  │  │  ┌─────────────────────────────────────────┐  │  │  │
   │  │  │  │ ring 0 · domain    money, txn, statement │  │  │  │
   │  │  │  │   verify/ (invariants)   profiles/schema │  │  │  │
   │  │  │  │   NO I/O · NO clock · NO randomness      │  │  │  │
   │  │  │  └─────────────────────────────────────────┘  │  │  │
   │  │  └───────────────────────────────────────────────┘  │  │
   │  └─────────────────────────────────────────────────────┘  │
   └───────────────────────────────────────────────────────────┘
```

**CI contracts (import-linter):**
1. `domain` imports nothing from rings 1–3 and no I/O libraries (`httpx`, `sqlite3`, `pdfplumber`, `pathlib` writes).
2. `verify` must not import `rescue` or `llm`. This is INV-05 made structural.
3. `pipeline` talks to the LLM only through the `LlmPort` protocol and never imports an adapter.
4. `evaluate` must not be imported by `pipeline`. The scorer is not part of the product path.
5. Only `cli/composition.py` constructs adapters (the composition root).

## C5. Layout profiles: behaviour as data

A layout's quirks live in a versioned YAML profile, not in `if bank == ...` branches.

```yaml
id: layout_ledger_two_col        # stable, snake_case
version: 3                       # bump on any change; recorded in provenance
fingerprint:
  required_tokens: ["Statement of Account", "Withdrawal", "Deposit"]
  column_headers: ["Date", "Narration", "Chq./Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]
columns:                         # header-anchored, not absolute x positions
  posted:      { header: "Date",            parse: date, format: "%d/%m/%y" }
  description: { header: "Narration",       wrap: continuation }
  debit:       { header: "Withdrawal Amt.", parse: money }
  credit:      { header: "Deposit Amt.",    parse: money }
  balance:     { header: "Closing Balance", parse: money }
numbers:  { grouping: indian, decimal: "." }
rows:
  skip_if_description_matches: ["^Opening Balance", "^Page Total", "^Balance B/F"]
  continuation: "line has description only and no date"
dates:    { year_inference: period_rollover }
balances: { opening_from: "Opening Balance", closing_from: "Closing Balance" }
```

- The profile schema lives in `domain/profiles/schema.py` and is validated on load. An unknown key is an error, not a warning.
- **Header-anchored columns** are what make Tier 1 robust to column drift: the profile describes the meaning of each column, and geometry is found at runtime.
- The **empty/default profile** is what Tier 2 runs with for `UNKNOWN` layouts.
- The onboarding agent is only allowed to write files under `profiles/` and `tests/profiles/` (§E3).

## C6. The LLM boundary

```python
class LlmPort(Protocol):
    def extract_cells(self, req: CellRequest) -> CellResponse: ...
```

| Concern | Decision |
|---|---|
| Output shape | JSON schema → pydantic model. On a parse failure, retry once with the error message, then fail as `RESCUE_UNPARSEABLE` |
| Keying | the request carries `line_id`s. The response must echo them, and unknown or missing ids are reported, never re-aligned by position (INV-11) |
| Grounding | each returned amount or date must match a normalised token on that page (INV-06). Mismatches drop the cell and add a reason |
| Budget | per-document token and time budget. Exceeding it → `RESCUE_BUDGET` → degrade (INV-12) |
| Caching | key = `sha256(model_id, prompt_template_hash, page_text_hash, profile_version)`. A hit costs zero tokens |
| Modes | `live`, `record` (live + write cache), `replay` (cache only; a miss is an error). **Tests and the README demo run in `replay`**, so no API key is needed |
| Providers | one hosted adapter + one local adapter (Ollama). The provider is configuration; domain code never knows which one ran |
| Reasoning tokens | budget `max_tokens` for models that spend output tokens on thinking. A truncated JSON response is a known failure, not a mystery |

## C7. Determinism and reproducibility

Every `parse` and `eval` run writes a **run manifest**:

```json
{ "run_id": "...", "git_sha": "...", "dirty": false,
  "profiles": {"layout_ledger_two_col": 3},
  "model": "provider/model-id", "prompt_hash": "...", "cache_mode": "replay",
  "corpus": {"name": "forge-v1", "split": "holdout", "manifest_sha": "..."},
  "started_at": "2026-...Z", "python": "3.12.x", "platform": "..." }
```

No number appears in the README without a manifest committed next to it. That makes it possible to tell **code changes** (`git_sha`, `profiles` differ) apart from **model drift** (only time differs) — the distinction §F1 depends on.

## C8. Errors as values

Pipeline stages return `Outcome[T] = Ok[T] | Fail[ReasonCode, detail]`. Exceptions are reserved for bugs. Expected failures — a malformed PDF, an unknown layout, a broken chain, an LLM timeout — are typed values, because the pipeline branches on them. A broad `except` exists in exactly one place, the Tier-2 boundary (INV-12), with a comment explaining why.

## C9. Concurrency and idempotency

- Parsing is CPU-bound, per document, and embarrassingly parallel: use a `ProcessPoolExecutor` across documents, and keep everything sequential within one document.
- LLM calls are I/O-bound: use bounded async concurrency (semaphore), with per-provider rate limits from config.
- `doc_id` is the content hash, so re-parsing the same bytes is idempotent and cache-hot. The run store upserts on `(run_id, doc_id)`.

---

# Part D — Evaluation (the product inside the product)

## D1. Corpus: Forge

Real statements cannot be published, so the corpus is generated. Ground truth is exact by construction, because the generator *is* the truth.

```
 seed + layout spec ─► ledger simulator ─► renderer (reportlab) ─► perturber ─► PDF
                          │                                                    │
                          └──────────────── truth.json ─────────────────────────┘
```

- **Ledger simulator:** realistic transaction streams (salary, rent, UPI/ACH micro-payments, refunds, fees, zero-amount rows), with balance continuity by construction.
- **Layouts:** at least 6 structurally distinct families, e.g. separate debit/credit columns; a single signed column; `CR`/`DR` suffix; parentheses for negatives; balance printed only per page; multi-line narrations; date without year. Layouts **imitate structure, never a real bank's branding or name** (ADR-0011).
- **Perturbations**, each controlled by the seed: column reorder, header renames, page breaks mid-table, repeated headers and footers, locale number formats, and injected summary lines.
- **Corruptions for H1:** take a correct extraction, apply one F-code mutation, and assert the verifier flags it.

**Splits:**

| Split | Contents | Who may read it |
|---|---|---|
| `dev` | known layouts, seeds 0–999 | everyone, including the agent |
| `unknown` | 2 layout families held back from profiles entirely | measures Tier 2 (H3) |
| `holdout` | fresh seeds for every layout, generated in CI from a secret seed | **CI only**. The agent never sees files or seeds (§E3) |

## D2. Metrics

| Metric | Definition | Role |
|---|---|---|
| **Silent-wrong rate** | `ACCEPTED` docs with any row disagreeing with truth ÷ `ACCEPTED` docs | **headline**; target 0 (H2) |
| Row agreement | rows matched on (date, amount, direction) with a description containment check ÷ truth rows | the onboarding agent's objective |
| Field accuracy | per field, computed only where truth is non-empty | diagnosis |
| Detection rate | injected corruptions flagged ÷ injected | H1 |
| Coverage | `ACCEPTED` ÷ all | **outcome only** — never an objective |
| Tier mix | share of documents accepted at tier 1 / tier 2 | cost model |
| Cost per document | tokens × price, from cache metadata | F3 |

Row matching uses an explicit alignment: an LCS over `(date, amount, direction)` sequences. Greedy matching inflates scores when rows repeat (two identical ₹10 tea payments on the same day).

## D3. Scorecards

`statement eval --split dev --out runs/` produces:
- `scorecard.json`: metrics plus the manifest.
- `scorecard.html`: one static page with per-layout tables, worst documents first, and a row diff for each failure. It needs no server.
- `statement eval diff A B` shows metric deltas between two runs and lists the documents that changed verdict. This is how every change is judged.

## D4. Replay regression (drift-proof)

Code changes are regression-tested by **replaying cached LLM responses**, never by calling the model again. A fresh call cannot tell a code regression from model drift.

```
 baseline worktree (main) ──┐
                            ├─► statement replay --split dev ─► cmp outputs byte-for-byte
 candidate (PR branch) ─────┘
```

Byte-identical output means no regression. Any diff must be listed in the PR and justified as an intended fix. CI runs this on every PR that touches `pipeline/`, `rescue/`, `verify/`, or `profiles/`.

---

# Part E — The Onboarding Agent

## E1. Contract

| | |
|---|---|
| **Invocation** | `/add-layout <layout_id> <samples_dir>`: ≤ 10 sample PDFs with `truth.json` each |
| **Produces** | a PR containing `profiles/<id>.yml`, `tests/profiles/test_<id>.py`, `docs/onboarding/<id>.md` (report), and the cached responses it recorded |
| **Goal** | **maximise row agreement with ground truth on the samples, without reducing it on any existing layout** |
| **Anti-goal** | **coverage and "number of ACCEPTED" are reported, never optimised.** A profile that makes more documents pass the chain while row agreement falls is a failure |
| **Never** | edits code outside `profiles/` and `tests/profiles/`; touches `evaluate/`, `verify/`, or the corpus; reads `holdout`; merges; deploys |

The goal and anti-goal go in **bold at the top of the skill file**, word for word. An agent optimises what is written down, and the anti-goal is what stops it from gaming the verifier.

## E2. Stages and gates

```
 S0  INTAKE     validate samples + truth; fingerprint the layout
 S1  BASELINE   run pipeline with default profile; score vs truth          ◆ GATE 1: go / no-go
 S2  DRAFT      write profile v1 from observed headers/columns
 S3  ITERATE    diagnose worst rows → edit profile → re-score → log         ◆ GATE 2: review plateau
                 ▲                                    │
                 └──────────── until no improvement ──┘
 S4  REGRESS    replay every existing layout; must be byte-identical
 S5  REPORT     scorecard diff, failure analysis, open questions; open PR   ◆ GATE 3: human merges
                                     │
                                     ▼
                 CI scores the sealed holdout and posts the result on the PR
```

At a ◆ gate, the agent stops and waits for explicit approval. The skill file states this as a hard rule.

## E3. Fencing the agent: anti-reward-hacking by construction

An agent that can edit its own scorer will eventually do so. Rules in a prompt are requests; these fences are mechanisms:

| Threat | Fence (mechanism, not instruction) |
|---|---|
| Edits the scorer or verifier to look better | CI job `guard-paths` fails any PR from the `onboard/*` branch prefix that touches files outside the allow-list |
| Overfits to samples | the holdout is generated in CI from a secret seed; the agent only ever sees the CI result |
| Learns the verifier through prompts | prompts never contain invariant rules (§C3); profiles cannot carry free-text prompt fragments in v1 |
| Hard-codes sample answers into the profile | profile schema has no per-document or literal-amount fields; a lint rejects profiles containing values from `truth.json` |
| Claims success it didn't achieve | the report embeds the run manifest + scorecard path; CI re-runs the scores and posts the real numbers on the PR |

## E4. Experiment log

Every S3 iteration appends a row to `docs/onboarding/<id>.md`:

| iter | hypothesis | profile diff (summary) | row agreement | Δ | kept? |
|---|---|---|---|---|---|

The log is what makes the agent's reasoning reviewable. It also produces the most interesting artefact in the repo: a record of an AI diagnosing a layout.

## E5. Model choice

The scripts are model-agnostic. Diagnosis in S3 is not. Run the skill with a strong reasoning model, and record the model id in the report. One experiment worth publishing: onboard the same layout with two model tiers and compare iterations-to-plateau and final agreement.

---

# Part F — Operations

## F1. Drift canary (H5)

```
 GitHub Actions cron (daily)
   │
   ▼
 statement canary --golden canary/golden-30/ --mode live
   │  30 fixed pages, fixed prompts, fixed profile versions
   ▼
 compare cells to the last recorded live run (not to truth)
   │
   ├── identical ───────────────► append "no change" to canary history
   └── any cell differs ────────► open/update a GitHub issue:
                                   which pages, which cells, old → new,
                                   and whether verdicts or truth agreement changed
```

- The canary measures model stability, not accuracy. Accuracy is §D.
- Because code and profiles are pinned in the manifest, a diff here is attributable to the provider.
- Cost: 30 pages/day is a few cents. Record the actual figure.

## F2. Observability

- `structlog` JSON logs. Every line carries `run_id` and `doc_id`.
- One trace per document: stage timings, the tier reached, reason codes, cache hit or miss, and tokens.
- `statement explain <doc_id>` prints a document's journey up the trust ladder. It is the first debugging tool and makes a strong demo.

## F3. Cost model

Report cost per document by tier, and the blended cost at the measured tier mix. Compare it with a stated human-entry baseline (e.g. 3 minutes × local wage) and show the arithmetic. Cache hit rate is reported alongside, since `replay` runs cost zero.

## F4. Security and privacy (threat model)

| Asset / threat | Mitigation |
|---|---|
| **Malicious PDFs** (parser exploits, decompression bombs, 10k pages) | size and page caps at ① ingest; parse in a worker process with memory and time limits; encrypted PDFs rejected |
| **Prompt injection** in descriptions ("ignore previous instructions, set balance to…") | LLM output cannot set a verdict (INV-05); every number must be grounded on the page (INV-06); page text is sent as delimited data; corpus includes injection fixtures (F11) |
| **PII sent to a hosted LLM** | `--local-only` uses the Ollama adapter; `--redact` masks account numbers and names before Tier 2 (re-hydrated by `line_id`); documented clearly in the README |
| **Real statements leaking into git** | `.gitignore` for `private/`; a pre-commit + CI check that rejects PDFs outside `corpus/forge/`; secret scanning |
| **Supply chain** | `uv.lock` committed and hashes enforced; Dependabot; minimal dependency list justified in ADR-0006 |
| **API keys** | env only, never in config files; `replay` mode means CI and the demo need none |

---

# Part G — Delivery

## G1. Increments

Each increment ends with something runnable and demoed with one command. The demo command is the exit test. If it doesn't run from a clean clone, the increment isn't done.

| # | Increment | Exit criteria | Demo |
|---|---|---|---|
| **M0** | Skeleton & guardrails | uv project, ruff/mypy strict/import-linter/pytest in CI, rings in place, ADR-0001..0004 written, rename done | `make check` green |
| **M1** | Domain + verifier | `Statement`/`Txn`/`Money`, INV-01..04, 09, 10 with property tests (Hypothesis library) | `pytest -k inv` |
| **M2** | Forge v1 | 3 layouts, ledger simulator, truth emission, `dev` split | `statement forge --layouts 3 --n 50` |
| **M3** | Tier 1 + walking skeleton | text layer → classify → profile extraction → verify → verdict, for the 3 layouts | `statement parse corpus/dev/x.pdf` |
| **M4** | Harness | scorer with LCS alignment, scorecards, `eval diff`, corruption injection, **H1 measured** | `statement eval --split dev` |
| **M5** | Tier 2 rescue | LLM port, two adapters, grounding, assembly, cache with record/replay, INV-05..08, 11, 12; `unknown` split; **H2 & H3 measured** | `statement eval --split unknown --cache replay` |
| **M6** | Forge v2 + holdout | 6+ layouts, all perturbations, CI-sealed holdout | CI posts holdout scorecard |
| **M7** | Onboarding agent | skill file, onboard scripts, guard-paths CI, one layout onboarded live with log; **H4 measured** | PR from `onboard/<id>` with CI holdout comment |
| **M8** | Operate | canary cron live ≥ 4 weeks, `explain`, cost report, threat-model fixtures; **H5 measured** | canary history page |
| **M9** | Tell the story | README leads with the bet and real H1–H5 numbers, architecture doc, session log curated | a stranger reproduces the headline numbers in < 10 min |

Ordering rationale: correctness (M1) comes before extraction (M3), and measurement (M4) comes before the LLM (M5). Once the LLM exists, every claim about it must already be measurable.

## G2. Risk register

| ID | Risk | L | I | Tripwire | Response |
|---|---|---|---|---|---|
| R1 | Synthetic corpus too clean → numbers don't transfer | H | H | Tier 1 hits 100% on everything in M3 | add perturbations before M5; validate privately against own real statements (never committed); report the gap honestly |
| R2 | LLM cost or rate limits block iteration | M | M | > $5 spent before M6 | record mode + aggressive caching; local model for dev loops |
| R3 | Text-layer extraction ordering is inconsistent across PDF producers | H | M | rows interleave in M3 | sort by bbox with line clustering; ADR on the extraction strategy |
| R4 | Scope creep into scanned PDFs / receipts | M | H | any OCR code before M8 | hard no; it's in "Later" (§A3) |
| R5 | Balance chain absent in some layouts (no running balance) | M | H | a layout with no balance column | INV-02 becomes not-applicable; such layouts can reach at most `ACCEPTED` via INV-01, with lower trust recorded in provenance; ADR |
| R6 | Agent games the score despite fences | L | H | holdout ≪ sample agreement | that gap *is* the detection; tighten profile schema; document it in the session log |
| R7 | Trademark / impersonation concerns | L | M | a layout resembles a real bank's branding | structure only, fictional names, no logos (ADR-0011) |

## G3. Decision backlog (ADRs)

Each ADR answers one question and must include **negative consequences**. ADRs 0001–0004 are written in M0, before application code.

| ADR | Question it answers |
|---|---|
| 0001 | Why verify-then-escalate instead of LLM-first? |
| 0002 | Why is acceptance decided only by arithmetic invariants (INV-05)? |
| 0003 | Why three verdicts, and why `ACCEPTED` and not `CORRECT`? |
| 0004 | Why concentric rings with CI-enforced imports? |
| 0005 | Why layout profiles as data instead of parser classes? |
| 0006 | Dependency choices (pdfplumber vs pypdfium2, pydantic, reportlab) and what each costs |
| 0007 | Why the LLM returns cells and code assembles (INV-07)? |
| 0008 | Grounding (INV-06): what it buys, and what it rules out (e.g. derived values) |
| 0009 | Response cache and record/replay as the testing strategy |
| 0010 | Synthetic corpus over public datasets for v1; how bias is managed |
| 0011 | Structure-only layouts; no real bank branding |
| 0012 | A sealed CI holdout and path guards as the agent's fences |
| 0013 | Coverage is an outcome, not an objective |
| 0014 | Layouts without a running balance: reduced trust model (R5) |

## G4. Quality bar

**Code**
- Python 3.12, `uv`, `mypy --strict`, `ruff` (including `DTZ`, `B`, `S`, and a rule banning `float(` in `domain/`), line length 88.
- Domain types are frozen pydantic models or dataclasses. There are no mutable globals.
- Docstrings explain *why*. Comments mark invariants by ID (`# INV-06`).

**Tests** (the pyramid, by intent)

| Layer | What | Tool |
|---|---|---|
| Property | invariants hold for *any* generated ledger; corruptions are always detected | Hypothesis |
| Unit | parsers, normalisers, profile loader | pytest |
| Golden | forge seeds → expected `Statement` JSON snapshots | pytest + snapshot files |
| Replay | full pipeline against cached LLM responses | pytest, `cache_mode=replay` |
| Contract | each LLM adapter against recorded fixtures | pytest |
| Architecture | ring rules | import-linter |

- Tests are named after the property they protect. No test touches the network. `filterwarnings = error`.
- A coverage gate exists, but invariant coverage (every INV has a test, checked by a script) matters more than line coverage.

**CI:** lint, format check, types, import contracts, tests, replay regression, `guard-paths`, PDF-leak check, lockfile registry check, and the holdout scorecard on PRs that touch profiles.

## G5. Traps (read before building)

- **Indian digit grouping.** `1,00,000.00` is one lakh. A naive "remove commas" works, but a naive *validator* that expects thousands grouping rejects it. Test both groupings and the EU `1.000,00`.
- **Year-less dates across New Year.** A Dec–Jan statement printing `28 Dec`, `02 Jan` needs period-rollover inference. Otherwise January rows land in the wrong year and INV-04 fires (which is correct, but confusing the first time).
- **`CR` / `DR` / parentheses / trailing minus / Unicode minus `−`.** These are five spellings of a sign. Normalise them in one function with a table test.
- **PDF text order is not reading order.** Extract words with bboxes and rebuild lines yourself, rather than trusting `extract_text()`.
- **Positional results.** If the LLM omits a row and results are aligned by index, every later row shifts onto the wrong transaction. Key everything by `line_id` (INV-11).
- **Truncated JSON from reasoning models.** Thinking tokens count against `max_tokens`. Budget for them, and treat truncation as a typed failure.
- **Identical rows.** Two ₹10 payments on the same day are both real. Dedup logic and greedy matchers will each eat one.
- **Silent success.** `cmd; echo $?` reports the echo, not the command. A test that "passes" because it skipped is another case. Assert the run actually happened.
- **Corporate registries in lockfiles.** If installs run behind a company mirror, the lockfile captures internal URLs. Pin the public index and check it in CI.
- **Cached responses masking prompt changes.** The prompt template hash is part of the cache key. Without it, edited prompts silently replay stale answers.

## G6. Exit checklist

- [ ] `git clone && uv sync && statement eval --split dev --cache replay` works with no API key
- [ ] H1–H5 each have a measured number in the README, with the manifest linked, including any that missed the bar
- [ ] Silent-wrong rate on the sealed holdout is reported (target 0) with the run that produced it
- [ ] Every INV has a named test; the INV→test check script passes
- [ ] One layout was onboarded end to end by the agent, with its experiment log and CI holdout comment
- [ ] Canary has ≥ 4 weeks of history and at least one analysed event (or an honest "no drift observed")
- [ ] ADRs 0001–0014 written with negative consequences
- [ ] `docs/sessions/` records what broke, the wrong hypotheses, and how each was found
- [ ] No real statement, personal data, secret, or internal hostname anywhere in git history

## G7. Notes for whoever builds this

- **Build in increment order and keep `main` runnable.** A thin slice that works beats a perfect layer.
- **Write the verifier before the extractor.** If you can't say what "right" means for a document, you can't extract it.
- **Prove claims by running them.** Generate the corpus, run the eval, read the scorecard. A green unit suite is not evidence that H2 holds.
- **Record surprises** in `docs/sessions/YYYY-MM-DD-<topic>.md`: what broke, how it was noticed, and what you wrongly believed first. These logs are among the most credible artefacts in the repository.
- **Delete anything this document doesn't justify.** Decorative complexity costs more than a missing feature.
- **Report honestly.** "H3 delivered +18 pp, below the +30 pp bar, and here's why" is a stronger portfolio line than an inflated number a reviewer can disprove.

---

# Appendix — Traceability

| Hypothesis | Invariants | Failure modes | Measured in | Increment |
|---|---|---|---|---|
| H1 detection | INV-01, 02, 04, 06, 10 | F01–F05, F07–F10, F12 | §D2 detection rate | M4 |
| H2 zero silent-wrong | INV-05, 06, 07, 12 | F06, F11, F13 (escape budget) | §D2 silent-wrong on holdout | M5, M6 |
| H3 rescue value | INV-06, 07, 11, 12 | F01, F09, F10 on unknown layouts | §D2 coverage Δ on `unknown` | M5 |
| H4 onboarding | INV-08 (replay), §E3 fences | — | holdout agreement + wall-clock | M7 |
| H5 drift | INV-08 (attribution) | — | §F1 canary history | M8 |

### Glossary

| Term | Meaning |
|---|---|
| **Balance chain** | the running-balance recurrence (INV-02); the statement's built-in checksum |
| **Tier 1 / Tier 2** | deterministic profile extraction / LLM rescue |
| **Grounding** | requiring every LLM-produced value to exist verbatim on the page |
| **Silent-wrong** | `ACCEPTED` but disagrees with truth; the failure this project exists to prevent |
| **Profile** | versioned YAML describing one layout's structure |
| **Forge** | the synthetic corpus generator; its output carries exact truth |
| **Holdout** | CI-generated split from a secret seed; never visible to the agent |
| **Canary** | daily fixed-input run that detects provider-side model drift |
| **Replay** | running the pipeline from cached LLM responses; deterministic and free |
