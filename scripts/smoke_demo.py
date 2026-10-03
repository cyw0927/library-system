"""Read-only HTTP + actual Streamlit AppTest checks against a running local demo."""
import os
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest


def main():
    url = os.getenv("LIBRARY_API_URL", "http://127.0.0.1:8000")
    headers = {"X-Admin-Token": os.environ["ADMIN_TOKEN"]}
    with httpx.Client(base_url=url, headers=headers, timeout=180) as client:
        for path in ("/health", "/health/db", "/docs", "/books", "/volumes", "/analysis/overview", "/qa/issues", "/bookmarks", "/reading/progress", "/rag/status", "/sync/status"):
            response = client.get(path)
            response.raise_for_status()
            print(f"HTTP {path}: {response.status_code}")
        books = client.get("/books").json()
        book = min((b for b in books if b["chapter_count"] > 0), key=lambda b: b["chapter_count"])
        chapters = client.get(f'/books/{book["id"]}/chapters').json()
        chapter = client.get(f'/chapters/{chapters[0]["id"]}').json()
        assert chapter["paragraphs"] and "reading-nav:start" not in chapter["markdown_content"]
        query = chapter["paragraphs"][0]["plain_text"][:8]
        result = client.get("/search", params={"q": query, "book_id": book["id"]}).json()
        assert result["total"] > 0 and result["results"][0]["source_url"]
        fts = client.get("/search", params={"q": "은행", "mode": "fts"})
        assert fts.status_code == 200
        grounded = client.post("/ask", json={"question": query, "book_id": book["id"]}).json()
        assert grounded["status"] == "excerpts" and grounded["sources"]
        print(f'Search: {result["total"]} literal hits; FTS: 200; grounded excerpts: {len(grounded["sources"])} sources')
        script = Path(__file__).resolve().parents[1] / "frontend" / "streamlit_app.py"
        for page in ["Library", "Book", "Reader", "Search", "QA", "Terms", "Reading", "Analysis", "Ask", "Sync"]:
            at = AppTest.from_file(str(script), default_timeout=60)
            at.query_params.update(page=page, book=str(book["id"]), chapter=str(chapter["id"]), paragraph="1")
            at.run(timeout=60)
            assert not at.exception, f"{page}: {at.exception}"
            assert not at.error, f"{page}: {at.error}"
            print(f"Streamlit {page}: PASS")


if __name__ == "__main__":
    main()
