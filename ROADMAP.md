# ROADMAP.md — 개발 로드맵 (진행 상태의 단일 진실 공급원)

**현재 상태: MVP 배포 완료·운영 중 (2026-07-05).** 신규 조회 E2E 검증 완료. 남은 확인은 사용자 폰에서의 캐시 히트·/update 시나리오뿐.

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
- [ ] 1-5 (A) 검증: 실제 URL(돈멜 본점)로 리뷰 50개 수집을 직접 실행 확인 → 커밋
  - 2026-07-04 1차 시도: resolve_place 성공(pinId 33099281), fetch_place_detail에서 429 — 탐사 시 인트로스펙션이 유발한 IP 쿨다운 미회복. 코드는 설계대로 무재시도 즉시 중단. 쿨다운 후 재시도 예정

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
- [~] 4-4 (A) E2E: 최초 배포 후 실기기 테스트에서 429 실패 발견 → 원인 규명·수정·재배포 → Lambda 직접 호출로 전 구간 성공 검증(소이빙수, 31.8s, 에러 없음)
  - **버그①(핵심)**: config가 모바일 호스트 m.place에 데스크톱 UA를 보내 429 차단 → 모바일 UA로 수정(실측: 데스크톱 429/모바일 200). collector 테스트가 전부 Mock이라 미검출
  - **버그②**: 시크릿 TELEGRAM_DEVELOPER_CHAT_ID에 따옴표 포함 → 에러 알림 400. 따옴표 제거
  - **보안**: httpx 오류 문자열로 봇 토큰이 CloudWatch 로그에 노출 → _redact_token으로 가림. (기노출 토큰은 사용자 BotFather 재발급 권장)
  - 남은 확인: 사용자 폰에서 ② 재조회(캐시 히트) ③ /update 시나리오

## Phase 5 — 웹 진입점 (Telegram 외 진입 경로, 격리 신규 스택)

브레인스토밍·설계: `~/.claude/plans/temporal-orbiting-wand.md`. 목표=지인 확산용 웹(PWA) 진입점. 제약=기존 Telegram 봇 영향 0(별도 SAM 스택 `naver-review-web`), 비용 통제. 초점=**확장성 우선**(일일 쿼터는 Phase 6). 응답 구조=**비동기 잡+폴링**(캐시 미스 파이프라인 ~30초 → API GW 타임아웃 회피, 기존 2-Lambda 비동기 계승).

- [x] 5-0 (A) 브레인스토밍·격리/비용/UI 결정 확정, 비동기 잡+폴링 확정, 플랜 승인 (2026-07-06)
- [x] 5-1 (D) 웹 코어 로직: `config.py` 확장(web 시크릿·테이블·킬스위치), `web_store.py`(jobs/usage/web캐시/prod 읽기전용 read-through), `web_auth.py`(세션토큰·초대코드·admin) + moto·단위 테스트 (커밋 0538b1b)
- [x] 5-2 (D) Lambda 핸들러+인프라: `web_api_handler.py`(라우팅·초대/세션/잡생성/폴링/admin), `web_worker_handler.py`(resolve→캐시→collector→analyst→잡결과·사용량), `template-web.yaml`(WebApi+WebWorker 2함수·3테이블·IAM 최소권한·Budget Alarm·킬스위치) + 테스트
- [x] 5-3 (A) 백엔드 검증: Advisor 직접 `pytest tests/` 152 passed, `sam validate --lint -t template-web.yaml` valid 확인 → 커밋. (배포·실AWS E2E는 5-5)
- [x] 5-4 (D) Next.js 15/shadcn PWA: 초대 게이트 + URL 입력 + 결과 카드(review_analyst JSON 렌더) + 폴링 + 관리자 통계 페이지, 웹 공유 타겟 (`web-frontend/`, npm run build/lint 통과, 커밋 952662f)
- [ ] 5-5 (A) E2E 검증·배포 (**사용자 준비물 필요** — 아래 배포 런북): ① Secrets Manager `naver-review/web` 생성 ② `sam deploy -t template-web.yaml --stack-name naver-review-web` ③ Vercel 배포(Root Dir=web-frontend, NEXT_PUBLIC_API_BASE_URL=WebApiUrl) ④ AllowedOrigin을 Vercel 도메인으로 축소 재배포 ⑤ Telegram 봇 무손상 확인 + 신규/캐시히트/admin 시나리오 검증

## 백로그 (MVP 이후, VOC 기반 결정)

- per-identity 일일 쿼터 (Phase 6 — 웹 확산 시. 5-1 사용량 카운터 재사용)
- 카카오 소셜 로그인 전환 / 카카오 채널·알림톡

- 장소명 텍스트 검색 (URL 없이)
- 개인 리뷰 기록/조회 (/review, /review_update — UC-3)
- 블로그 리뷰 수집 확대
- 캐시 자동 만료(TTL) 재검토
