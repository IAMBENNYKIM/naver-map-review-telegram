# ROADMAP.md — 개발 로드맵 (진행 상태의 단일 진실 공급원)

**현재 상태: MVP + 웹 진입점 모두 라이브 (2026-07-07).** Telegram 봇(`naver-map-review-telegram`) 운영 중 + 웹 진입점(`naver-review-web` 스택 + Vercel `benny-naver-review.vercel.app`) 배포·CORS 축소·프로덕션 E2E 확인 완료. Phase 0~5 전부 닫힘. 2026-07-09 명세·스킬 체계화(단일 원천 재편, `/deploy-*`·`/verify`·`/delegate` 스킬, 에이전트 정의 현행화) 완료. 이후 작업은 백로그(Phase 6+) 참조.

작업 완료 시 체크박스를 갱신한다. 태스크 담당: A=Advisor 직접, D=worker-dev, S=worker-scraper.

## Phase 0 — 문서·골격 재구축

- [x] 0-1 (A) 명세 문서 작성: CLAUDE.md, REQUIREMENTS.md, PRD.md, ROADMAP.md, ARCHITECTURE.md
- [x] 0-2 (A) Worker 에이전트 정의: `.claude/agents/worker-dev.md`, `.claude/agents/worker-scraper.md`
- [x] 0-3 (D) ref 모듈 이식 + 2-Lambda 반영: `config.py`, `telegram_sender.py`, `review_formatter.py`, `webhook_handler.py`, `worker_handler.py`(신규), `dynamo_writer.py`, `template.yaml`, `samconfig.toml`, `requirements.txt`, `.env.example`, `tests/` 기본
- [x] 0-4 (A) 검증: `pytest tests/` 41개 통과, `sam validate --lint` 통과, diff 확인 → 커밋

## Phase 1 — 스크래핑 확정 ⚠️ 게이트

- [x] 1-1 (S) naver.me 리다이렉트 추적 → place_id 추출 규칙 실측 확정 (`pinId` 쿼리 파라미터)
- [x] 1-2 (S) 리뷰 엔드포인트·페이지네이션·응답 스키마 실측 확정 (`experiments/findings.md`, 덤프 검증 완료)
- [x] 1-3 (A) 게이트 판정: **httpx 단독 구현 가능 — Playwright 불필요** (50건 덤프 직접 검증)
- [x] 1-4 (D) `naver_review_collector.py` 구현: place_id 해석 + 리뷰 50개 수집 + 파서, mock 단위 테스트 + `-m live` 실측 테스트
- [x] 1-5 (A) 검증: 실제 URL로 리뷰 50개 수집 직접 실행 확인 → 커밋
  - 2026-07-04 1차 시도: resolve_place 성공(pinId 33099281), fetch_place_detail에서 429 — 탐사 시 인트로스펙션이 유발한 IP 쿨다운 미회복. 코드는 설계대로 무재시도 즉시 중단
  - 종결: 4-4 재배포 E2E(소이빙수, Lambda 전 구간 31.8s 성공) + 5-7 라이브 수집(행복치킨 정자점 49/50건)으로 실URL 수집 검증 완료

## Phase 2 — 분석·응답 파이프라인

- [x] 2-1 (D) `review_analyst.py`: Claude JSON 구조화 출력(총평·장단점·메뉴별 추천도), 파싱 실패 폴백
- [x] 2-2 (D) `review_formatter.py`: 분석 JSON → MarkdownV2 응답 포맷 (캐시 히트 문구 포함)
- [x] 2-3 (D) `command_router.py`: URL 추출, /update·/start·/help 라우팅, Worker 이벤트 계약 (Phase 0에서 선반영 완료)
- [x] 2-4 (A) 검증: 실측 리뷰 덤프(50건)를 MockTransport로 프로덕션 파서에 통과 + Claude 실호출 — 요약·메뉴 추천 품질 우수 확인, 이스케이프 정상 → 커밋

## Phase 3 — 캐시·/update 흐름

- [x] 3-1 (D) `dynamo_writer.py`: 캐시 read/write, `last#<chat_id>` 항목, float→Decimal (Phase 0에서 선반영)
- [x] 3-2 (D) `worker_handler.py` 통합: 캐시 히트/미스/update 분기 완성 (Phase 2에서 선반영)
- [x] 3-3 (A) 검증: moto·mock으로 3개 시나리오(신규/히트/update) 테스트 커버 확인, 84 passed → 커밋

## Phase 4 — 배포·E2E

