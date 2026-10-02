# Onboarding report — `split_zero_filled`

| | |
|---|---|
| Skill | `/add-layout` (`.claude/commands/add-layout.md`) |
| Ran by | Claude (Opus-class model) in the build session, 2026-10-02 |
| Samples | 10 PDFs, 317 truth rows (`statement forge --split unknown --n 10 --layouts split_zero_filled`) |
| Result | profile `split_zero_filled` **v2** — 10/10 exact on samples, **40/40 exact on the sealed holdout, 0 silent-wrong** |
| Wall clock | ≈ 3 minutes, intake to holdout (manifests: 18:06:51Z → 18:07:21Z for S1–S3) |

## ⚠ Read this before quoting the result

This run demonstrates the **mechanism**, not a blind trial:

- **The agent that ran the skill also wrote the forge.** It knew this layout's
  structure before it opened a sample. A fair H4 trial needs a layout the
  onboarding agent has never seen. See the open items.
- **The three gates were approved by the builder,** inside the same session,
  under the user's instruction to build end to end. In normal use a human
  approves each gate (the skill says so in bold).
- **The holdout was generated after S3,** from a random secret that was
  generated inline and never printed. The agent did not read
  `corpus/holdout/` before scoring. That is a procedural fence here. In CI
  it is a mechanical one: the secret is a repository secret.

## Iteration log

| iter | hypothesis | profile change | rows agreed | silent-wrong | coverage | kept? |
|---|---|---|---|---|---|---|
| 0 | baseline: no profile for this layout | — | 0.0% | 0 | 0% | — |
| 1 | page 1 of sample 0 shows the full structure: Date/Details/Debit/Credit/Balance, ISO dates, `Balance brought forward` as opening, `Page total` ending the table | v1 drafted from sample 0's first page only | 98.4% | **2** | **100%** | no |
| 2 | the 5 wrong rows all end with `*** Important: keep your contact details…` — a bank notice printed *inside* the table, appended to the previous row as a wrapped description | add skip pattern `^\*\*\*` (v2) | 100.0% | 0 | 100% | **yes** |

**Iteration 1 is why the anti-goal exists.** Coverage was already 100% and
every document passed the arithmetic. An agent told to "maximise accepted
documents" would have stopped there and shipped two silently wrong
statements. The notice line carries no amounts, so the balance chain cannot
see it (an F06-class escape, §B5). Only L3 agreement with ground truth showed
the problem.

Scorecards for every iteration:
`docs/results/2026-10-02/onboarding/split_zero_filled-iter{0,1,2}.scorecard.json`.

## Regression (S4)

`statement replay` over `corpus/dev` (160 docs) and `corpus/drift` (160 docs),
before and after adding the profile: **byte-identical** (`cmp` exit 0).
`test_fingerprints_do_not_overlap` confirms every layout still classifies only
to its own profile.

## Fences

- `scripts/guard_paths.py`: all 3 changed paths are inside the allow-list.
- `scripts/check_profile_literals.py`: no truth value appears in the profile.

## Open items

1. **Blind trial for H4.** Have a fresh session, with no access to
   `src/statement/forge/`, onboard a seventh layout written by someone else.
   Until then, H4 is "mechanism works", not "agent generalises".
2. The skill's S4 uses `git stash`. Without a git repo, this run diffed
   saved replay dumps instead. Same check, different mechanics.
