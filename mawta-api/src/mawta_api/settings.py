"""Runtime configuration, read from the environment (and .env in development).

Same variable names as the former server. An empty variable counts as unset.
A value that cannot be parsed fails at boot instead of silently using the
default.
"""

import base64
import re
from typing import Annotated, Any

from pydantic import BeforeValidator, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    model_config = SettingsConfigDict(
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

    anthropic_api_key: SecretStr = SecretStr("")
    planning_agent_model: str = "claude-sonnet-5-5"
    agent_timeout: Duration = 90.0
    agent_price_input_per_mtok: float = 0
    agent_price_output_per_mtok: float = 0
    agent_price_cache_read_per_mtok: float = 0
    agent_price_cache_write_per_mtok: float = 0

    redaction_agent_model: str = "claude-haiku-5-5"
    redaction_agent_price_input_per_mtok: float = 0
    redaction_agent_price_output_per_mtok: float = 0
    redaction_agent_price_cache_read_per_mtok: float = 0
    redaction_agent_price_cache_write_per_mtok: float = 0
    conclusions_agent_model: str = "claude-sonnet-5-5"
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
        "redaction_agent_price_input_per_mtok",
        "redaction_agent_price_output_per_mtok",
        "redaction_agent_price_cache_read_per_mtok",
        "redaction_agent_price_cache_write_per_mtok",
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

    def prices(self, which: str) -> AgentPrices:
        """Prices for "agent" (planning), "redaction" or "conclusions"."""
        prefix = "agent" if which == "planning" else which + "_agent"
        return AgentPrices(
            input_per_mtok=getattr(self, f"{prefix}_price_input_per_mtok"),
            output_per_mtok=getattr(self, f"{prefix}_price_output_per_mtok"),
            cache_read_per_mtok=getattr(self, f"{prefix}_price_cache_read_per_mtok"),
            cache_write_per_mtok=getattr(self, f"{prefix}_price_cache_write_per_mtok"),
        )


_ = Field  # re-exported for subclasses in tests
