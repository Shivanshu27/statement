# 0005 — Why layout profiles as data, not parser classes?

**Decision.** A layout's quirks live in a versioned YAML file validated by a
strict pydantic schema with `extra="forbid"`. Tier 1 is one generic
interpreter of that schema.

**Because.**
- **Reviewability.** A 30-line YAML diff is reviewable by someone who has
  never read the code. A new parser class is not.
- **Safe agent output.** The onboarding agent writes data that cannot
  execute. CI can fence it to one directory (ADR-0012).
- **Provenance.** `profile_id` and `version` are recorded in every output, so
  a wrong result can be traced to the exact profile that produced it.
- **Robust columns.** Header-anchored columns find geometry at runtime,
  tolerating jitter and shifted columns without code.

**What it costs.**
- The schema caps expressiveness. A layout that needs logic the schema
  lacks needs a schema change (an ADR and code), not a profile.
- Some real layouts will need levers that don't exist yet: multi-line
  headers, columns that change mid-document.

**Revisit if** three or more onboarding attempts end with "needs a schema
change". That is the signal the schema is too narrow.
