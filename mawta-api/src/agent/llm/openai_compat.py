"""A model behind any OpenAI-compatible chat completions API (Ollama, OpenRouter), answering
through structured outputs."""

import json
from typing import Any, cast

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONSchema

from agent.llm import LLMError, Request, Response, Usage
from agent.llm.providers import ModelRef, extra_body


class OpenAICompat:
    name: str
    _ref: ModelRef | None
    _client: AsyncOpenAI | None

    def __init__(self, ref: ModelRef | None, client: AsyncOpenAI | None) -> None:
        """No ref or no client is allowed so the server boots without a model; generate() then
        fails permanently and the HTTP layer answers agent_unavailable before ever enqueueing.
        The name is the whole "provider:model", which is what agent_generations records."""
        self.name = str(ref) if ref is not None else ""
        self._ref = ref
        self._client = client

    async def generate(self, req: Request) -> Response:
        if self._ref is None or self._client is None:
            raise LLMError("llm: no model configured for this agent", permanent=True)

        # Providers have no per-block cache control here; local servers cache the shared prefix
        # on their own, so the stable blocks still go first.
        system = "\n\n".join(block.text for block in req.system)
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system},
            {"role": "user", "content": req.prompt},
        ]
        response_format: ResponseFormatJSONSchema = {
            "type": "json_schema",
            "json_schema": {
                "name": req.tool.name,
                "strict": True,
                "schema": strict_schema(
                    {
                        "type": "object",
                        "properties": req.tool.properties,
                        "required": req.tool.required,
                    }
                ),
            },
        }
        try:
            completion = await self._client.chat.completions.create(
                model=self._ref.model,
                max_tokens=req.max_tokens,
                messages=messages,
                response_format=response_format,
                extra_body=extra_body(self._ref),
            )
        except Exception as exc:
            raise classify(exc) from exc
        return read_completion(completion)


def read_completion(completion: ChatCompletion) -> Response:
    """The structured answer of a completion, or the reason it cannot be used. A permanent error
    still carries the usage, since the call was billed."""
    resp = Response(message_id=completion.id or "", usage=usage_of(completion))
    if not completion.choices:
        raise LLMError("llm: the provider returned no answer", permanent=True, response=resp)
    choice = completion.choices[0]
    resp.stop_reason = str(choice.finish_reason)
    if choice.finish_reason == "length":
        raise LLMError("llm: answer cut off at max_tokens", permanent=True, response=resp)
    if choice.finish_reason == "content_filter" or choice.message.refusal:
        raise LLMError("llm: the model refused to answer", permanent=True, response=resp)
    try:
        resp.input = json.loads(unfence(choice.message.content or ""))
    except ValueError:
        raise LLMError(
            f"llm: the answer is not the requested JSON (finish_reason {choice.finish_reason})",
            permanent=True,
            response=resp,
        ) from None
    return resp


def usage_of(completion: ChatCompletion) -> Usage:
    u = completion.usage
    if u is None:
        return Usage()
    cached = 0
    if u.prompt_tokens_details is not None and u.prompt_tokens_details.cached_tokens:
        cached = u.prompt_tokens_details.cached_tokens
    return Usage(
        input_tokens=u.prompt_tokens,
        output_tokens=u.completion_tokens,
        cache_read_tokens=cached,
    )


def unfence(text: str) -> str:
    """Some models wrap JSON in a ```json fence even under a schema; the content is the same."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def strict_schema(node: Any) -> Any:
    """Close every object of a JSON schema (additionalProperties: false), which strict structured
    outputs require, without changing the caller's dict."""
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in cast(dict[str, Any], node).items():
        if key == "properties":
            out[key] = {name: strict_schema(p) for name, p in value.items()}
        elif key == "items":
            out[key] = strict_schema(value)
        else:
            out[key] = value
    if out.get("type") == "object":
        out["additionalProperties"] = False
    return out


def classify(exc: Exception) -> LLMError:
    """Sort provider errors into transient (worth a retry) and permanent. The provider's error
    body is never included: it is not needed to decide, and the error text ends up in logs."""
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        if status in (429, 408) or status >= 500:
            return LLMError(f"llm: provider status {status} (transient)", permanent=False)
        return LLMError(f"llm: provider status {status}", permanent=True)
    # Network failures and timeouts: transient. They come from the HTTP client, not the
    # provider, so they carry no response body.
    return LLMError(f"llm: request failed (transient): {type(exc).__name__}", permanent=False)
