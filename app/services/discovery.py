from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SyncState
from app.services.github_client import Snapshot


def record_inventory(session: Session, snapshot: Snapshot) -> int:
    """Record new blobs without overwriting the last successfully imported SHA."""
    existing = set(session.scalars(select(SyncState.github_path)))
    created = 0
    for file in snapshot.files:
        if file.path in existing:
            continue
        session.add(SyncState(github_path=file.path, github_sha=file.sha,
                              entity_type="metadata" if file.path.lower().endswith("readme.md") else "chapter"))
        created += 1
    session.commit()
    return created
