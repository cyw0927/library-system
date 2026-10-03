from types import SimpleNamespace

from app.core.config import get_settings
from app.services.qa_service import detect_issues
from tests.test_library_api import seed


def test_navigation_terminology_and_literal_math_stars():
    chapter = SimpleNamespace(markdown_content="# 제목\n\n2 * 3 = 6. 이스트 워치.\n\n<!-- reading-nav:start -->\n[목차](README.md) [다음](missing.md)\n<!-- reading-nav:end -->",
                              github_path="Book/01.md")
    term = SimpleNamespace(canonical="이스트워치", variants=[SimpleNamespace(variant="이스트 워치")])
    detected = detect_issues(chapter, {"Book/README.md"}, [term])
    assert any(i["issue_type"] == "terminology" and i["expected_value"] == "이스트워치" for i in detected)
    assert any(i["severity"] == "ERROR" and i["detected_value"] == "missing.md" for i in detected)
    assert not any(i["issue_type"] == "markdown" for i in detected)


def test_qa_resolution_survives_rerun_and_term_crud(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    get_settings.cache_clear()
    headers = {"X-Admin-Token": "test-token"}
    try:
        seed(client)
        body = {"canonical": "표준", "variants": ["변형", "변형"]}
        created = client.post("/terms", json=body, headers=headers)
        assert created.status_code == 201 and created.json()["variants"] == ["변형"]
        assert client.post("/terms", json=body, headers=headers).status_code == 409
        assert client.post("/qa/run", json={}, headers=headers).json()["chapters_checked"] == 2
        issue = client.get("/qa/issues").json()["results"][0]
        client.patch(f'/qa/issues/{issue["id"]}', json={"resolved": True}, headers=headers)
        client.post("/qa/run", json={}, headers=headers)
        resolved = client.get("/qa/issues", params={"resolved": True}).json()
        assert resolved["results"][0]["id"] == issue["id"]
        term_id = created.json()["id"]
        assert client.put(f"/terms/{term_id}", json={"canonical": "새 표준", "variants": ["변형"]}, headers=headers).status_code == 200
        assert client.delete(f"/terms/{term_id}", headers=headers).status_code == 204
        assert client.get("/terms").json() == []
    finally:
        get_settings.cache_clear()
