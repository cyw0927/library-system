import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from frontend import client as api

st.set_page_config(page_title="내 도서관", page_icon="📚", layout="wide")
PAGES = ["Library", "Book", "Reader", "Search", "QA", "Terms", "Sync"]


def number_param(name, default=None):
    try:
        return int(st.query_params[name]) if name in st.query_params else default
    except (ValueError, TypeError):
        return default


def navigate(page, **params):
    st.query_params.clear()
    st.query_params.update(page=page, **{k: str(v) for k, v in params.items() if v is not None})
    st.session_state["page_nav"] = page


def book_picker():
    books = api.get("/books")
    if not books:
        st.info("아직 도서가 없습니다. 동기화를 실행해 주세요.")
        st.stop()
    ids = [b["id"] for b in books]
    wanted = number_param("book")
    selected = st.selectbox("작품", ids, index=ids.index(wanted) if wanted in ids else 0,
                            format_func=lambda value: next(b["title"] for b in books if b["id"] == value))
    return next(b for b in books if b["id"] == selected)


def library_page():
    st.title("📚 내 도서관")
    st.caption("GitHub 원본을 읽기 전용으로 구조화한 개인 전자도서관")
    books = api.get("/books")
    if not books:
        st.info("도서가 없습니다. 먼저 python -m scripts.initial_sync를 실행해 주세요.")
    for book in books:
        with st.container(border=True):
            st.subheader(book["title"])
            st.caption(f'{book.get("author") or "저자 정보 없음"} · {book["volume_count"]}권 · {book["chapter_count"]}개 장 파일')
            if book.get("expected_chapters"):
                st.write(f'README 기준 전체: {book["expected_chapters"]}장 (부록 등 파일 수와 다를 수 있음)')
            if book.get("translation_progress") is not None:
                st.progress(min(1.0, book["translation_progress"]))
            st.button("작품 열기", key=f'book-{book["id"]}', on_click=navigate, args=("Book",), kwargs={"book": book["id"]})


def book_page():
    st.title("작품 탐색")
    book = book_picker()
    if book.get("description"):
        st.caption(book["description"])
    volumes = api.get(f'/books/{book["id"]}/volumes')
    options = [None] + [v["id"] for v in volumes]
    volume_id = st.selectbox("권", options, format_func=lambda value: "전체" if value is None else next(v["title"] for v in volumes if v["id"] == value))
    chapters = api.get(f'/books/{book["id"]}/chapters', volume_id=volume_id, limit=1000)
    if not chapters:
        st.info("이 작품 또는 권에는 아직 본문이 없습니다.")
    for chapter in chapters:
        left, right = st.columns([7, 1])
        left.write(f'{chapter.get("chapter_code") or ""} · {chapter["title"]} · {chapter["paragraph_count"]}문단')
        right.button("읽기", key=f'chapter-{chapter["id"]}', on_click=navigate, args=("Reader",), kwargs={"chapter": chapter["id"]})


def reader_page():
    chapter_id = number_param("chapter")
    if chapter_id is None:
        st.info("작품 탐색에서 읽을 장을 선택해 주세요.")
        return
    chapter = api.get(f"/chapters/{chapter_id}")
    st.caption(chapter["book"]["title"] + (" / " + chapter["volume"]["title"] if chapter["volume"] else ""))
    st.title(chapter["title"])
    st.link_button("GitHub 원본", chapter["source_url"])
    previous, contents, following = st.columns(3)
    if chapter["previous"]:
        previous.button("← 이전 장", on_click=navigate, args=("Reader",), kwargs={"chapter": chapter["previous"]["id"]})
    contents.button("목차", on_click=navigate, args=("Book",), kwargs={"book": chapter["book_id"]})
    if chapter["next"]:
        following.button("다음 장 →", on_click=navigate, args=("Reader",), kwargs={"chapter": chapter["next"]["id"]})
    font_size = st.sidebar.slider("글자 크기", 14, 30, 18)
    line_height = st.sidebar.slider("줄 간격", 1.2, 2.4, 1.8)
    width = st.sidebar.slider("본문 폭", 500, 1200, 850)
    dark = st.sidebar.toggle("다크 모드", False)
    # Only fixed CSS and bounded numeric values enter unsafe HTML, never book text.
    colors = "background:#171923;color:#edf2f7;" if dark else ""
    st.markdown(f'<style>.stApp{{{colors}}} .block-container{{max-width:{width}px}} [data-testid="stMarkdown"] p{{font-size:{font_size}px;line-height:{line_height}}}</style>', unsafe_allow_html=True)
    target = number_param("paragraph", 1)
    paragraphs = chapter["paragraphs"]
    show_all = st.toggle("전체 본문 보기", value="paragraph" not in st.query_params)
    if show_all:
        st.markdown(chapter["markdown_content"])
    else:
        target = st.number_input("문단으로 이동", min_value=1, max_value=max(1, len(paragraphs)), value=min(max(target, 1), max(1, len(paragraphs))))
        for paragraph in paragraphs[max(0, target - 4):target + 11]:
            if paragraph["paragraph_number"] == target:
                st.info(f'선택한 문단 §{target}')
            st.caption(f'§{paragraph["paragraph_number"]}')
            st.markdown(paragraph["markdown_content"])


