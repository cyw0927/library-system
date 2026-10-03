"""Run the same integrity checks on SQLite and migrated PostgreSQL."""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Book, Chapter, Paragraph, SyncState, Volume


@pytest.fixture(scope="session")
def postgres_model_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(params=["sqlite", "postgresql"])
def model_db(request):
    if request.param == "postgresql":
        engine = request.getfixturevalue("postgres_model_engine")
        # These tests use the schema created by Alembic, never create_all().
    else:
        engine = create_engine("sqlite+pysqlite:///:memory:")

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)

    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()
    if request.param == "sqlite":
        engine.dispose()


def sample_library(db):
    book = Book(slug="sample-book", title="테스트 작품", github_path="Sample")
    volume = Volume(book=book, slug="volume-one", title="권 하나", github_path="Sample/One")
    chapter = Chapter(
        book=book, volume=volume, title="장 하나", github_path="Sample/One/01.md",
        github_sha="a" * 40, markdown_content="# 장 하나\n\n본문 하나.",
    )
    paragraph = Paragraph(
        chapter=chapter, paragraph_number=1, markdown_content="*본문 하나.*",
        plain_text="본문 하나.", char_count=6,
    )
    state = SyncState(
        github_path=chapter.github_path, github_sha=chapter.github_sha, entity_type="chapter",
    )
    db.add_all([book, paragraph, state])
    db.flush()
    return book, volume, chapter, paragraph, state


def test_optional_volume_and_unicode_round_trip(model_db):
    book = Book(slug="standalone", title="단권 작품", github_path="Standalone")
    chapter = Chapter(
        book=book, title="서문", chapter_number=None, github_path="Standalone/preface.md",
        github_sha="b" * 40, markdown_content="# 서문\n\n한국어와 é, 🙂.",
    )
    model_db.add(chapter)
    model_db.flush()
    model_db.expire_all()

    saved = model_db.get(Chapter, chapter.id)
    assert saved.volume is None
    assert saved.book.title == "단권 작품"
    assert "é, 🙂" in saved.markdown_content
    assert saved.chapter_number is None


def test_relationships_and_defaults(model_db):
    book, volume, chapter, paragraph, state = sample_library(model_db)
    model_db.expire_all()

    assert book.volumes == [volume]
    assert book.chapters == [chapter]
    assert volume.chapters == [chapter]
    assert chapter.paragraphs == [paragraph]
    assert paragraph.chapter is chapter
    assert book.is_active and volume.is_active and chapter.is_active
    assert book.status == "unknown"
    assert chapter.paragraph_count == 0
    assert state.sync_status == "pending"
    assert state.entity_id is None and state.last_synced_at is None
    for item in (book, volume, chapter, paragraph):
        assert item.created_at is not None and item.updated_at is not None
        if model_db.bind.dialect.name == "postgresql":
            assert item.created_at.tzinfo is not None


def test_chapter_and_paragraph_order(model_db):
    book, volume, chapter, paragraph, _ = sample_library(model_db)
    chapter.sort_order = 2
    earlier = Chapter(
        book=book, volume=volume, title="앞 장", github_path="Sample/One/00.md",
        github_sha="c" * 40, markdown_content="본문", sort_order=1,
    )
    later_paragraph = Paragraph(
        chapter=chapter, paragraph_number=2, markdown_content="두 번째", plain_text="두 번째",
    )
    model_db.add_all([earlier, later_paragraph])
    model_db.flush()
    model_db.expire_all()

    assert book.chapters == [earlier, chapter]
    assert volume.chapters == [earlier, chapter]
    assert chapter.paragraphs == [paragraph, later_paragraph]


