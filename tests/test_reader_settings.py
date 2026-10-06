from app.core.config import get_settings
from app.api.dependencies import Identity, require_private
from app.main import app


def test_reader_preferences_persist_validate_and_require_credentials(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    get_settings.cache_clear()
    headers = {"X-Admin-Token": "test-token"}
    preferences = dict(font_size=24, line_height=2.1, width=1000, dark=True, show_full_text=False)
    try:
        assert client.get("/reading/settings").status_code == 401
        assert client.put("/reading/settings", json=preferences).status_code == 401
        assert client.get("/reading/settings", headers=headers).json()["font_size"] == 18
        assert client.put("/reading/settings", json=preferences, headers=headers).json() == preferences
        assert client.get("/reading/settings", headers=headers).json() == preferences
        for invalid in ({**preferences, "font_size": 100}, {**preferences, "line_height": 10},
                        {**preferences, "width": 99999}, {**preferences, "user_id": "someone-else"}):
            assert client.put("/reading/settings", json=invalid, headers=headers).status_code == 422
        assert client.get("/reading/settings", headers=headers).json() == preferences
    finally:
        get_settings.cache_clear()


def test_reader_preferences_are_isolated_by_authenticated_identity(client):
    try:
        app.dependency_overrides[require_private] = lambda: Identity("alice", "reader", "alice")
        assert client.put("/reading/settings", json={"font_size": 26, "dark": True}).status_code == 200
        app.dependency_overrides[require_private] = lambda: Identity("bob", "reader", "bob")
        assert client.get("/reading/settings").json()["font_size"] == 18
        assert client.put("/reading/settings", json={"font_size": 16}).status_code == 200
        app.dependency_overrides[require_private] = lambda: Identity("alice", "reader", "alice")
        assert client.get("/reading/settings").json()["font_size"] == 26
        assert client.get("/reading/settings").json()["dark"] is True
    finally:
        app.dependency_overrides.pop(require_private, None)