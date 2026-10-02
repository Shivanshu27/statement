"""Record/replay cache and HTTP adapters, with no network."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from statement.adapters.llm_cache import CachedLlm, CacheMode, cache_key
from statement.adapters.llm_http import AnthropicLlm, OllamaLlm
from statement.domain.outcome import Fail, Ok
from statement.domain.reasons import Code
from statement.ports import LlmRequest
from tests.conftest import ScriptedLlm, reply

REQ = LlmRequest(
    system="s", user="u", template_hash="t1", payload_hash="p1", max_tokens=100
)


def test_replay_miss_is_an_error_not_a_call(tmp_path: Path) -> None:
    out = CachedLlm(tmp_path, CacheMode.REPLAY, None, "m").complete(REQ)
    assert isinstance(out, Fail) and out.reasons[0].code is Code.RESCUE_CACHE_MISS


def test_record_then_replay(tmp_path: Path) -> None:
    live = ScriptedLlm(reply('{"rows": []}'), model="m")
    assert isinstance(
        CachedLlm(tmp_path, CacheMode.RECORD, live, "m").complete(REQ), Ok
    )
    again = CachedLlm(tmp_path, CacheMode.REPLAY, None, "m").complete(REQ)
    assert (
        isinstance(again, Ok)
        and again.value.cached
        and again.value.text == '{"rows": []}'
    )


def test_prompt_edit_changes_the_cache_key() -> None:
    edited = LlmRequest(
        system="s", user="u", template_hash="t2", payload_hash="p1", max_tokens=100
    )
    assert cache_key("m", REQ) != cache_key("m", edited)
    assert cache_key("m", REQ) != cache_key("other-model", REQ)


def _client(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")


def test_anthropic_adapter_parses_and_flags_truncation() -> None:
    seen: list[dict[str, object]] = []

    def ok(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.headers["x-api-key"] == "k"
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "{}"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 7, "output_tokens": 3},
            },
        )

    out = AnthropicLlm("k", "claude-test", client=_client(ok)).complete(REQ)
    assert isinstance(out, Ok) and out.value.input_tokens == 7
    assert seen[0]["temperature"] == 0 and seen[0]["system"] == "s"

    def cut(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"content": [], "stop_reason": "max_tokens", "usage": {}}
        )

    out = AnthropicLlm("k", "claude-test", client=_client(cut)).complete(REQ)
    assert isinstance(out, Fail) and out.reasons[0].code is Code.RESCUE_BUDGET


def test_http_errors_are_values() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    out = OllamaLlm("llama", client=_client(down)).complete(REQ)
    assert isinstance(out, Fail) and out.reasons[0].code is Code.RESCUE_ERROR

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    out = OllamaLlm("llama", client=_client(timeout)).complete(REQ)
    assert isinstance(out, Fail) and out.reasons[0].code is Code.RESCUE_BUDGET
