from datetime import timedelta
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest
import yaml

from app.core.config import get_settings
from app.core.security import utcnow
from app.services.openai_provider import OpenAIProvider, ProviderError
from app.services.rag_service import ask, index_paragraphs
from scripts.backup import sha256
from scripts.backup_job import check_backups, create_backup
from scripts.deployment_check import check_compose, check_secret_directory, check_tls, check_live

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_paid_ai_disabled_even_with_key_model_and_injected_provider(monkeypatch):
    monkeypatch.setenv("PAID_AI_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key-not-real")
    monkeypatch.setenv("OPENAI_MODEL", "dummy-model")
    with patch("app.services.openai_provider.httpx.Client.post") as post:
        provider = OpenAIProvider("dummy-key", "dummy-model")
        try:
            with pytest.raises(ProviderError, match="disabled"):
                provider.embed(["text"])
            with pytest.raises(ProviderError, match="disabled"):
                provider.answer("question", [])
            post.assert_not_called()
        finally:
            provider.close()
    with pytest.raises(ProviderError, match="disabled"):
        ask(None, "question", mode="openai", client=object())
    with pytest.raises(ProviderError, match="disabled"):
        index_paragraphs(None, provider="openai", client=object())


def test_api_rejects_paid_requests_even_with_admin_confirmation(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("PAID_AI_ENABLED", "false")
    headers = {"X-Admin-Token": "test-token"}
    assert client.post("/ask", json={"question": "질문입니다", "mode": "openai"}, headers=headers).status_code == 403
    assert client.post("/rag/index", json={"provider": "openai", "confirm_cost": True}, headers=headers).status_code == 403
    assert not client.get("/rag/status", headers=headers).json()["paid_ai_enabled"]
    assert client.post("/ask", json={"question": "질문입니다"}, headers=headers).status_code == 200


def test_default_deployment_is_private_pinned_and_has_durable_backup():
    assert "OK" in check_compose(ROOT / "compose.production.yaml")
    config = yaml.safe_load((ROOT / "compose.production.yaml").read_text())
    assert config["services"]["backup"]["secrets"] == ["database_url"]
    assert config["services"]["backup"]["volumes"] == ["production_backups:/backups"]
    assert "@sha256:" in (ROOT / "Dockerfile").read_text().splitlines()[0]


@pytest.mark.parametrize("change", ["public-db", "public-proxy", "paid", "floating", "logs"])
def test_preflight_rejects_dangerous_compose_changes(tmp_path, change):
    config = yaml.safe_load((ROOT / "compose.production.yaml").read_text())
    services = config["services"]
    if change == "public-db":
        services["db"]["ports"] = ["5432:5432"]
    elif change == "public-proxy":
        services["proxy"]["ports"] = ["443:8443"]
    elif change == "paid":
        services["api"]["environment"]["PAID_AI_ENABLED"] = "true"
    elif change == "floating":
        services["proxy"]["image"] = "nginx:stable"
    else:
        services["db"]["logging"] = {}
    path = tmp_path / "compose.yaml"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError):
        check_compose(path)


def secrets(directory):
    directory.mkdir(mode=0o700)
    values = dict(postgres_password="owner-long-random-password", runtime_password="runtime-long-random-password",
                  database_url="postgresql+psycopg://library_runtime:runtime-long-random-password@db/library_app",
                  migration_database_url="postgresql+psycopg://library_owner:owner-long-random-password@db/library_app",
                  github_token="", streamlit_cookie_secret="random-cookie-secret-longer-than-32-chars")
    for name, value in values.items():
        (directory / name).write_text(value)
    return directory


def test_secret_consistency_and_missing_or_wrong_values(tmp_path):
    directory = secrets(tmp_path / "secrets")
    assert "consistent" in check_secret_directory(directory)
    (directory / "database_url").write_text("postgresql+psycopg://library_owner:owner-long-random-password@db/library_app")
    with pytest.raises(ValueError):
        check_secret_directory(directory)
    (directory / "github_token").unlink()
    with pytest.raises(ValueError):
        check_secret_directory(directory)


@pytest.mark.skipif(os.name == "nt", reason="Windows uses ACLs instead of Unix mode bits")
def test_shared_secret_directory_is_rejected(tmp_path):
    directory = secrets(tmp_path / "secrets")
    directory.chmod(0o755)
    with pytest.raises(ValueError, match="0700"):
        check_secret_directory(directory)


def certificate(directory, days=30):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "library.test")])
    now = utcnow()
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("library.test")]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert_path, key_path


def test_tls_checks_hostname_expiry_and_key_match(tmp_path):
    cert, key = certificate(tmp_path)
    assert "CA trust" in check_tls(cert, key, "library.test")
    with pytest.raises(ValueError, match="hostname"):
        check_tls(cert, key, "evil.test")
    cert, key = certificate(tmp_path, days=7)
    with pytest.raises(ValueError, match="expires"):
        check_tls(cert, key, "library.test")
    cert, key = certificate(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _, other_key = certificate(other)
    with pytest.raises(ValueError, match="mismatch"):
        check_tls(cert, other_key, "library.test")


@pytest.mark.skipif(os.name == "nt", reason="Windows uses ACLs instead of Unix mode bits")
def test_shared_tls_key_directory_is_rejected(tmp_path):
    cert, key = certificate(tmp_path)
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError, match="0700"):
        check_tls(cert, key, "library.test")


@pytest.mark.parametrize("url", ["http://library.test", "https://user:secret@library.test", "https://library.test/path", "https://library.test?token=secret"])
def test_live_checks_reject_non_tls_or_secret_urls(url):
    with pytest.raises(ValueError):
        check_live(url)


def completed_backup(directory):
    path = directory / "library-test.dump"
    path.write_bytes(b"PGDMP-test")
    Path(str(path) + ".json").write_text(json.dumps(dict(format="pg_dump_custom", sha256=sha256(path))))
    return path


def test_backup_monitor_detects_missing_old_corrupt_and_disk_pressure(tmp_path):
    with pytest.raises(ValueError, match="No completed"):
        check_backups(tmp_path, min_free_mb=1)
    archive = completed_backup(tmp_path)
    assert check_backups(tmp_path, min_free_mb=1) == archive
    with patch("scripts.backup_job.shutil.disk_usage", return_value=SimpleNamespace(free=0)):
        with pytest.raises(ValueError, match="disk"):
            check_backups(tmp_path, min_free_mb=1)
    old = utcnow().timestamp() - 30 * 3600
    os.utime(archive, (old, old))
    with pytest.raises(ValueError, match="too old"):
        check_backups(tmp_path, min_free_mb=1)
    os.utime(archive, None)
    archive.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        check_backups(tmp_path, min_free_mb=1)
    assert archive.exists()  # Monitoring never removes files.


def test_backup_job_uses_unique_names_and_never_deletes_old_backup(tmp_path):
    old = completed_backup(tmp_path)
    def fake_backup(url, path, pg_bin):
        path.write_bytes(b"new-archive")
        Path(str(path) + ".json").write_text(json.dumps(dict(format="pg_dump_custom", sha256=sha256(path))))
        return path
    with patch("scripts.backup_job.backup", side_effect=fake_backup):
        first = create_backup(tmp_path, min_free_mb=1)
        second = create_backup(tmp_path, min_free_mb=1)
    assert first != second and first.exists() and second.exists() and old.exists()
