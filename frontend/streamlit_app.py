import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from frontend import client as api

st.set_page_config(page_title="내 도서관", page_icon="📚", layout="wide")
PAGES = ["Library", "Book", "Reader", "Search", "QA", "Terms", "Reading", "Analysis", "Ask", "Sync"]


def is_admin():
    return not api.auth_enabled() or st.session_state.get("user", {}).get("role") == "admin"


def clear_login():
    for key in list(st.session_state):
        del st.session_state[key]


def login_gate():
    if not api.auth_enabled():
        return
    if st.session_state.get("access_token"):
        try:
            st.session_state["user"] = api.get("/auth/me")
        except api.APIError as exc:
            if exc.status_code == 401:
                clear_login()
            else:
                st.error(str(exc))
                st.stop()
    if not st.session_state.get("access_token"):
        st.title("📚 내 도서관 로그인")
        st.caption("초대받은 계정만 원문과 개인 독서 기록에 접근할 수 있습니다.")
        with st.form("login", clear_on_submit=True):
            name = st.text_input("아이디", max_chars=64)
            password = st.text_input("비밀번호", type="password", max_chars=128)
            submitted = st.form_submit_button("로그인")
        if submitted:
            try:
                result = api.request("POST", "/auth/login", body={"username": name, "password": password}, token="")
                st.session_state["access_token"] = result["access_token"]
                st.session_state["user"] = result["user"]
                st.rerun()
            except api.APIError as exc:
                st.error(str(exc))
        st.stop()
    st.sidebar.caption(f'{st.session_state["user"]["username"]} · {st.session_state["user"]["role"]}')
    if st.sidebar.button("로그아웃"):
        try:
            api.post("/auth/logout")
        except api.APIError:
            st.warning("서버 연결 실패 시 세션은 최대 만료 시간까지 유지될 수 있습니다.")
        clear_login()
        st.rerun()


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
            volume_label = f'{book["volume_count"]}권' if book["volume_count"] else "권 구분 없음"
            st.caption(f'{book.get("author") or "저자 정보 없음"} · {volume_label} · {book["chapter_count"]}개 장 파일')
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
    st.divider()
    with st.expander("독서 위치 · 북마크 · 메모"):
        position = st.number_input("저장할 문단", min_value=1, max_value=max(1, len(paragraphs)), value=min(max(target, 1), max(1, len(paragraphs))), key=f'position-{chapter_id}')
        completed = st.checkbox("이 장 읽기 완료", key=f'completed-{chapter_id}')
        if st.button("독서 위치 저장"):
            api.request("PUT", "/reading/progress", body=dict(chapter_id=chapter_id, paragraph_number=position, completed=completed))
            st.success("저장했습니다.")
        note = st.text_area("메모", key=f'note-{chapter_id}')
        if st.button("북마크·메모 저장"):
            api.post("/bookmarks", chapter_id=chapter_id, paragraph_number=position, note=note)
            st.success("북마크를 저장했습니다.")


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
    if is_admin() and st.button("QA 실행"):
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
            if is_admin() and st.button("다시 열기" if resolved else "검토 완료", key=f'qa-resolve-{issue["id"]}'):
                api.request("PATCH", f'/qa/issues/{issue["id"]}', body={"resolved": not resolved})
                st.rerun()


def terms_page():
    st.title("표준 용어")
    if not is_admin():
        st.caption("용어 변경은 관리자만 가능합니다.")
        for term in api.get("/terms"):
            with st.expander(f'{term["canonical"]} · {term["category"]}'):
                st.write(term["description"] or "")
                st.write(" / ".join(term["variants"]))
        return
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


def reading_page():
    st.title("내 독서 기록")
    page = st.number_input("기록 페이지", 1, value=1)
    st.subheader("최근 읽은 장")
    for record in api.get("/reading/progress", offset=(page - 1) * 50):
        st.write(f'{record["chapter_title"]} · §{record["paragraph_number"]} · {"완료" if record["completed"] else "읽는 중"}')
        if record["source_changed"]:
            st.warning("저장 후 원문이 바뀌었습니다. 문단 위치를 확인해 주세요.")
        st.button("이어 읽기", key=f'continue-{record["id"]}', on_click=navigate, args=("Reader",), kwargs={"chapter": record["chapter_id"], "paragraph": record["paragraph_number"]}, disabled=not record["chapter_active"])
    st.subheader("북마크·메모")
    for record in api.get("/bookmarks", offset=(page - 1) * 50):
        with st.container(border=True):
            st.write(f'{record["chapter_title"]} · §{record["paragraph_number"] or 1}')
            if record["source_changed"]:
                st.warning("원문 변경: 이 위치의 내용이 달라졌을 수 있습니다.")
            note = st.text_area("메모", record["note"] or "", key=f'memo-{record["id"]}')
            if st.button("메모 수정", key=f'edit-memo-{record["id"]}'):
                api.request("PATCH", f'/bookmarks/{record["id"]}', body={"note": note})
                st.success("저장했습니다.")
            st.button("북마크 읽기", key=f'bookmark-read-{record["id"]}', on_click=navigate, args=("Reader",), kwargs={"chapter": record["chapter_id"], "paragraph": record["paragraph_number"]}, disabled=not record["chapter_active"])
            confirm = st.checkbox("북마크를 삭제합니다", key=f'confirm-bookmark-{record["id"]}')
            if st.button("삭제", key=f'delete-bookmark-{record["id"]}', disabled=not confirm):
                api.request("DELETE", f'/bookmarks/{record["id"]}')
                st.rerun()


