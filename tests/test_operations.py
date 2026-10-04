import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from scripts.backup import backup, pg_environment, restore, sha256, validate_restore_target


def test_production_hides_docs_rejects_wrong_host_and_always_requires_login(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://app:random-long-db-password@db/library_app")
    monkeypatch.setenv("ALLOWED_HOSTS", '["testserver"]')
    # testserver is deliberately forbidden in production; use a real-shaped explicit host.
    monkeypatch.setenv("ALLOWED_HOSTS", '["library.test"]')
    monkeypatch.setenv("ADMIN_TOKEN", "")
    monkeypatch.setenv("GITHUB_USE_GIT_CREDENTIALS", "false")
    get_settings.cache_clear()
    try:
        with TestClient(create_app(), base_url="http://library.test") as client:
            assert client.get("/health").status_code == 200
            assert client.get("/health", headers={"Host": "evil.invalid"}).status_code == 400
            for path in ("/docs", "/redoc", "/openapi.json"):
                assert client.get(path).status_code == 404
            response = client.get("/books")
            assert response.status_code == 401
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
    finally:
        get_settings.cache_clear()


def test_pg_credentials_are_not_in_command_arguments():
    env = pg_environment("postgresql+psycopg://user:secret%25password@localhost:55432/source?sslmode=require")
    assert env["PGPASSWORD"] == "secret%password" and env["PGSSLMODE"] == "require"
    assert env["PGDATABASE"] == "source" and env["PGPORT"] == "55432"


def test_backup_checksums_excludes_sessions_and_refuses_overwrite(tmp_path):
    path = tmp_path / "archive.dump"
    def fake_dump(argv, **options):
        assert "--exclude-table-data=*.login_sessions" in argv
        assert "password" not in " ".join(argv)
        options["stdout"].write(b"PGDMP-test-data")
        return SimpleNamespace(returncode=0)
    with patch("scripts.backup.executable", return_value="pg_dump"), patch("scripts.backup.subprocess.run", side_effect=fake_dump):
        backup("postgresql+psycopg://user:password@localhost/source", path)
        metadata = json.loads(Path(str(path) + ".json").read_text())
        assert metadata["sha256"] == sha256(path) and metadata["sessions_excluded"]
        with pytest.raises(ValueError, match="already exists"):
            backup("postgresql+psycopg://user:password@localhost/source", path)
    assert path.read_bytes() == b"PGDMP-test-data"


def test_failed_dump_removes_only_its_own_partial_archive(tmp_path):
    path = tmp_path / "new.dump"
    with patch("scripts.backup.executable", return_value="pg_dump"), patch("scripts.backup.subprocess.run", return_value=SimpleNamespace(returncode=1)):
        with pytest.raises(ValueError, match="pg_dump failed"):
            backup("postgresql+psycopg://user@localhost/source", path)
    assert not path.exists()


def test_restore_requires_confirmation_checksum_and_different_database(tmp_path):
    with pytest.raises(ValueError, match="confirm-empty"):
        restore("postgresql+psycopg://user@localhost/source", "", "none")
    with pytest.raises(ValueError, match="different name"):
        validate_restore_target("postgresql+psycopg://user@localhost/source", "postgresql+psycopg://user@other/source")
    path = tmp_path / "untrusted.dump"
    path.write_bytes(b"bad")
    Path(str(path) + ".json").write_text(json.dumps({"sha256": "wrong", "format": "pg_dump_custom"}))
    with pytest.raises(ValueError, match="checksum"):
        restore("postgresql+psycopg://user@localhost/source", "postgresql+psycopg://user@localhost/target", path, confirmed=True)


def test_file_secrets_are_supported_without_exposing_them(tmp_path, monkeypatch):
    (tmp_path / "github_token").write_text("private-file-token")
    monkeypatch.setenv("LIBRARY_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().github_token == "private-file-token"
        assert "private-file-token" not in repr(get_settings())
    finally:
        get_settings.cache_clear()
