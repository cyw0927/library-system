from app.core.config import get_settings
from tests.test_library_api import seed


def test_progress_bookmark_and_private_notes(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    get_settings.cache_clear()
    headers = {"X-Admin-Token": "test-token"}
    try:
        seed(client)
        cid = client.get("/chapters").json()[0]["id"]
        assert client.get("/bookmarks").status_code == 401
        saved = client.put("/reading/progress", json=dict(chapter_id=cid, paragraph_number=1, completed=True), headers=headers)
        assert saved.status_code == 200
        assert client.put("/reading/progress", json=dict(chapter_id=cid, paragraph_number=999), headers=headers).status_code == 422
        records = client.get("/reading/progress", headers=headers).json()
        assert len(records) == 1 and records[0]["completed"]
        bookmark = client.post("/bookmarks", json=dict(chapter_id=cid, paragraph_number=1, note="개인 메모"), headers=headers)
        assert bookmark.status_code == 201
        bid = bookmark.json()["id"]
        assert client.patch(f"/bookmarks/{bid}", json={"note": "새 메모"}, headers=headers).json()["note"] == "새 메모"
        assert client.get("/bookmarks", headers=headers).json()[0]["source_changed"] is False
        assert client.delete(f"/bookmarks/{bid}", headers=headers).status_code == 204
    finally:
        get_settings.cache_clear()
