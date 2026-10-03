import hashlib
import json
import posixpath
import re
from collections import Counter
from urllib.parse import unquote, urlsplit

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.db.models import Chapter, QAIssue, SourceDocument, SyncState, Term
from app.services.metadata_service import map_path
from app.services.parser_service import END, MARKDOWN, START, ParseError, parse_chapter, without_navigation


def detect_issues(chapter, paths, terms):
    source = chapter.markdown_content
    issues = []

    def add(kind, severity, message, line=None, paragraph=None, found=None, expected=None):
        item = dict(issue_type=kind, severity=severity, message=message, line_number=line,
                    paragraph_number=paragraph, detected_value=found, expected_value=expected)
        item["fingerprint"] = hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        issues.append(item)

    if not source.strip():
        add("structure", "ERROR", "파일이 비어 있습니다.")
    tokens = MARKDOWN.parse(without_navigation(source))
    h1 = [t for t in tokens if t.type == "heading_open" and t.tag == "h1"]
    if not h1:
        add("structure", "WARNING", "최상위 제목(H1)이 없습니다.")
    if len(h1) > 1:
        add("structure", "WARNING", "최상위 제목(H1)이 여러 개입니다.", h1[1].map[0] + 1)
    previous_level = 0
    for token in tokens:
        if token.type == "heading_open":
            level = int(token.tag[1:])
            if previous_level and level > previous_level + 1:
                add("markdown", "WARNING", "제목 단계가 건너뛰었습니다.", token.map[0] + 1)
            previous_level = level
        if token.type == "inline" and token.children:
            # Unparsed link-like text, not raw star counts. Code spans are excluded by token type.
            for child in token.children:
                if child.type == "text" and re.search(r"\[[^\]]+\]\([^)]*$", child.content):
                    add("markdown", "WARNING", "닫히지 않은 링크 구문 후보입니다. 수동 검토가 필요합니다.", token.map[0] + 1, found=child.content[:200])
                if child.type == "text" and re.search(r"(?<!\w)\*{1,2}[^*\s][^*]+$", child.content):
                    add("markdown", "INFO", "파서에 강조로 인식되지 않은 표기입니다. 리터럴일 수도 있습니다.", token.map[0] + 1, found=child.content[:200])
    if source.count("<!--") != source.count("-->"):
        add("markdown", "WARNING", "HTML 주석 시작과 종료 수가 다릅니다.")
    starts, ends = source.count(START), source.count(END)
    if starts != 1 or ends != 1 or source.find(END) < source.find(START):
        add("navigation", "WARNING", "읽기 이동 marker가 없거나 중복·순서 오류가 있습니다.", found=f"start={starts}, end={ends}")
    else:
        nav = source.split(START, 1)[1].split(END, 1)[0]
        links = []
        for token in MARKDOWN.parse(nav):
            for child in token.children or []:
                if child.type == "link_open":
                    links.append(child.attrGet("href"))
        if not any("readme.md" in url.lower() for url in links):
            add("navigation", "WARNING", "목차 README 링크가 없습니다.")
        for url in links:
            parsed_url = urlsplit(url)
            if parsed_url.scheme or parsed_url.netloc or not parsed_url.path:
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(chapter.github_path), unquote(parsed_url.path)))
            if target not in paths:
                add("navigation", "ERROR", "저장소에 없는 상대 링크입니다.", found=url, expected=target)
    mapped = map_path(chapter.github_path)
    if mapped.number is None:
        add("filename", "INFO", "번호 없는 파일명입니다. 순서는 경로의 자연 정렬을 사용합니다.")
    try:
        parsed = parse_chapter(source)
    except ParseError as exc:
        add("structure", "ERROR", str(exc))
        return issues
    counts = Counter(p.plain for p in parsed.paragraphs if len(p.plain) >= 40)
    for n, paragraph in enumerate(parsed.paragraphs, 1):
        if counts[paragraph.plain] > 1:
            add("duplicate", "INFO", "동일한 긴 문단이 반복됩니다. 의도된 반복인지 검토하세요.", paragraph.line, n, paragraph.plain[:200])
        for term in terms:
            for variant in term.variants:
                pattern = re.escape(variant.variant)
                if variant.variant.isascii():
                    pattern = r"(?<![A-Za-z0-9])" + pattern + r"(?![A-Za-z0-9])"
                if re.search(pattern, paragraph.plain, re.I):
                    add("terminology", "WARNING", "등록한 표준 용어와 다른 표기가 있습니다.", paragraph.line, n,
                        variant.variant, term.canonical)
    return issues


def run_qa(session, chapter_id=None, book_id=None):
    query = select(Chapter).where(Chapter.is_active)
    if chapter_id is not None:
        query = query.where(Chapter.id == chapter_id)
    if book_id is not None:
        query = query.where(Chapter.book_id == book_id)
    paths = set(session.scalars(select(SyncState.github_path).where(SyncState.sync_status != "deactivated")))
    terms = list(session.scalars(select(Term).options(selectinload(Term.variants))))
    existing = {}
    for issue in session.scalars(select(QAIssue).join(Chapter).where(Chapter.id.in_(query.with_only_columns(Chapter.id)))):
        existing[(issue.chapter_id, issue.fingerprint)] = issue
        issue.is_current = False
    total, inspected = 0, 0
    for chapter in session.scalars(query):
        relevant = [t for t in terms if t.book_id is None or t.book_id == chapter.book_id]
        for detected in detect_issues(chapter, paths, relevant):
            key = (chapter.id, detected["fingerprint"])
            issue = existing.get(key)
            if issue is None:
                issue = QAIssue(chapter_id=chapter.id, source_sha=chapter.github_sha, **detected)
                session.add(issue)
                existing[key] = issue
            issue.source_sha, issue.is_current = chapter.github_sha, True
            total += 1
        inspected += 1
    session.commit()
    return {"chapters_checked": inspected, "issues": total, "automatic_source_changes": 0}
