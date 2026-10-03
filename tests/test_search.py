from app.db.session import get_db
from app.services.sync_service import sync_snapshot
from tests.test_sync import FakeSource


def test_literal_query_metadata_filters_pagination_and_nav_exclusion(client):
    with next(client.app.dependency_overrides[get_db]()) as db:
        source = FakeSource({"Book/README.md": "# 작품 제목", "Book/01_Jon_01.md":
                             "# 존\n\n브라보스 아이언 뱅크.\n\n100% 정확한 _표기_.\n\n<!-- reading-nav:start -->\n네비게이션전용단어\n<!-- reading-nav:end -->"})
        sync_snapshot(db, source, source.snapshot())
    result = client.get("/search", params={"q": "아이언 뱅크"}).json()
    assert result["total"] == 1 and result["results"][0]["paragraph_number"] == 1
    assert client.get("/search", params={"q": "%"}).json()["total"] == 1
    assert client.get("/search", params={"q": "작품 제목", "limit": 1, "offset": 1}).json()["total"] == 2
    assert client.get("/search", params={"q": "네비게이션전용단어"}).json()["total"] == 0
    assert client.get("/search", params={"q": "브라보스", "pov": "Jon"}).json()["total"] == 1
    assert client.get("/search", params={"q": "브라보스", "book_id": 999}).json()["total"] == 0
    assert client.get("/search", params={"q": " "}).status_code == 422
