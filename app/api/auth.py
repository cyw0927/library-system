import secrets
import time
from collections import deque
from datetime import timedelta
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.dependencies import DB, Identity, authenticated
from app.core.config import get_settings
from app.core.security import PASSWORD_SLOTS, aware, token_hash, username, utcnow, verify_password
from app.db.models import Account, LoginSession

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginLimiter:
    """Bound all login attempts, including nonexistent names and Streamlit calls.

    Socket peer only: untrusted X-Forwarded-For can never bypass this budget.
    Account lockout is persisted separately; this small budget is per process.
    """
    def __init__(self):
        self.lock = Lock()
        self.peers = {}
        self.global_attempts = deque()

    def allow(self, peer):
        now = time.monotonic()
        with self.lock:
            for key in list(self.peers):
                queue = self.peers[key]
                while queue and queue[0] <= now - 60:
                    queue.popleft()
                if not queue:
                    del self.peers[key]
            while self.global_attempts and self.global_attempts[0] <= now - 60:
                self.global_attempts.popleft()
            queue = self.peers.get(peer)
            if len(self.global_attempts) >= 120 or (queue is not None and len(queue) >= 20):
                return False
            if queue is None:
                if len(self.peers) >= 512:
                    return False
                queue = self.peers[peer] = deque()
            queue.append(now)
            self.global_attempts.append(now)
            return True


login_limiter = LoginLimiter()


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=128, repr=False)


@router.post("/login")
def login(body: Credentials, db: DB, response: Response, request: Request):
    if not login_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(429, "Too many login attempts; retry later", headers={"Retry-After": "60"})
    if not PASSWORD_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Login temporarily busy; retry later", headers={"Retry-After": "5"})
    try:
        try:
            name = username(body.username)
        except ValueError:
            name = "local"  # Reserved, never a login-capable account.
        account = db.scalar(select(Account).where(Account.username == name).with_for_update())
        now = utcnow()
        locked = bool(account and account.locked_until and aware(account.locked_until) > now)
        valid = verify_password(body.password, account.password_hash if account else "disabled")
        if not account or not account.is_active or locked or not valid:
            if account and account.is_active and not locked:
                if account.locked_until:
                    account.failed_attempts = 0
                    account.locked_until = None
                account.failed_attempts += 1
                if account.failed_attempts >= 5:
                    account.locked_until = now + timedelta(minutes=15)
                db.commit()
            raise HTTPException(401, "Invalid credentials or account temporarily unavailable")
        account.failed_attempts, account.locked_until = 0, None
        # Prune only expired/revoked sessions, never other active users' sessions.
        db.execute(delete(LoginSession).where((LoginSession.expires_at <= now) | LoginSession.revoked))
        token = secrets.token_urlsafe(32)
        expires = now + timedelta(hours=get_settings().session_hours)
        db.add(LoginSession(token_hash=token_hash(token), user_id=account.id, expires_at=expires))
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return dict(access_token=token, token_type="bearer", expires_at=expires,
                    user=dict(id=account.id, username=account.username, role=account.role))
    finally:
        PASSWORD_SLOTS.release()


@router.get("/me")
def me(identity: Annotated[Identity, Depends(authenticated)]):
    return dict(id=identity.id, username=identity.username, role=identity.role)


@router.post("/logout", status_code=204)
def logout(db: DB, identity: Annotated[Identity, Depends(authenticated)],
           authorization: Annotated[str, Header()]):
    session = db.get(LoginSession, token_hash(authorization.partition(" ")[2]))
    session.revoked = True
    db.commit()
