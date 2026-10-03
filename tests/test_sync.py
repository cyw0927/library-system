import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Book, Chapter, Paragraph, SourceDocument, SyncState, Volume
from app.services.github_client import GitHubError, RemoteFile, Snapshot, blob_sha
from app.services.sync_service import sync_snapshot


class FakeSource:
    def __init__(self, files):
        self.files = files
        self.calls = []

    def content(self, file, commit):
        self.calls.append(file.path)
        value = self.files[file.path]
        if isinstance(value, Exception):
            raise value
        return value

    def snapshot(self):
        return Snapshot("commit", [RemoteFile(p, blob_sha(str(v).encode())) for p, v in self.files.items()])


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        yield s
    engine.dispose()


def test_import_incremental_change_delete_and_reappear(session):
    source = FakeSource({"README.md": "# Library", "Novel/README.md": "# 작품",
                         "Novel/chapter_01.md": "# 첫 장\n\n첫 본문.",
                         "Empty/README.md": "# 빈 책", "Novel/02_Volume/README.md": "# 빈 권"})
    first = sync_snapshot(session, source, source.snapshot())
    assert first["created"] == 5 and not first["errors"]
    assert len(list(session.scalars(select(Book)))) == 2
    assert len(list(session.scalars(select(Volume)))) == 1
    chapter = session.scalar(select(Chapter))
    pid = chapter.paragraphs[0].id
    source.calls.clear()
    assert sync_snapshot(session, source, source.snapshot())["unchanged"] == 5
    assert not source.calls
    source.files["Novel/chapter_01.md"] = "# 변경\n\n둘 본문.\n\n새 문단."
    assert sync_snapshot(session, source, source.snapshot())["updated"] == 1
    assert chapter.title == "변경" and chapter.paragraphs[0].id == pid
    assert chapter.paragraph_count == 2
    del source.files["Novel/chapter_01.md"]
    assert sync_snapshot(session, source, source.snapshot())["deactivated"] == 1
    assert not chapter.is_active
    assert len(list(session.scalars(select(Paragraph)))) == 2
    source.files["Novel/chapter_01.md"] = "# 복구\n\n본문."
    sync_snapshot(session, source, source.snapshot())
    assert chapter.is_active and chapter.title == "복구"


def test_file_failure_preserves_previous_data_and_sha(session):
    source = FakeSource({"Novel/chapter_01.md": "# 제목\n\n본문."})
    sync_snapshot(session, source, source.snapshot())
    chapter = session.scalar(select(Chapter))
    old_sha = chapter.github_sha
    for invalid in ["# 본문 없는 장", GitHubError("GitHub HTTP 503")]:
        source.files["Novel/chapter_01.md"] = invalid
        report = sync_snapshot(session, source, source.snapshot())
        assert report["errors"] and chapter.title == "제목" and chapter.is_active
        state = session.scalar(select(SyncState))
        assert state.sync_status == "error" and state.github_sha == old_sha


def test_readme_only_change_updates_parent_without_chapter_download(session):
    source = FakeSource({"Novel/README.md": "# 원래 제목", "Novel/chapter_01.md": "# 장\n\n본문."})
    sync_snapshot(session, source, source.snapshot())
    source.files["Novel/README.md"] = "# 새 제목"
    source.calls.clear()
    sync_snapshot(session, source, source.snapshot())
    assert session.scalar(select(Book)).title == "새 제목"
    assert source.calls == ["Novel/README.md"]
    assert len(list(session.scalars(select(SourceDocument)))) == 1
