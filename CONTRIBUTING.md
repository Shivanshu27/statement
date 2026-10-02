# Contributing

The most valuable contribution is a **new layout family**: a structural
pattern the forge doesn't produce yet. Examples: balances printed only at the
end of each day, a date column that changes format mid-document, multi-line
column headers.

## Setup

```bash
make sync     # needs uv and Python 3.12; everything stays inside the repo
make check    # must be green before a PR
```

## The bar for a change

- `make check` is green: ruff, format, mypy --strict, import contracts,
  guards, tests, and the coverage gate (85%).
- Behaviour changes that touch `pipeline/`, `extract/`, `rescue/`, `domain/`
  or `profiles/` include a replay comparison. Run
  `statement replay corpus/dev --out after.jsonl` on your branch and on
  `main`, then `cmp` the two. Every difference must be explained in the PR.
- Numbers in docs come with the scorecard that produced them (and its
  manifest).
- A new invariant gets an ID in `docs/BUILD-PLAN.md` §B3 and a test whose
  docstring names it.

## Adding a layout family to the forge

1. Add a `Layout` in `src/statement/forge/layouts.py`. Use structure only,
   with a fictional name and no real bank's branding (ADR-0011).
2. `uv run --frozen pytest tests/test_forge.py` checks that the truth
   verifies and nothing overflows.
3. Keep it out of `profiles/`, and then onboard it with `/add-layout`. The
   iteration log is part of the contribution.

## Decision records

A change to a rule in BUILD-PLAN Part B, or to anything an ADR decided,
needs a new ADR in `docs/adr/`. Use the question-first format: Question,
Decision, Because, **What it costs**, Revisit if. A record with no costs
will be sent back.

## Things that will be declined

- Anything that lets model output influence a verdict.
- Tuning against coverage.
- Real statements, or caches derived from them, in any form.
- Dependencies that duplicate an existing one, or that no code path uses.
