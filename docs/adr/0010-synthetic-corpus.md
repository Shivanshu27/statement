# 0010 — Why a synthetic corpus, and how is its bias managed?

**Decision.** v1 is evaluated on a generated corpus, the forge:
- a ledger simulator plus six structural layout families, plus four
  drifted templates;
- seeded and byte-deterministic;
- ground truth emitted next to every PDF.

**Because.**
- Real statements cannot be published, and a portfolio project's numbers
  must be reproducible by a stranger.
- Truth is exact by construction, so L3 measures the system, not annotator
  noise.
- Unlimited volume, plus targeted traps: Indian grouping, New Year
  rollover, identical rows, page totals, notices inside the table, and
  prompt injection.

**Bias, and how it is managed.**
- **Too clean (risk R1).** It tripped on day one: 100% on dev. Response: the
  `drift` split, where Tier 1 drops to 0% coverage with 0 silent-wrong. More
  perturbations are listed under Revisit.
- **Generator/reader coupling.** The same author wrote both, and only a
  stranger's layout breaks that. Both onboarding reports carry this caveat.
- **Text-layer only.** No scans, so no OCR noise.

**What it costs.** Numbers on synthetic data do not transfer to real
statements. The README states them as "on the forge corpus" every time.

**Revisit if** a private, never-committed set of real statements becomes
available for a one-off transfer check. Report that gap honestly.
