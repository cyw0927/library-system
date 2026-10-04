# Library App

GitHub `cyw0927/library`의 Markdown을 읽기 전용으로 수집하는 개인 전자도서관입니다. 앱 코드는 `cyw0927/library-system`에서 관리합니다. GitHub main이 원본이고 PostgreSQL은 검색·QA·분석용 파생 저장소입니다. 앱은 도서 저장소에 commit/push하거나 번역문을 자동 수정하지 않습니다.

## 구현 상태

운영 준비 기능(초대형 로그인, admin/reader 역할, 사용자별 독서 기록 격리, 안전한 DB 백업/복구, 독립 TLS Docker 구성)을 추가했습니다. [운영 가이드](deploy/OPERATIONS.md)를 먼저 읽으세요. **외부 배포/PR 병합은 수행하지 않습니다.** production은 모든 원문 API에 로그인을 강제하고 legacy ADMIN_TOKEN을 거부합니다.

Phase 1–13의 MVP 코드를 순서대로 구현했습니다. 외부 서비스의 실제 운영 검증은 별도입니다.

- [x] FastAPI, PostgreSQL, SQLAlchemy, Alembic, health, pytest/CI
- [x] SHA 검증·commit 고정 GitHub 탐색, 비공개 저장소 인증, 증분 sync
- [x] Markdown 제목·문단·plain text 파싱, reading-nav 검색 제외
- [x] 경로 기반 Book → optional Volume → Chapter → Paragraph 매핑
- [x] README 원문·메타데이터 보존, 파일별 transaction, soft delete, 동기화 이력
- [x] 책·권·장 API, 이전/다음 장과 commit 고정 출처
- [x] 문단 ILIKE 검색, 작품/권/장/POV 필터, PostgreSQL FTS GIN 인덱스
- [x] Streamlit Library / Book / Reader / Search, 글자 크기·줄 간격·폭·다크 모드
- [x] 비파괴 번역 QA, 용어·변형 관리, 검토 상태 보존
- [x] 개인 독서 위치·읽은 장·북마크·메모, 원문 변경 경고
- [x] 글자 수·장 길이·POV·등록 인물/용어·반복 어절 분석
- [x] 마지막 단계 RAG: 제한된 문단 검색, 출처 검증, 근거 부족 응답, API 어댑터
- [x] pgvector SQL 코사인 검색 경로와 CI 검사
- [ ] 실제 OpenAI 유료 호출: API 키와 접근 가능한 모델 설정 후 별도 확인 필요

무료 기본 모드는 **본문 발췌**입니다. AI 해석 답변이 아닙니다. 로컬 n-gram 해시 벡터도 어휘 기반이며 의미 임베딩으로 표시하지 않습니다.

## 구조와 기술 스택

```text
GitHub main (원본; GET only)
  → commit 고정 tree / blob SHA 검증
  → Markdown / README metadata parser
  → PostgreSQL (파생 데이터 + 개인 독서 기록)
  → FastAPI → Streamlit
  → 마지막 단계: keyword + vector retrieval → 선택적 OpenAI 답변 + 출처
```

Python 3.11+, FastAPI, PostgreSQL 18, SQLAlchemy 2, psycopg 3, Alembic, markdown-it-py, Streamlit, httpx, pgvector, pytest.

```text
app/api/              # health, library, search, sync, QA/terms, reading, analysis, RAG
app/db/models/        # 15개 도메인 테이블 (계정·세션 포함)
app/services/         # GitHub, parser, metadata, sync, QA, analysis, provider, RAG
frontend/             # API만 사용하는 Streamlit reader
scripts/              # discover, initial_sync, run_qa, rebuild_index, enable_pgvector, dev
alembic/versions/     # 0001–0009; 0004 빈 revision은 후속 0005에서 보완
tests/                # SQLite API/unit + 실제 PostgreSQL + Streamlit AppTest
.github/workflows/    # Python 3.11/3.12, PostgreSQL 18 + 실제 pgvector
compose.yaml          # 선택적 localhost 개발 PostgreSQL + pgvector
compose.production.yaml # 독립 운영 구성: TLS 프록시 / 내부 DB·API·UI
deploy/OPERATIONS.md  # 계정, secrets, 배포 체크리스트, 백업·복구
```

