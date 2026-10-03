import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import session as db_module


def test_request_session_rolls_back_uncommitted_work(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE session_check (value INTEGER)"))
        monkeypatch.setattr(
            db_module, "get_session_factory",
            lambda: sessionmaker(bind=engine),
        )
        dependency = db_module.get_db()
        session = next(dependency)
        session.execute(text("INSERT INTO session_check (value) VALUES (1)"))

        with pytest.raises(RuntimeError, match="request failed"):
            dependency.throw(RuntimeError("request failed"))

        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM session_check")) == 0
    finally:
        engine.dispose()
