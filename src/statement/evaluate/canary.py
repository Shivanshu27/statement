"""The drift canary (BUILD-PLAN §F1, H5).

Fixed pages, fixed prompt, fixed profiles, run against the live model every
day. The output is compared with the previous live run, not with truth:
this measures whether the *provider* changed, which accuracy metrics
cannot separate from code changes. A diff here, with an unchanged git sha
and prompt hash in the manifest, is attributable to the model.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from statement.domain.outcome import Fail
from statement.domain.text import TextDocument
from statement.ports import LlmPort, LlmRequest
from statement.rescue.prompt import SYSTEM, TEMPLATE_HASH, build_user, payload_hash
from statement.rescue.schema import parse_response
from statement.rescue.tier2 import Budget


@dataclass(frozen=True, slots=True)
class Change:
    doc: str
    where: str
    before: str
    after: str


def observe(docs: Sequence[tuple[str, TextDocument]], llm: LlmPort) -> dict[str, Any]:
    """One live reading per golden document, as comparable JSON."""
    out: dict[str, Any] = {}
    for name, doc in docs:
        req = LlmRequest(
            system=SYSTEM,
            user=build_user(doc),
            template_hash=TEMPLATE_HASH,
            payload_hash=payload_hash(doc),
            max_tokens=Budget().max_tokens,
        )
        reply = llm.complete(req)
        if isinstance(reply, Fail):
            out[name] = {"error": sorted(r.code.value for r in reply.reasons)}
            continue
        parsed = parse_response(reply.value.text)
        if isinstance(parsed, Fail):
            out[name] = {"error": sorted(r.code.value for r in parsed.reasons)}
            continue
        out[name] = json.loads(parsed.value.model_dump_json())
    return out


def compare(before: dict[str, Any], after: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []
    for name in sorted(set(before) | set(after)):
        a, b = before.get(name), after.get(name)
        if a == b:
            continue
        if (
            not isinstance(a, dict)
            or not isinstance(b, dict)
            or "error" in a
            or "error" in b
        ):
            changes.append(
                Change(name, "document", json.dumps(a)[:120], json.dumps(b)[:120])
            )
            continue
        for key in sorted(set(a) | set(b)):
            if key == "rows":
                continue
            if a.get(key) != b.get(key):
                changes.append(Change(name, key, str(a.get(key)), str(b.get(key))))
        rows_a, rows_b = a.get("rows", []), b.get("rows", [])
        if len(rows_a) != len(rows_b):
            changes.append(
                Change(name, "rows", f"{len(rows_a)} rows", f"{len(rows_b)} rows")
            )
        for i, (ra, rb) in enumerate(zip(rows_a, rows_b, strict=False)):
            for cell in sorted(set(ra) | set(rb)):
                if ra.get(cell) != rb.get(cell):
                    changes.append(
                        Change(
                            name,
                            f"rows[{i}].{cell}",
                            str(ra.get(cell)),
                            str(rb.get(cell)),
                        )
                    )
    return changes
