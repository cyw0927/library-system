import re
from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.library import chapter_query
from app.db.models import Book, Chapter, Paragraph, Term, Volume


def chapter_lengths(session, book_id=None):
    active_ids = chapter_query()
    if book_id is not None:
        active_ids = active_ids.where(Chapter.book_id == book_id)
    query = (select(Chapter.id, Chapter.book_id, Chapter.volume_id, Chapter.title, Chapter.pov, Chapter.sort_order,
                    func.coalesce(func.sum(Paragraph.char_count), 0).label("characters"), func.count(Paragraph.id).label("paragraphs"))
             .outerjoin(Paragraph).where(Chapter.id.in_(active_ids.with_only_columns(Chapter.id)))
             .group_by(Chapter.id, Chapter.book_id, Chapter.volume_id, Chapter.title, Chapter.pov, Chapter.sort_order)
             .order_by(Chapter.sort_order, Chapter.id))
    return [dict(row._mapping) for row in session.execute(query)]


def overview(session):
    rows = chapter_lengths(session)
    totals = defaultdict(lambda: dict(chapters=0, paragraphs=0, characters=0))
    for chapter in rows:
        total = totals[chapter["book_id"]]
        total["chapters"] += 1
        total["paragraphs"] += chapter["paragraphs"]
        total["characters"] += chapter["characters"]
    books = [dict(book_id=b.id, title=b.title, **totals[b.id]) for b in session.scalars(select(Book).where(Book.is_active).order_by(Book.title))]
    return dict(books=books, total_books=len(books), total_chapters=len(rows),
                total_paragraphs=sum(x["paragraphs"] for x in rows), total_characters=sum(x["characters"] for x in rows))


def analyze_book(session, book):
    lengths = chapter_lengths(session, book.id)
    pov = Counter(c["pov"] for c in lengths if c["pov"])
    volume_pov = Counter((c["volume_id"], c["pov"]) for c in lengths if c["pov"])
    vocabulary = Counter()
    terms = list(session.scalars(select(Term).where((Term.book_id == book.id) | Term.book_id.is_(None)).options(selectinload(Term.variants))))
    patterns = {t.id: re.compile("|".join(re.escape(x) for x in sorted({t.canonical, *(v.variant for v in t.variants)}, key=len, reverse=True)), re.I) for t in terms}
    mentions = Counter()
    sentences, sentence_characters, dialogue_paragraphs = 0, 0, 0
    ids = [c["id"] for c in lengths]
    for text in session.scalars(select(Paragraph.plain_text).where(Paragraph.chapter_id.in_(ids)).execution_options(yield_per=1000)):
        vocabulary.update(word.casefold() for word in re.findall(r"[가-힣]{2,}|[A-Za-z][A-Za-z'-]{1,}", text))
        parts = [part.strip() for part in re.split(r"[.!?。！？]+", text) if part.strip()]
        sentences += len(parts)
        sentence_characters += sum(len(part) for part in parts)
        if text.lstrip().startswith(('“', '"', '「', '『', '—')):
            dialogue_paragraphs += 1
        for term_id, pattern in patterns.items():
            mentions[term_id] += len(pattern.findall(text))
    total_characters = sum(c["characters"] for c in lengths)
    total_paragraphs = sum(c["paragraphs"] for c in lengths)
    return dict(book_id=book.id, title=book.title, chapters=len(lengths), paragraphs=total_paragraphs,
                characters=total_characters, average_chapter_characters=total_characters / len(lengths) if lengths else 0,
                average_sentence_characters=sentence_characters / sentences if sentences else 0,
                dialogue_paragraph_ratio=dialogue_paragraphs / total_paragraphs if total_paragraphs else 0,
                chapter_lengths=lengths, longest_chapters=sorted(lengths, key=lambda x: (-x["characters"], x["id"]))[:10],
                pov_counts=[dict(pov=name, chapters=count) for name, count in pov.most_common()],
                volume_pov_counts=[dict(volume_id=v, pov=name, chapters=count) for (v, name), count in volume_pov.items()],
                term_mentions=[dict(term_id=t.id, canonical=t.canonical, category=t.category, mentions=mentions[t.id]) for t in terms],
                term_candidates=[dict(token=word, occurrences=count) for word, count in vocabulary.most_common(100)],
                methods={"characters": "검색용 plain text의 공백 포함 길이", "sentences": "문장부호 경계의 단순 추정",
                         "dialogue": "따옴표·대시로 시작하는 문단의 비율", "entities": "등록한 person 용어의 표기 매칭; 자동 NER 아님",
                         "candidates": "형태소 분석 없는 반복 어절; 조사·접미사가 포함될 수 있음"})
