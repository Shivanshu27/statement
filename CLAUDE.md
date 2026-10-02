# Working on Statement

Bank-statement PDFs to verified transactions. A deterministic Tier 1, an LLM
rescue in Tier 2, and **arithmetic decides acceptance**. Read
`docs/BUILD-PLAN.md` Part B (the contract) before changing behaviour, and
`docs/ARCHITECTURE.md` for what is actually built.

## Commands

```bash
make sync | make check | make corpus | make eval | make corrupt
uv run --frozen statement explain <pdf>      # first debugging tool
uv run --frozen statement replay corpus/dev --out /tmp/x.jsonl   # regression dump
```

Everything runs inside this folder: `UV_CACHE_DIR=.uv-cache`, `.venv`,
`corpus/`, `runs/`. Use `make` targets, or export those variables first.
Don't install anything globally.

## Rules that are not style

1. **Only `domain/verify.py` decides acceptance (INV-05).** Never add a path
   where model output, confidence or a flag upgrades a verdict.
   `statement.rescue` must not import the verifier; import-linter enforces it.
2. **No number from a model without grounding (INV-06).** If you add a field
   to the Tier-2 schema, add its grounding rule in the same change.
3. **Both tiers assemble through `domain/assemble.py` (INV-07).** No
   interpretation of signs, locales or dates anywhere else.
4. **Money is Decimal end to end (INV-09).** `scripts/check_no_float.py`
   scans the domain.
5. **Key by `line_id`, never by position (INV-11).**
6. **Coverage is never an objective (ADR-0013).** Don't tune anything
   (profiles, prompts, thresholds) against "more ACCEPTED". Tune against row
   agreement, and report silent-wrong first.
7. **Errors are values.** Return `Fail(Reason(...))`. The single broad
   `except` is the Tier-2 boundary (INV-12).
8. **Every invariant has a test whose docstring names it.**
   `scripts/check_inv_tests.py` fails otherwise.
9. **Never commit real statements**, or LLM cache files made from them.
   PDFs are allowed only under `canary/golden/`.

## Adding things

- **A layout:** run the `/add-layout` skill. It writes only `profiles/<id>.yml`,
  `tests/profiles/test_<id>.py` and `docs/onboarding/<id>.md`.
- **A reason code:** add it to `domain/reasons.py`. If it means "not a
  statement at all", add it to `REJECTING`.
- **An LLM provider:** add an adapter in `adapters/llm_http.py` returning
  `Outcome[LlmResponse]`, and wire it in `cli/composition.py` only.
- **A forge layout:** add it in `forge/layouts.py`. The forge must refuse
  overlapping text, so if it raises, fix the geometry, not the guard.

## Traps (each one cost time; see docs/sessions/)

- Overlapping text in a PDF makes pdfplumber interleave characters, and the
  arithmetic can't see it. Watch the description columns.
- A label that is also a column header (`Closing Balance`): label search
  takes the first line containing it.
- Pydantic converts only `ValueError` raised in validators. A `TypeError`
  escapes as a crash.
- A test's invented number may be printed on the page (the injection
  fixture prints `9999999.00`).
- Ambient `ANTHROPIC_BASE_URL` may point somewhere else on dev machines.
  Adapters read `STATEMENT_*` only.
- Run directories are per-second. `_run_dir` disambiguates; don't remove
  that.

## Session log

When something surprising breaks, add an entry to
`docs/sessions/YYYY-MM-DD-<topic>.md`: the symptom, the wrong first
hypothesis, the cause and the fix.
