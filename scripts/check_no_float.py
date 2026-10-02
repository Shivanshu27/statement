"""INV-09, lexically: no float literal or float() call in the domain ring."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

DOMAIN = Path(__file__).resolve().parents[1] / "src" / "statement" / "domain"


def main() -> int:
    bad: list[str] = []
    for path in sorted(DOMAIN.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                bad.append(f"{path.name}:{node.lineno} float literal {node.value}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "float"
            ):
                bad.append(f"{path.name}:{node.lineno} float() call")
    # domain/text.py carries PDF coordinates, which are geometry, not money.
    bad = [b for b in bad if not b.startswith("text.py")]
    for b in bad:
        print(b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
