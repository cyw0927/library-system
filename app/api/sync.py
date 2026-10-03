from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.dependencies import Admin, DB, columns
from app.core.config import get_settings
from app.db.models import SyncRun
from app.services.github_client import GitHubClient, GitHubError
from app.services.sync_service import SyncBusy, run_sync

router = APIRouter(tags=["Sync"], dependencies=[Admin])


@router.get("/sync/status")
def status(db: DB):
    return [columns(r) for r in db.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(20))]


@router.post("/sync/github")
def sync(db: DB):
    settings = get_settings()
    try:
        source = GitHubClient(settings.github_repository, settings.github_branch, settings.github_token, settings.github_cache_dir,
                              use_git_credentials=settings.github_use_git_credentials)
        try:
            return run_sync(db, source)
        finally:
            source.close()
    except GitHubError as exc:
        raise HTTPException(502, str(exc)) from None
    except SyncBusy as exc:
        raise HTTPException(409, str(exc)) from None
