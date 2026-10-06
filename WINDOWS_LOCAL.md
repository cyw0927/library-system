# Windows 로컬 실행

Python 3.12와 Docker Desktop을 사용해 검증한 실행 방법입니다.
작업 폴더는 `C:\dev\library-system`입니다. `.env`, 가상환경, DB 볼륨,
도서 캐시, 실행 로그와 자격증명은 Git에 저장하지 않습니다.

## 설치

```powershell
Set-Location C:\dev\library-system
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . -r requirements-dev.txt -c requirements-windows.txt
.\.venv\Scripts\python.exe -m pip check
# .env가 없을 때만 복사합니다. 기존 설정을 덮어쓰지 마세요.
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

`.env`에서 `POSTGRES_PASSWORD`에 로컬 전용 비밀번호를 지정하고,
`DATABASE_URL`에도 같은 비밀번호를 사용합니다. Docker DB 주소는
`127.0.0.1:5433`, 사용자와 DB 이름은 `library_app`입니다.
도서 원본 설정은 `GITHUB_REPOSITORY=cyw0927/library`, `GITHUB_BRANCH=main`입니다.

공개 API 접근이 가능하면 `GITHUB_TOKEN`은 비워둡니다.
API가 404를 반환하고 기존 Git 로그인으로 접근 가능한 경우에만
`GITHUB_USE_GIT_CREDENTIALS=true`로 기존 Git Credential Manager 로그인을 사용합니다.
새 토큰을 만들거나 자격증명을 문서와 로그에 적지 않습니다.
`OPENAI_API_KEY`는 비워두어도 Reader, Search, QA와 무료 본문 발췌가 동작합니다.

## DB와 최초 동기화

시스템에 `DEBUG=release`가 설정된 경우 앱의 boolean 설정과 충돌합니다.
아래 설정은 현재 PowerShell 프로세스에만 적용합니다.

```powershell
$env:DEBUG = 'false'
$env:PYTHONUTF8 = '1'
docker compose up -d db
docker compose ps
# DB가 healthy 상태인지 확인한 다음 실행합니다.
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m scripts.enable_pgvector
.\.venv\Scripts\python.exe -m scripts.discover
.\.venv\Scripts\python.exe -m scripts.initial_sync
```

각 명령의 성공 여부를 확인한 뒤 다음 명령을 실행합니다.
기존 DB를 초기화하거나 migration을 downgrade하지 않습니다.

선택적으로 `GITHUB_CACHE_DIR`을 지정할 수 있습니다. 캐시는 원본 Git blob과
SHA가 일치할 때만 사용됩니다. Windows의 `core.autocrlf=true` checkout은
줄바꿈 때문에 SHA가 달라질 수 있습니다. 원본 바이트를 보존하려면
읽기용 clone에서 `git -c core.autocrlf=false archive`로 별도 캐시를 만들고
그 추출 경로를 지정합니다. 원본 저장소 파일을 수정하지 않습니다.

## 실행과 재실행

```powershell
.\scripts\Start-Library.ps1
```

도우미는 프로젝트 폴더로 이동하고 현재 프로세스의 `DEBUG=false`와 UTF-8을
설정한 뒤 Docker DB와 공식 `scripts.dev`를 실행합니다.
이미 서버가 실행 중이면 먼저 해당 개발 서버를 종료하세요.
Ctrl+C로 API와 Reader를 종료할 수 있습니다.

- Reader: http://127.0.0.1:8501
- Swagger: http://127.0.0.1:8000/docs
- DB health: http://127.0.0.1:8000/health/db
- 서버 로그: `work/api.log`, `work/frontend.log`

`requirements-windows.txt`는 Windows에서 차단된 pandas 3.0.6 DLL 대신
이 PC에서 검증된 2.2.3을 사용하도록 설치 시 버전을 제한합니다.
Windows 보안 정책과 시스템 전체 환경 설정은 변경하지 않습니다.

## 테스트

로컬 `.env`의 빈 토큰 값이 파일 기반 secret 테스트보다 우선하므로,
전체 테스트는 `.env`가 없는 `work` 폴더에서 실행합니다.
개발 DB를 `TEST_DATABASE_URL`로 지정하지 않습니다.

```powershell
Set-Location C:\dev\library-system
$env:DEBUG = 'false'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = (Get-Location).Path
New-Item -ItemType Directory -Path work -Force | Out-Null
Push-Location work
try { ..\.venv\Scripts\python.exe -m pytest ..\tests -ra }
finally { Pop-Location }
```

2026-10-06 검증 결과: 115 passed, 33 skipped.
Skip은 별도 PostgreSQL 테스트 DB 미설정에 따른 것입니다.
실제 DB 마이그레이션, HTTP health, 도서 본문, 일반 검색, FTS,
무료 본문 발췌 및 Streamlit 10개 화면은 별도로 검증했습니다.
동기화 결과는 8권, 20권 구성(Volume), 1,265장, 95,536문단이며 오류는 0건입니다.
원문 QA의 검토 항목 44건은 자동 수정하지 않았습니다.
