from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password, token_hash, utcnow, verify_password
from app.db.models import Account, LoginSession
from app.db.session import get_db
from app.main import app
from scripts.accounts import change_password, claim_local, create_account, deactivate
from tests.test_library_api import seed

PASSWORD = "a-long-test-password-2026"


@pytest.fixture(scope="module")
def encoded():
    return hash_password(PASSWORD)


@pytest.fixture
def auth(client, monkeypatch, encoded):
    from app.api.auth import LoginLimiter
    monkeypatch.setattr("app.api.auth.login_limiter", LoginLimiter())
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "legacy-must-not-bypass")
    get_settings.cache_clear()
    with next(app.dependency_overrides[get_db]()) as db:
        db.add_all([Account(id="alice-id", username="alice", password_hash=encoded, role="reader"),
                    Account(id="bob-id", username="bob", password_hash=encoded, role="reader"),
                    Account(id="admin-id", username="admin", password_hash=encoded, role="admin")])
        db.commit()
    try:
        yield client
    finally:
        get_settings.cache_clear()


def login(client, username="alice"):
    response = client.post("/auth/login", json=dict(username=username, password=PASSWORD))
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.mark.parametrize("path", ["/books", "/volumes", "/chapters", "/search?q=test", "/terms",
                                  "/qa/issues", "/analysis/overview", "/sync/status", "/rag/status",
                                  "/reading/progress", "/bookmarks"])
def test_originals_and_private_data_require_login(auth, path):
    assert auth.get(path).status_code == 401
    assert auth.get(path, headers={"X-Admin-Token": "legacy-must-not-bypass"}).status_code == 401
    assert auth.get(path, headers={"Authorization": "Bearer not-a-valid-session"}).status_code == 401
    assert auth.get("/health").status_code == 200


def test_passwords_and_sessions_are_hashed_and_revocable(auth, encoded):
    headers = login(auth)
    raw_token = headers["Authorization"].split()[1]
    assert auth.get("/auth/me", headers=headers).json()["username"] == "alice"
    with next(app.dependency_overrides[get_db]()) as db:
        account = db.get(Account, "alice-id")
        assert account.password_hash == encoded and PASSWORD not in account.password_hash
        session = db.get(LoginSession, token_hash(raw_token))
        assert session and session.token_hash != raw_token
    response = auth.post("/auth/logout", headers=headers)
    assert response.status_code == 204 and response.headers["cache-control"] == "no-store"
    assert auth.get("/books", headers=headers).status_code == 401


def test_expiry_and_disabled_accounts_reject_existing_sessions(auth):
    headers = login(auth)
    with next(app.dependency_overrides[get_db]()) as db:
        session = db.scalar(select(LoginSession).where(LoginSession.user_id == "alice-id"))
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert auth.get("/auth/me", headers=headers).status_code == 401
    headers = login(auth)
    with next(app.dependency_overrides[get_db]()) as db:
        deactivate(db, db.get(Account, "alice-id"))
        db.commit()
    assert auth.get("/books", headers=headers).status_code == 401
    assert auth.post("/auth/login", json=dict(username="alice", password=PASSWORD)).status_code == 401


def test_account_lockout_is_persistent_and_generic(auth):
    for name in ["unknown", "alice", "alice", "alice", "alice", "alice"]:
        response = auth.post("/auth/login", json=dict(username=name, password="wrong"))
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials or account temporarily unavailable"
    assert auth.post("/auth/login", json=dict(username="alice", password=PASSWORD)).status_code == 401
    with next(app.dependency_overrides[get_db]()) as db:
        account = db.get(Account, "alice-id")
        assert account.failed_attempts == 5 and account.locked_until
        account.locked_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert auth.post("/auth/login", json=dict(username="ALICE", password=PASSWORD)).status_code == 200


def test_other_users_cannot_see_edit_delete_personal_records(auth):
    seed(auth)
    alice, bob, admin = login(auth), login(auth, "bob"), login(auth, "admin")
    cid = auth.get("/chapters", headers=alice).json()[0]["id"]
    position = dict(chapter_id=cid, paragraph_number=1, completed=True)
    assert auth.put("/reading/progress", json=position, headers=alice).status_code == 200
    assert auth.get("/reading/progress", headers=bob).json() == []
    created = auth.post("/bookmarks", json={"chapter_id": cid, "note": "private alice"}, headers=alice)
    bid = created.json()["id"]
    for other in [bob, admin]:
        assert auth.get("/bookmarks", headers=other).json() == []
        assert auth.patch(f"/bookmarks/{bid}", headers=other, json={"note": "attack"}).status_code == 404
        assert auth.delete(f"/bookmarks/{bid}", headers=other).status_code == 404
    assert auth.get("/bookmarks", headers=alice).json()[0]["note"] == "private alice"
    assert auth.post("/bookmarks", headers=bob, json={"chapter_id": cid, "user_id": "alice-id"}).json()["user_id"] == "bob-id"


@pytest.mark.parametrize("method,path,body", [("POST", "/sync/github", {}), ("POST", "/qa/run", {}),
    ("POST", "/terms", {"canonical": "용어"}), ("POST", "/rag/index", {}),
    ("POST", "/ask", {"question": "some question", "mode": "openai"})])
def test_readers_cannot_change_shared_data_or_spend_money(auth, method, path, body):
    assert auth.request(method, path, headers=login(auth), json=body).status_code == 403


def test_admin_can_manage_terms_but_not_bypass_ownership(auth):
    assert auth.post("/terms", headers=login(auth, "admin"), json={"canonical": "표준어"}).status_code == 201


def test_password_change_revokes_all_sessions_and_last_admin_is_preserved(auth):
    headers = login(auth)
    with next(app.dependency_overrides[get_db]()) as db:
        change_password(db, db.get(Account, "alice-id"), "new-password-2026-okay")
        with pytest.raises(ValueError, match="last active"):
            deactivate(db, db.get(Account, "admin-id"))
        db.commit()
    assert auth.get("/auth/me", headers=headers).status_code == 401


def test_login_validation_does_not_echo_password(auth):
    password = "private-too-long" * 20
    response = auth.post("/auth/login", json={"username": "alice", "password": password})
    assert response.status_code == 422 and password not in response.text


def test_explicit_legacy_record_transfer_preserves_notes(auth):
    seed(auth)
    from app.db.models import Bookmark, Chapter
    with next(app.dependency_overrides[get_db]()) as db:
        chapter = db.scalar(select(Chapter))
        db.add(Bookmark(chapter_id=chapter.id, user_id="local", note="legacy note", source_sha=chapter.github_sha))
        db.commit()
        counts = claim_local(db, db.get(Account, "alice-id"))
        assert counts["bookmarks"] == 1
        db.commit()
    assert auth.get("/bookmarks", headers=login(auth)).json()[0]["note"] == "legacy note"


def test_scrypt_verification_and_password_limits(encoded):
    assert verify_password(PASSWORD, encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password(PASSWORD, "invalid")
    with pytest.raises(ValueError):
        hash_password("short")


def test_login_limit_is_not_bypassed_with_forwarded_headers(auth):
    from app.api.auth import login_limiter
    for _ in range(20):
        assert login_limiter.allow("testclient")
    response = auth.post("/auth/login", headers={"X-Forwarded-For": "different-ip"},
                         json=dict(username="unknown", password=PASSWORD))
    assert response.status_code == 429 and response.headers["Retry-After"] == "60"
