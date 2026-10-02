# 0012 — How is the onboarding agent kept from gaming its score?

**Decision.** The fences are mechanisms, not instructions:

| Threat | Fence |
|---|---|
| Edits the scorer or verifier | `scripts/guard_paths.py` fails any `onboard/*` branch touching paths outside `profiles/`, `tests/profiles/`, `docs/onboarding/` |
| Overfits to samples | the holdout is generated in CI from a repository secret; the agent sees only the posted result |
| Memorises answers | the profile schema has no per-document or literal-amount fields; `check_profile_literals.py` rejects truth values in profiles |
| Learns the verifier through prompts | profiles cannot carry prompt text; prompts never mention arithmetic |
| Claims success it didn't achieve | CI re-scores and posts the real numbers; the report must cite a manifest |
| Declares victory on coverage | the goal and anti-goal are in bold at the top of the skill (ADR-0013) |

**Because.** An agent optimises what is measurable and reachable. The skill
file is a request; these fences are what make breaking a request fail CI.

**What it costs.**
- The agent cannot fix a real code bug it finds while onboarding. It must
  stop and report it, which is slower.
- The holdout needs CI secrets, so local runs only emulate it. In the build
  session it was generated from an inline random secret and scored once.

**Revisit if** onboarding regularly stalls on "needs code". The answer is a
better schema (ADR-0005), not looser fences.
