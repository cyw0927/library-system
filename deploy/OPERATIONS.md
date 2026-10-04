# 운영 준비 / 초대형 개인 전자도서관

이 변경은 **배포 준비**이며 외부 공개를 승인하거나 실행하지 않습니다. 모든 작품을 볼 수 있는 초대형 `reader`와 공유 데이터를 관리하는 `admin` 두 역할입니다. 작품별 라이선스/사용자별 도서 접근 정책은 별도입니다. MFA/SSO/메일 비밀번호 재설정은 포함하지 않습니다.

## 로그인과 데이터 경계

- `APP_ENV=production`은 `AUTH_REQUIRED=false`여도 로그인 강제. localhost에서 먼저 시험하려면 `AUTH_REQUIRED=true`.
- 원문·검색·QA·용어·분석 API는 로그인 필요. `/health`, `/health/db`, 로그인은 민감 내용을 반환하지 않는 공개 엔드포인트입니다.
- 독서 위치/북마크/메모는 서버가 세션의 계정 ID로 소유자를 결정. 다른 계정(관리자 포함)은 조회·수정·삭제할 수 없습니다. 제출한 `user_id`는 사용하지 않습니다.
- `admin`: 동기화, QA 실행/검토, 용어 변경, 로컬 벡터 색인. `reader`: 원문/검색/분석/QA/용어 읽기, 자신의 기록, 무료 발췌 Ask. **유료 AI는 현재 제외**: `PAID_AI_ENABLED=false`가 API·CLI·서비스에서 호출을 차단합니다. production Compose도 false로 고정했습니다.
- 공개 가입 없음. 계정은 DB 접근 권한을 가진 운영자가 CLI로 생성. 비밀번호 12–128자, 무작위 16바이트 salt + scrypt N=2^17/r=8/p=1.
- 세션: 256비트 무작위 Bearer, DB에는 SHA-256만 저장. 고정 8시간(1–24시간 설정) 후 만료. 로그아웃/비밀번호 변경/계정 비활성화 시 즉시 폐기. Streamlit 서버의 사용자별 세션 메모리에만 원본 토큰 저장, URL/localStorage/로그에 기록하지 않음. 브라우저 새로고침/서버 재시작 시 다시 로그인할 수 있습니다.
- 계정별 실패 5회 → 15분 잠금(재시작해도 보존); HTTP 응답은 없는 계정/잘못된 비밀번호/비활성화/잠금을 구분하지 않습니다. 별도 socket-peer 제한 20회/분, 프로세스 전체 120회/분, scrypt 동시 실행 최대 2개. Streamlit 이용자는 backend 관점에서 같은 peer 예산을 공유합니다. 분산 배포에는 공유 rate limiter와 외부 IdP/MFA가 필요합니다.
- production은 DEBUG, 기존 ADMIN_TOKEN, Git credential 자동 사용, 빈/짧은 DB 비밀번호, 무제한 Host를 거부합니다. `/docs`, `/redoc`, `/openapi.json` 비활성화. POST validation은 제출 비밀번호를 오류 응답에 반사하지 않습니다.
- development의 AUTH_REQUIRED=false는 기존 로컬 데모 호환용이며, 그 모드를 절대로 인터넷에 공개하지 마세요.

## 로컬 로그인 사용

```powershell
Set-Location C:\dev\library-app
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.accounts create myadmin --role admin
.\.venv\Scripts\python.exe -m scripts.accounts create myreader --role reader
$env:AUTH_REQUIRED = 'true'
.\.venv\Scripts\python.exe -m scripts.dev
```

