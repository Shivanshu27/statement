# 0003 — Why three verdicts, and why "ACCEPTED" not "CORRECT"?

**Decision.** Every document ends in exactly one of three verdicts:
- `ACCEPTED`: all invariants hold and no extraction doubts remain.
- `NEEDS_REVIEW`: the document was parsed, but something failed or could not
  be proven. The best available reading is shown, never as trusted.
- `REJECTED`: not a statement we can process (not a PDF, encrypted, no text
  layer, too large).

**Because.**
- A binary pass/fail forces a choice between dropping partial reads (losing
  work a reviewer could finish in seconds) and trusting them (the failure
  this project exists to prevent).
- `ACCEPTED` names what we can actually prove: arithmetic consistency (L2).
  Calling it `CORRECT` would claim L3, which needs ground truth that does not
  exist at runtime.

**What it costs.**
- Consumers must handle `NEEDS_REVIEW` as a real workflow, not as an error.
- The name `ACCEPTED` will still be read as "correct" by some users. The
  README states the escape classes explicitly.

**Revisit if** a review UI ships. Then `NEEDS_REVIEW` may want sub-states,
such as "one row unclear" versus "unknown layout".