## 설치 (PowerShell)

```powershell
git clone https://github.com/cyw0927/library-system.git C:\dev\library-app
Set-Location C:\dev\library-app
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . -r requirements-dev.txt
Copy-Item .env.example .env
```

기존 clone에서는 해당 폴더를 사용합니다. 이 구현은 `feat/library-platform` PR 브랜치에 있습니다. 기반 Phase 1/2 PR 이후 순서대로 병합하거나 해당 브랜치를 체크아웃하세요.

## DB 설정과 migration

기존 PostgreSQL에서 앱 전용 사용자/DB를 만들고 `DATABASE_URL`을 지정합니다. 기존 DB를 초기화하지 마세요.

```sql
CREATE USER library_app WITH PASSWORD 'replace-with-a-strong-password';
CREATE DATABASE library_app OWNER library_app;
```

```dotenv
DATABASE_URL=postgresql+psycopg://library_app:your-password@127.0.0.1:5432/library_app
```

비밀번호의 특수문자는 URL 인코딩합니다(`%` → `%25`). 연결·쿼리 제한시간은 기본 5초입니다.

pgvector가 필요하면 선택적 Docker DB를 사용할 수 있습니다.

```powershell
# .env의 POSTGRES_PASSWORD 설정 후, DATABASE_URL도 같은 비밀번호와 port 5433으로 설정
docker compose up -d db
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.enable_pgvector
```

일반 PostgreSQL도 reader/search/QA에 사용할 수 있습니다. pgvector 미설치는 숨기지 않고 `/rag/status`에 표시합니다. migration은 확장 설치를 강제하지 않습니다. 기존 Windows PostgreSQL 설치 파일을 앱이 자동 수정하지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

앱 시작 시 `create_all()`은 실행하지 않습니다. **데이터가 있는 DB에서 downgrade base를 실행하지 마세요.** 도서 인덱스뿐 아니라 개인 독서 기록도 같은 DB에 있으므로 운영 DB 전체 초기화 대신 백업과 migration을 사용하세요.

## GitHub 연결 및 가져오기

```dotenv
GITHUB_REPOSITORY=cyw0927/library
GITHUB_BRANCH=main
GITHUB_TOKEN=
GITHUB_CACHE_DIR=
GITHUB_USE_GIT_CREDENTIALS=false
```

비공개 원본에는 contents read 권한의 fine-grained GitHub 토큰이 필요합니다. Windows 로컬 개발에서는 명시적으로 `GITHUB_USE_GIT_CREDENTIALS=true`를 설정해 기존 Git Credential Manager 로그인을 사용할 수도 있습니다. 자격증명은 출력·저장하지 않으며 GitHub API에만 전송합니다.