def search_page():
    st.title("통합검색")
    books = api.get("/books")
    options = [None] + [b["id"] for b in books]
    book_id = st.selectbox("작품 필터", options, format_func=lambda value: "전체" if value is None else next(b["title"] for b in books if b["id"] == value))
    volumes = api.get("/volumes", book_id=book_id) if book_id else []
    volume_id = st.selectbox("권 필터", [None] + [v["id"] for v in volumes], format_func=lambda value: "전체" if value is None else next(v["title"] for v in volumes if v["id"] == value))
    q = st.text_input("검색어", placeholder="아이언 뱅크")
    pov = st.text_input("POV 필터 (선택)")
    page = st.number_input("결과 페이지", 1, value=1)
    if q.strip():
        result = api.get("/search", q=q, book_id=book_id, volume_id=volume_id, pov=pov.strip() or None, offset=(page - 1) * 20)
        st.write(f'{result["total"]:,}건')
        for item in result["results"]:
            with st.container(border=True):
                st.write(f'{item["book_title"]} / {item["volume_title"] or ""} / {item["chapter_title"]} / §{item["paragraph_number"]}')
                st.write(item["excerpt"])
                st.button("문단 읽기", key=f'result-{item["paragraph_id"]}', on_click=navigate, args=("Reader",), kwargs={"chapter": item["chapter_id"], "paragraph": item["paragraph_number"]})


def qa_page():
    st.title("번역 QA")
    st.caption("구조·Markdown·내비게이션·파일명·용어·중복을 검사합니다. 원본을 자동 수정하지 않습니다.")
    books = api.get("/books")
    book_id = st.selectbox("검사 작품", [None] + [b["id"] for b in books], format_func=lambda v: "전체" if v is None else next(b["title"] for b in books if b["id"] == v))
    if st.button("QA 실행"):
        with st.spinner("검사 중"):
            st.success(api.post("/qa/run", book_id=book_id))
    severity = st.selectbox("심각도", [None, "ERROR", "WARNING", "INFO"], format_func=lambda v: v or "전체")
    resolved = st.toggle("해결한 항목 보기", False)
    page = st.number_input("문제 페이지", 1, value=1)
    result = api.get("/qa/issues", book_id=book_id, severity=severity, resolved=resolved, offset=(page - 1) * 50)
    st.write(f'{result["total"]:,}건')
    for issue in result["results"]:
        with st.container(border=True):
            st.write(f'{issue["severity"]} · {issue["issue_type"]} · {issue["chapter_title"]}')
            st.write(issue["message"])
            st.caption(issue["source_path"] + (f' / §{issue["paragraph_number"]}' if issue["paragraph_number"] else ""))
            if issue["detected_value"]:
                st.write(f'발견: {issue["detected_value"]} → 기준: {issue["expected_value"] or "수동 검토"}')
            st.button("문제 위치 읽기", key=f'qa-read-{issue["id"]}', on_click=navigate, args=("Reader",), kwargs={"chapter": issue["chapter_id"], "paragraph": issue["paragraph_number"]})
            if st.button("다시 열기" if resolved else "검토 완료", key=f'qa-resolve-{issue["id"]}'):
                api.request("PATCH", f'/qa/issues/{issue["id"]}', body={"resolved": not resolved})
                st.rerun()


def terms_page():
    st.title("표준 용어")
    books = api.get("/books")
    categories = ["person", "place", "organization", "title", "ship", "concept", "house", "event"]
    with st.form("new-term"):
        canonical = st.text_input("표준 표기")
        variants = st.text_area("다른 표기 (한 줄에 하나)")
        category = st.selectbox("분류", categories)
        book_id = st.selectbox("적용 작품", [None] + [b["id"] for b in books], format_func=lambda v: "전체 작품" if v is None else next(b["title"] for b in books if b["id"] == v))
        description = st.text_area("설명")
        if st.form_submit_button("용어 등록"):
            api.post("/terms", canonical=canonical, variants=variants.splitlines(), category=category, book_id=book_id, description=description)
            st.rerun()
    for term in api.get("/terms"):
        with st.expander(f'{term["canonical"]} · {term["category"]}'):
            with st.form(f'edit-term-{term["id"]}'):
                updated = st.text_input("표준 표기", term["canonical"])
                aliases = st.text_area("다른 표기", "\n".join(term["variants"]))
                note = st.text_area("설명", term["description"] or "")
                if st.form_submit_button("저장"):
                    api.request("PUT", f'/terms/{term["id"]}', body=dict(canonical=updated, variants=aliases.splitlines(), category=term["category"], book_id=term["book_id"], description=note))
                    st.rerun()
            confirm = st.checkbox("이 용어를 삭제합니다", key=f'term-confirm-{term["id"]}')
            if st.button("삭제", key=f'term-delete-{term["id"]}', disabled=not confirm):
                api.request("DELETE", f'/terms/{term["id"]}')
                st.rerun()
    st.caption("용어를 바꾼 뒤 QA를 다시 실행하면 새 기준으로 검사합니다.")


def sync_page():
    st.title("GitHub 동기화")
    st.warning("GitHub → DB 읽기 전용 동기화입니다. 원본을 commit하거나 push하지 않습니다.")
    if st.button("변경 파일 동기화"):
        with st.spinner("동기화 중 — 실행 중에는 다시 요청하지 마세요"):
            st.json(api.post("/sync/github"))
    for run in api.get("/sync/status"):
        with st.expander(f'{run["id"]} · {run["status"]} · {run["started_at"]}'):
            st.json(run)


requested = st.query_params.get("page", "Library")
page = st.sidebar.radio("메뉴", PAGES, index=PAGES.index(requested) if requested in PAGES else 0, key="page_nav")
try:
    {"Library": library_page, "Book": book_page, "Reader": reader_page, "Search": search_page,
     "QA": qa_page, "Terms": terms_page, "Sync": sync_page}[page]()
except api.APIError as exc:
    st.error(str(exc))
