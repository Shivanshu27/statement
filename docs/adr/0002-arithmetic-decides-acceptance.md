# 0002 — Why does only arithmetic decide acceptance? (INV-05)

**Decision.** `ACCEPTED` is a function of the invariant engine's output and
nothing else. No confidence score, model self-report, or prompt text can set
or influence a verdict.

The rule is enforced in two ways:
- **Structurally.** `statement.rescue` may not import
  `statement.domain.verify` (import-linter contract).
- **Behaviourally.** `test_llm_cannot_reach_verdict` feeds a confidently
  worded, grounded, wrong reading and checks it is `NEEDS_REVIEW`.

**Because.**
- A bank statement checks itself: the running balance is a hash chain over
  the rows. Arithmetic is a far stronger signal than any model's belief about
  its own output.
- Model confidence is uncalibrated on exactly the inputs where it matters
  (unfamiliar layouts).
- It removes a whole class of prompt-injection outcomes. A document can tell
  the model anything, but it cannot tell the verifier anything.

**What it costs.**
- Errors that keep the arithmetic intact (F06 misattached descriptions, F13
  compensating errors) are accepted. The scorer measures them, but nothing at
  runtime can catch them. See ADR-0003.
- Layouts without running balances get a weaker check (ADR-0014).

**Revisit if** a second independent runtime signal appears that is as hard to
fake as arithmetic, for example agreement between two different extractors
on description text.
