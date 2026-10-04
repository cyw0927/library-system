import os
from pathlib import Path
import shutil
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.models import Account, Bookmark, LoginSession
from app.core.security import utcnow
from scripts.backup import backup, restore, validate_restore_target
from tests.test_models import sample_library

ROOT = Path(__file__).resolve().parents[2]


def test_real_dump_restore_preserves_personal_data_without_sessions(tmp_path):
    url = os.getenv("TEST_DATABASE_URL")
    pg_bin = os.getenv("PG_BIN")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not pg_bin and not shutil.which("pg_dump"):
        if os.getenv("PG_BACKUP_REQUIRED") == "1":
            pytest.fail("PostgreSQL 18 backup tools are required")
        pytest.skip("PostgreSQL 18 client tools are not configured")
    # Unique, disposable databases only. No existing test/demo database is dropped.
    names = ["backup_src_" + uuid4().hex, "backup_dst_" + uuid4().hex]
    parsed = make_url(url)
    admin = create_engine(parsed, isolation_level="AUTOCOMMIT")
    created, engines = [], []
    try:
        with admin.connect() as connection:
            for name in names:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
                created.append(name)
        source_url, target_url = [parsed.set(database=name).render_as_string(hide_password=False) for name in names]
        source = create_engine(source_url)
        target = create_engine(target_url)
        engines.extend([source, target])
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "alembic"))
        with source.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with Session(source) as db:
            _, _, chapter, _, _ = sample_library(db)
            db.add(Account(id="backup-user", username="backup-user", password_hash="disabled", role="reader"))
            db.flush()
            db.add(Bookmark(user_id="backup-user", chapter_id=chapter.id, source_sha=chapter.github_sha,
                            note="복구되어야 하는 개인 메모"))
            db.add(LoginSession(user_id="backup-user", token_hash="f" * 64, expires_at=utcnow()))
            db.commit()
        archive = backup(source_url, tmp_path / "roundtrip.dump", pg_bin)
        restore(source_url, target_url, archive, pg_bin, confirmed=True)
        with Session(target) as db:
            note = db.scalar(select(Bookmark))
            assert note.note == "복구되어야 하는 개인 메모" and note.user_id == "backup-user"
            assert db.get(Account, "backup-user") is not None
            assert db.scalar(select(func.count()).select_from(LoginSession)) == 0
        with pytest.raises(ValueError, match="not empty"):
            validate_restore_target(source_url, target_url)
        with Session(source) as db:
            assert db.scalar(select(func.count()).select_from(Bookmark)) == 1
    finally:
        for engine in engines:
            engine.dispose()
        with admin.connect() as connection:
            for name in created:
                assert name.startswith(("backup_src_", "backup_dst_")) and len(name) < 64
                connection.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()
