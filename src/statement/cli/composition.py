"""The composition root: the only module that constructs adapters (contract 5, §C4).

Configuration comes from ``STATEMENT_*`` environment variables. Defaults are
safe: no LLM, cache in replay mode, so nothing leaves the machine and
nothing costs money unless asked for.
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from statement.adapters.llm_cache import CachedLlm, CacheMode
from statement.adapters.llm_http import AnthropicLlm, OllamaLlm
from statement.adapters.pdf_reader import PdfplumberReader
from statement.adapters.profiles_fs import DirectoryProfiles
from statement.domain.profile import Profile
from statement.pipeline.run import Pipeline
from statement.ports import LlmPort
from statement.rescue.prompt import TEMPLATE_HASH

DEFAULT_MODELS = {"anthropic": "claude-haiku-4-5-20251001", "ollama": "llama3.1:8b"}


@dataclass(frozen=True, slots=True)
class Settings:
    profiles_dir: Path
    llm: str  # none | anthropic | ollama
    model: str
    cache_mode: CacheMode
    cache_dir: Path
    base_url: str | None

    @property
    def model_id(self) -> str:
        return f"{self.llm}/{self.model}" if self.llm != "none" else "none"

    @classmethod
    def from_env(cls, **overrides: Any) -> Settings:
        llm = overrides.get("llm") or os.environ.get("STATEMENT_LLM", "none")
        if llm not in ("none", "anthropic", "ollama"):
            raise ValueError(
                f"STATEMENT_LLM must be none|anthropic|ollama, got {llm!r}"
            )
        model = (
            overrides.get("model")
            or os.environ.get("STATEMENT_LLM_MODEL")
            or DEFAULT_MODELS.get(llm, "none")
        )
        return cls(
            profiles_dir=Path(
                overrides.get("profiles_dir")
                or os.environ.get("STATEMENT_PROFILES", "profiles")
            ),
            llm=llm,
            model=model,
            cache_mode=CacheMode(
                overrides.get("cache_mode")
                or os.environ.get("STATEMENT_CACHE_MODE", "replay")
            ),
            cache_dir=Path(
                overrides.get("cache_dir")
                or os.environ.get("STATEMENT_CACHE_DIR", "cache/llm")
            ),
            base_url=os.environ.get("STATEMENT_LLM_BASE_URL"),
        )


def build_llm(s: Settings) -> LlmPort | None:
    if s.llm == "none":
        return None
    inner: LlmPort | None = None
    if s.cache_mode is not CacheMode.REPLAY:
        if s.llm == "anthropic":
            key = os.environ.get("STATEMENT_ANTHROPIC_API_KEY")
            if not key:
                raise SystemExit(
                    "STATEMENT_ANTHROPIC_API_KEY is not set (live/record mode)"
                )
            inner = AnthropicLlm(
                key, s.model, base_url=s.base_url or "https://api.anthropic.com"
            )
        else:
            inner = OllamaLlm(s.model, base_url=s.base_url or "http://127.0.0.1:11434")
    return CachedLlm(s.cache_dir, s.cache_mode, inner, s.model_id)


def load_profiles(s: Settings) -> tuple[Profile, ...]:
    return DirectoryProfiles(s.profiles_dir).profiles()


def build_pipeline(s: Settings) -> Pipeline:
    return Pipeline(PdfplumberReader(), load_profiles(s), build_llm(s))


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def corpus_fingerprint(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.name.encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:16]


def manifest(
    s: Settings, *, corpus: Path, files: list[Path], extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Every number carries the conditions that produced it (§C7).

    Separating code changes (git sha, profile versions) from model drift
    (only time differs) is what the canary depends on.
    """
    sha = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    return {
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": sha or "not-a-git-repo",
        "dirty": bool(status) if status is not None else None,
        "profiles": {p.id: p.version for p in load_profiles(s)},
        "llm": s.model_id,
        "prompt_hash": TEMPLATE_HASH,
        "cache_mode": s.cache_mode.value,
        "corpus": str(corpus),
        "corpus_docs": len(files),
        "corpus_sha": corpus_fingerprint(files),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        **(extra or {}),
    }
