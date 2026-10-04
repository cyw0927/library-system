# 무료 전용 Library App — 인수 범위

원래 명세의 MVP 완료 기준입니다. 예시 데이터 수치를 코드에 고정하지 않으며, 책 원본 `cyw0927/library`는 읽기 전용입니다.

| 범위 | 구현/검증 근거 |
|---|---|
| Phase 1–2 foundation/DB | health, PostgreSQL, Alembic 0001–0009; test_health/config/session/models + 실제 DB migration roundtrip |
| Phase 3–6 수집/파싱/매핑/실제 import | SHA 검증, commit 고정, 증분 처리, README metadata, 삭제 감지, 부분 실패 보존; test_github/parser/metadata/sync |
| Phase 7 도서 API | book/optional volume/chapter/paragraph, 활성 필터, 이전/다음, 고정 출처; test_library_api |
| Phase 8 검색 | AI 독립 ILIKE/필터/문단 출처, PostgreSQL FTS; test_search + integration/test_search_vector |
| Phase 9 Reader | Library/Book/Reader/Search, 글자 크기/줄간격/폭/다크; test_frontend + 실제 API AppTest |
| Phase 10 번역 QA/용어 | 구조/Markdown/navigation/filename/등록 용어/중복, 검토 상태 보존, 자동 수정 없음; test_qa |
| Phase 11 독서 | 개인 진행/읽은 장/북마크/메모, 원문 변경 경고; test_reading/auth |
| Phase 12 분석 | 글자/장 길이/POV/등록 인물·용어/어절 후보; test_analysis |
| Phase 13 무료 부분 | 본문 인용/출처/근거 부족, lexical vector; test_rag/deployment. **유료 AI 제외** |
| 로그인/권한 | 초대형 admin/reader, 세션 만료/폐기, 계정 잠금, 개인 기록 분리; test_auth, 19개 인증 화면 AppTest |
| 배포 준비 | standalone localhost-only TLS, non-root/read-only, owner/runtime DB 권한 분리, digest pin, bounded logs; production-smoke |
| 백업/복구 | 원본 보존, SHA manifest, 새 빈 DB 복구, session 제외, 지속 volume/job/monitor/timer 템플릿; test_operations/deployment + 실제 PostgreSQL/컨테이너 복구 |
| 비용 차단 | PAID_AI_ENABLED=false 기본값/Compose/로컬 설정; 키/관리자/비용 확인이 있어도 유료 요청 거부; test_deployment |
| 보안/점검 | 읽기 전용 preflight, TLS expiry/SAN/key match, live HTTPS, PyPI 의존성 audit; test_deployment + CI dependency-audit |

## 실제 데이터 확인

2026-10-04 원본 snapshot `0bc85e7bc481b72796af8fd4dba68f2ce610f965`에서 7개 작품, 19개 권, 1,022개 장, 86,775개 문단, README metadata 37개를 가져왔습니다. 이는 확인 당시 결과이며 UI의 고정값이 아닙니다. 도서 원본 수정은 없습니다. 기존 pre-auth dump의 별도 DB 복구도 수행했고 원본 도서 수치를 보존했습니다.

## 완료와 실제 운영의 경계

공개 서버/도메인/신뢰 TLS 발급·갱신, 도서 이용 권한 확인, 실제 운영 secret/첫 계정 입력, 방화벽 공개, 자동 백업 timer 설치·오프사이트 암호화·알림 담당자, OS 이미지 취약점 검사는 운영 환경이 결정되어야 합니다. 제공된 CI는 격리된 임시 스택 검증이며 인터넷 공개 운영을 뜻하지 않습니다. PR은 검토 대상으로 제공하며 자동 병합하지 않습니다.

MFA/SSO, 작품별 ACL, 자동 NER·인물 관계망, native vector/HNSW, job queue는 원래 MVP 밖의 향후 확장입니다. 원본 편집/commit/push와 과금 API 테스트는 수행하지 않습니다.
