# ARCHITECTURE.md — 코드 구조 지도

## 배포 현황 (운영 중, 2026-07-05)

- CloudFormation 스택 `naver-map-review-telegram` (리전 ap-northeast-2), 배포 프로파일 `naver-review`(전용 IAM 사용자).
- Webhook 엔드포인트: `https://5q69qs7tq3.execute-api.ap-northeast-2.amazonaws.com/webhook` (Telegram setWebhook 등록 완료).
- 함수: `naver-review-webhook`, `naver-review-worker` / 테이블: `prod_review_cache` / 시크릿: `naver-review/production`.
- 로그: `aws logs tail /aws/lambda/naver-review-worker --profile naver-review --region ap-northeast-2` (Windows Git Bash는 `MSYS_NO_PATHCONV=1` 필요).

### 웹 진입점 스택 (naver-review-web, 2026-07-07 배포)

Telegram과 **완전히 격리된 별도 CloudFormation 스택**(제약: 기존 봇 영향 0). 프론트는 Vercel(정적 Next.js `web-frontend/`).

- 스택 `naver-review-web` / 템플릿 `template-web.yaml`. 함수 `naver-review-web-api`·`naver-review-web-worker`.
- 테이블 `prod_web_review_cache`·`prod_web_jobs`(TTL 1h)·`prod_web_usage` / 시크릿 `naver-review/web`.
- **응답 구조 = 비동기 잡+폴링**: API가 잡 생성 후 즉시 `job_id` 반환 → WebWorker가 파이프라인 수행·잡에 결과 기록 → 프론트가 폴링(캐시 미스 파이프라인 ~30초 > API GW 30초 타임아웃 회피).
- **비용 격리**: WebWorker는 Telegram `prod_review_cache`를 **읽기전용 read-through**(신규 장소만 과금·워밍). 웹은 Telegram WorkerFunction invoke 권한 없음(무인증 공백 차단).
- 배포/함정: `docs/setup-guide.md` §8 참조(`--stack-name` 필수·`sam deploy`는 build 후 `-t` 없이·samconfig 누출 주의).

## 전체 흐름

```
[사용자] ─ 네이버지도 공유 텍스트 ─> [Telegram]
                                        │ webhook (POST /webhook)
                                        v
[API Gateway HTTP API] ─> [WebhookFunction: webhook_handler.py]
   secret token 상수시간 비교 → chat_id 허용목록 → command_router로 파싱
   → WorkerFunction 비동기 invoke(InvocationType=Event) → "분석 중" 발송 → 200
                                        │
                                        v
[WorkerFunction: worker_handler.py]
   naver.me → place_id 해석 (naver_review_collector)
   → 캐시 조회 (dynamo_writer)
   ├─ 히트: 저장 요약 + 갱신 시점 + /update 안내 발송
   └─ 미스/update: 리뷰 50개 수집 (naver_review_collector)
        → Claude 분석 (review_analyst)
        → MarkdownV2 포맷 (review_formatter)
        → 발송 (telegram_sender) → 캐시 저장 (dynamo_writer, non-critical)
```

## 모듈 카탈로그

| 모듈 | 역할 | 유의점 |
|------|------|--------|
| `config.py` | 설정·시크릿 이중 로드(.env ↔ Secrets Manager), 전역 상수 | 모든 모듈이 import. `_SECRET_KEYS` = `.env.example` |
| `webhook_handler.py` | WebhookFunction 진입점. 검증·파싱·비동기 invoke·즉답 | 항상 200. `asyncio.run` 래퍼 |
| `worker_handler.py` | WorkerFunction 진입점. 수집→분석→발송 오케스트레이션 | 예외 시 사용자 실패 안내 + 개발자 알림 |
| `command_router.py` | 메시지 → 액션 결정(analyze/update/help), Worker 이벤트 생성 | URL 정규식 추출 |
| `naver_review_collector.py` | place_id 해석, 리뷰 50개 수집·파싱 (조회당 3요청: naver.me 리다이렉트 → m.place Apollo → pcmap-api GraphQL). `search_places(keyword, limit=10)`=instant-search 후보 리스트(웹 검색용, **coords 필수**) | httpx only, **모바일 UA 필수**(데스크톱 429), 429 무재시도. 검색 엔드포인트·`coords` 원천 `experiments/findings.md` §6 |
| `review_analyst.py` | Claude 1회 호출, PRD §4 JSON 계약 출력 | non-critical, 실패 시 None |
| `review_formatter.py` | 분석 JSON → MarkdownV2, 이스케이프 헬퍼 | 모든 동적 텍스트 이스케이프 강제 |
| `dynamo_writer.py` | 캐시·last_query read/write | 쓰기 non-critical, float→Decimal |
| `telegram_sender.py` | 발송·재시도(429/403/400)·개발자 에러 알림 | MarkdownV2 |
| `web_api_handler.py` | WebApiFunction 진입점. 초대/세션·`/search` 동기 검색·잡 생성+비동기 invoke·결과 폴링·`/admin/stats` 통계(일별 `daily` 포함) (HttpApi 라우팅) | 빠른 응답, 소유권 404, Decimal→JSON |
| `web_worker_handler.py` | WebWorkerFunction 진입점. resolve(`place_id` 수신 시 생략)→캐시(web/prod read-through)→수집→분석→잡 결과·사용량 | `asyncio.run` 래퍼, Telegram/formatter 없음 |
| `web_store.py` | 웹 DynamoDB(jobs·web캐시·usage) + prod 캐시 read-through. `log_usage`는 누적 합계+일별 카운터(`req#`/`llm#`/`search#`) ADD, `summarize_usage_item`이 `daily` 정돈 | `dynamo_writer` 규약(non-critical), 읽기전용 prod |
| `web_auth.py` | HMAC 세션토큰 발급/검증·초대코드→identity·admin 토큰 | 상수시간 비교, 순수 로직 |
| `search_normalizer.py` | 자연어 프롬프트 → 네이버 검색어 정규화(Claude Haiku 1회). `SEARCH_LLM_ENABLED` off·어떤 실패에도 원문 폴백 | non-critical, 필수 경로 아님 |

