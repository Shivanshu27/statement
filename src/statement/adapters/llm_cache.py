"""Content-addressed LLM response cache with live / record / replay modes (ADR-0009).

- ``live``: call the model, don't write.
- ``record``: call the model on a miss and write the answer.
- ``replay``: cache only; a miss is an error. Tests, CI and the README demo
  run here, so none of them need an API key and all of them are
  deterministic (INV-08).

The key includes the prompt template hash. Without it an edited prompt
would silently replay answers to the old prompt (G5).
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path

from statement.domain.outcome import Fail, Ok, Outcome
from statement.domain.reasons import Code, Reason
from statement.ports import LlmPort, LlmRequest, LlmResponse


class CacheMode(StrEnum):
    LIVE = "live"
    RECORD = "record"
    REPLAY = "replay"


def cache_key(model_id: str, req: LlmRequest) -> str:
    material = json.dumps(
        [model_id, req.template_hash, req.payload_hash], separators=(",", ":")
    )
    return hashlib.sha256(material.encode()).hexdigest()


class CachedLlm:
    def __init__(
        self, root: Path, mode: CacheMode, inner: LlmPort | None, model_id: str
    ) -> None:
        if mode is not CacheMode.REPLAY and inner is None:
            raise ValueError(f"cache mode {mode} needs a live model")
        self._root = root
        self._mode = mode
        self._inner = inner
        self._model_id = inner.model_id if inner else model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    def _path(self, key: str) -> Path:
        return self._root / key[:2] / f"{key}.json"

    def complete(self, req: LlmRequest) -> Outcome[LlmResponse]:
        key = cache_key(self._model_id, req)
        path = self._path(key)
        if self._mode is not CacheMode.LIVE and path.exists():
            entry = json.loads(path.read_text(encoding="utf-8"))
            return Ok(
                LlmResponse(
                    text=entry["text"],
                    model_id=entry["model_id"],
                    input_tokens=entry["input_tokens"],
                    output_tokens=entry["output_tokens"],
                    cached=True,
                )
            )
        if self._mode is CacheMode.REPLAY:
            return Fail(Reason(Code.RESCUE_CACHE_MISS, key[:12]))
        assert self._inner is not None
        out = self._inner.complete(req)
        if isinstance(out, Ok) and self._mode is CacheMode.RECORD:
            path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "model_id": out.value.model_id,
                "template_hash": req.template_hash,
                "payload_hash": req.payload_hash,
                "input_tokens": out.value.input_tokens,
                "output_tokens": out.value.output_tokens,
                "text": out.value.text,
            }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(entry, indent=1, ensure_ascii=False), encoding="utf-8"
            )
            tmp.replace(path)
        return out