비밀번호는 터미널의 숨겨진 프롬프트에서 입력합니다. 채팅/명령 인수/commit에 넣지 마세요. 비대화형 secret-manager pipe는 명시적 `--password-stdin`으로만 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m scripts.accounts password myreader
.\.venv\Scripts\python.exe -m scripts.accounts disable myreader
.\.venv\Scripts\python.exe -m scripts.accounts enable myreader
```

마지막 활성 관리자는 비활성화할 수 없습니다. 계정 삭제 대신 비활성화해 메모를 보존합니다. 기존 `local` 독서 기록은 0009 migration에서 **삭제·자동 소유권 변경하지 않습니다**. 원래 소유자가 지정한 계정으로 옮길 때만 다음을 실행합니다. 같은 장의 독서 위치 충돌은 전체 전송을 거부하고 기존 데이터를 그대로 둡니다.

```powershell
.\.venv\Scripts\python.exe -m scripts.accounts claim-local myadmin --confirm-claim-local
```

## Linux Docker Compose 배포 구성

`compose.production.yaml`은 **독립 구성**입니다. 개발용 `compose.yaml`과 합치지 마세요. DB/API/UI 호스트 포트는 없습니다. DB/UI는 내부 네트워크, API는 GitHub/선택적 AI를 위한 outbound 네트워크, nginx는 외부 TLS 수신용 edge 네트워크에 추가 연결합니다. 비특권 앱 UID 10001, 읽기 전용 root filesystem, capability 제거, 상태 검사, DB 영속 volume, 자동 migration 단계를 포함합니다. TLS nginx도 UID 101로 실행합니다.

DB bootstrap 소유자 `library_owner` 자격증명은 DB/일회성 migrate에만 전달합니다. 일회성 bootstrap은 migration·pgvector 설치 후 별도 `library_runtime`을 생성/갱신하고 테이블 DML/sequence 사용만 부여합니다. API에는 runtime 연결만 전달하여 superuser·DB/role 생성·스키마 CREATE·migration version 변경을 막습니다. DB owner 자격증명을 API/UI에 mount하지 마세요. 기존 다른 앱의 역할과 충돌하지 않도록 앱 전용 PostgreSQL cluster 기준입니다.

실제 환경의 Docker build/Compose/인증서/WebSocket은 아래 체크리스트와 CI smoke 결과로 검증한 뒤 공개합니다. 기본 프록시는 **127.0.0.1:8443**만 bind하며 외부 접근이 불가능합니다. 인터넷 공개에는 별도 도메인/방화벽/TLS 설정 승인이 필요합니다.

### 비밀 파일 (Git ignore; 직접 작성)

`deploy/secrets/`:

| 파일 | 내용 / 접근 서비스 |
|---|---|
| `postgres_password` | 무작위 16자 이상 owner DB 비밀번호 / DB만 |
| `migration_database_url` | owner 비밀번호의 `postgresql+psycopg://library_owner:URL_ENCODED_PASSWORD@db:5432/library_app` / migration만 |
| `runtime_password` | owner와 다른 무작위 16자 이상 runtime DB 비밀번호 / migration만 |
| `database_url` | runtime 비밀번호의 `postgresql+psycopg://library_runtime:URL_ENCODED_PASSWORD@db:5432/library_app` / API만 |
| `github_token` | 원본 private repo contents **read-only** 토큰. 공개 repo면 빈 파일 / API만 |
| `streamlit_cookie_secret` | 무작위 32자 이상 / UI만 |

`deploy/tls/fullchain.pem`, `deploy/tls/privkey.pem`: 도메인에 유효한 인증서/개인키. 인증서를 새로 발급하거나 업로드하는 행위는 이 구현이 수행하지 않습니다. 개발 self-signed 테스트와 실제 신뢰 인증서를 혼동하지 마세요.

Linux host에서는 `deploy/`와 비밀 파일의 상위 디렉터리를 owner-only(0700)로 보호합니다. Compose 파일 secrets는 bind mount이므로 `uid/mode`가 적용되지 않을 수 있습니다. 컨테이너 UID 10001/101도 읽을 수 있도록 **보호된 0700 상위 디렉터리 안의 개별 파일**은 read-only 0444로 두거나 UID 기반 ACL을 설정하세요. 일반 공유 디렉터리의 키를 world-readable로 만들지 마세요. Windows에서는 해당 폴더 ACL을 사용자/관리자로 한정합니다. 이미지/build context에는 secret 파일을 포함하지 않습니다.

```bash
export PUBLIC_HOST=your-real-host.example
docker compose -f compose.production.yaml build
docker compose -f compose.production.yaml config --quiet
docker compose -f compose.production.yaml up -d
docker compose -f compose.production.yaml exec api python -m scripts.accounts create myadmin --role admin
docker compose -f compose.production.yaml exec api python -m scripts.accounts create myreader --role reader
docker compose -f compose.production.yaml exec api python -m scripts.initial_sync
docker compose -f compose.production.yaml ps
```

`scripts.initial_sync`는 read-only GitHub → DB입니다. 이전 source DB를 이 운영 DB로 복구할 계획이라면 **빈 대상 DB 복구를 먼저** 하고 그 뒤 migration/app 시작을 수행합니다. migration을 적용해 테이블을 만든 DB에는 restore 안전장치가 복구를 허용하지 않습니다.

OpenAI secrets는 기본 구성에 넣지 않았습니다(자동 과금 방지). 추후 API 키 연결 승인 시 `openai_api_key` 파일을 **api에만** 추가 mount하고 모델 설정을 추가합니다. UI에 GitHub/DB/OpenAI 비밀을 넘기지 마세요.

### 외부 공개 전 체크리스트

