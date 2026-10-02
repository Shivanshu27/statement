"""PDF bytes -> TextDocument via pdfplumber.

PDF text order is not reading order (G5), so lines are rebuilt from word
geometry: words are clustered by their top coordinate and sorted by x.
"""

from __future__ import annotations

import io

import pdfplumber

from statement.domain.outcome import Fail, Ok, Outcome
from statement.domain.reasons import Code, Reason
from statement.domain.text import Line, Page, TextDocument, Word, line_id


class PdfplumberReader:
    def __init__(self, *, max_pages: int = 50, line_tolerance: float = 2.5) -> None:
        self._max_pages = max_pages
        self._tol = line_tolerance

    def read(self, data: bytes, doc_id: str) -> Outcome[TextDocument]:
        try:
            pdf = pdfplumber.open(io.BytesIO(data))
        except Exception as exc:
            msg = str(exc).lower()
            code = (
                Code.PDF_ENCRYPTED
                if "password" in msg or "encrypt" in msg
                else Code.NOT_PDF
            )
            return Fail(Reason(code, type(exc).__name__))
        with pdf:
            if len(pdf.pages) > self._max_pages:
                return Fail(
                    Reason(Code.TOO_MANY_PAGES, f"{len(pdf.pages)} > {self._max_pages}")
                )
            pages: list[Page] = []
            total = 0
            for p_idx, page in enumerate(pdf.pages):
                try:
                    raw = page.extract_words(
                        keep_blank_chars=False, use_text_flow=False
                    )
                except Exception as exc:
                    return Fail(
                        Reason(Code.NOT_PDF, f"page {p_idx}: {type(exc).__name__}")
                    )
                words = [
                    Word(
                        str(w["text"]), float(w["x0"]), float(w["x1"]), float(w["top"])
                    )
                    for w in raw
                ]
                total += len(words)
                pages.append(
                    Page(
                        p_idx,
                        float(page.width),
                        float(page.height),
                        self._lines(p_idx, words),
                    )
                )
        if total == 0:
            return Fail(Reason(Code.NO_TEXT_LAYER, "no extractable text (scanned?)"))
        return Ok(TextDocument(doc_id=doc_id, pages=tuple(pages)))

    def _lines(self, page: int, words: list[Word]) -> tuple[Line, ...]:
        words = sorted(words, key=lambda w: (w.top, w.x0))
        groups: list[list[Word]] = []
        for w in words:
            if groups and abs(w.top - groups[-1][0].top) <= self._tol:
                groups[-1].append(w)
            else:
                groups.append([w])
        return tuple(
            Line(line_id(page, i), page, tuple(sorted(g, key=lambda w: w.x0)))
            for i, g in enumerate(groups)
        )
