import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Embedding, Paragraph
from app.db.session import get_db
from app.services.openai_provider import OpenAIProvider, ProviderError
from app.services.rag_service import INSUFFICIENT, ask, index_paragraphs, local_vector, retrieve
from tests.test_sync import FakeSource, session
from app.services.sync_service import sync_snapshot


@pytest.fixture(autouse=True)
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def library(session):
    source = FakeSource({"Book/01.md": "# 제목\n\n아이언 뱅크는 자금을 빌려주는 은행이다.\n\n다른 문단은 여행에 관한 이야기이다."})
    sync_snapshot(session, source, source.snapshot())


def test_extracts_sources_abstains_and_invalidates_stale_embeddings(session):
    library(session)
    assert index_paragraphs(session)["indexed"] == 2
    assert index_paragraphs(session)["unchanged"] == 2
    result = ask(session, "아이언 뱅크")
    assert result["status"] == "excerpts" and result["sources"][0]["paragraph_number"] == 1
    assert "AI가 생성한 해석 답변은 아닙니다" in result["answer"]
    # Keyword retrieval must not depend on embeddings; stale vectors are excluded.
    paragraph = session.scalar(select(Paragraph).order_by(Paragraph.id))
    paragraph.plain_text = "새로 바뀐 본문."
    session.commit()
    contexts, citations, info = retrieve(session, "아이언 뱅크")
    assert not any(s["paragraph_id"] == paragraph.id for s in citations)
    empty = ask(session, "아즈텍퀘이사뉴트리노")
    assert empty["answer"] == INSUFFICIENT and empty["sources"] == []


def test_generated_answer_requires_real_quote_and_known_source(session, monkeypatch):
    monkeypatch.setenv("PAID_AI_ENABLED", "true")
    get_settings.cache_clear()
    library(session)
    class Provider:
        def answer(self, question, sources):
            return dict(supported=True, answer="은행으로 묘사됩니다.", citations=[dict(source_id=sources[0]["source_id"], quote=sources[0]["text"][:15])])
    assert ask(session, "아이언 뱅크", mode="openai", client=Provider())["status"] == "answered"
    class BadProvider:
        def answer(self, question, sources):
            return dict(supported=True, answer="지어낸 답", citations=[dict(source_id=999999, quote="지어낸 인용문입니다.")])
    assert ask(session, "아이언 뱅크", mode="openai", client=BadProvider())["status"] == "invalid_citation"
    assert ask(session, "아즈텍퀘이사뉴트리노", mode="openai", client=BadProvider())["status"] == "insufficient_evidence"


def test_openai_request_format_and_sanitized_failure(monkeypatch):
    monkeypatch.setenv("PAID_AI_ENABLED", "true")
    get_settings.cache_clear()
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if request.url.path.endswith("embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 1536}]})
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"supported": False, "answer": "", "citations": []})}]}]})
    provider = OpenAIProvider("test-key", "configured-model", transport=httpx.MockTransport(handler))
    assert len(provider.embed(["본문"])[0]) == 1536
    assert provider.answer("질문", [{"source_id": 1, "text": "본문"}])["supported"] is False
    assert calls[1]["store"] is False and calls[1]["text"]["format"]["strict"]
    assert calls[0]["dimensions"] == 1536
    provider.close()
    failed = OpenAIProvider("secret-must-not-leak", "model", transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "secret-must-not-leak"})))
    with pytest.raises(ProviderError, match="OpenAI HTTP 401") as exc:
        failed.embed(["text"])
    assert "secret-must-not-leak" not in str(exc.value)
    failed.close()


def test_api_requires_auth_cost_confirmation_and_real_configuration(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    headers = {"X-Admin-Token": "test-token"}
    try:
        assert client.post("/ask", json={"question": "질문입니다"}).status_code == 401
        assert client.post("/ask", json={"question": "질문입니다", "mode": "openai"}, headers=headers).status_code == 403
        assert client.post("/rag/index", json={"provider": "openai"}, headers=headers).status_code == 403
        assert client.get("/rag/status", headers=headers).json()["openai_configured"] is False
    finally:
        get_settings.cache_clear()
