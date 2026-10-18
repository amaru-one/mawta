"""Claude through the Messages API with structured outputs."""

import json
from typing import Any

import anthropic

from mawta_api.agent.llm import LLMError, Request, Response, Usage


class Anthropic:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        """An empty api_key is allowed so the server boots without one; generate() then fails
        permanently and the HTTP layer answers agent_unavailable before ever enqueueing."""
        self.name = model
        self._client = client
        if self._client is None and api_key:
            # One quick SDK retry absorbs a momentary 429/529; anything longer is the job
            # queue's backoff.
            self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=1)

    def configured(self) -> bool:
        return self._client is not None

    async def generate(self, req: Request) -> Response:
        if self._client is None:
            raise LLMError("llm: ANTHROPIC_API_KEY not configured", permanent=True)

        system: list[dict[str, Any]] = []
        for block in req.system:
            item: dict[str, Any] = {"type": "text", "text": block.text}
            if block.cache:
                item["cache_control"] = {"type": "ephemeral"}
            system.append(item)
        # Structured outputs: the answer must be a JSON object matching the tool's schema.
        # (Forcing a tool call is not supported by every model - claude-sonnet-5-5 rejects
        # tool_choice "tool" - while structured outputs guarantee the shape on all of them.)
        schema = strict_schema(
            {
                "type": "object",
                "properties": req.tool.properties,
                "required": req.tool.required,
            }
        )
        try:
            msg = await self._client.messages.create(
                model=self.name,
                max_tokens=req.max_tokens,
                system=system,
                messages=[{"role": "user", "content": [{"type": "text", "text": req.prompt}]}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except Exception as exc:
            raise classify(exc) from exc

        resp = Response(
            message_id=msg.id,
            stop_reason=str(msg.stop_reason),
            usage=Usage(
                input_tokens=msg.usage.input_tokens,
                output_tokens=msg.usage.output_tokens,
                cache_read_tokens=msg.usage.cache_read_input_tokens or 0,
                cache_write_tokens=msg.usage.cache_creation_input_tokens or 0,
            ),
        )
        if msg.stop_reason == "max_tokens":
            raise LLMError("llm: answer cut off at max_tokens", permanent=True, response=resp)
        if msg.stop_reason == "refusal":
            raise LLMError("llm: the model refused to answer", permanent=True, response=resp)
        answer = "".join(b.text for b in msg.content if b.type == "text").strip()
        try:
            resp.input = json.loads(answer)
        except ValueError:
            raise LLMError(
                f"llm: the answer is not the requested JSON (stop_reason {msg.stop_reason})",
                permanent=True,
                response=resp,
            ) from None
        return resp


def strict_schema(node: Any) -> Any:
    """Close every object of a JSON schema (additionalProperties: false), which structured
    outputs require, without changing the caller's dict."""
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
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
    if isinstance(exc, anthropic.APIStatusError):
        status = exc.status_code
        if status in (429, 408) or status >= 500:
            return LLMError(f"llm: provider status {status} (transient)", permanent=False)
        return LLMError(f"llm: provider status {status}", permanent=True)
    # Network failures and timeouts: transient. They come from the HTTP client, not the
    # provider, so they carry no response body.
    return LLMError(f"llm: request failed (transient): {type(exc).__name__}", permanent=False)
