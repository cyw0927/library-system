from app.core.config import get_settings
from app.db.session import get_db
from tests.test_sync import FakeSource
from app.services.sync_service import sync_snapshot


def seed(client):
    override = client.app.dependency_overrides[get_db]
    with next(override()) as db:
        source = FakeSource({"Novel/README.md": "# 작품", "Novel/chapter_01.md": "# 첫 장\n\n본문 하나.",
                             "Novel/chapter_02.md": "# 둘 장\n\n본문 둘."})
        sync_snapshot(db, source, source.snapshot())


def test_reader_lists_navigation_and_not_found(client):
    seed(client)
    books = client.get("/books").json()
    assert books[0]["chapter_count"] == 2 and books[0]["expected_chapters"] is None
    chapters = client.get(f'/books/{books[0]["id"]}/chapters').json()
    detail = client.get(f'/chapters/{chapters[0]["id"]}').json()
    assert detail["previous"] is None and detail["next"]["id"] == chapters[1]["id"]
    assert detail["paragraphs"][0]["plain_text"] == "본문 하나."
    assert "commit/Novel/chapter_01.md" in detail["source_url"]
    assert client.get("/books/999").status_code == 404
    assert client.get("/chapters?limit=1001").status_code == 422
    assert client.get("/volumes").json() == []


def test_mutations_are_disabled_or_authenticated(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "")
    get_settings.cache_clear()
    assert client.post("/sync/github").status_code == 503
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    get_settings.cache_clear()
    try:
        assert client.post("/sync/github").status_code == 401
        assert client.get("/sync/status", headers={"X-Admin-Token": "test-token"}).status_code == 200
    finally:
        get_settings.cache_clear()
