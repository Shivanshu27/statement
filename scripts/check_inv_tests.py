"""Every invariant in the build plan has a test whose docstring names it.

The plan is the contract; this keeps the test suite honest about it.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    plan = (ROOT / "docs" / "BUILD-PLAN.md").read_text(encoding="utf-8")
    invariants = sorted(set(re.findall(r"\*\*(INV-\d{2})\*\*", plan)))
    covered: set[str] = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                doc = ast.get_docstring(node) or ""
                covered.update(re.findall(r"INV-\d{2}", doc))
    missing = [i for i in invariants if i not in covered]
    if missing:
        print(f"invariants without a named test: {', '.join(missing)}")
        return 1
    print(f"all {len(invariants)} invariants have named tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
