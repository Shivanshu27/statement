"""S0 intake for /add-layout: validate samples and show the page structure.

Prints, for the first sample, every line of page 1 with its id and the x
position of each word, and flags lines that look like a table header
(several short title-case words, no digits).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from statement.adapters.pdf_reader import PdfplumberReader
from statement.domain.outcome import Fail
from statement.pipeline.run import doc_id_for


def main(samples: Path) -> int:
    pdfs = sorted(samples.glob("*.pdf"))
    if not pdfs:
        print(f"no PDFs in {samples}")
        return 1
    problems = 0
    rows = 0
    for pdf in pdfs:
        truth = pdf.with_suffix("").with_suffix(".truth.json")
        if not truth.exists():
            print(f"missing truth for {pdf.name}")
            problems += 1
            continue
        stmt = json.loads(truth.read_text(encoding="utf-8"))["statement"]
        if stmt["doc_id"] != doc_id_for(pdf.read_bytes()):
            print(f"truth doc_id does not match bytes: {pdf.name}")
            problems += 1
        rows += len(stmt["transactions"])
    print(f"{len(pdfs)} samples, {rows} truth rows, {problems} problems")
    if len(pdfs) > 10:
        print("note: the skill expects <= 10 samples")

    doc = PdfplumberReader().read(pdfs[0].read_bytes(), "intake")
    if isinstance(doc, Fail):
        print(f"cannot read {pdfs[0].name}: {doc.reasons}")
        return 1
    page = doc.value.pages[0]
    print(f"\n{pdfs[0].name} page 0 ({len(doc.value.pages)} pages)")
    for line in page.lines:
        headerish = (
            len(line.words) >= 3
            and not re.search(r"\d", line.text)
            and sum(w.text[:1].isupper() for w in line.words) >= len(line.words) - 1
        )
        mark = "  <- header?" if headerish else ""
        xs = " ".join(f"{w.text}@{w.x0:.0f}" for w in line.words[:8])
        print(f"  {line.line_id:<8} {xs}{' …' if len(line.words) > 8 else ''}{mark}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
