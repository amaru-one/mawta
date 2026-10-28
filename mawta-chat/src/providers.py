"""Where a model runs: a "provider:model" value names both.

Every provider speaks the OpenAI-compatible chat completions API, so moving a task between a local
Ollama and OpenRouter is a configuration change: `PLANNING_AGENT_MODEL=ollama:gemma4:12b-it-qat`
or `PLANNING_AGENT_MODEL=openrouter:qwen/qwen3-30b-a3b`. The provider is what comes before the
first colon; the rest is the model's name at that provider, colons included (Ollama tags have one).
"""

from dataclasses import dataclass
from typing import override

from openai import AsyncOpenAI

OLLAMA = "ollama"
OPENROUTER = "openrouter"
PROVIDERS = (OLLAMA, OPENROUTER)

# The SDK refuses to build a client without an api_key, but a local Ollama ignores it.
_OLLAMA_PLACEHOLDER_KEY = "ollama"


@dataclass(frozen=True)
class ModelRef:
    provider: str
    model: str

    @override
    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


def parse(value: str) -> ModelRef:
    """ "ollama:gemma4:12b-it-qat" -> ModelRef("ollama", "gemma4:12b-it-qat")."""
    provider, sep, model = value.strip().partition(":")
    if not sep or not model.strip():
        raise ValueError(
            f'"{value}" is not "provider:model" (for example "ollama:gemma4:12b-it-qat")'
        )
    if provider not in PROVIDERS:
        raise ValueError(f'unknown provider "{provider}" in "{value}"; use one of {PROVIDERS}')
    return ModelRef(provider, model.strip())


@dataclass(frozen=True)
class Endpoints:
    """The providers' addresses and keys, from configuration."""

    ollama_url: str
    ollama_api_key: str
    openrouter_url: str
    openrouter_api_key: str


def configured(ref: ModelRef, ep: Endpoints) -> bool:
    """Whether the provider has what it needs: an address for Ollama, a key for OpenRouter."""
    if ref.provider == OLLAMA:
        return bool(ep.ollama_url)
    return bool(ep.openrouter_url and ep.openrouter_api_key)


def client_for(ref: ModelRef, ep: Endpoints, timeout: float) -> AsyncOpenAI:
    """A client for the model's provider. One quick SDK retry absorbs a momentary 429/5xx;
    anything longer is the job queue's backoff."""
    if ref.provider == OLLAMA:
        url, key = ep.ollama_url, ep.ollama_api_key or _OLLAMA_PLACEHOLDER_KEY
    else:
        url, key = ep.openrouter_url, ep.openrouter_api_key
    return AsyncOpenAI(base_url=url, api_key=key, timeout=timeout, max_retries=1)


def extra_body(ref: ModelRef) -> dict[str, object] | None:
    """OpenRouter routes a request to any provider that serves the model; require_parameters keeps
    it to the ones that honour every parameter sent (the JSON schema, the tools)."""
    if ref.provider == OPENROUTER:
        return {"provider": {"require_parameters": True}}
    return None
