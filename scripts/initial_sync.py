import json

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.services.github_client import GitHubClient
from app.services.sync_service import run_sync


def main():
    config = get_settings()
    source = GitHubClient(config.github_repository, config.github_branch, config.github_token, config.github_cache_dir,
                          use_git_credentials=config.github_use_git_credentials)
    try:
        with get_session_factory()() as session:
            report = run_sync(session, source)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["errors"]:
            raise SystemExit(1)
    finally:
        source.close()


if __name__ == "__main__":
    main()
