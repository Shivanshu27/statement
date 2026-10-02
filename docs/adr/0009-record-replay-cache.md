# 0009 — Why record/replay as the testing strategy for the LLM?

**Decision.** All LLM calls go through a content-addressed cache with three
modes: `live`, `record` and `replay`.
- The cache key is `(model id, prompt template hash, page-text hash)`.
- Tests, CI and the demo run in `replay`.
- In `replay`, a cache miss is an error, never a silent live call.

**Because.**
- **Drift-proof regression.** The model changes from day to day, so a fresh
  call cannot tell a code regression from drift. Replaying cached answers
  through new code can (§D4).
- **Zero-cost reproduction.** A reviewer reproduces the numbers with no API
  key.
- **Safe prompt edits.** The template hash is part of the key, so an edited
  prompt cannot silently replay answers given to the old prompt.

**What it costs.**
- Cached answers go stale against a moving model. That is what the canary is
  for (H5).
- Cache files are data that must be reviewed and must contain only synthetic
  text. A cache built from real statements must never be committed (§F4).

**Status note.** In this build the cache machinery is fully tested with
scripted doubles, but **no real-model cassette has been recorded yet.**
