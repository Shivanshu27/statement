# 0007 — Why does the model return cells and code assemble? (INV-07)

**Decision.** Tier 2 asks the model only to *copy* raw printed cells (date,
description, debit, credit, amount, balance), keyed by line id. Code then:
- infers the reading rules (number locale, date format, sign convention,
  balance policy) from those cells, and
- builds the `Statement` with the same `assemble()` that Tier 1 uses.

**Because.**
- **One implementation of every interpretation rule.** Sign spellings, lakh
  grouping and year rollover exist once and are tested once.
- **Determinism.** The same cells always produce the same statement, so
  replay regression is exact (INV-08).
- **Ambiguity is detected.** DD/MM versus MM/DD is decided by evidence across
  the whole document. If two readings both fit, the result is
  `DATE_FORMAT_AMBIGUOUS`, never a guess.

**What it costs.**
- The model cannot fix what it reads. If a cell is printed wrongly, the
  rescue is wrong too, and verification catches it.
- Rule inference can fail where a human would shrug. An all-days-≤12
  statement with a long period is unresolvable by design.

**Revisit if** a model's structured output proves more reliable than our
inference on real data. Even then, keep the assembly in code.
