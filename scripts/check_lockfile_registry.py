"""G5 trap: a corporate mirror captured in uv.lock leaks hostnames and breaks clones."""

from __future__ import annotations

import re
import sys
from pathlib import Path

LOCK = Path(__file__).resolve().parents[1] / "uv.lock"
PUBLIC = ("https://pypi.org/simple", "https://files.pythonhosted.org/")


def main() -> int:
    urls = set(re.findall(r'https?://[^"\s]+', LOCK.read_text(encoding="utf-8")))
    bad = sorted(u for u in urls if not u.startswith(PUBLIC))
    for u in bad:
        print(f"non-public URL in uv.lock: {u}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