- [ ] 사용 권한/저작권 확인: 모든 초대 reader가 원문을 볼 수 있어도 되는지 확인.
- [ ] production mode, 기존 ADMIN_TOKEN 제거, 강한 계정/DB 비밀번호, secrets 권한 확인.
- [ ] DB 사용자 최소 권한: 제공 bootstrap으로 owner/runtime 분리 확인. API current_user=library_runtime, superuser=false, public schema CREATE=false, alembic_version UPDATE=false.
- [ ] 실제 도메인의 신뢰 TLS, 인증서 갱신, nginx `-t`, WebSocket/로그인/로그아웃 확인.
- [ ] 독립 운영 Host allowlist, API/UI/DB 포트가 외부에 직접 노출되지 않는지 확인.
- [ ] 무인증 API 401, reader 관리자 동작 403, 다른 사용자 메모 404, 만료·폐기 세션 401.
- [ ] 백업 생성·다른 빈 DB 복원·메모 확인. 백업 암호화와 별도 장치/서버 보관.
- [ ] DB/backup 디스크 용량, 로그 회전/상태 모니터링과 담당자, 보존 기간 설정.
- [ ] 이미지/OS 의존성 취약점 검사. Python/nginx/pgvector 이미지는 확인한 multi-platform digest로 고정했고 CI는 실제 앱 이미지의 Python 패키지도 검사합니다. OS 패키지/CVE 전체 검사, 이미지 서명 검증은 실제 서버의 추가 배포 조건입니다. digest 고정은 업데이트를 대신하지 않으므로 갱신 때 검사/전체 CI를 재실행하세요.
- [ ] 외부 공개 설정(예: 프록시만 `443:8443`)을 별도 검토·승인. 앱이 자동으로 포트를 열지 않습니다.

## 백업 / 안전한 복구

PostgreSQL **18 client**를 사용합니다. Docker 앱 이미지에 pg_dump/pg_restore 18 포함. 원본은 다시 받을 수 있지만 독서 기록·메모·용어·계정은 반드시 DB 백업이 필요합니다. custom-format archive + SHA-256 manifest를 생성하고 기존 파일은 절대 덮어쓰지 않습니다. 로그인 세션 데이터는 제외합니다. SHA는 손상 검사이지 서명/진위 증명이 아닙니다. **신뢰하는 본인 백업만** 복원하세요. pg_restore archive는 SQL 실행이 가능합니다.

```powershell
# 로컬 Windows: backup 폴더의 ACL도 본인/관리자만으로 제한
.\.venv\Scripts\python.exe -m scripts.backup create backups\library-20261004.dump --pg-bin 'C:\Program Files\PostgreSQL\18\bin'
# 새 빈 DB를 별도로 만든 뒤 비밀번호를 환경에만 지정. 운영 DB 이름과 달라야 함.
$env:RESTORE_DATABASE_URL = 'postgresql+psycopg://app:URL_ENCODED_PASSWORD@127.0.0.1:5432/library_restore_20261004'
.\.venv\Scripts\python.exe -m scripts.backup restore backups\library-20261004.dump --pg-bin 'C:\Program Files\PostgreSQL\18\bin' --confirm-empty-restore
```

복구 도구는 DB 이름이 원본과 같거나 대상에 사용자 테이블/뷰/sequence가 있으면 거부합니다. `DROP`, `--clean`, 원본 덮어쓰기 없음. 복구는 single transaction + exit-on-error, 세션 모두 폐기. 성공 후 별도 DB에서 모델/migration/read API와 기록을 확인한 다음에만 DATABASE_URL 전환. 전환 전에는 두 DB에 새 메모를 쓰지 않도록 앱을 정지합니다.

로그인 도입 전(0008 이하) 백업도 복구할 수 있습니다. 복원된 원래 revision을 보존하며, `login_sessions`가 없는 이전 백업에는 세션 UPDATE를 실행하지 않습니다. 복구 검증 후 `alembic upgrade head`를 적용하세요.

컨테이너에서 백업을 export할 때는 archive와 `.json` manifest를 모두 가져와야 합니다. read-only root인 API `/tmp`는 임시 공간이므로 **검증 후 host/별도 저장소로 옮긴 뒤** 컨테이너를 재시작하세요. 운영에서는 전용 backup volume/백업 작업 컨테이너에 영속 경로를 mount하는 것을 권장합니다. 비밀번호는 argv가 아닌 libpq 환경에 전달하고 오류 로그에는 DB URL을 출력하지 않습니다.

지속 백업 작업과 일일 timer 템플릿은 아래에 제공합니다. 실제 스케줄 등록·보존 삭제·원격 업로드는 설치하지 않았습니다. 최소 하루 1회 및 migration 전 백업, 주기적인 별도 DB 복구 훈련을 권장합니다. DB dump는 cluster 역할/권한을 복원하지 않으므로 운영 역할 DDL은 별도 안전한 IaC로 보관합니다.

## 배포 전 사전 점검 (읽기 전용)

```bash
python -m pip install -r requirements-ops.txt
python -m scripts.deployment_check --host your-real-host.example
# 서버를 별도 승인받아 시작한 뒤: 기본 CA 검증을 사용, TLS 우회 옵션 없음
python -m scripts.deployment_check --host your-real-host.example --live-url https://your-real-host.example
```

