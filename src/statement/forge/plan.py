"""A page as positioned text: what the renderer adapter draws, and nothing else.

Keeping layout decisions here (pure) and drawing in the adapter means the
forge is testable without producing a single PDF.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Align(StrEnum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class TextItem:
    x: float  # left edge for LEFT, right edge for RIGHT
    top: float  # distance from the top of the page
    text: str
    size: float = 8.0
    bold: bool = False
    align: Align = Align.LEFT


@dataclass(frozen=True, slots=True)
class PagePlan:
    items: tuple[TextItem, ...]


@dataclass(frozen=True, slots=True)
class RenderPlan:
    pages: tuple[PagePlan, ...]
    width: float = 595.0
    height: float = 842.0
    title: str = "Statement"


# Helvetica advance widths (per 1000 em) from the standard AFM, for planning
# line wraps without importing a PDF library into the application layer.
_W = {
    " ": 278,
    "/": 278,
    ".": 278,
    ",": 278,
    ":": 278,
    ";": 278,
    "-": 333,
    "(": 333,
    ")": 333,
    "*": 389,
    "&": 667,
    "'": 191,
    "!": 278,
    "?": 556,
    "A": 667,
    "B": 667,
    "C": 722,
    "D": 722,
    "E": 667,
    "F": 611,
    "G": 778,
    "H": 722,
    "I": 278,
    "J": 500,
    "K": 667,
    "L": 556,
    "M": 833,
    "N": 722,
    "O": 778,
    "P": 667,
    "Q": 778,
    "R": 722,
    "S": 667,
    "T": 611,
    "U": 722,
    "V": 667,
    "W": 944,
    "X": 667,
    "Y": 667,
    "Z": 611,
    "f": 278,
    "i": 222,
    "j": 222,
    "l": 222,
    "m": 833,
    "r": 333,
    "t": 278,
    "w": 722,
}


def text_width(text: str, size: float = 8.0, bold: bool = False) -> float:
    em = sum(_W.get(c, 556) for c in text)
    return em * size / 1000 * (1.06 if bold else 1.0)


def wrap(text: str, max_width: float, size: float = 8.0) -> list[str]:
    """Greedy word wrap. Joining the result with single spaces restores ``text``."""
    words = text.split(" ")
    lines: list[str] = []
    cur: list[str] = []
    for w in words:
        trial = " ".join([*cur, w])
        if cur and text_width(trial, size) > max_width:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines
