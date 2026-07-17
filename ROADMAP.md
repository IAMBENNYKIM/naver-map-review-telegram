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

- [x] 5-8 (A/D) 장소 텍스트 검색 (URL 없이, 2026-07-17):
  - **기능**: 자연어 프롬프트 → LLM 검색어 정규화 → 네이버 instant-search 후보 리스트 → 후보 클릭 시 `place_id` 직행 분석. LLM은 검색어 변환만 담당, 후보는 네이버 결과만 사용(환각 0).
  - **백엔드**: `POST /search` 신설(WebApiFunction 동기 처리, `{prompt}`→`{keyword, places[]}`), `POST /analyze`가 `naver_url` **또는** `place_id`(`^\d+$`, 우선) 수용 + Worker 이벤트에 `place_id`(수신 시 `resolve_place` 생략). 신규 `search_normalizer.normalize_search_query`(모델 `claude-haiku-4-5`, timeout 5초·재시도 0·전 실패 원문 폴백), `naver_review_collector.search_places(keyword, limit=10)`(instant-search, coords 필수 — findings §6). config 상수 `SEARCH_LLM_MODEL`/`SEARCH_LLM_MAX_TOKENS`(100)/`SEARCH_LLM_ENABLED`.
  - **통계**: `web_usage`에 `search_count` 누적 + `search#YYYY-MM-DD` 일별 카운터(스키마리스 ADD), `/admin/stats`에 `search_count`·`daily[].search` 노출.
  - **인프라**: WebApiFunction `/search` 라우트·`SEARCH_LLM_ENABLED` 환경변수·usage `UpdateItem` IAM·Timeout 10→20초, `web_jobs` `place_id` 속성, 템플릿 파라미터 `SearchLlmEnabled`(테이블·IAM 최소 변경, 격리 유지).
  - **프론트**: 첫 화면 탭 구조(검색 기본 / 붙여넣기 보조, `?prefill=`은 붙여넣기 탭 활성), `useAnalysis` 훅으로 분석·폴링 공유, `SearchView` 후보 클릭→place_id 분석, 관리자 테이블 검색 횟수 컬럼.
  - 관련 커밋 `d9bca7a`·`da0f378`·`579abb3`·`1ef05cc`. 프로덕션 live 실측 통과. 설계 근거·거부 대안은 `docs/web-design.md` 결정 6, 검색 실측은 `experiments/findings.md` §6.

- [x] 5-9 (A/D) 웹 응답 시간 단축 6종 (2026-07-17):
  - **캐시 히트 API 직결(#1)**: `/analyze` place_id 경로에서 WebApiFunction이 공유 캐시(`lookup_cached_summary`)를 직접 조회, 히트 시 `create_completed_job`으로 done 잡 즉시 생성·워커 invoke 생략(API 계약 무변경 202). `naver_url` 경로는 종전대로 워커행.
  - **리뷰 분석 모델 Haiku 4.5 전환(#2)**: `ANTHROPIC_MODEL=claude-haiku-4-5`(리뷰 48건 실측 Sonnet 4.5 16.5초→Haiku 9.8초, 품질 동등). 프롬프트 결함(menus에 장소 통계 라벨·수치 복사) 수정 + mentions 내림차순 방어 정렬, anthropic 클라이언트 timeout 60초·재시도 0. Sonnet 5는 기본 thinking으로 비스트리밍 호출과 비호환이라 제외. `ANTHROPIC_MODEL`은 Telegram 공유 상수(재배포 전까지 종전 모델).
  - **워밍 핑(#3)**: EventBridge Schedule(`rate(5 minutes)`, `{"warmup": true}`)이 두 Lambda 상시 워밍, 핸들러 최상단 즉시 반환(콜드스타트 실측 14.6초 대응, 비용 사실상 0).
  - **프론트 폴링 백오프(#4)**: `useAnalysis` 첫 조회 250ms→750ms→이후 1500ms 정속(총 예산 59.5초), 종전 고정 1.5초 선대기 제거.
  - **rate limit 간격 방식(#5)**: `_respect_rate_limit()`가 마지막 요청 시각(monotonic) 기준 잔여분만 대기(첫 요청 대기 0, 요청 간 0.5초 간격 유지).
  - **단계별 latency 계측(#6)**: 워커 파이프라인(cache/collect/llm/save)·검색(normalize/search/usage) 소요 INFO 1줄 로깅(PII 없음) + 루트 로거 레벨 INFO 명시(Lambda 기본 WARNING이라 INFO 미출력이던 문제 수정).
  - **실측(2026-07-17, 웜)**: /analyze 캐시 미스 26.9초→11.0초(**59% 단축**), /search 1.73초→1.2~1.4초, 캐시 히트 폴링 대기 1.5초→0.25초. 설계 근거·전후 실측표는 `docs/web-design.md` 결정 7. 관련 커밋 `f1452ad`~`827c780`, 프로덕션 배포·실측 완료.
- [x] 5-10 (A+D) 외부 보안 진단 대응 하드닝 (2026-07-18):
  - **SSRF 차단**: `/analyze`의 `naver_url`을 서버측 허용호스트(`https`+`WEB_ALLOWED_NAVER_HOSTS`) 검증, 실패 400.
  - **per-identity 일일 LLM 상한**(백로그 승격): `WEB_DAILY_LLM_LIMIT`(기본 50, 캐시 미스만 카운트) 초과 시 429. 5-1 사용량 카운터(`llm#`) 재사용.
  - **API GW 스로틀**(burst 10/rate 5) + **CORS 기본값 고정**(template 기본을 Vercel 도메인으로 — `*` 원복 함정 제거) + **프론트 보안 헤더**(CSP·HSTS·X-Frame-Options 등, `next.config.ts`).
  - 검증 pytest 226·`sam validate`·`npm build/lint` 그린, 웹 스택 배포·Telegram 무손상 확인·Vercel 헤더 실측. 설계 근거는 `docs/web-design.md` 결정 8. 커밋 `f94a943`·`87e821e`·`fa98e0a`.

## 백로그 (MVP 이후, VOC 기반 결정)

- ~~per-identity 일일 쿼터~~ → 5-10에서 구현 완료(`WEB_DAILY_LLM_LIMIT`, 2026-07-18). 확산 시 한도 조정·검색 경로 쿼터 확대는 잔여 과제.
- 카카오 소셜 로그인 전환 / 카카오 채널·알림톡
- 카카오 SDK 리치 공유(피드 템플릿) — 카카오 개발자 앱 등록·JS키·도메인 등록 필요 (현재는 Web Share API로 대체)

- 개인 리뷰 기록/조회 (/review, /review_update — UC-3)
- 블로그 리뷰 수집 확대
- 캐시 자동 만료(TTL) 재검토
