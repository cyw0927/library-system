"""Build/run a DISPOSABLE localhost-only TLS production stack in GitHub CI."""
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, HTTPSHandler, ProxyHandler, build_opener
from uuid import uuid4


def main():
    if os.getenv("GITHUB_ACTIONS") != "true":
        raise SystemExit("CI-only: never runs against a user's production stack")
    root = Path(__file__).resolve().parents[1]
    runtime = root / "work" / ("ci-production-" + uuid4().hex)
    runtime.mkdir(parents=True, mode=0o700)
    project = "library-ci-" + uuid4().hex[:12]
    password = secrets.token_urlsafe(24)
    ui_password = secrets.token_urlsafe(24)
    names = {"postgres_password": password,
             "database_url": f"postgresql+psycopg://library_app:{quote(password)}@db:5432/library_operations_test",
             "github_token": "", "streamlit_cookie_secret": secrets.token_urlsafe(48)}
    for name, value in names.items():
        path = runtime / name
        path.write_text(value, encoding="utf-8")
        path.chmod(0o444)  # Parent stays 0700; bind-mounted individual files are readable by service UID.
    cert, key = runtime / "fullchain.pem", runtime / "privkey.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
                    "-keyout", str(key), "-out", str(cert)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cert.chmod(0o444)
    key.chmod(0o444)
    overrides = dict(services={"db": {"environment": {"POSTGRES_DB": "library_operations_test"}},
                               "frontend": {"environment": {"CI": "true"}}},
                     secrets={name: {"file": str(runtime / name)} for name in names})
    overrides["secrets"].update(tls_certificate={"file": str(cert)}, tls_private_key={"file": str(key)})
    override_path = runtime / "override.json"
    override_path.write_text(json.dumps(overrides), encoding="utf-8")
    compose = ["docker", "compose", "-p", project, "-f", str(root / "compose.production.yaml"), "-f", str(override_path)]
    env = {**os.environ, "PUBLIC_HOST": "localhost"}

    def run(args, input_text=None, capture=False):
        result = subprocess.run(compose + args, input=input_text, text=True, env=env,
                                stdout=subprocess.PIPE if capture else None, check=True, timeout=900)
        return result.stdout if capture else None

    context = ssl.create_default_context(cafile=str(cert))
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))

    def http(path, method="GET", body=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request("https://localhost:8443" + path, method=method, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        try:
            response = opener.open(request, timeout=10)
        except HTTPError as exc:
            response = exc
        content = response.read()
        try:
            parsed = json.loads(content) if content else None
        except ValueError:
            parsed = content.decode("utf-8")
        return response.status, parsed

    try:
        run(["config", "--quiet"])
        run(["build"])
        run(["up", "-d", "--wait", "--wait-timeout", "180"])
        run(["exec", "-T", "proxy", "nginx", "-t"])
        last_error = "no response"
        for _ in range(30):
            try:
                status, health = http("/api/health/db")
                if status == 200:
                    break
                last_error = f"HTTP {status}: {health}"
            except (URLError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(1)
        else:
            raise AssertionError("TLS proxy readiness failed: " + last_error)
        assert http("/")[0] == 200
        assert http("/api/books")[0] == 401
        assert http("/api/docs")[0] == 404
        for name, role in [("ci-admin", "admin"), ("ci-reader", "reader"), ("ci-other", "reader")]:
            run(["exec", "-T", "api", "python", "-m", "scripts.accounts", "create", name,
                 "--role", role, "--password-stdin"], input_text=ui_password + "\n")
        # Fixture is injected ONLY into a database with the explicit disposable name.
        fixture = """from app.db.session import get_session_factory
from app.core.config import get_settings
from sqlalchemy.engine import make_url
from app.db.models import Book,Chapter,Paragraph
assert make_url(get_settings().database_url).database == 'library_operations_test'
with get_session_factory()() as db:
    book=Book(slug='ci-fixture',title='CI fixture',github_path='CI')
    chapter=Chapter(book=book,title='CI chapter',github_path='CI/01.md',github_sha='a'*40,source_commit='a'*40,markdown_content='# CI chapter\\n\\nTest paragraph.',paragraph_count=1)
    paragraph=Paragraph(chapter=chapter,paragraph_number=1,markdown_content='Test paragraph.',plain_text='Test paragraph.',char_count=15)
    db.add(paragraph)
    db.commit()
"""
        run(["exec", "-T", "api", "python", "-c", fixture])
        run(["exec", "-T", "api", "python", "-m", "scripts.enable_pgvector"])
        tokens = {}
        for name in ["ci-admin", "ci-reader", "ci-other"]:
            status, result = http("/api/auth/login", "POST", {"username": name, "password": ui_password})
            assert status == 200
            tokens[name] = result["access_token"]
        reader, other = tokens["ci-reader"], tokens["ci-other"]
        status, chapters = http("/api/chapters", token=reader)
        assert status == 200
        cid = chapters[0]["id"]
        status, note = http("/api/bookmarks", "POST", {"chapter_id": cid, "note": "CI private note"}, reader)
        assert status == 201
        assert http("/api/bookmarks", token=other) == (200, [])
        assert http(f'/api/bookmarks/{note["id"]}', "PATCH", {"note": "attack"}, other)[0] == 404
        assert http("/api/sync/github", "POST", {}, reader)[0] == 403
        assert http("/api/auth/logout", "POST", {}, other)[0] == 204
        assert http("/api/books", token=other)[0] == 401
        for name, role in [("ci-admin", "admin"), ("ci-reader", "reader")]:
            run(["exec", "-T", "frontend", "python", "-m", "scripts.smoke_authenticated",
                 "--username", name, "--role", role], input_text=ui_password + "\n")
        run(["exec", "-T", "api", "python", "-m", "scripts.backup", "create", "/tmp/ci.dump"])
        run(["exec", "-T", "db", "psql", "-U", "library_app", "-d", "library_operations_test", "-v", "ON_ERROR_STOP=1",
             "-c", "CREATE DATABASE library_restore_test OWNER library_app;"])
        target_url = f"postgresql+psycopg://library_app:{quote(password)}@db:5432/library_restore_test"
        restore_code = "from scripts.backup import restore; from app.core.config import get_settings; import sys; restore(get_settings().database_url, sys.stdin.readline().strip(), '/tmp/ci.dump', confirmed=True); print('Real production-container backup/restore passed')"
        run(["exec", "-T", "api", "python", "-c", restore_code], input_text=target_url + "\n")
        result = run(["exec", "-T", "db", "psql", "-U", "library_app", "-d", "library_restore_test", "-At",
                      "-c", "SELECT (SELECT count(*) FROM bookmarks), (SELECT count(*) FROM accounts), (SELECT count(*) FROM login_sessions);"], capture=True)
        assert result.strip() == "1|3|0"
        print("Production smoke passed: non-root image, secret mounts, migrations, TLS, API isolation, 19 authenticated UI pages, pgvector, backup/restore")
    except BaseException:
        run(["logs", "--tail", "80", "api", "proxy", "frontend", "migrate"])
        raise
    finally:
        # Only our unique CI project/volume. Never removes a user's production volume.
        assert project.startswith("library-ci-") and os.getenv("GITHUB_ACTIONS") == "true"
        run(["down", "--volumes", "--remove-orphans"])


if __name__ == "__main__":
    main()
