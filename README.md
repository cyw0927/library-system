# Library App

GitHub `cyw0927/library`의 Markdown 자료를 읽기 전용으로 수집하고 구조화·검색·검증하기 위한 개인 전자도서관입니다. 앱 코드는 `cyw0927/library-system`에서 관리합니다.

현재 **Phase 1 — Foundation**과 **Phase 2 — Core Database**를 구현했습니다. GitHub는 원본이며 PostgreSQL은 검색·분석용 파생 데이터 저장소로 사용합니다. 원본 데이터 수집은 다음 단계입니다.

## 구조와 구현 상태

```text
GitHub Library (원본)
       ↓
Sync / Markdown Parser (향후)
       ↓
PostgreSQL (파생 데이터)
       ↓
FastAPI → Reader / Search / QA (향후)
```

```text
app/
  main.py
  api/          # /health, /health/db
  core/         # 환경 설정, logging
  db/           # SQLAlchemy Base, engine, request session
    models/     # Book, Volume, Chapter, Paragraph, SyncState
alembic/        # migration 환경
  versions/     # 0001_core_library
tests/          # 단위 테스트
  integration/  # 실제 PostgreSQL, Alembic, Uvicorn HTTP 테스트
.github/workflows/tests.yml
```

- [x] FastAPI 기본 프로젝트와 Swagger UI
- [x] 환경 변수와 .env 설정
- [x] PostgreSQL + psycopg + SQLAlchemy 세션
- [x] Alembic 설정
- [x] GET /health
- [x] GET /health/db: 실제 SELECT 1, 실패 시 503
- [x] pytest 및 PostgreSQL CI 검사 구성
- [x] Phase 2: Book, Volume, Chapter, Paragraph, SyncState 및 첫 migration
- [x] 외래 키·유일성·수치 범위 검사, nullable volume, soft delete 필드
- [ ] GitHub Sync → Parser → Reader → Search → QA
- [ ] 독서 기능 → 분석 → AI RAG

## 기술 스택

Python 3.11+, FastAPI, PostgreSQL 18, SQLAlchemy 2, psycopg 3, Alembic, pydantic-settings, pytest.

## 설치 (Windows PowerShell)

```powershell
git clone https://github.com/cyw0927/library-system.git C:\dev\library-app
Set-Location C:\dev\library-app
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . -r requirements-dev.txt
Copy-Item .env.example .env
```

명령은 프로젝트 루트에서 실행합니다. 이미 clone한 경우에는 해당 폴더를 사용합니다. PowerShell 활성화 정책을 변경할 필요 없이 가상환경 실행파일을 직접 사용할 수 있습니다.

## PostgreSQL 설정

PostgreSQL에서 앱 전용 사용자와 데이터베이스를 만듭니다. 아래는 관리자 계정으로 psql에서 실행할 예시입니다.

```sql
CREATE USER library_app WITH PASSWORD 'replace-with-your-password';
CREATE DATABASE library_app OWNER library_app;
```

`.env`의 `DATABASE_URL`을 실제 접속 정보에 맞게 설정합니다.

```dotenv
DATABASE_URL=postgresql+psycopg://library_app:replace-with-your-password@127.0.0.1:5432/library_app
DATABASE_TIMEOUT_SECONDS=5
```

비밀번호에 `@`, `%`, `/` 같은 문자가 있다면 URL 인코딩합니다. 예를 들어 `%`는 `%25`입니다. 앱은 PostgreSQL psycopg URL을 사용하며, 연결과 쿼리에 제한시간을 적용합니다.

## 환경 변수

| 변수 | 의미 | 기본값 |
|---|---|---|
| APP_NAME | API 문서 이름 | Library App API |
| APP_ENV | 실행 환경 | development |
| DEBUG | 디버그 모드 | false |
| DATABASE_URL | PostgreSQL 연결 URL | .env.example 참고 |
| DATABASE_TIMEOUT_SECONDS | 연결·쿼리 제한시간(1–60초) | 5 |

환경 변수는 `.env`보다 우선합니다. `.env`, 비밀번호, 토큰은 커밋하지 않습니다. 향후 Sync 단계에서 GitHub 인증 설정을 추가합니다.

## Migration

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

첫 revision `0001_core_library`는 `books`, `volumes`, `chapters`, `paragraphs`, `sync_state`를 생성합니다. `alembic check`는 ORM 모델과 실제 schema의 차이가 없는지 검사합니다. 앱 시작 시 `create_all()`을 실행하지 않으며 스키마 변경은 Alembic으로 관리합니다.

## Core Database

