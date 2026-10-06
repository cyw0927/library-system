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


def reader_library_get(path, **params):
    book = {"id": 1, "title": "Test book", "volume_count": 0, "chapter_count": 2}
    chapters = [{"id": n, "title": f"Chapter {n}", "paragraph_count": 1} for n in (101, 102)]
    if path == "/books":
        return [book]
    if path == "/books/1/volumes":
        return []
    if path == "/books/1/chapters":
        return chapters
    if path in ("/chapters/101", "/chapters/102"):
        chapter_id = int(path.rsplit("/", 1)[1])
        return {"id": chapter_id, "book_id": 1, "book": book, "volume": None,
                "title": f"Chapter {chapter_id}", "source_url": "https://github.com/example/book",
                "previous": {"id": 101} if chapter_id == 102 else None,
                "next": {"id": 102} if chapter_id == 101 else None,
                "markdown_content": "Actual chapter text",
                "paragraphs": [{"paragraph_number": 1, "markdown_content": "Actual chapter text"}]}
    raise AssertionError(f"Unexpected API call: {path}")


def test_reader_bottom_next_and_browser_history_restore_routes():
    with patch("frontend.client.get", side_effect=reader_library_get):
        at = AppTest.from_file(str(SCRIPT)).run()
        at.button(key="book-1").click().run()
        book_route = dict(at.query_params)
        at.button(key="chapter-101").click().run()
        reader_route = dict(at.query_params)
        assert not at.exception
        assert at.button(key="reader-bottom-previous").disabled
        at.button(key="reader-bottom-next").click().run()
        next_route = dict(at.query_params)
        assert not at.exception and at.title[0].value == "Chapter 102"
        assert at.query_params["book"] == "1"
        assert at.button(key="reader-bottom-next").disabled

        # Simulate the URLs delivered by browser Back and Forward in one session.
        for route, menu, title in ((reader_route, "Reader", "Chapter 101"),
                                   (book_route, "Book", "작품 탐색"),
                                   (next_route, "Reader", "Chapter 102")):
            at.query_params.clear()
            at.query_params.update(route)
            at.run()
            assert not at.exception
            assert at.sidebar.radio[0].value == menu
            assert at.title[0].value == title


def test_bottom_next_from_paragraph_result_opens_full_next_chapter():
    with patch("frontend.client.get", side_effect=reader_library_get):
        at = AppTest.from_file(str(SCRIPT))
        at.query_params.update(page="Reader", chapter="101", paragraph="1")
        at.run()
        assert not at.exception and not at.toggle(key="reader-full-101").value
        at.button(key="reader-bottom-next").click().run()
        assert not at.exception and "paragraph" not in at.query_params
        assert at.title[0].value == "Chapter 102"
        assert at.toggle(key="reader-full-102").value
        at.button(key="reader-bottom-contents").click().run()
        assert not at.exception and at.query_params == {"page": "Book", "book": "1"}
