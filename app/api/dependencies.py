import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db

DB = Annotated[Session, Depends(get_db)]


def require_admin(x_admin_token: Annotated[str | None, Header()] = None):
    token = get_settings().admin_token
    if not token:
        raise HTTPException(503, "Set ADMIN_TOKEN to enable private and mutating endpoints")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, token):
        raise HTTPException(401, "An admin token is required")


Admin = Depends(require_admin)


def columns(entity, exclude=()):
    return {column.key: getattr(entity, column.key) for column in entity.__table__.columns
            if column.key not in exclude}
