import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_NAME=From dotenv\nDATABASE_TIMEOUT_SECONDS=3\n", encoding="utf-8"
    )
    monkeypatch.setenv("APP_NAME", "From environment")
    settings = Settings(_env_file=env_file)

    assert settings.app_name == "From environment"
    assert settings.database_timeout_seconds == 3


@pytest.mark.parametrize("value", ["not-a-url", "sqlite:///test.db", "postgresql+psycopg://localhost"])
def test_invalid_database_url_is_rejected(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=value)


@pytest.mark.parametrize("value", [0, 61])
def test_database_timeout_is_bounded(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_timeout_seconds=value)


def test_database_credentials_are_not_in_settings_repr():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://reader:private-password@localhost/library_app",
    )
    assert "private-password" not in repr(settings)


def production(**overrides):
    options = dict(_env_file=None, app_env="production",
                   database_url="postgresql+psycopg://app:long-random-db-password@db/library_app",
                   allowed_hosts=["library.example.com", "api"], admin_token="", github_use_git_credentials=False)
    return Settings(**{**options, **overrides})


def test_production_always_requires_login():
    assert production(auth_required=False).auth_enabled


@pytest.mark.parametrize("overrides", [{"debug": True}, {"admin_token": "bypass"},
    {"github_use_git_credentials": True}, {"allowed_hosts": ["*"]}, {"allowed_hosts": []},
    {"database_url": "postgresql+psycopg://app@db/library_app"},
    {"database_url": "postgresql+psycopg://app:postgres@db/library_app"}])
def test_unsafe_production_settings_are_rejected(overrides):
    with pytest.raises(ValidationError):
        production(**overrides)