선택적 clone 캐시는 각 파일의 실제 Git blob SHA가 일치할 때만 사용합니다. 불일치/새 파일은 인증된 GitHub blob API로 가져옵니다. 캐시를 Source of Truth로 취급하지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m scripts.discover
.\.venv\Scripts\python.exe -m scripts.initial_sync
```

같은 SHA의 synced 파일은 다운로드·본문 재파싱하지 않습니다. 읽기 오류는 이전 내용/SHA를 유지하고 error 상태로 기록합니다. 불완전하거나 비어 있는 tree/API 오류에서는 비활성화하지 않습니다. 완전한 snapshot에서 사라진 파일만 soft delete합니다. PostgreSQL advisory lock으로 겹치는 sync를 막습니다. 변경된 snapshot은 QA도 실행합니다.

README는 장 수에 포함하지 않습니다. 번호 범위 폴더는 권으로 만들지 않습니다. 제목/저자는 README에서 파싱하며 확인할 수 없으면 경로 기반 제목/unknown으로 둡니다. 파일명의 명시적 POV만 사용하고 별칭에서 인물을 추측하지 않습니다.

## 실행

```powershell
.\.venv\Scripts\python.exe -m scripts.dev
```

- Reader: http://127.0.0.1:8501
- API 문서: http://127.0.0.1:8000/docs
- Ctrl+C: 두 서버 종료
- 로그: `work/api.log`, `work/frontend.log`

`scripts.dev`는 ADMIN_TOKEN이 없으면 프로세스 메모리에 임시 토큰을 생성해 API/UI에 공유합니다. DB health 실패 시 화면이 정상인 것처럼 시작하지 않습니다. 별도 실행은 다음과 같습니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m streamlit run frontend/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

development에서 AUTH_REQUIRED=false인 기존 localhost 모드에 한해 ADMIN_TOKEN을 두 프로세스에 동일하게 지정합니다. 없으면 private/mutating endpoint는 503, 잘못된 토큰은 401입니다. 요청 헤더는 `X-Admin-Token`입니다. 이 모드는 인터넷에 공개하지 마세요. 로그인 모드는 AUTH_REQUIRED=true로 API와 UI 모두 실행하고 계정을 생성합니다. production은 인증을 강제하며 공유 ADMIN_TOKEN을 허용하지 않습니다. 기본 실행은 localhost로 제한합니다.

## 주요 API

로그인 모드에서 `/auth/login`(POST username/password) → `/auth/me`(GET), `/auth/logout`(POST)와 `Authorization: Bearer ...`를 사용합니다. 아래 원문/분석 API는 모두 로그인 필요, 관리자 작업은 admin 역할 필요, 개인 기록은 로그인한 계정 소유 데이터만 반환합니다. `/health`와 `/health/db`는 공개 상태 확인입니다.

| 용도 | Endpoint |
|---|---|
| 상태 | GET /health, /health/db |
| 작품·권 | GET /books, /books/{id}, /volumes, /books/{id}/volumes |
| 장·Reader | GET /chapters, /chapters/{id}, /books/{id}/chapters, /volumes/{id}/chapters |
| 검색 | GET /search?q=...&book_id=...&volume_id=...&chapter_id=...&pov=...&limit=20&offset=0 |
| FTS | GET /search?q=...&mode=fts |
| 동기화(인증) | POST /sync/github, GET /sync/status |
| QA | POST /qa/run(인증), GET /qa/issues, PATCH /qa/issues/{id}(인증) |
| 용어 | GET /terms, POST /terms, PUT/DELETE /terms/{id}(변경은 인증) |
| 독서 위치(인증) | GET/PUT /reading/progress |
| 북마크·메모(인증) | GET/POST /bookmarks, PATCH/DELETE /bookmarks/{id} |
| 분석 | GET /analysis/overview, /analysis/books/{id} |
| RAG(인증) | GET /rag/status, POST /rag/index, POST /ask |

한국어의 조사·어미 때문에 FTS 토큰 일치만으로는 누락이 생길 수 있습니다. 기본 검색은 literal ILIKE이고 `%`, `_`도 와일드카드가 아닌 실제 문자로 검색합니다. FTS는 선택적 최적화입니다. 장 이전/다음은 활성 장의 자연 정렬 순서로 계산합니다.

## QA·독서·분석

QA는 구조/H1/본문, heading 단계, 링크 구문, HTML 주석, reading-nav marker/목차/상대 링크, 파일명, 등록 용어 변형, 긴 중복 문단을 검사합니다. 리터럴 별표를 오류로 단정하지 않습니다. 강조 후보와 반복 문단은 INFO이며 수동 검토가 필요합니다. 자동 수정은 없습니다. 같은 fingerprint의 검토 완료 상태는 재검사해도 보존합니다. 원문 SHA가 바뀐 옛 QA는 현재 목록에서 제외합니다.

동기화는 문단 번호에 따라 ID를 최대한 보존합니다. 줄 추가로 문단 의미가 이동할 수 있으므로 독서 위치와 북마크에는 SHA 변경 경고를 표시합니다. 사라진 문단 FK는 NULL로 바뀌지만 메모와 원래 번호는 보존합니다.

분석의 글자 수는 plain text 공백 포함 길이입니다. 문장 길이/대화 비율/어절 후보는 휴리스틱입니다. 인물 언급은 등록한 person 용어 기준이며 자동 NER/인물 관계망은 MVP에 포함하지 않습니다.

## RAG와 비용

기본 요청:

```json
{"question":"아이언 뱅크와 관련한 본문을 찾아줘","mode":"extractive"}
```

관련 문단을 인용할 뿐 인과관계를 AI가 해석하지 않습니다. 검색 결과가 없으면 “현재 Library 데이터에서 충분한 근거를 찾지 못했습니다.”라고 반환합니다.

```powershell
# 최대 1,000개 변경 문단만; 반복 실행하여 remaining을 줄일 수 있음
.\.venv\Scripts\python.exe -m scripts.rebuild_index --provider local --limit 1000
```

OpenAI 모드는 `OPENAI_API_KEY`와 사용 권한이 있는 `OPENAI_MODEL`을 직접 설정합니다. 공식 Responses API + strict JSON schema와 Embeddings API를 사용합니다. 답변의 source_id 및 정확한 인용문을 실제 제공 문단과 대조하며 유효하지 않으면 답변을 보류합니다. 이 검사는 문장 의미의 완전한 entailment 증명이 아니므로 중요한 해석은 원문과 대조하세요.

```powershell
# 유료: 명시적으로 비용 승인해야 실행됨
.\.venv\Scripts\python.exe -m scripts.rebuild_index --provider openai --limit 1000 --confirm-cost
```

API 색인도 `confirm_cost=true`를 요구합니다. 자동 유료 전체 색인은 하지 않습니다. AI 요청은 상위 5–15개 이내(기본 최대 8개) 문단만 사용하며, 문단당 문맥은 최대 1,500자입니다. 임베딩 입력은 문단 앞 2,000자로 제한하고 처리 길이를 저장합니다. 원문이 바뀐 stale embedding은 검색에서 제외합니다.

벡터는 JSON에 저장하고 pgvector 설치 시 SQL `vector(dim)` cast + cosine distance로 검색합니다. 현재는 **exact search**, native vector column/HNSW 대규모 인덱스는 후속 최적화입니다. 벡터 후보는 기본 최대 5,000개로 제한되며 응답에 스캔 수/한도를 표시합니다. 대규모 의미 검색 운영 전 native vector/HNSW와 비용·검색 품질 평가를 추가하세요. pgvector가 없으면 제한된 Python 코사인 검색을 사용합니다. 일반 /search는 LLM 장애와 무관하게 작동합니다.

공식 근거: [Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create), [Embeddings](https://developers.openai.com/api/docs/guides/embeddings), [pgvector](https://github.com/pgvector/pgvector).

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pip check
# 운영 DB가 아닌 전용 테스트 DB만 사용
$env:TEST_DATABASE_URL = "postgresql+psycopg://library_test:your-password@127.0.0.1:5432/library_app_test"
.\.venv\Scripts\python.exe -m pytest -ra
```

