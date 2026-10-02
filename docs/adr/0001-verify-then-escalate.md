# 0001 — Why verify-then-escalate instead of LLM-first?

**Decision.** Every document goes to a deterministic profile parser (Tier 1)
first. The LLM (Tier 2) runs only when Tier 1's result fails verification or
the layout is unknown. Both tiers face the same verifier.

**Because.**
- Most statements come from a small set of layouts. Tier 1 reads them in
  about 45 ms per document (≈27 ms per page on an M4), with no tokens and no
  drift.
- An LLM-first design pays model cost and model risk on every document,
  including the 100% of them Tier 1 already reads exactly.
- Escalation turns the LLM into a *rescue*. Its worst case is the Tier-1
  worst case, `NEEDS_REVIEW`, never something worse.

**What it costs.**
- Two code paths to maintain. A layout handled only by Tier 2 has no
  deterministic fallback.
- Profiles have to be written, by a person or by the onboarding agent, for
  each layout that should be fast and free.
- A Tier-1 result that verifies but is semantically wrong (F06/F13) never
  reaches the LLM, which might have read it correctly.

**Revisit if** model costs fall to near zero *and* drift becomes measurably
negligible. Even then, the verifier stays.
