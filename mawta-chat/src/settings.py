"""Runtime configuration, read from the environment (and .env in development)."""

from typing import ClassVar

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from providers import REASONING_EFFORTS, Endpoints, ModelRef, configured, parse


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_file=".env", extra="ignore")

    # The mawta database, as the mawta_chat role: reads chat_api, writes chat.
    chat_database_url: str
    # The langgraph database, owned by LangGraph (checkpoints only).
    langgraph_database_url: str
    # {"kid": "<base64 Ed25519 public key>"} — the keys mawta-server signs the
    # director's chat token with (chat-director D002).
    chat_token_public_keys: dict[str, str]
    # The chat's model as "provider:model", e.g. "local:gemma4:12b-it-qat" or
    # "openrouter:qwen/qwen3-30b-a3b" (see providers.py).
    chat_model: str

    # The school's own model server ("local"): Ollama on a laptop, Ollama or vLLM on a DGX Spark
    # or a cloud GPU server.
    local_llm_url: str = "http://127.0.0.1:11434/v1"
    local_llm_api_key: SecretStr = SecretStr("")
    openrouter_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: SecretStr = SecretStr("")

    chat_max_tokens: int = 16000
    # Sent to the model only when set; "none" stops a model that reasons first
    # (gemma4, qwen3) from spending its token budget on hidden reasoning.
    chat_reasoning_effort: str = ""
    # Model calls per question (each tool round is one more call).
    chat_max_model_calls: int = 6

    @field_validator("chat_reasoning_effort")
    @classmethod
    def _reasoning_effort(cls, value: str) -> str:
        if value not in REASONING_EFFORTS:
            raise ValueError(f"must be one of {REASONING_EFFORTS[1:]} or empty")
        return value

    @field_validator("chat_model")
    @classmethod
    def _provider_model(cls, value: str) -> str:
        parse(value)  # raises with a message naming the expected format
        return value.strip()

    @model_validator(mode="after")
    def _provider_ready(self) -> "Settings":
        if not configured(self.model_ref(), self.endpoints()):
            raise ValueError(f"CHAT_MODEL {self.chat_model} needs OPENROUTER_API_KEY")
        return self

    def model_ref(self) -> ModelRef:
        return parse(self.chat_model)

    def endpoints(self) -> Endpoints:
        return Endpoints(
            local_url=self.local_llm_url,
            local_api_key=self.local_llm_api_key.get_secret_value(),
            openrouter_url=self.openrouter_url,
            openrouter_api_key=self.openrouter_api_key.get_secret_value(),
        )
