"""Runtime configuration, read from the environment (and .env in development).

Same variable names as the former server. An empty variable counts as unset.
A value that cannot be parsed fails at boot instead of silently using the
default.
"""

import base64
import re
from typing import Annotated, Any, ClassVar

from pydantic import BeforeValidator, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from agent.llm.providers import REASONING_EFFORTS, Endpoints, ModelRef, parse

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


class AgentPrices(BaseSettings):
    """One agent model's prices in US dollars per million tokens."""

    input_per_mtok: float = 0
    output_per_mtok: float = 0
    cache_read_per_mtok: float = 0
    cache_write_per_mtok: float = 0


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True, populate_by_name=True
    )

    database_url: str
    # Connects as a role with DDL rights or the pre-tenant bypass `useradd` needs.
    admin_database_url: str = ""
    http_addr: str = ":8080"
    worker_enabled: bool = True
    worker_concurrency: int = 2
    worker_queue: str = "default"
    storage_dir: str = "./data/audio"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    log_level: str = "info"
    request_body_capture: bool = False

    transcribe_openrouter_api_key: str = ""
    transcribe_model: str = "openai/whisper-large-v3"

    # Where the agents' models run (see agent/llm/providers.py). Each agent names its model as
    # "provider:model", e.g. "ollama:gemma4:12b-it-qat" or "openrouter:qwen/qwen3-30b-a3b".
    # Empty: that agent is unavailable and its routes answer agent_unavailable.
    ollama_url: str = "http://127.0.0.1:11434/v1"
    ollama_api_key: SecretStr = SecretStr("")
    openrouter_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: SecretStr = SecretStr("")

    planning_agent_model: str = ""
    # One model call (AGENT_TIMEOUT) and a whole generation, repair round included
    # (AGENT_DEADLINE). A slow local model needs both raised.
    agent_timeout: Duration = 90.0
    agent_deadline: Duration = 300.0
    # Sent to the agents' models only when set. "none" stops a model that reasons first (gemma4,
    # qwen3) from spending its token budget on hidden reasoning.
    agent_reasoning_effort: str = ""
    agent_price_input_per_mtok: float = 0
    agent_price_output_per_mtok: float = 0
    agent_price_cache_read_per_mtok: float = 0
    agent_price_cache_write_per_mtok: float = 0

    conclusions_agent_model: str = ""
    conclusions_agent_price_input_per_mtok: float = 0
    conclusions_agent_price_output_per_mtok: float = 0
    conclusions_agent_price_cache_read_per_mtok: float = 0
    conclusions_agent_price_cache_write_per_mtok: float = 0

    session_cookie_name: str = "mawta_session"
    # Fails closed: Secure unless a dev .env turns it off.
    session_cookie_secure: bool = True
    session_ttl: Duration = 720 * 3600.0
    session_idle_timeout: Duration = 336 * 3600.0
    login_max_failures: int = 8
    login_lockout: Duration = 15 * 60.0
    bcrypt_cost: int = 12

    # base64 32-byte Ed25519 seed, made with `chatkey`. Empty: the route
    # answers chat_unavailable. Set but invalid: refuse to boot.
    chat_token_signing_key: str = ""
    chat_token_key_id: str = ""
    chat_token_ttl: Duration = 3600.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [p.strip() for p in value.split(",") if p.strip()]
        return value

    @field_validator(
        "agent_price_input_per_mtok",
        "agent_price_output_per_mtok",
        "agent_price_cache_read_per_mtok",
        "agent_price_cache_write_per_mtok",
        "conclusions_agent_price_input_per_mtok",
        "conclusions_agent_price_output_per_mtok",
        "conclusions_agent_price_cache_read_per_mtok",
        "conclusions_agent_price_cache_write_per_mtok",
    )
    @classmethod
    def _non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("price must not be negative")
        return value

    @field_validator("agent_reasoning_effort")
    @classmethod
    def _reasoning_effort(cls, value: str) -> str:
        if value not in REASONING_EFFORTS:
            raise ValueError(f"must be one of {REASONING_EFFORTS[1:]} or empty")
        return value

    @field_validator("planning_agent_model", "conclusions_agent_model")
    @classmethod
    def _provider_model(cls, value: str) -> str:
        if value.strip():
            parse(value)  # raises with a message naming the expected format
        return value.strip()

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.chat_token_signing_key:
            try:
                seed = base64.b64decode(self.chat_token_signing_key, validate=True)
            except ValueError as exc:
                raise ValueError("CHAT_TOKEN_SIGNING_KEY is not valid base64") from exc
            if len(seed) != 32:
                raise ValueError("CHAT_TOKEN_SIGNING_KEY must be a 32-byte Ed25519 seed")
            if not self.chat_token_key_id:
                raise ValueError("CHAT_TOKEN_KEY_ID is required with CHAT_TOKEN_SIGNING_KEY")
            if self.chat_token_ttl <= 0:
                raise ValueError("CHAT_TOKEN_TTL must be positive")
        if self.session_cookie_secure and "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS may not contain '*' when SESSION_COOKIE_SECURE is true")
        return self

    # --- derived helpers -------------------------------------------------

    @property
    def host_port(self) -> tuple[str, int]:
        host, _, port = self.http_addr.rpartition(":")
        return (host or "0.0.0.0", int(port))

    def agent_model(self, which: str) -> ModelRef | None:
        """The model of "planning" or "conclusions", or None when that agent has none."""
        value = self.planning_agent_model if which == "planning" else self.conclusions_agent_model
        return parse(value) if value else None

    def endpoints(self) -> Endpoints:
        return Endpoints(
            ollama_url=self.ollama_url,
            ollama_api_key=self.ollama_api_key.get_secret_value(),
            openrouter_url=self.openrouter_url,
            openrouter_api_key=self.openrouter_api_key.get_secret_value(),
        )

    def prices(self, which: str) -> AgentPrices:
        """Prices for "planning" or "conclusions"."""
        prefix = "agent" if which == "planning" else which + "_agent"
        return AgentPrices(
            input_per_mtok=getattr(self, f"{prefix}_price_input_per_mtok"),
            output_per_mtok=getattr(self, f"{prefix}_price_output_per_mtok"),
            cache_read_per_mtok=getattr(self, f"{prefix}_price_cache_read_per_mtok"),
            cache_write_per_mtok=getattr(self, f"{prefix}_price_cache_write_per_mtok"),
        )


_ = Field  # re-exported for subclasses in tests