secret 파일 누락/역할·비밀번호 불일치/짧은 키, Unix parent 권한, localhost-only 포트, paid AI 차단, 이미지 digest, 로그 회전, TLS 개인키 일치·SAN hostname·14일 내 만료를 점검합니다. 실패하면 exit 1, 비밀 값은 출력하지 않습니다. `--root`로 검사할 checkout을 명시할 수 있습니다. 파일 검사 성공은 공개 CA 신뢰/인증서 갱신/방화벽/도서 이용 권한의 증명이 아닙니다. `--live-url`은 신뢰 TLS, DB health 200, 무인증 책 API 401, docs 404를 GET으로 확인합니다. Windows ACL 검사는 별도입니다. 이 도구는 서비스를 띄우거나 포트를 열지 않습니다.

## 지속 백업과 상태 확인

```bash
# 정상 운영 DB가 이미 시작된 뒤; 기존 백업 삭제/덮어쓰기 없음
docker compose -f compose.production.yaml --profile operations run --rm --no-deps backup
# 새 컨테이너에서도 같은 production_backups volume을 조회
docker compose -f compose.production.yaml --profile operations run --rm --no-deps backup \
  python -m scripts.backup_job --directory /backups --check-only
```

새 named volume은 이미지의 `/backups` UID 10001 권한을 상속합니다. 기존/외부 volume 권한이 다르면 실패하며 자동으로 넓히지 않습니다. job은 UTC timestamp + UUID 파일명, 최소 1GB 여유 공간, dump/manifest 검증을 사용합니다. `--check-only`는 기본 26시간 내 최신 백업과 checksum/여유 공간을 확인하고 실패 시 exit 1을 반환합니다. 빈/오래된/손상된 백업을 정상으로 표시하지 않습니다. 이 검사는 실제 복구 훈련을 대신하지 않습니다.

archive와 manifest는 컨테이너가 아니라 `production_backups`에 유지됩니다. 이는 DB와 **같은 서버의 미암호화 백업**이므로 서버 장애/침해 대비에는 충분하지 않습니다. 관리자만 접근하고 암호화된 별도 장치/서버로 둘 다 export해야 합니다. 보존 삭제·원격 업로드는 자동 수행하지 않습니다. 디스크 알림과 보존 계획을 운영자가 정하세요. `docker compose down --volumes`는 DB와 백업을 지울 수 있으므로 운영에서 실행하지 마세요.

로컬 Windows에서도 같은 도구를 쓸 수 있습니다:

```powershell
.\.venv\Scripts\python.exe -m scripts.backup_job --directory backups --pg-bin 'C:\Program Files\PostgreSQL\18\bin'
.\.venv\Scripts\python.exe -m scripts.backup_job --directory backups --check-only
```

## 주기 실행과 로그

`deploy/systemd/library-backup.service` / `.timer`는 **미설치 템플릿**입니다. 승인된 Linux 서버에서 WorkingDirectory·PUBLIC_HOST·시간대·실패 알림을 설정하고 수동 백업/복구를 확인한 후에만 등록하세요. 기본 시간은 서버 시간대의 매일 03:00 + 15분 이내 jitter, 놓친 작업은 Persistent=true로 재개합니다. Docker 접근은 root에 준하므로 서비스 파일/checkout은 신뢰하는 관리자만 수정할 수 있어야 합니다. 실패 알림 수신자는 정하지 않았으므로 자동 통보를 약속하지 않습니다.

각 컨테이너 로그는 `json-file` 최대 10MB × 3개로 회전합니다. 수치는 컨테이너당 제한이며 DB/backup 데이터 용량 제한이 아닙니다. 운영 health 모니터는 승인된 서버에서 HTTPS preflight와 backup `--check-only`의 exit status를 감시하도록 연결하세요. 별도 프로세스를 이 PC에 등록하지 않았습니다.

## 보안 검사

CI `dependency-audit`는 앱/운영 점검/테스트 패키지의 알려진 PyPI 취약점을 검사합니다. production-smoke는 **빌드한 이미지에 실제 설치된** Python 패키지를 별도로 검사합니다. 결과가 나오면 무시하지 않고 실패 처리합니다. 검사 시 패키지 이름/버전만 공개 취약점 서비스에 전송합니다. 이 검사는 미발견 취약점·OS 패키지·코드 전체 보안 감사의 부재를 보증하지 않습니다.

근거: [Docker 로그 회전](https://docs.docker.com/engine/logging/drivers/json-file/), [pip-audit](https://github.com/pypa/pip-audit), [OpenAI 운영 비용 관리](https://developers.openai.com/api/docs/guides/production-best-practices).

근거: [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html), [PostgreSQL pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html), [pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html), [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).
