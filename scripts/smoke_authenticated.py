"""CI-only real API + Streamlit login/logout and role-aware page smoke."""
import argparse
import os
from pathlib import Path
import sys

import httpx
from streamlit.testing.v1 import AppTest


def main():
    if os.getenv("CI") != "true":
        raise SystemExit("Only run against disposable CI accounts/databases")
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", choices=["admin", "reader"], required=True)
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip("\r\n")
    script = Path(__file__).resolve().parents[1] / "frontend" / "streamlit_app.py"
    at = AppTest.from_file(str(script), default_timeout=20).run()
    assert not at.exception and "로그인" in at.title[0].value
    at.text_input[0].set_value(args.username)
    at.text_input[1].set_value(password)
    at.button[0].click().run()
    assert not at.exception and at.session_state["user"]["role"] == args.role
    assert "도서관" in at.title[0].value
    pages = at.sidebar.radio[0].options
    assert ("Sync" in pages) == (args.role == "admin")
    for page in pages:
        at.query_params.update(page=page)
        if page == "Reader":
            with httpx.Client(base_url=os.environ["LIBRARY_API_URL"], trust_env=False) as client:
                chapter = client.get("/chapters", headers={"Authorization": "Bearer " + at.session_state["access_token"]}).json()[0]
            at.query_params.update(chapter=str(chapter["id"]))
        at.session_state["page_nav"] = page
        at.run()
        assert not at.exception and not at.error, f"Page failed: {page}"
    token = at.session_state["access_token"]
    at.sidebar.button[0].click().run()
    assert not at.exception and "로그인" in at.title[0].value
    with httpx.Client(base_url=os.environ["LIBRARY_API_URL"], trust_env=False) as client:
        assert client.get("/books", headers={"Authorization": "Bearer " + token}).status_code == 401
    print(f"Authenticated {args.role}: {len(pages)} pages, login and server-revoked logout passed")


if __name__ == "__main__":
    main()
