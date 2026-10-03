from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    app_name: str = "Library App API"
    app_env: str = "development"
    debug: bool = False
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/library_app",
        repr=False,
    )
    database_timeout_seconds: int = Field(default=5, ge=1, le=60)

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
