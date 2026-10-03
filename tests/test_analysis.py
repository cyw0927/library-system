from tests.test_library_api import seed


def test_real_counts_and_empty_analysis(client):
    assert client.get("/analysis/overview").json()["total_books"] == 0
    seed(client)
    book = client.get("/books").json()[0]
    overall = client.get("/analysis/overview").json()
    assert overall["total_chapters"] == 2 and overall["total_paragraphs"] == 2
    analysis = client.get(f'/analysis/books/{book["id"]}').json()
    assert analysis["characters"] == len("본문 하나.") + len("본문 둘.")
    assert analysis["pov_counts"] == []
    assert analysis["term_candidates"][0]["token"] == "본문"
    assert client.get("/analysis/books/999").status_code == 404
