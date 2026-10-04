import hashlib
import json
import math
import re
from collections import Counter

from sqlalchemy import Text, case, cast, func, or_, select, text
from pgvector.sqlalchemy import VECTOR
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.library import chapter_query
from app.core.config import get_settings
from app.db.models import Book, Chapter, Embedding, Paragraph, Volume
from app.services.openai_provider import OpenAIProvider, ProviderError
from app.services.search_service import source_result

INSUFFICIENT = "현재 Library 데이터에서 충분한 근거를 찾지 못했습니다."
LOCAL_MODEL = "hash-ngram-v1"


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: int = Field(gt=0)
    quote: str = Field(min_length=8, max_length=1500)


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    supported: bool
    answer: str = Field(max_length=6000)
    citations: list[Citation] = Field(max_length=15)


def content_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def local_vector(value, dimensions=256):
    """Deterministic lexical n-gram vector, explicitly NOT a semantic AI embedding."""
    vector = [0.0] * dimensions
    for word in re.findall(r"[\w]+", value.casefold()):
        features = [word] + [word[n:n + 2] for n in range(len(word) - 1)]
        for feature in features:
            index = int.from_bytes(hashlib.sha256(feature.encode()).digest()[:4], "big") % dimensions
            vector[index] += 1
    length = math.sqrt(sum(n * n for n in vector)) or 1
    return [n / length for n in vector]


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / ((math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))) or 1)


