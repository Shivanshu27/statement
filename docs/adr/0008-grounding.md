# 0008 — What does grounding buy, and what does it rule out? (INV-06)

**Decision.** Grounding works at three levels:
- **Row values.** Every returned amount and balance must appear verbatim
  (after whitespace and case normalisation) on the lines the model cites for
  that row.
- **Dates.** A date may also be grounded on an earlier line of the same page,
  for layouts that print the date only on a day's first row.
- **Document fields** (period, opening, closing) must appear somewhere in the
  document.

Description words must all appear on the cited lines. Any ungrounded value is
dropped and reported as `RESCUE_UNGROUNDED`.

**Because.** It removes the "invented but plausible" failure class entirely
for text-layer PDFs, at the cost of a substring check.

**What it rules out, deliberately.**
- *Derived values.* A model may not compute a missing balance, even
  correctly.
- *Normalised descriptions.* "Grocery shopping (summarised)" is rejected.

**What it does not do.** It proves a number is *printed*, not that it is the
*right* number. The forge's prompt-injection fixture prints `9999999.00`
inside a description, so a model that obeys it produces a grounded but wrong
closing balance. The verifier catches that (`TOTALS_MISMATCH`), and so does
`test_prompt_injection_cannot_move_a_number`.

**What it costs.** Scanned PDFs, where the text comes from OCR, would need
grounding against OCR output, with its own error rate.
