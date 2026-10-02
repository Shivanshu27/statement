"""The text layer as plain data: words with boxes, grouped into lines.

PDF text order is not reading order (G5), so the reader adapter rebuilds
lines from word geometry and hands the application this structure. Every
line has a stable ``line_id``; results that cross a stage boundary are keyed
by it, never by list position (INV-11).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WS = re.compile(r"\s+")


def norm_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass(frozen=True, slots=True)
class Line:
    line_id: str  # "p{page}-l{index}", stable for identical bytes
    page: int
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def top(self) -> float:
        return self.words[0].top if self.words else 0.0


@dataclass(frozen=True, slots=True)
class Page:
    index: int
    width: float
    height: float
    lines: tuple[Line, ...]


@dataclass(frozen=True, slots=True)
class TextDocument:
    doc_id: str
    pages: tuple[Page, ...]

    def lines(self) -> tuple[Line, ...]:
        return tuple(line for page in self.pages for line in page.lines)

    def line_map(self) -> dict[str, Line]:
        return {line.line_id: line for line in self.lines()}

    def full_text(self) -> str:
        return "\n".join(line.text for line in self.lines())


def line_id(page: int, index: int) -> str:
    return f"p{page}-l{index}"
