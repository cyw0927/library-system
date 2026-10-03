import json

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.services.discovery import record_inventory
from app.services.github_client import GitHubClient


def main():
    settings = get_settings()
    source = GitHubClient(settings.github_repository, settings.github_branch, settings.github_token,
                          settings.github_cache_dir, use_git_credentials=settings.github_use_git_credentials)
    try:
        snapshot = source.snapshot()
        with get_session_factory()() as session:
            created = record_inventory(session, snapshot)
        print(json.dumps({"commit": snapshot.commit, "markdown_files": len(snapshot.files),
                          "new_pending": created}, ensure_ascii=False))
    finally:
        source.close()


if __name__ == "__main__":
    main()
