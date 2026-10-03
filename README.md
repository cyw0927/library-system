# Library App

GitHub `cyw0927/library`의 Markdown 자료를 읽기 전용으로 수집하고 구조화·검색·검증하기 위한 개인 전자도서관입니다. 앱 코드는 `cyw0927/library-system`에서 관리합니다.

현재 구현 범위는 **Phase 1 — Foundation**입니다. GitHub는 원본이며 PostgreSQL은 향후 검색·분석용 파생 데이터 저장소로 사용합니다.

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
alembic/        # migration 환경 (현재 도서 테이블 없음)
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
- [ ] Phase 2: Book, Volume, Chapter, Paragraph, SyncState
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

Phase 1에는 도서 모델과 revision이 없습니다. 위 명령은 실제 DB 연결과 migration 환경을 검증하며 Alembic의 버전 관리 테이블만 생성할 수 있습니다. Phase 2 지시를 받은 뒤 모델과 첫 revision을 추가합니다.

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

일반 테스트는 SQLite 세션을 주입하여 API 성공·실패, 설정 검증, 세션 정리와 롤백을 검사합니다. 테스트 DB를 지정하지 않으면 PostgreSQL 통합 테스트 2개는 명시적으로 skip됩니다.

실제 PostgreSQL 통합 테스트에는 **전용 테스트 DB**를 사용합니다. 개발/운영 DB를 사용하지 마세요. Alembic이 버전 테이블을 만들 수 있습니다.

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://library_test:your-password@127.0.0.1:5432/library_app_test"
.\.venv\Scripts\python.exe -m pytest -ra -s
```

GitHub Actions는 Python 3.11/3.12와 PostgreSQL 18에서 전체 테스트를 실행합니다. CI는 URL 인코딩된 비밀번호, `alembic upgrade head`, 실제 Uvicorn 기동, HTTP `/health`·`/health/db` 응답을 확인합니다. CI 코드에는 임시 테스트 서비스 전용 비밀번호만 포함됩니다.

## 개발 단계

Phase 1 검증 후 사용자의 다음 지시가 있을 때 Phase 2의 핵심 모델과 migration을 구현합니다. 이후 Sync, Markdown Parser, 데이터 매핑·Import, Reader API, 검색, Streamlit, QA 순으로 진행합니다. AI RAG는 마지막 단계입니다.