- [x] 4-1 (D) SAM 템플릿 최종화: 2-Lambda, IAM 최소권한(invoke·dynamo·secrets), Outputs
- [x] 4-2 (D) `docs/setup-guide.md` 갱신 (2-Lambda 기준)
- [x] 4-3 (A) 배포: Secrets Manager 등록 → `sam deploy --profile naver-review` → setWebhook 등록·검증(ok, 오류 없음)
  - 신규 IAM 사용자 `naver-review-deployer`(AdministratorAccess)로 배포. TELEGRAM_WEBHOOK_SECRET는 비어 있던 것을 64자 랜덤으로 채움
  - WebhookApiUrl: `https://5q69qs7tq3.execute-api.ap-northeast-2.amazonaws.com/webhook`
- [x] 4-4 (A) E2E: 최초 배포 후 실기기 테스트에서 429 실패 발견 → 원인 규명·수정·재배포 → Lambda 직접 호출로 전 구간 성공 검증(소이빙수, 31.8s, 에러 없음)
  - **버그①(핵심)**: config가 모바일 호스트 m.place에 데스크톱 UA를 보내 429 차단 → 모바일 UA로 수정(실측: 데스크톱 429/모바일 200). collector 테스트가 전부 Mock이라 미검출
  - **버그②**: 시크릿 TELEGRAM_DEVELOPER_CHAT_ID에 따옴표 포함 → 에러 알림 400. 따옴표 제거
  - **보안**: httpx 오류 문자열로 봇 토큰이 CloudWatch 로그에 노출 → _redact_token으로 가림. (기노출 토큰은 사용자 BotFather 재발급 권장)
  - 종결: 이후 실사용 운영(캐시 히트·/update 포함)으로 잔여 시나리오 확인 완료

## Phase 5 — 웹 진입점 (Telegram 외 진입 경로, 격리 신규 스택)

브레인스토밍·설계: `~/.claude/plans/temporal-orbiting-wand.md`. 목표=지인 확산용 웹(PWA) 진입점. 제약=기존 Telegram 봇 영향 0(별도 SAM 스택 `naver-review-web`), 비용 통제. 초점=**확장성 우선**(일일 쿼터는 Phase 6). 응답 구조=**비동기 잡+폴링**(캐시 미스 파이프라인 ~30초 → API GW 타임아웃 회피, 기존 2-Lambda 비동기 계승).

- [x] 5-0 (A) 브레인스토밍·격리/비용/UI 결정 확정, 비동기 잡+폴링 확정, 플랜 승인 (2026-07-06)
- [x] 5-1 (D) 웹 코어 로직: `config.py` 확장(web 시크릿·테이블·킬스위치), `web_store.py`(jobs/usage/web캐시/prod 읽기전용 read-through), `web_auth.py`(세션토큰·초대코드·admin) + moto·단위 테스트 (커밋 0538b1b)
- [x] 5-2 (D) Lambda 핸들러+인프라: `web_api_handler.py`(라우팅·초대/세션/잡생성/폴링/admin), `web_worker_handler.py`(resolve→캐시→collector→analyst→잡결과·사용량), `template-web.yaml`(WebApi+WebWorker 2함수·3테이블·IAM 최소권한·Budget Alarm·킬스위치) + 테스트
- [x] 5-2b (D) **배포 패키지 250MB 초과 긴급 수정**: 배포 Python 13개+`requirements.txt`를 `src/`로 이동, 두 템플릿 `CodeUri: src/` → 함수당 44MB (원인: 루트 `CodeUri: .`가 `.venv`·`web-frontend/node_modules`·`.git` 포함, sam build는 .gitignore 무시). 커밋 5457031. 교훈은 `docs/setup-guide.md` §8·`CLAUDE.md` #14에 반영
- [x] 5-3 (A) 백엔드 검증: Advisor 직접 `pytest tests/` 152 passed, `sam validate --lint -t template-web.yaml` valid 확인 → 커밋. (배포·실AWS E2E는 5-5)
- [x] 5-4 (D) Next.js 15/shadcn PWA: 초대 게이트 + URL 입력 + 결과 카드(review_analyst JSON 렌더) + 폴링 + 관리자 통계 페이지, 웹 공유 타겟 (`web-frontend/`, npm run build/lint 통과, 커밋 952662f)
- [x] 5-5 (A) E2E 검증·배포 (런북·함정은 `docs/setup-guide.md` §8):
  - [x] 백엔드 배포: 시크릿 `naver-review/web` 생성 → `sam build -t template-web.yaml` → `sam deploy --stack-name naver-review-web`(‑t 없이·`--parameter-overrides` 명시) 성공, `WebApiUrl` 확보 (250MB 이슈는 5-2b로 해결)
  - [x] 프론트 배포: Vercel Import(Root=`web-frontend`, `NEXT_PUBLIC_API_BASE_URL`=WebApiUrl) 성공. **프로덕션 반영은 `main` 병합 필요** — feature 브랜치 push는 Preview만 생성(Vercel Production Branch=main). `main` ff/rebase 후 push로 프로덕션 배포 완료. URL은 `benny-naver-review.vercel.app`(Vercel 프로젝트 rename)
  - [x] 웹 신규 분석 E2E 확인: 붙여넣기 → 요약 정상 동작 (프로덕션 URL)
  - [x] CORS 축소: `AllowedOrigin=https://benny-naver-review.vercel.app`로 재배포 완료 (`WebHttpApi`만 `UPDATE_COMPLETE`, 스택 격리 유지 — Telegram 무손상)
  - [x] 잔여 검증: 사용자 프로덕션 E2E "잘 동작" 확인 (붙여넣기·복사·공유·갱신·관리자·분석)