| 테이블 | 역할 | 주요 제약조건 |
|---|---|---|
| books | 작품·시리즈 메타데이터 | slug, GitHub path 각각 유일 |
| volumes | 작품 내 권 | 작품 내 slug 유일, GitHub path 유일 |
| chapters | 장·원본 Markdown·SHA | volume nullable, GitHub path 유일 |
| paragraphs | 장 내 문단·검색용 plain text | 장 내 문단 번호 유일, 번호는 1부터 |
| sync_state | 파일별 SHA·동기화 상태 | GitHub path 유일 |

장에는 필수 `book_id`와 선택 `volume_id`가 있습니다. 복합 외래 키로 장과 권이 같은 작품에 속하도록 강제합니다. ORM에서 다권 장을 만들 때는 `Chapter(book=book, volume=volume, ...)`처럼 두 관계를 함께 지정합니다. `chapter_number`는 서문 등 번호 없는 장을 위해 nullable이며, 0은 프롤로그 등에 사용할 수 있습니다.

Book·Volume·Chapter의 `is_active`는 soft delete 용도입니다. 참조 중인 작품·권의 실제 삭제는 DB가 거부합니다. 장을 실제로 삭제하면 그 장의 파생 문단만 cascade 삭제됩니다. 동기화에서는 soft delete를 기본으로 사용하며, 상하위 active 상태 조정은 향후 Sync 서비스가 담당합니다.

생성·수정 시각은 timezone-aware 필드입니다. `updated_at`은 ORM update 시 갱신됩니다. `sort_order`로 권과 장을 정렬하고, 장의 이전/다음은 이후 Reader 단계에서 계산합니다. `paragraph_count`·`char_count`는 파생 값이며 Sync/Parser가 저장 시 계산해야 합니다. 현재 데이터 import나 자동 계산 서비스는 없습니다.

SyncState 상태는 `pending`, `synced`, `error`, `deactivated`입니다. 처음 실패한 파일·README 메타데이터도 추적할 수 있도록 `entity_id`와 `last_synced_at`은 nullable입니다. `entity_type` + `entity_id`는 다형적 참조여서 물리적 외래 키를 두지 않으며, 다음 Sync 단계에서 대상 검증을 구현합니다.

## 실행과 API

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

- Swagger UI: http://127.0.0.1:8000/docs
- `GET /health` → `200 {"status":"ok"}`
- `GET /health/db` → `200 {"status":"ok","database":"ok"}`
- DB 접속 실패 → `503 {"detail":"Database is unavailable"}`

`/health`는 앱 생존 여부를 확인합니다. `/health/db`는 DB 연결을 별도로 검사합니다. DB 장애를 앱 기동 시 숨기지 않고 상태 API로 확인할 수 있습니다. 실패 로그와 응답에는 DB 접속 정보가 포함되지 않습니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest -ra
```

일반 테스트는 SQLite 세션으로 API 성공·실패, 설정, 세션 롤백과 모델 무결성을 검사합니다. 같은 모델 무결성 검사를 실제 PostgreSQL에서도 실행합니다. `TEST_DATABASE_URL`을 지정하지 않으면 PostgreSQL 전용 검사는 명시적으로 skip됩니다.

실제 PostgreSQL 통합 테스트에는 **전용 테스트 DB**를 사용합니다. 개발/운영 DB를 사용하지 마세요. 테스트는 Alembic으로 핵심 테이블을 생성하며 데이터 변경은 테스트별 transaction으로 rollback합니다. Migration 되돌리기 검사는 새 임시 schema 안에서만 실행하고 schema 생성 자체도 rollback합니다. `downgrade base`는 도서 테이블을 제거하므로 실제 데이터가 있는 DB에서 실행하지 마세요.

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://library_test:your-password@127.0.0.1:5432/library_app_test"
.\.venv\Scripts\python.exe -m pytest -ra -s
```

GitHub Actions는 Python 3.11/3.12와 PostgreSQL 18에서 migration 적용, 모델/schema 일치, DB 제약조건, migration 왕복, 실제 Uvicorn 기동 및 `/health`·`/health/db` 응답을 확인합니다. CI 코드에는 임시 테스트 서비스 전용 비밀번호만 포함됩니다.

## 개발 단계

다음은 **Phase 3 — GitHub Tree Sync**입니다. 사용자 지시 후 저장소 tree·Markdown 파일 탐색·SHA 추적을 구현합니다. 이후 Markdown Parser, 데이터 매핑·Import, Reader API, 검색, Streamlit, QA 순으로 진행합니다. AI RAG는 마지막 단계입니다.
