"""§E3 fence: a profile must not contain values copied from ground truth.

Every money amount, date and description in the given truth files is
collected; any profile string containing one of them is a memorised answer.
Usage: python scripts/check_profile_literals.py profiles/x.yml samples/*.truth.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def main(args: list[str]) -> int:
    profiles = [Path(a) for a in args if a.endswith(".yml")]
    truths = [Path(a) for a in args if a.endswith(".json")]
    needles: set[str] = set()
    for t in truths:
        stmt = json.loads(t.read_text(encoding="utf-8"))["statement"]
        needles.update(str(stmt[k]) for k in ("opening_balance", "closing_balance"))
        for txn in stmt["transactions"]:
            needles.update(
                str(txn[k])
                for k in ("debit", "credit", "balance")
                if txn[k] not in (None, "0", "0.00")
            )
            if len(txn["description"]) > 12:
                needles.add(txn["description"])
    bad = []
    for p in profiles:
        for s in _strings(yaml.safe_load(p.read_text(encoding="utf-8"))):
            hits = [n for n in needles if len(n) >= 4 and n in s]
            if hits:
                bad.append(f"{p}: {s!r} contains truth value {hits[0]!r}")
    for b in bad:
        print(b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
