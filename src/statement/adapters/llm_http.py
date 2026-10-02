"""LLM providers over plain HTTP. The provider is configuration; the domain never knows.

Base URLs come from Statement's own settings, never from ambient variables
such as ``ANTHROPIC_BASE_URL`` that other tools on the machine may set.
"""

from __future__ import annotations

from typing import Any

import httpx

from statement.domain.outcome import Fail, Ok, Outcome
from statement.domain.reasons import Code, Reason
from statement.ports import LlmRequest, LlmResponse


def _transport_error(exc: Exception) -> Fail:
    if isinstance(exc, httpx.TimeoutException):
        return Fail(Reason(Code.RESCUE_BUDGET, "timeout"))
    return Fail(Reason(Code.RESCUE_ERROR, type(exc).__name__))


class AnthropicLlm:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://api.anthropic.com",
        timeout_s: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._model = model
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_s)
        self._headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    @property
    def model_id(self) -> str:
        return f"anthropic/{self._model}"

    def complete(self, req: LlmRequest) -> Outcome[LlmResponse]:
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": req.max_tokens,
            "temperature": 0,
            "system": req.system,
            "messages": [{"role": "user", "content": req.user}],
        }
        try:
            r = self._client.post("/v1/messages", json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            return _transport_error(exc)
        if r.status_code != 200:
            return Fail(Reason(Code.RESCUE_ERROR, f"HTTP {r.status_code}"))
        data = r.json()
        if data.get("stop_reason") == "max_tokens":
            return Fail(Reason(Code.RESCUE_BUDGET, "reply truncated at max_tokens"))
        text = "".join(
            b.get("text", "")
            for b in data.get("content", [])
            if b.get("type") == "text"
        )
        usage = data.get("usage", {})
        return Ok(
            LlmResponse(
                text=text,
                model_id=self.model_id,
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            )
        )


class OllamaLlm:
    """Local models: nothing leaves the machine (``--local-only``, §F4)."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout_s: float = 300.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._model = model
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_s)

    @property
    def model_id(self) -> str:
        return f"ollama/{self._model}"

    def complete(self, req: LlmRequest) -> Outcome[LlmResponse]:
        body = {
            "model": self._model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": req.max_tokens},
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user},
            ],
        }
        try:
            r = self._client.post("/api/chat", json=body)
        except httpx.HTTPError as exc:
            return _transport_error(exc)
        if r.status_code != 200:
            return Fail(Reason(Code.RESCUE_ERROR, f"HTTP {r.status_code}"))
        data = r.json()
        return Ok(
            LlmResponse(
                text=str(data.get("message", {}).get("content", "")),
                model_id=self.model_id,
                input_tokens=int(data.get("prompt_eval_count", 0)),
                output_tokens=int(data.get("eval_count", 0)),
            )
        )
