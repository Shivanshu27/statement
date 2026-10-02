# 0006 — Which dependencies, and what does each cost?

| Dependency | Why | Cost / risk |
|---|---|---|
| **pdfplumber** (pdfminer.six) | word boxes with coordinates, pure Python, MIT | slower than PyMuPDF; text order is not reading order (we rebuild lines ourselves) |
| **reportlab** | deterministic PDF output with `invariant=1`; standard fonts | Type-1 fonts lack ₹ (layouts print `INR`) |
| **pydantic v2** | frozen, strict models; the output contract and the profile schema | float coercion must be blocked explicitly (INV-09) |
| **httpx** | one small client for both providers; `MockTransport` for tests | no vendor SDK conveniences (retries are ours) |
| **typer** | CLI with types | adds click |
| **pyyaml** | profiles | `safe_load` only |

**Rejected.**
- **PyMuPDF**: AGPL licence.
- **Vendor LLM SDKs**: two providers would mean two dependency trees, for
  about 40 lines of HTTP each.
- **pandas**: nothing tabular here needs it.
- **structlog**: planned (§F2), removed during the build. Per-document
  trace events (`ParseResult.trace`, `statement explain`) carry the
  observability v1 needs, and an unused dependency is a liability.

**What it costs overall.** Six runtime dependencies, each pinned in
`uv.lock`. The lockfile is checked to point only at public PyPI.
