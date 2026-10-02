---
description: Onboard a new bank-statement layout by writing a declarative profile, scored against ground truth. Use when asked to add/support a layout, or when a layout lands in NEEDS_REVIEW with UNKNOWN_LAYOUT. Input - a layout id and a directory of <=10 sample PDFs each with a .truth.json. Produces a profile + tests + report on an onboard/<id> branch; never merges.
---

# Add a layout profile

> **GOAL: maximise row agreement with ground truth on the samples, without
> reducing it on any existing layout.**
>
> **ANTI-GOAL: coverage and "number of ACCEPTED" are reported, never
> optimised. A profile that makes more documents pass the chain while row
> agreement falls is a failure.** (BUILD-PLAN §E1, ADR-0013)

## Hard rules

- **Three gates. Stop and wait for explicit approval at each ◆.** Do not
  proceed on silence, and do not treat approval of one gate as approval of the next.
- **You may only write:** `profiles/<id>.yml`, `tests/profiles/test_<id>.py`,
  `docs/onboarding/<id>.md`. CI (`scripts/guard_paths.py`) rejects anything
  else on an `onboard/*` branch. If a fix seems to need code, stop and say so
  in the report as an open item; do not make it.
- **Never read the holdout** (`corpus/holdout/`, `STATEMENT_HOLDOUT_SECRET`).
  CI scores it and posts the result.
- **Never put values from `truth.json` into a profile** (amounts, dates,
  descriptions). `scripts/check_profile_literals.py` enforces this.
- **Describe structure, not documents.** Every pattern must be justified by
  something printed on *every* statement of this layout.
- Run everything inside the repo with `make` / `uv run --frozen`. No installs.

## Stages

```
S0 INTAKE    validate samples + truth; look at the page structure
S1 BASELINE  run with existing profiles; score                    ◆ GATE 1
S2 DRAFT     write profile v1 from what is printed
S3 ITERATE   score -> read worst diffs -> one hypothesis -> edit -> re-score
             (log every iteration)                                ◆ GATE 2
S4 REGRESS   replay every existing layout; must be byte-identical
S5 REPORT    report + PR on onboard/<id>                          ◆ GATE 3 (human merges)
```

### S0 — Intake

```bash
uv run --frozen python scripts/onboard/intake.py <samples_dir>
```

Checks every PDF has a truth file and prints, for one sample, the first
page's lines with ids and x positions, plus candidate header lines. Read
two samples yourself (`statement explain <pdf>`).

### S1 — Baseline + ◆ GATE 1

```bash
uv run --frozen statement eval <samples_dir> --out runs --workers 1
```

Expect `UNKNOWN_LAYOUT`. Report: sample count, rows, what the layout looks
like (columns, sign convention, number format, date format, where opening
and closing balances are printed, non-transaction lines inside the table).
Ask to proceed.

### S2 — Draft

Write `profiles/<id>.yml` (schema: `src/statement/domain/profile.py`;
examples: the other profiles). Decide, from the page:

| field | look for |
|---|---|
| `fingerprint.required_tokens` | 2–3 strings printed on page 1 of every sample, absent from other layouts |
| `columns` | header text exactly as printed, left to right; `align` only if not the default |
| `locale` | `dot` (1,234.56 / 1,23,456.78) or `comma` (1.234,56) |
| `date_format`, `period` | strptime formats; period regex with exactly two groups |
| `amount_mode` | `split` (two columns), `signed` (minus/parentheses), `suffix` (Dr/Cr) |
| `opening` / `closing` | a label whose line ends in the amount — not a column header |
| `rows.skip_patterns` | lines inside the table that are not transactions |
| `rows.stop_patterns` | lines that end the table on a page (footers, summaries) |

### S3 — Iterate + ◆ GATE 2

Each iteration: one hypothesis, one change, re-score, log a row in the report.

```bash
uv run --frozen statement eval <samples_dir> --out runs --workers 1
uv run --frozen statement explain <worst_pdf>
```

Diagnose from reason codes and row diffs in `scorecard.html`, not from the
summary number. Typical causes: a total or carried-forward line read as a
transaction (`CHAIN_BREAK` right after a page break), a label that also
appears as a column header, a footer appended to a description.

Stop when row agreement is 100% or two iterations make no progress. Present
the log and the final scorecard. Ask to proceed.

### S4 — Regress (mandatory)

```bash
uv run --frozen statement replay corpus/dev --out /tmp/after.jsonl
git stash && uv run --frozen statement replay corpus/dev --out /tmp/before.jsonl && git stash pop
cmp /tmp/before.jsonl /tmp/after.jsonl
```

Byte-identical, or explain every difference. A new profile that changes
classification of an existing layout is a fingerprint bug.

### S5 — Report + ◆ GATE 3

Write `docs/onboarding/<id>.md` with: the iteration log, the final
scorecard numbers with the run manifest path, the regression result, the
model that ran this skill, and open questions. Commit on `onboard/<id>` and
open a PR. CI posts the holdout scorecard on it. **A human merges.**

## Known failure modes

- **Fingerprint too broad:** stealing another layout's documents. Caught in S4.
- **Over-fitting to samples:** a skip pattern that names a merchant. Caught by
  the holdout; avoid by asking "is this printed on every statement?".
- **Declaring victory on coverage.** Re-read the anti-goal.
