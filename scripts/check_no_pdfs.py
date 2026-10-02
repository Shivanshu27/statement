"""§F4: no PDF may be committed except the fixed canary set (synthetic, forged).

Real statements must never enter git. Runs against `git ls-files` when the
repo is a git checkout, else against the working tree.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = ("canary/golden/",)


def tracked() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        )
        return out.stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        skip = {".venv", ".uv-cache", "corpus", "runs", "private"}
        return [
            str(p.relative_to(ROOT))
            for p in ROOT.rglob("*.pdf")
            if not (set(p.relative_to(ROOT).parts) & skip)
        ]


def main() -> int:
    bad = [
        f for f in tracked() if f.lower().endswith(".pdf") and not f.startswith(ALLOWED)
    ]
    for f in bad:
        print(f"PDF outside {ALLOWED}: {f}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
