"""Speech-to-text for voice notes through OpenRouter (port of internal/stt).

Sends recorded MP3 audio to OpenRouter's dedicated transcription endpoint and returns the Spanish
text it hears. One provider, one function. Every actual provider attempt also logs exactly one
usage event (task, attempt, model, generation id, duration, outcome, and the cost the provider
reported, never a price we invented). The event is emitted inside the call, before the caller's
database write, so a later persistence failure cannot hide a billable call. It never carries the
audio, the base64 payload, the transcript text, or the raw provider response or error body.
"""

import base64
import logging
import time
from dataclasses import dataclass

import httpx

import applog

DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/audio/transcriptions"
PROVIDER_NAME = "openrouter"


class SttError(Exception):
    """A transient transcription failure (network, 429, 5xx): the job's backoff applies."""


class SttPermanentError(SttError):
    """A failure the worker should not retry: a missing API key, or a non-429 4xx from
    OpenRouter (bad/empty/unsupported audio, unknown model)."""


@dataclass
class UsageMetadata:
    """What the provider reported about one call. Every field is optional: a reported zero cost
    is a real zero, not a missing one. Nothing here is invented or priced locally."""

    cost_usd: float | None = None
    generation_id: str = ""
    audio_seconds: float | None = None
    tokens: int | None = None


class Client:
    def __init__(
        self,
        api_key: str,
        model: str = "",
        endpoint: str = DEFAULT_ENDPOINT,
        logger: logging.Logger | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or "openai/whisper-large-v3"
        self.endpoint = endpoint
        self.logger = logger
        self._http = http or httpx.AsyncClient(timeout=30.0)

    async def transcribe(self, audio_mp3: bytes) -> str:
        text, _ = await self.transcribe_with_usage(audio_mp3)
        return text

    async def transcribe_with_usage(self, audio_mp3: bytes) -> tuple[str, UsageMetadata]:
        usage = UsageMetadata()
        if not self.api_key:
            # No provider call happens, so no usage event: nothing to account.
            raise SttPermanentError("stt: TRANSCRIBE_OPENROUTER_API_KEY not configured")

        body = {
            "model": self.model,
            "input_audio": {"data": base64.b64encode(audio_mp3).decode(), "format": "mp3"},
            "language": "es",
        }
        start = time.monotonic()
        try:
            resp = await self._http.post(
                self.endpoint,
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except httpx.HTTPError as exc:  # network error: transient
            self._log_usage(usage, start, "error", "transient")
            raise SttError(f"stt: request: {type(exc).__name__}") from exc

        # The provider's response body is never copied into an error (and so never into a log or
        # a jobs.errors row): the status code plus the classification is what an operator needs.
        if resp.status_code == 429 or resp.status_code >= 500:
            self._log_usage(usage, start, "error", "transient")
            raise SttError(f"stt: transient error {resp.status_code}")
        if resp.status_code != 200:
            self._log_usage(usage, start, "error", "permanent")
            raise SttPermanentError(f"stt: openrouter {resp.status_code}")
        try:
            parsed = resp.json()
            text = parsed.get("text", "") if isinstance(parsed, dict) else ""
            if not isinstance(parsed, dict):
                raise ValueError("not an object")
        except ValueError as exc:
            self._log_usage(usage, start, "error", "transient")
            raise SttError("stt: decode response") from exc

        provider_usage = parsed.get("usage") or {}
        usage = UsageMetadata(
            cost_usd=provider_usage.get("cost"),
            generation_id=parsed.get("id") or "",
            audio_seconds=provider_usage.get("audio_seconds"),
            tokens=provider_usage.get("tokens"),
        )
        self._log_usage(usage, start, "success", "")
        return text, usage

    def _log_usage(
        self, usage: UsageMetadata, start: float, outcome: str, error_class: str
    ) -> None:
        logger = self.logger or logging.getLogger(applog.SERVICE_NAME)
        task = applog.stt_task() or applog.STTTask(0, 0)
        applog.log_stt_usage(
            logger,
            task_id=task.task_id,
            attempt=task.attempt,
            provider=PROVIDER_NAME,
            model=self.model,
            duration_ms=int((time.monotonic() - start) * 1000),
            outcome=outcome,
            generation_id=usage.generation_id,
            error_class=error_class,
            cost_usd=usage.cost_usd,
            audio_seconds=usage.audio_seconds,
            tokens=usage.tokens,
        )