def has_pgvector(session):
    return session.get_bind().dialect.name == "postgresql" and bool(session.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector')")))


def embedding_spec(provider):
    settings = get_settings()
    return (settings.openai_embedding_model, 1536) if provider == "openai" else (LOCAL_MODEL, 256)


def index_paragraphs(session, provider="local", book_id=None, limit=1000, client=None):
    if provider == "openai" and not get_settings().paid_ai_enabled:
        raise ProviderError("Paid AI is disabled; use provider=local")
    model, dimensions = embedding_spec(provider)
    active = chapter_query()
    if book_id is not None:
        active = active.where(Chapter.book_id == book_id)
    rows = list(session.scalars(select(Paragraph).where(Paragraph.chapter_id.in_(active.with_only_columns(Chapter.id))).order_by(Paragraph.id)))
    existing = {e.paragraph_id: e for e in session.scalars(select(Embedding).where(Embedding.provider == provider, Embedding.model == model))}
    pending = [p for p in rows if p.id not in existing or existing[p.id].content_hash != content_hash(p.plain_text)]
    batch = pending[:limit]
    if provider == "openai" and client is None:
        settings = get_settings()
        client = OpenAIProvider(settings.openai_api_key, settings.openai_model, model)
        close = True
    else:
        close = False
    try:
        for start in range(0, len(batch), 32):
            paragraphs = batch[start:start + 32]
            vectors = client.embed([p.plain_text for p in paragraphs]) if provider == "openai" else [local_vector(p.plain_text[:2000]) for p in paragraphs]
            for paragraph, vector in zip(paragraphs, vectors):
                record = existing.get(paragraph.id)
                if record is None:
                    record = Embedding(paragraph_id=paragraph.id, provider=provider, model=model)
                    session.add(record)
                record.content_hash, record.dimensions = content_hash(paragraph.plain_text), dimensions
                record.input_characters, record.vector_data = min(len(paragraph.plain_text), 2000), vector
            session.commit()
    finally:
        if close:
            client.close()
    return dict(provider=provider, model=model, indexed=len(batch), remaining=len(pending) - len(batch),
                unchanged=len(rows) - len(pending), semantic=provider == "openai")


def query_terms(question):
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", question)
    stop = {"뭐야", "무엇", "이유", "설명", "해줘", "알려줘", "왜", "어떻게", "했어", "대한", "거래한", "관한"}
    terms = []
    for word in words:
        word = re.sub(r"(?:에서|에게|으로|는|은|가|이|을|를|와|과|의)$", "", word)
        if len(word) >= 2 and word not in stop and word not in terms:
            terms.append(word)
    return terms[:8]


def source_rows(session, ids):
    if not ids:
        return {}
    query = (select(Paragraph, Chapter, Book, Volume).select_from(Paragraph).join(Chapter, Paragraph.chapter_id == Chapter.id).join(Book, Chapter.book_id == Book.id)
             .outerjoin(Volume, Chapter.volume_id == Volume.id).where(Paragraph.id.in_(ids),
             Chapter.id.in_(chapter_query().with_only_columns(Chapter.id))))
    return {row[0].id: row for row in session.execute(query)}


def retrieve(session, question, provider="local", book_id=None, volume_id=None, client=None):
    settings = get_settings()
    active = chapter_query()
    if book_id is not None:
        active = active.where(Chapter.book_id == book_id)
    if volume_id is not None:
        active = active.where(Chapter.volume_id == volume_id)
    active_ids = active.with_only_columns(Chapter.id)
    terms = query_terms(question)
    scores = Counter()
    if terms:
        matches = [Paragraph.plain_text.ilike("%" + word + "%") for word in terms]
        weight = sum((case((match, 1), else_=0) for match in matches))
        keyword_ids = session.scalars(select(Paragraph.id).where(Paragraph.chapter_id.in_(active_ids), or_(*matches)).order_by(weight.desc(), Paragraph.id).limit(100))
        for rank, pid in enumerate(keyword_ids):
            scores[pid] += 1 / (60 + rank)
    model, dimensions = embedding_spec(provider)
    indexed = list(session.execute(select(Embedding, Paragraph.plain_text).join(Paragraph).where(
        Embedding.provider == provider, Embedding.model == model, Embedding.dimensions == dimensions,
        Paragraph.chapter_id.in_(active_ids)).order_by(Embedding.id).limit(settings.rag_vector_scan_limit)))
    # Never use embeddings from previous paragraph contents after sync.
    fresh = [(e, value) for e, value in indexed if e.content_hash == content_hash(value)]
    pgvector = has_pgvector(session)
    if fresh:
        query_vector = client.embed([question])[0] if provider == "openai" else local_vector(question[:2000])
        if pgvector:
            fresh_ids = [e.id for e, value in fresh]
            # Numeric dimension is validated by provider; vectors and IDs are bound parameters.
            distance = cast(cast(Embedding.vector_data, Text), VECTOR(dimensions)).cosine_distance(query_vector)
            ranked = session.execute(select(Embedding.paragraph_id, distance.label("distance"))
                                     .where(Embedding.id.in_(fresh_ids)).order_by(distance).limit(15))
            vector_results = [(pid, 1 - float(value)) for pid, value in ranked]
        else:
            vector_results = sorted(((e.paragraph_id, cosine(e.vector_data, query_vector)) for e, value in fresh), key=lambda pair: -pair[1])[:15]
        for rank, (pid, similarity) in enumerate(vector_results):
            if similarity >= (0.3 if provider == "openai" else 0.2):
                scores[pid] += 1 / (60 + rank)
    ids = [pid for pid, score in scores.most_common(settings.rag_max_sources)]
    rows = source_rows(session, ids)
    contexts, citations = [], []
    for pid in ids:
        if pid not in rows:
            continue
        paragraph, chapter, book, volume = rows[pid]
        context = paragraph.plain_text[:1500]
        contexts.append(dict(source_id=pid, text=context))
        citations.append(dict(**source_result(paragraph, chapter, book, volume), context=context))
    return contexts, citations, dict(pgvector=pgvector, provider=provider, semantic=provider == "openai", scanned_vectors=len(indexed), vector_scan_limit=settings.rag_vector_scan_limit)


def ask(session, question, mode="extractive", book_id=None, volume_id=None, client=None):
    settings = get_settings()
    if mode == "openai" and not settings.paid_ai_enabled:
        raise ProviderError("Paid AI is disabled; use mode=extractive")
    if mode == "openai" and client is None and (not settings.openai_api_key or not settings.openai_model):
        raise ProviderError("Set OPENAI_API_KEY and OPENAI_MODEL to enable AI answers")
    close = False
    if mode == "openai" and client is None:
        client = OpenAIProvider(settings.openai_api_key, settings.openai_model, settings.openai_embedding_model)
        close = True
    try:
        contexts, sources, retrieval = retrieve(session, question, "openai" if mode == "openai" else "local", book_id, volume_id, client)
        base = dict(mode=mode, question=question, retrieval=retrieval)
        if not contexts:
            return dict(**base, status="insufficient_evidence", answer=INSUFFICIENT, sources=[])
        if mode == "extractive":
            answer = "관련 본문 발췌입니다. AI가 생성한 해석 답변은 아닙니다.\n\n" + "\n\n".join(f'[{i + 1}] {s["context"][:500]}' for i, s in enumerate(sources))
            return dict(**base, status="excerpts", answer=answer, sources=sources)
        try:
            answer = GroundedAnswer.model_validate(client.answer(question, contexts)).model_dump()
        except ValidationError:
            return dict(**base, status="invalid_citation", answer=INSUFFICIENT, sources=[])
        allowed = {c["source_id"]: c["text"] for c in contexts}
        citations = answer.get("citations", [])
        if (not answer.get("supported") or not isinstance(answer.get("answer"), str) or not answer["answer"].strip()
                or not citations or not isinstance(citations, list)):
            return dict(**base, status="insufficient_evidence", answer=INSUFFICIENT, sources=[])
        for cite in citations:
            if not isinstance(cite, dict) or cite.get("source_id") not in allowed or not isinstance(cite.get("quote"), str) or len(cite["quote"]) < 8 or cite["quote"] not in allowed[cite["source_id"]]:
                return dict(**base, status="invalid_citation", answer=INSUFFICIENT, sources=[])
        cited_ids = {cite["source_id"] for cite in citations}
        return dict(**base, status="answered", answer=answer["answer"][:6000],
                    sources=[dict(**s, quotes=[c["quote"] for c in citations if c["source_id"] == s["paragraph_id"]]) for s in sources if s["paragraph_id"] in cited_ids])
    finally:
        if close:
            client.close()
