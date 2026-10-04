import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.db.models import Account, LoginSession
from app.core.security import aware, token_hash, utcnow

DB = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True)
class Identity:
    id: str
    role: str
    username: str


def unauthorized():
    raise HTTPException(401, "Login required or session expired", headers={"WWW-Authenticate": "Bearer"})


def authenticated(db: DB, authorization: Annotated[str | None, Header()] = None):
    if not authorization:
        unauthorized()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.isascii() or not 40 <= len(token) <= 128:
        unauthorized()
    session = db.get(LoginSession, token_hash(token))
    if not session or session.revoked or aware(session.expires_at) <= utcnow():
        unauthorized()
    account = db.get(Account, session.user_id)
    if not account or not account.is_active:
        unauthorized()
    return Identity(account.id, account.role, account.username)


def require_reader(db: DB, authorization: Annotated[str | None, Header()] = None):
    if get_settings().auth_enabled or authorization:
        return authenticated(db, authorization)
    return None


def legacy_admin(x_admin_token):
    token = get_settings().admin_token
    if not token:
        raise HTTPException(503, "Set ADMIN_TOKEN to enable private and mutating endpoints")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, token):
        raise HTTPException(401, "An admin token is required")


def require_private(db: DB, authorization: Annotated[str | None, Header()] = None,
                    x_admin_token: Annotated[str | None, Header()] = None):
    if get_settings().auth_enabled or authorization:
        return authenticated(db, authorization)
    legacy_admin(x_admin_token)
    return Identity("local", "admin", "local")


def require_admin(identity: Annotated[Identity, Depends(require_private)]):
    if identity.role != "admin":
        raise HTTPException(403, "Administrator permission required")
    return identity


Admin = Depends(require_admin)
Reader = Depends(require_reader)
Private = Annotated[Identity, Depends(require_private)]


def columns(entity, exclude=()):
    return {column.key: getattr(entity, column.key) for column in entity.__table__.columns
            if column.key not in exclude}
