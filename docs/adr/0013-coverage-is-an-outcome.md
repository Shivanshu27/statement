# 0013 — Why is coverage never an objective?

**Decision.**
- The headline metric is the **silent-wrong rate**: documents `ACCEPTED`
  that disagree with truth. Its target is 0.
- **Coverage** (the share `ACCEPTED`) is reported beside it and is never a
  target for any person, test or agent.
- The onboarding agent optimises row agreement with truth.

**Because.** Coverage is gameable, and the cheapest ways to raise it make
the system worse:
- skip-patterns that hide inconvenient rows;
- loosened checks;
- prompts that teach a model to emit numbers that reconcile.

This happened in the first real onboarding run. Profile v1 for
`split_zero_filled` reached **100% coverage with 2 silent-wrong documents**:
a bank notice was appended to descriptions. Coverage said "done"; row
agreement said 98.4%.

**What it costs.** Lower headline coverage. A reader skimming for "accuracy"
sees `NEEDS_REVIEW` counts that a coverage-maximising system would hide.

**Revisit never** for the objective. The metric set may grow, for example
cost-weighted review time.
