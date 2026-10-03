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
