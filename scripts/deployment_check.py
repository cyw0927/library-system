"""Read-only preflight. Never prints secrets, starts services or opens ports."""
import argparse
from datetime import timedelta
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
from urllib.request import ProxyHandler, build_opener

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from sqlalchemy.engine import make_url
import yaml

from app.core.config import Settings
from app.core.security import utcnow


def check_tls(cert_path, key_path, hostname):
    for path in (Path(cert_path), Path(key_path)):
        if path.is_symlink() or not path.is_file():
            raise ValueError("TLS files must be regular files")
    if os.name != "nt" and Path(key_path).parent.stat().st_mode & 0o077:
        raise ValueError("TLS private-key directory must have mode 0700 or stricter")
    cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    key = serialization.load_pem_private_key(Path(key_path).read_bytes(), password=None)
    public = lambda obj: obj.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if public(cert) != public(key):
        raise ValueError("TLS key mismatch")
    now = utcnow()
    if cert.not_valid_before_utc > now or cert.not_valid_after_utc < now + timedelta(days=14):
        raise ValueError("TLS certificate invalid or expires within 14 days")
    names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    try:
        address = ipaddress.ip_address(hostname)
        matched = address in names.get_values_for_type(x509.IPAddress)
    except ValueError:
        hostname = hostname.lower()
        matched = any(name.lower() == hostname or
                      (name.startswith("*.") and hostname.count(".") == name.count(".") and hostname.endswith(name[1:].lower()))
                      for name in names.get_values_for_type(x509.DNSName))
    if not matched:
        raise ValueError("TLS hostname mismatch")
    # Also let the actual TLS library validate PEM chain/key compatibility.
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert_path, key_path)
    return "TLS files valid; public CA trust still requires a live HTTPS check"


def check_secret_directory(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Secret directory must be a real protected directory")
    if os.name != "nt":
        # Individual bind-mounted files may be 0444; parent MUST block other users.
        if directory.stat().st_mode & 0o077:
            raise ValueError("Secret directory must have mode 0700 or stricter")
    values = {}
    for name in ("postgres_password", "migration_database_url", "runtime_password", "database_url", "github_token", "streamlit_cookie_secret"):
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("A required secret file is missing or unsafe")
        values[name] = path.read_text(encoding="utf-8").strip()
    if min(len(values[n]) for n in ("postgres_password", "runtime_password")) < 16:
        raise ValueError("DB secrets are too short")
    if values["postgres_password"] == values["runtime_password"]:
        raise ValueError("Owner and runtime secrets must differ")
    if len(values["streamlit_cookie_secret"]) < 32:
        raise ValueError("Cookie secret is too short")
    runtime, owner = [make_url(values[n]) for n in ("database_url", "migration_database_url")]
    for url, username, password in ((runtime, "library_runtime", values["runtime_password"]), (owner, "library_owner", values["postgres_password"])):
        if (url.drivername != "postgresql+psycopg" or url.username != username or url.password != password
                or url.host != "db" or (url.port or 5432) != 5432 or not url.database or url.query):
            raise ValueError("DB URL must match its isolated Compose role/password/host")
    if owner.database != runtime.database:
        raise ValueError("Owner/runtime database mismatch")
    # Explicit values and no dotenv/environment parsing for checks unrelated to process env.
    Settings(_env_file=None, app_env="production", database_url=values["database_url"],
             allowed_hosts=["api", "localhost", "127.0.0.1"], admin_token="",
             debug=False, github_use_git_credentials=False, paid_ai_enabled=False)
    return "Secrets consistent; Windows ACLs must be checked separately" if os.name == "nt" else "Secrets consistent and parent permissions restricted"


def check_compose(path):
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    services = config["services"]
    for name in ("db", "api", "frontend", "migrate", "backup"):
        if services[name].get("ports"):
            raise ValueError("Only the TLS proxy may publish ports")
    if services["proxy"]["ports"] != ["127.0.0.1:8443:8443"]:
        raise ValueError("Default TLS proxy must remain localhost-only")
    if services["api"]["environment"].get("PAID_AI_ENABLED") != "false":
        raise ValueError("Paid AI must stay disabled")
    for name in ("db", "proxy"):
        if not re.search(r"@sha256:[a-f0-9]{64}$", services[name]["image"]):
            raise ValueError("External images must be digest pinned")
    for service in services.values():
        if service.get("logging", {}).get("options") != {"max-size": "10m", "max-file": "3"}:
            raise ValueError("Container logs must have bounded rotation")
    if services["backup"].get("profiles") != ["operations"]:
        raise ValueError("Backup must be an explicit one-shot operation")
    return "Compose isolation, image pins, paid-AI off and log rotation OK"


def check_live(url):
    from urllib.error import HTTPError
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Use an HTTPS origin without credentials or path")
    opener = build_opener(ProxyHandler({}))  # Default CA/hostname verification; no bypass.
    for path, expected in (("/api/health/db", 200), ("/api/books", 401), ("/api/docs", 404)):
        try:
            response = opener.open(url.rstrip("/") + path, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            if response.status != expected or response.geturl() != url.rstrip("/") + path:
                raise ValueError("Live HTTPS status or redirect mismatch")
    return "Trusted live TLS, DB health and unauthenticated API isolation OK"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--host", required=True)
    parser.add_argument("--live-url")
    args = parser.parse_args()
    checks = [("compose", lambda: check_compose(args.root / "compose.production.yaml")),
              ("secrets", lambda: check_secret_directory(args.root / "deploy/secrets")),
              ("tls", lambda: check_tls(args.root / "deploy/tls/fullchain.pem", args.root / "deploy/tls/privkey.pem", args.host))]
    if args.live_url:
        checks.append(("live_https", lambda: check_live(args.live_url)))
    results = []
    for name, check in checks:
        try:
            results.append(dict(check=name, passed=True, detail=check()))
        except Exception:
            # Third-party parser exceptions may contain a complete DB URL or PEM.
            results.append(dict(check=name, passed=False, detail="Failed: check missing files, values, permissions or TLS validity; secrets are not displayed"))
    print(json.dumps(dict(passed=all(r["passed"] for r in results), checks=results,
                         public_deployment_performed=False), ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(r["passed"] for r in results) else 1)


if __name__ == "__main__":
    main()
