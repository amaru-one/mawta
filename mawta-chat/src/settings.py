"""Runtime configuration, read from the environment (and .env in development)."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The mawta database, as the mawta_chat role: reads chat_api, writes chat.
    chat_database_url: str
    # The langgraph database, owned by LangGraph (checkpoints only).
    langgraph_database_url: str
    # {"kid": "<base64 Ed25519 public key>"} — the keys mawta-server signs the
    # director's chat token with (chat-director D002).
    chat_token_public_keys: dict[str, str]
    anthropic_api_key: SecretStr

    chat_model: str = "claude-sonnet-5-5"
    chat_effort: str = "medium"
    chat_max_tokens: int = 16000
    # Model calls per question (each tool round is one more call).
    chat_max_model_calls: int = 6
