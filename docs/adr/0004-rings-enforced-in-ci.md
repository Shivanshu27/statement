# 0004 — Why concentric rings with CI-enforced imports?

**Decision.** The code is organised as four rings:
- **domain**: pure. No I/O, no clock, no randomness.
- **application**: pipeline, extract, rescue, evaluate, forge.
- **adapters**: pdfplumber, reportlab, httpx, the cache, profile files.
- **entrypoints**: the CLI and composition root.

Dependencies point inward only. Four import-linter contracts run in CI.

**Because.**
- The verifier must be trustworthy, so it must be small, pure and testable
  in isolation. A domain that cannot import an HTTP client cannot
  accidentally consult a model.
- The contracts turn two invariants into structure: INV-05 (rescue cannot see
  the verifier) and "the scorer is not on the product path".
- Swapping pdfplumber or the LLM provider touches one adapter.

**What it costs.**
- Some indirection: `ports.py` protocols, a composition root, and the
  `Extraction` type living in the ports module so sibling tiers can share it.
- Contracts constrain refactors. Moving a type across rings means editing the
  contract with a reason.

**Revisit if** the codebase grows a second product surface (a web API) that
needs its own entrypoint ring.