- [x] 5-6 (A) 웹 UX 개선 6종 (Telegram 패리티, 2026-07-07):
  - **URL 확정(#1)**: `benny-naver-review.vercel.app` (Vercel 프로젝트 rename). 코드 브랜딩은 이미 중립.
  - **결과 복사(#2)·공유(#3)**: `ResultCard` 액션바 — 복사하기(평문 클립보드, `summary-text.buildShareText`가 Telegram 포맷 이스케이프 없이 재현) + 공유하기(Web Share API, 미지원 시 복사 폴백). Kakao SDK 리치공유는 백로그.
  - **붙여넣기 URL 자동감지(#4)**: 입력 Textarea 전환, 공유 텍스트 통째 붙여넣기 → `extractNaverUrl` 추출.
  - **갱신 시점·갱신 버튼(#5)**: `updated_at`을 `/result`까지 전파(백엔드 `save_web_summary`→`complete_job`) + `force_refresh`로 캐시 무시 재분석(Telegram `/update` 패리티).
  - **관리자 링크(#6)**: `/admin` 진입 링크 추가(페이지는 기존).
  - worker-dev 2병렬(백엔드/프론트) → Advisor 검증(`pytest` 156 passed / `next build` 통과) → 커밋 `000b3fa`(백엔드)·`fd8e7d7`(프론트), `main` 반영.

- [x] 5-7 (A/D) 관리자 통계 강화 + 초대 페이지 설명 3종 (2026-07-07):
  - **관리자 통계 일별 시계열(#1)**: `web_store.log_usage`에 `req#YYYY-MM-DD`·`llm#YYYY-MM-DD` 일별 최상위 카운터를 `ADD`로 누적(새 테이블·인프라 무변경, 스키마리스), `summarize_usage_item`으로 `/admin/stats`에 `daily` 배열 제공. 프론트: 연월 구간 필터·지표 토글(총요청/LLM/둘다)·표 범위 연동 + recharts 사용자별 일별 꺾은선(총요청 실선·LLM 점선). 커밋 `89324e8`(백엔드)·`aabf6df`(프론트).
  - **관리자 나가기(#2)**: `/admin`에 "← 홈으로" 링크 + "나가기"(토큰·상태 초기화).
  - **초대 페이지 설명(#3)**: 실측 확정 사실만으로 작동 방식·신뢰 설명 추가. **정렬 실측**: 우리 GraphQL은 정렬 파라미터 없이 네이버 기본=**최신순**을 받는다(덤프 방문일 내림차순 + 라이브 `naver.me/G58TjgA7` 재확인). 네이버 UI 기본은 추천순이라 다름 → "리뷰 탭 정렬을 '최신순'으로 바꿔 대조"로 안내. 메뉴 언급 숫자 출처=리뷰 탭 '메뉴' 칩.
  - 검증(Advisor 직접): `pytest tests/` 160 passed, `npm run build`·`lint` 그린, diff·계약(`daily`) 대조 완료.
  - **배포 완료(2026-07-07)**: 백엔드 `naver-review-web` 재배포 — 파라미터 7개 현행값 그대로 명시(CORS 축소값·예산 유지), 변경은 `WebApiFunction`·`WebWorkerFunction` 코드에만 국한(테이블·IAM·API GW 무변경), Telegram 스택 무영향(격리 유지). 배포 함수 invoke 스모크 정상(무인증 401). 프론트 `main` ff 병합·push(`dd5e8da..b971ad4`)로 Vercel 자동 배포. **잔여: 사용자 프로덕션 E2E 확인.**

## 백로그 (MVP 이후, VOC 기반 결정)

- per-identity 일일 쿼터 (Phase 6 — 웹 확산 시. 5-1 사용량 카운터 재사용)
- 카카오 소셜 로그인 전환 / 카카오 채널·알림톡
- 카카오 SDK 리치 공유(피드 템플릿) — 카카오 개발자 앱 등록·JS키·도메인 등록 필요 (현재는 Web Share API로 대체)

- 장소명 텍스트 검색 (URL 없이)
- 개인 리뷰 기록/조회 (/review, /review_update — UC-3)
- 블로그 리뷰 수집 확대
- 캐시 자동 만료(TTL) 재검토
