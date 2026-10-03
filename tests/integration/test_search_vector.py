import os

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db.models import Embedding, Paragraph
from app.services.rag_service import ask, has_pgvector, index_paragraphs
from app.services.search_service import search
from app.services.sync_service import sync_snapshot
from tests.test_sync import FakeSource

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not configured")


def test_postgres_literal_and_fts_search():
    engine = create_engine(URL)
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
            source = FakeSource({"SearchFixture/01.md": "# 제목\n\n브라보스 아이언 뱅크.\n\n은행에 관한 설명입니다."})
            sync_snapshot(session, source, source.snapshot())
            assert search(session, "아이언 뱅크")["total"] == 1
            assert search(session, "아이언 뱅크", mode="fts")["total"] == 1
            assert connection.scalar(text("SELECT count(*) FROM pg_indexes WHERE indexname='ix_paragraphs_search_fts'")) == 1
        transaction.rollback()
    engine.dispose()


def test_real_pgvector_retrieval():
    engine = create_engine(URL)
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
            if not has_pgvector(session):
                if os.getenv("PGVECTOR_REQUIRED") == "1":
                    pytest.fail("CI must provide pgvector")
                pytest.skip("Local server has no pgvector; CI tests the real extension")
            source = FakeSource({"VectorFixture/01.md": "# 제목\n\n아이언 뱅크는 은행이다.\n\n겨울 숲의 이야기."})
            sync_snapshot(session, source, source.snapshot())
            assert index_paragraphs(session, limit=10)["indexed"] >= 2
            result = ask(session, "아이언 뱅크")
            assert result["retrieval"]["pgvector"] and result["sources"]
        transaction.rollback()
    engine.dispose()