## 인프라 (template.yaml)

- **WebhookFunction**: python3.12, 256MB, Timeout 10s, `POST /webhook`. 권한: WorkerFunction invoke, Secrets read.
- **WorkerFunction**: python3.12, 512MB, Timeout 120s. 권한: DynamoDB Get/Put(review_cache만), Secrets read.
- **ReviewCacheTable**: `${TablePrefix}review_cache`, PK `place_key`(S), PAY_PER_REQUEST, TTL 없음.
- Parameters: `TablePrefix`(dev_/prod_), `SecretsName`. Region: ap-northeast-2.
- 두 함수 모두 `CodeUri: src/`(배포 대상 Python은 `src/`에만 — 루트는 `.venv`·`web-frontend` 때문에 250MB 초과).

## 웹 인프라 (template-web.yaml, 별도 스택)

- **WebApiFunction**: python3.12, 256MB, **20s**(정규화 LLM 5초 + 네이버 검색 동기 처리 여유). HttpApi(CORS `AllowedOrigin`) 라우트 `POST /invite`·`POST /search`·`POST /analyze`·`GET /result/{job_id}`·`GET /admin/stats`. 환경변수 `SEARCH_LLM_ENABLED`. 권한: WebWorker invoke, jobs Get/Put/Update·usage Scan·**usage UpdateItem(검색 카운터)**·Secrets read. (`/search`는 동기 처리 — 잡+폴링 아님, 근거 `docs/web-design.md` 결정 6)
- **WebWorkerFunction**: python3.12, 512MB, 120s(비동기 invoke). 권한: jobs Update·webcache Get/Put·usage Update·**prod 캐시 GetItem(읽기전용, 이름 참조)**·Secrets read.
- 테이블: `${TablePrefix}web_review_cache`(PK place_key), `${TablePrefix}web_jobs`(PK job_id, TTL `ttl`, `place_id` 속성=검색 경로 직행 분석용), `${TablePrefix}web_usage`(PK identity, 누적 합계 `total_count`·`llm_call_count`·`search_count` + 일별 최상위 카운터 `req#YYYY-MM-DD`·`llm#YYYY-MM-DD`·`search#YYYY-MM-DD`). 모두 PAY_PER_REQUEST. **일별 카운터·`search_count`·`place_id`는 스키마리스 속성 추가라 테이블·템플릿 변경 불필요.**
- **MonthlyCostBudget**(Condition `HasBudgetEmail`): 계정 전역 월 예산 알림 50/80/100%.
- Parameters: `TablePrefix`·`SecretsName`(기본 `naver-review/web`)·`ProdReviewCacheTable`·`AllowedOrigin`·`BudgetLimitAmount`·`BudgetNotificationEmail`·`LlmCommentaryEnabled`·`SearchLlmEnabled`(검색 정규화 킬 스위치).
- prod 캐시 테이블은 이 스택이 **정의하지 않음**(Telegram 스택 소유 — 이름으로만 참조).

## 디렉토리

```
├── src/*.py              # 배포 대상 Python (Telegram+웹, 평면 구조). 두 템플릿 CodeUri: src/
│                         #   ★ 루트가 아닌 src/에 두는 이유: 루트는 .venv·web-frontend·.git 때문에
│                         #     Lambda 패키지 250MB 초과(sam build는 .gitignore 무시) → src/ 분리로 44MB
├── src/requirements.txt  # Lambda 런타임 최소 의존성 (sam build가 이것만 설치)
├── web-frontend/         # 웹 진입점 프론트 (Next.js 15/shadcn PWA, Vercel 배포. 배포 제외 대상)
├── tests/                # pytest (외부 API mock, -m live 실측 옵트인). conftest는 src/를 sys.path에 추가
├── experiments/          # 스크래핑 탐사 스크립트·덤프 (배포 제외). findings.md = 스크래핑 실측 원천
├── docs/setup-guide.md   # 배포 절차 (§8 웹 배포 포함)
├── docs/web-design.md    # 웹 진입점 설계 결정·근거
├── .claude/agents/       # worker-dev(구현)·worker-scraper(탐사) 서브에이전트 정의
├── .claude/skills/       # deploy-telegram·deploy-web·verify·delegate 워크플로우 스킬
├── ref/                  # 이전 구현 참조본 (읽기 전용)
├── template.yaml (Telegram) / template-web.yaml (웹) / samconfig.toml (Telegram 전용)
└── CLAUDE.md / REQUIREMENTS.md / PRD.md / ROADMAP.md / ARCHITECTURE.md
```
