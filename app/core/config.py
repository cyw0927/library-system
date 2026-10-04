from functools import lru_cache
import os
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    app_name: str = "Library App API"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/library_app",
        repr=False,
    )
    database_timeout_seconds: int = Field(default=5, ge=1, le=60)
    github_repository: str = "cyw0927/library"
    github_branch: str = "main"
    github_token: str = Field(default="", repr=False)
    github_cache_dir: str = ""
    github_use_git_credentials: bool = False
    admin_token: str = Field(default="", repr=False)
    auth_required: bool = False
    session_hours: int = Field(default=8, ge=1, le=24)
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "testserver"])
    openai_api_key: str = Field(default="", repr=False)
    paid_ai_enabled: bool = False
    openai_model: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    rag_max_sources: int = Field(default=8, ge=5, le=15)
    rag_vector_scan_limit: int = Field(default=5000, ge=100, le=50000)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        try:
            url = make_url(value)
        except ArgumentError as exc:
            raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from exc
        if url.drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use postgresql+psycopg")
        if not url.database:
            raise ValueError("DATABASE_URL must include a database name")
        return value

    @property
    def auth_enabled(self) -> bool:
        return self.auth_required or self.app_env == "production"

    @model_validator(mode="after")
    def production_safety(self):
        if self.app_env == "production":
            url = make_url(self.database_url)
            if self.debug or self.admin_token or self.github_use_git_credentials:
                raise ValueError("Production forbids DEBUG, legacy ADMIN_TOKEN and Git credential fallback")
            if not url.password or len(url.password) < 16 or url.password.lower() in {"replace-with-a-strong-password"}:
                raise ValueError("Production requires a database password of at least 16 characters")
            if not self.allowed_hosts or any(host in {"*", "testserver"} for host in self.allowed_hosts):
                raise ValueError("Production requires explicit ALLOWED_HOSTS without * or testserver")
        return self


@lru_cache
def get_settings() -> Settings:
    # Container secrets are mounted files; no key/DB URL needs to enter image layers.
    return Settings(_secrets_dir=os.getenv("LIBRARY_SECRETS_DIR") or None)
