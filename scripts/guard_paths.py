"""§E3 fence: an onboarding-agent branch may only touch profile data and its tests.

Usage (CI, on branches named onboard/*):
    python scripts/guard_paths.py $(git diff --name-only origin/main...HEAD)

The fence is a mechanism, not an instruction: the agent can be told not to
edit the scorer, but this is what makes it unable to merge if it does.
"""

from __future__ import annotations

import fnmatch
import sys

ALLOWED = (
    "profiles/*.yml",
    "tests/profiles/test_*.py",
    "docs/onboarding/*.md",
    "cache/llm/*/*.json",
)


def main(paths: list[str]) -> int:
    bad = [p for p in paths if not any(fnmatch.fnmatch(p, pat) for pat in ALLOWED)]
    for p in bad:
        print(f"onboarding branch may not touch: {p}")
    if not bad:
        print(f"{len(paths)} changed paths, all inside the onboarding allow-list")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
