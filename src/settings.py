"""Runtime configuration, read from the environment (and .env in development).

Same variable names as the former server. An empty variable counts as unset.
A value that cannot be parsed fails at boot instead of silently using the
default.
"""

import re
from typing import Annotated, Any, ClassVar

from pydantic import BeforeValidator, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from agent.llm.providers import REASONING_EFFORTS, Endpoints, ModelRef, configured, parse

_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ns|us|µs|ms|s|m|h)")
_UNIT_SECONDS = {
    "ns": 1e-9,
    "us": 1e-6,
    "µs": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
}


def parse_duration(value: Any) -> float:
    """Seconds from a duration string ("720h", "15m", "1h30m", "90s") or a number."""
    if isinstance(value, bool):
        raise ValueError("not a duration")
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    if not text or not re.fullmatch(rf"(?:{_DURATION_PART.pattern})+", text):
        raise ValueError(f"invalid duration {value!r}")
    return sum(float(n) * _UNIT_SECONDS[u] for n, u in _DURATION_PART.findall(text))


Duration = Annotated[float, BeforeValidator(parse_duration)]


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True, populate_by_name=True
    )

    database_url: str
    # The database owner (a superuser): migrations, `onboard` and `useradd`.
    admin_database_url: str = ""
    http_addr: str = ":8080"
    worker_enabled: bool = True
    worker_concurrency: int = 2
    worker_queue: str = "default"
    storage_dir: str = "./data/audio"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    log_level: str = "info"
    request_body_capture: bool = False

    # Voice-note transcription: Whisper through OpenRouter, with OPENROUTER_API_KEY (below).
    transcribe_model: str = "openai/whisper-large-v3"

    # Where the agents' models run (see agent/llm/providers.py). Every agent names its own model as
    # "provider:model": "local:<model>" is the school's model server (Ollama, vLLM… on a DGX Spark
    # or a cloud server), "openrouter:<model>" is OpenRouter. Agents never share a model setting:
    # an empty one makes that agent unavailable and its routes answer agent_unavailable.
    local_llm_url: str = "http://127.0.0.1:11434/v1"
    local_llm_api_key: SecretStr = SecretStr("")
    openrouter_url: str = "https://openrouter.ai/api/v1"
    # One OpenRouter account for everything that uses it: the voice-note transcription always,
    # and any agent whose model is "openrouter:...". A school running only local models needs it
    # for transcription alone.
    openrouter_api_key: SecretStr = SecretStr("")

    planning_agent_model: str = ""
    redaction_agent_model: str = ""
    conclusions_agent_model: str = ""
    # Sent to each agent's model only when set. "none" stops a model that reasons first (gemma4,
    # qwen3) from spending its token budget on hidden reasoning.
    planning_agent_reasoning_effort: str = ""
    redaction_agent_reasoning_effort: str = ""
    conclusions_agent_reasoning_effort: str = ""
    # One model call (AGENT_TIMEOUT) and a whole generation, repair round included
    # (AGENT_DEADLINE). A slow local model needs both raised.
    agent_timeout: Duration = 90.0
    agent_deadline: Duration = 300.0

    session_cookie_name: str = "mawta_session"
    # Fails closed: Secure unless a dev .env turns it off.
    session_cookie_secure: bool = True
    session_ttl: Duration = 720 * 3600.0
    session_idle_timeout: Duration = 336 * 3600.0
    login_max_failures: int = 8
    login_lockout: Duration = 15 * 60.0
    bcrypt_cost: int = 12

    # The director chat. Its model is "provider:model" like the agents'; empty makes the chat
    # unavailable (its routes answer chat_unavailable) without stopping the rest of the app.
    chat_model: str = ""
    chat_reasoning_effort: str = ""
    chat_max_tokens: int = 16000
    # Model calls per question (each tool round is one more call).
    chat_max_model_calls: int = 6
    # Questions answered at the same time; one more answers chat_busy. The chat shares this
    # process with the whole app, so it must not take all its memory.
    chat_max_concurrent: int = 3
    # LangGraph's checkpoints: this same database as mawta_langgraph, in schema langgraph
    # (options=-c search_path=langgraph). Needed only when the chat has a model.
    langgraph_database_url: str = ""
    # Traces in Langfuse (D006): the host and both keys, or nothing is sent.
    langfuse_host: str = ""
    langfuse_public_key: SecretStr = SecretStr("")
    langfuse_secret_key: SecretStr = SecretStr("")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [p.strip() for p in value.split(",") if p.strip()]
        return value

    @field_validator(
        "planning_agent_reasoning_effort",
        "redaction_agent_reasoning_effort",
        "conclusions_agent_reasoning_effort",
        "chat_reasoning_effort",
    )
    @classmethod
    def _reasoning_effort(cls, value: str) -> str:
        if value not in REASONING_EFFORTS:
            raise ValueError(f"must be one of {REASONING_EFFORTS[1:]} or empty")
        return value

    @field_validator(
        "planning_agent_model", "redaction_agent_model", "conclusions_agent_model", "chat_model"
    )
    @classmethod
    def _provider_model(cls, value: str) -> str:
        if value.strip():
            parse(value)  # raises with a message naming the expected format
        return value.strip()

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.chat_model and not self.langgraph_database_url:
            raise ValueError("CHAT_MODEL needs LANGGRAPH_DATABASE_URL (the chat's memory)")
        if self.chat_max_concurrent < 1:
            raise ValueError("CHAT_MAX_CONCURRENT must be at least 1")
        if self.session_cookie_secure and "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS may not contain '*' when SESSION_COOKIE_SECURE is true")
        return self

    # --- derived helpers -------------------------------------------------

    @property
    def host_port(self) -> tuple[str, int]:
        host, _, port = self.http_addr.rpartition(":")
        return (host or "0.0.0.0", int(port))

    def agent_model(self, agent: str) -> ModelRef | None:
        """The model of one agent ("planning", "redaction", "conclusions"), or None when it has
        none."""
        value: str = getattr(self, f"{agent}_agent_model")
        return parse(value) if value else None

    def agent_ready(self, agent: str) -> bool:
        """The agent has a model and its provider has what it needs (an address for the local
        server, a key for OpenRouter)."""
        ref = self.agent_model(agent)
        return ref is not None and configured(ref, self.endpoints())

    def chat_model_ref(self) -> ModelRef | None:
        return parse(self.chat_model) if self.chat_model else None

    def chat_ready(self) -> bool:
        """The chat has a model and its provider has what it needs."""
        ref = self.chat_model_ref()
        return ref is not None and configured(ref, self.endpoints())

    def agent_reasoning_effort(self, agent: str) -> str:
        return getattr(self, f"{agent}_agent_reasoning_effort")

    def langfuse_ready(self) -> bool:
        """Traces are sent only with LANGFUSE_HOST and both keys."""
        return bool(
            self.langfuse_host
            and self.langfuse_public_key.get_secret_value()
            and self.langfuse_secret_key.get_secret_value()
        )

    def endpoints(self) -> Endpoints:
        return Endpoints(
            local_url=self.local_llm_url,
            local_api_key=self.local_llm_api_key.get_secret_value(),
            openrouter_url=self.openrouter_url,
            openrouter_api_key=self.openrouter_api_key.get_secret_value(),
        )


_ = Field  # re-exported for subclasses in tests
