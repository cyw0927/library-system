from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from frontend.client import APIError

SCRIPT = Path(__file__).resolve().parents[1] / "frontend" / "streamlit_app.py"


def test_empty_library_and_server_failure_are_visible():
    with patch("frontend.client.get", return_value=[]):
        at = AppTest.from_file(str(SCRIPT)).run()
        assert not at.exception and at.info
    with patch("frontend.client.get", side_effect=APIError("DB 연결 실패")):
        at = AppTest.from_file(str(SCRIPT)).run()
        assert not at.exception and "DB 연결 실패" in at.error[0].value


def test_invalid_reader_url_does_not_crash():
    at = AppTest.from_file(str(SCRIPT))
    at.query_params.update(page="Reader", chapter="bad-id")
    at.run()
    assert not at.exception and at.info


def test_menu_navigation_updates_url_for_reload():
    with patch("frontend.client.get", return_value=[]):
        at = AppTest.from_file(str(SCRIPT)).run()
        at.sidebar.radio[0].set_value("Search").run()
        assert not at.exception and at.query_params["page"] == "Search"


def test_login_gate_never_loads_originals_before_authentication(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    with patch("frontend.client.get") as get:
        at = AppTest.from_file(str(SCRIPT)).run()
        assert not at.exception and "로그인" in at.title[0].value
        assert get.call_count == 0
        assert len(at.text_input) == 2 and at.text_input[1].proto.type == 1  # PASSWORD enum


def test_authenticated_reader_menu_has_no_admin_actions(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    def fake_get(path, **params):
        return {"id": "reader", "username": "reader", "role": "reader"} if path == "/auth/me" else []
    at = AppTest.from_file(str(SCRIPT))
    at.session_state["access_token"] = "test-session"
    with patch("frontend.client.get", side_effect=fake_get):
        at.run()
        assert not at.exception and "Sync" not in at.sidebar.radio[0].options
        at.sidebar.radio[0].set_value("Terms").run()
        assert not at.exception and not at.get("form")


def test_expired_ui_session_returns_to_login(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    at = AppTest.from_file(str(SCRIPT))
    at.session_state["access_token"] = "expired-session"
    with patch("frontend.client.get", side_effect=APIError("Expired", 401)):
        at.run()
        assert not at.exception and "로그인" in at.title[0].value
        assert "access_token" not in at.session_state


def test_admin_ask_screen_hides_all_paid_controls_when_disabled():
    def fake_get(path, **params):
        if path == "/rag/status":
            return dict(embeddings=0, pgvector=False, paid_ai_enabled=False)
        return []
    at = AppTest.from_file(str(SCRIPT))
    at.query_params.update(page="Ask")
    with patch("frontend.client.get", side_effect=fake_get):
        at.run()
        assert not at.exception
        assert at.selectbox[0].options == ["본문 발췌 (무료·로컬)"]
        assert not at.checkbox