@pytest.mark.parametrize("kind", ["book_slug", "book_path", "volume", "volume_path", "chapter", "paragraph", "sync"])
def test_unique_keys(model_db, kind):
    book, volume, chapter, _, state = sample_library(model_db)
    duplicates = {
        "book_slug": Book(slug=book.slug, title="duplicate", github_path="Other"),
        "book_path": Book(slug="different-slug", title="duplicate", github_path=book.github_path),
        "volume": Volume(book_id=book.id, slug=volume.slug, title="duplicate", github_path="Other/One"),
        "volume_path": Volume(
            book_id=book.id, slug="different-volume", title="duplicate", github_path=volume.github_path,
        ),
        "chapter": Chapter(
            book_id=book.id, title="duplicate", github_path=chapter.github_path,
            github_sha="d" * 40, markdown_content="본문",
        ),
        "paragraph": Paragraph(
            chapter_id=chapter.id, paragraph_number=1, markdown_content="duplicate", plain_text="duplicate",
        ),
        "sync": SyncState(github_path=state.github_path, github_sha="e" * 40, entity_type="chapter"),
    }
    model_db.add(duplicates[kind])
    with pytest.raises(IntegrityError):
        model_db.flush()


def test_volume_slug_is_scoped_to_book(model_db):
    _, volume, _, _, _ = sample_library(model_db)
    other = Book(slug="other", title="다른 작품", github_path="Other")
    other_volume = Volume(book=other, slug=volume.slug, title="다른 권", github_path="Other/One")
    model_db.add(other_volume)
    model_db.flush()
    assert other_volume.id != volume.id


def test_chapter_cannot_reference_another_books_volume(model_db):
    _, volume, _, _, _ = sample_library(model_db)
    other = Book(slug="other", title="다른 작품", github_path="Other")
    model_db.add(other)
    model_db.flush()
    model_db.add(Chapter(
        book_id=other.id, volume_id=volume.id, title="잘못 연결한 장",
        github_path="Other/01.md", github_sha="f" * 40, markdown_content="본문",
    ))
    with pytest.raises(IntegrityError):
        model_db.flush()


def test_orphan_paragraph_is_rejected(model_db):
    model_db.add(Paragraph(
        chapter_id=2_000_000_000, paragraph_number=1, markdown_content="본문", plain_text="본문",
    ))
    with pytest.raises(IntegrityError):
        model_db.flush()


@pytest.mark.parametrize("kind, field, value", [
    ("volume", "volume_number", 0),
    ("volume", "sort_order", -1),
    ("chapter", "chapter_number", -1),
    ("chapter", "paragraph_count", -1),
    ("chapter", "sort_order", -1),
    ("paragraph", "paragraph_number", 0),
    ("paragraph", "char_count", -1),
    ("sync", "sync_status", "not-a-status"),
    ("sync", "entity_id", 0),
])
def test_invalid_values_are_rejected(model_db, kind, field, value):
    _, volume, chapter, paragraph, state = sample_library(model_db)
    item = {"volume": volume, "chapter": chapter, "paragraph": paragraph, "sync": state}[kind]
    setattr(item, field, value)
    with pytest.raises(IntegrityError):
        model_db.flush()


@pytest.mark.parametrize("target", ["book", "volume"])
def test_referenced_parent_cannot_be_hard_deleted(model_db, target):
    book, volume, _, _, _ = sample_library(model_db)
    # Loaded children must not be silently detached by the ORM either.
    assert book.volumes and volume.chapters
    model_db.delete(book if target == "book" else volume)
    with pytest.raises(IntegrityError):
        model_db.flush()


def test_soft_delete_preserves_content(model_db):
    book, volume, chapter, paragraph, _ = sample_library(model_db)
    book.is_active = volume.is_active = chapter.is_active = False
    model_db.flush()
    model_db.expire_all()

    assert not model_db.get(Chapter, chapter.id).is_active
    assert model_db.get(Paragraph, paragraph.id).plain_text == "본문 하나."
    assert model_db.scalar(select(func.count()).select_from(Chapter)) == 1


def test_paragraph_replacement_removes_orphan(model_db):
    _, _, chapter, paragraph, _ = sample_library(model_db)
    paragraph_id = paragraph.id
    chapter.paragraphs.remove(paragraph)
    model_db.flush()
    assert model_db.get(Paragraph, paragraph_id) is None


def test_database_cascades_paragraphs_when_chapter_is_deleted(model_db):
    _, _, chapter, paragraph, _ = sample_library(model_db)
    paragraph_id = paragraph.id
    # Use SQL directly to exercise the database FK, not an ORM cascade.
    model_db.execute(delete(Chapter).where(Chapter.id == chapter.id))
    model_db.expire_all()
    assert model_db.get(Paragraph, paragraph_id) is None
