# Onboarding report — `no_balance`

| | |
|---|---|
| Skill | `/add-layout` |
| Ran by | Claude (Opus-class model) in the build session, 2026-10-02 |
| Samples | 10 PDFs, 312 truth rows |
| Result | profile `no_balance` **v1** — 10/10 exact on samples, **40/40 exact on the sealed holdout, 0 silent-wrong** |
| Trust | **reduced** — no running balance, so only INV-01 (totals) checks amounts (ADR-0014) |

The same caveats as [`split_zero_filled`](split_zero_filled.md) apply: the
agent wrote the forge, and the gates were self-approved in the build session.

## Iteration log

| iter | hypothesis | change | rows agreed | silent-wrong | kept? |
|---|---|---|---|---|---|
| 0 | baseline | — | 0% | 0 | — |
| 1 | no balance column, so `balance_policy: none`. The summary block (`Opening balance` … `Closing balance`) comes after the table and ends it. The `***` notice line is visible on sample 0's first page, so the skip pattern goes in from the start | v1 | 100% | 0 | yes |

## What reduced trust means here

Without a running balance, a misread amount is caught only if it changes the
statement total. On the holdout, every detectable single-row corruption was
still caught by INV-01 (corruption run:
`docs/results/2026-10-02/corrupt-holdout.corruption.json`). But two
compensating errors on this layout need **no** balance edits to escape. The
F13 class is therefore cheaper to hit here than on balance-printing layouts.
Provenance records `balance_policy: none`, so a consumer can apply a stricter
review policy to these documents.

## Regression and fences

Byte-identical replay on `corpus/dev` and `corpus/drift`. Path guard and
literal check both clean.
