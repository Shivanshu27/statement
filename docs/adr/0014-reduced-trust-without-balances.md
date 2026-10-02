# 0014 — What happens to layouts with no running balance?

**Decision.** A profile may declare `balance_policy: none`.
- INV-02 (the chain) and the balance-presence check become *not applicable*.
- INV-01 (totals) and INV-04 (dates) still apply.
- Such documents can be `ACCEPTED`. Their checks record `chain: n/a`, and
  provenance carries the policy, so consumers can apply stricter review.

Mixed balance presence in a Tier-2 reading is never a third policy. It is
treated as `every_row`, so the missing balances surface as
`BALANCE_MISSING`.

**Because.** Some real statements print no running balance. Refusing them
all would push every such document to review. Accepting them silently at
full trust would overstate what was proven.

**What it costs.** On these layouts, two compensating amount errors escape
with no balance edits at all, so F13 is cheaper to hit than on
balance-printing layouts. The no_balance onboarding report documents this.

**Revisit if** consumers ask for a per-policy acceptance threshold, for
example "never auto-accept `none` above some amount".