def analysis_page():
    st.title("텍스트 분석")
    overall = api.get("/analysis/overview")
    columns = st.columns(4)
    for column, label, key in zip(columns, ["작품", "장", "문단", "글자"], ["total_books", "total_chapters", "total_paragraphs", "total_characters"]):
        column.metric(label, f'{overall[key]:,}')
    book = book_picker()
    result = api.get(f'/analysis/books/{book["id"]}')
    st.write(f'평균 장 길이: {result["average_chapter_characters"]:,.0f}자 · 평균 문장 길이(추정): {result["average_sentence_characters"]:,.1f}자')
    st.subheader("장 길이")
    if result["chapter_lengths"]:
        st.bar_chart(result["chapter_lengths"], x="title", y="characters")
    st.subheader("명시적 POV별 장 수")
    if result["pov_counts"]:
        st.bar_chart(result["pov_counts"], x="pov", y="chapters")
    else:
        st.info("파일명에 명시된 POV가 없습니다. 별칭에서 인물을 추측하지 않습니다.")
    st.subheader("등록 용어·인물 언급")
    st.dataframe(result["term_mentions"], hide_index=True)
    st.subheader("반복 어절 후보")
    st.dataframe(result["term_candidates"], hide_index=True)
    with st.expander("집계 방법과 한계"):
        st.json(result["methods"])


def ask_page():
    st.title("Library에 질문하기")
    status = api.get("/rag/status")
    st.caption(f'임베딩 {status["embeddings"]:,}개 · pgvector {"사용 가능" if status["pgvector"] else "미설치 — 제한된 Python 벡터 검색"}')
    paid = status.get("paid_ai_enabled", False) and is_admin()
    st.info("본문 발췌는 무료·로컬 기능이며 AI 해석 답변이 아닙니다." + ("" if paid else " 유료 AI 호출은 비활성화되어 있습니다."))
    mode = st.selectbox("답변 방식", ["extractive", "openai"] if paid else ["extractive"], format_func=lambda v: "본문 발췌 (무료·로컬)" if v == "extractive" else "AI 답변 (OpenAI API)")
    books = api.get("/books")
    book_id = st.selectbox("질문 범위", [None] + [b["id"] for b in books], format_func=lambda v: "전체" if v is None else next(b["title"] for b in books if b["id"] == v))
    question = st.text_area("질문", placeholder="아이언 뱅크와 관련한 본문을 찾아줘")
    consent = st.checkbox("선택한 OpenAI 모드의 유료 API 호출에 동의합니다") if mode == "openai" else True
    if st.button("질문하기", disabled=not consent):
        with st.spinner("관련 문단 검색 중"):
            result = api.post("/ask", question=question, mode=mode, book_id=book_id)
        st.write(result["answer"])
        for source in result["sources"]:
            with st.expander(f'{source["book_title"]} / {source["chapter_title"]} / §{source["paragraph_number"]}'):
                st.write(source["context"])
                if source.get("quotes"):
                    st.write(source["quotes"])
                st.link_button("원본 출처", source["source_url"])
                st.button("문단 읽기", key=f'ask-read-{source["paragraph_id"]}', on_click=navigate, args=("Reader",), kwargs={"chapter": source["chapter_id"], "paragraph": source["paragraph_number"]})
    if not is_admin():
        return
    with st.expander("임베딩 색인 만들기"):
        provider = st.selectbox("임베딩 방식", ["local", "openai"] if paid else ["local"], format_func=lambda v: "어휘 n-gram 벡터 (AI 의미 임베딩 아님)" if v == "local" else "OpenAI 의미 임베딩 (유료)")
        cost = st.checkbox("OpenAI 색인 비용에 동의합니다", key="embedding-cost") if provider == "openai" else False
        if st.button("최대 1,000개 변경 문단 색인", disabled=provider == "openai" and not cost):
            with st.spinner("색인 중"):
                st.json(api.post("/rag/index", provider=provider, book_id=book_id, limit=1000, confirm_cost=cost))


def sync_page():
    st.title("GitHub 동기화")
    st.warning("GitHub → DB 읽기 전용 동기화입니다. 원본을 commit하거나 push하지 않습니다.")
    if st.button("변경 파일 동기화"):
        with st.spinner("동기화 중 — 실행 중에는 다시 요청하지 마세요"):
            st.json(api.post("/sync/github"))
    for run in api.get("/sync/status"):
        with st.expander(f'{run["id"]} · {run["status"]} · {run["started_at"]}'):
            st.json(run)


def sync_menu_url():
    st.query_params["page"] = st.session_state["page_nav"]


login_gate()
pages = PAGES if is_admin() else [page for page in PAGES if page != "Sync"]
requested = st.query_params.get("page", "Library")
page = st.sidebar.radio("메뉴", pages, index=pages.index(requested) if requested in pages else 0, key="page_nav", on_change=sync_menu_url)
try:
    {"Library": library_page, "Book": book_page, "Reader": reader_page, "Search": search_page,
     "QA": qa_page, "Terms": terms_page, "Reading": reading_page, "Analysis": analysis_page, "Ask": ask_page, "Sync": sync_page}[page]()
except api.APIError as exc:
    if api.auth_enabled() and exc.status_code == 401:
        clear_login()
        st.rerun()
    st.error(str(exc))