TEST_DATABASE_URL이 없으면 실제 PostgreSQL 검사는 명시적으로 skip합니다. CI는 Python 3.11/3.12에서 migration/모델 일치, isolated schema upgrade→downgrade→upgrade, 외래 키, 실제 Uvicorn HTTP, FTS, pgvector SQL retrieval까지 검사합니다. OpenAI는 HTTP mock으로 비용 없이 계약/오류/출처 guardrail을 검사하며 실제 유료 연결 성공으로 간주하지 않습니다.

Windows의 기본 임시 폴더에 권한 문제가 있을 때만 새 작업용 폴더를 사용하세요.

```powershell
$temp = Join-Path $PWD ("work/pytest-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temp -Force | Out-Null
.\.venv\Scripts\python.exe -m pytest -ra --basetemp $temp
```

`scripts.smoke_demo`는 실행 중인 API와 실제 데이터를 사용해 10개 Streamlit 화면을 AppTest로 확인합니다. 같은 ADMIN_TOKEN 환경 변수를 사용하는 별도 터미널에서 실행합니다. 원본·개인 기록을 수정하지 않는 검사입니다.

## 향후 개선

작품별 세부 접근 정책, MFA/SSO, native vector/HNSW, 형태소·NER, 긴 문단의 토큰 기반 chunking, 대규모 검색 품질·비용 평가, background job queue, 운영 환경별 자동 백업 스케줄 등록. 원본 자동 편집/commit/push는 초기 앱 범위 밖입니다.
