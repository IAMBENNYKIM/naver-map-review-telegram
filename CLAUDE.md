# CLAUDE.md — 네이버 지도 리뷰 요약 Telegram 봇

이 문서는 이 저장소에서 작업하는 모든 세션(Advisor·Worker)이 반드시 따라야 할 작업 지침이다.

## 프로젝트 한 줄 요약

네이버 지도 공유 URL(naver.me)을 Telegram 봇에 보내면 리뷰 요약 + 메뉴별 추천도를 응답하는 개인용 서버리스 봇.

## 문서 위계

REQUIREMENTS.md(요구사항) → PRD.md(MVP 명세) → ROADMAP.md(진행 상태의 단일 진실 공급원) → CLAUDE.md(구현 제약).
충돌 시 상위 문서가 우선하며, 구현 세부는 이 문서가 우선한다.

## 역할 분담: Advisor / Worker

- **Advisor(메인 세션)**: 요구사항 분석, 작업 분해, 설계 결정, 브리프 작성, diff·테스트 직접 검증, 커밋 승인, 사용자 보고.
- **Worker(Opus 서브에이전트)**: 구현 노동 전부. `.claude/agents/worker-dev.md`(구현), `.claude/agents/worker-scraper.md`(스크래핑 탐사).
- Worker의 완료 보고를 그대로 믿지 않는다. Advisor가 diff와 테스트로 확인 후 승인한다.
- 검증 실패는 수정 브리프로 재위임. Advisor 직접 수정은 한두 줄 마무리에만 허용.
- Worker는 커밋하지 않는다. 커밋은 Advisor 승인 후 작은 단위로, 메시지는 한국어로.

## 아키텍처 (큰 그림)

```
Telegram ─ webhook → API Gateway → WebhookFunction(검증·즉답·비동기 invoke)
                                        └→ WorkerFunction(수집→분석→발송)
                                              ├ 네이버 스크래핑 (httpx)
                                              ├ Claude API (요약+메뉴 추천)
                                              └ DynamoDB review_cache
```

상세는 ARCHITECTURE.md 참조.

## 반드시 지켜야 할 구현 제약

1. **HTTP 클라이언트는 httpx로 통일.** 다른 HTTP 라이브러리 추가 금지.
2. **`async def lambda_handler` 금지.** `def lambda_handler` 안에서 `asyncio.run()` 래퍼를 사용한다.
3. **Webhook은 어떤 경우에도 200 반환.** 예외를 흡수해 Telegram 재시도 폭주를 막는다. 무거운 처리는 WorkerFunction에 `InvocationType="Event"` 비동기 invoke로 넘긴다 (3초 응답 제한).
4. **보안**: chat_id 허용목록 검사 + `X-Telegram-Bot-Api-Secret-Token` 헤더를 `hmac.compare_digest` 상수시간 비교.
5. **설정 이중 로드**: 로컬은 `.env`, Lambda는 Secrets Manager. `config._SECRET_KEYS`와 `.env.example` 키 목록을 항상 일치시킨다. 시크릿 하드코딩 금지.
6. **DynamoDB 테이블 접두사**: 로컬 `dev_`, 프로덕션 `prod_` (`DYNAMO_TABLE_PREFIX`).
7. **캐시 쓰기는 non-critical**: DynamoDB 저장 실패해도 사용자 응답은 발송한다. float는 `Decimal`로 변환해 저장.
8. **Claude 요약 실패는 non-critical**: 실패 시 수집 성공 사실과 함께 폴백 응답을 발송한다.
9. **Telegram 발송은 MarkdownV2**: 모든 동적 텍스트는 `review_formatter`의 이스케이프 헬퍼를 반드시 경유한다.
10. **네이버 스크래핑 (2026-07-04 실측 확정 — `experiments/findings.md`)**: ① **모바일 Chrome User-Agent 필수** — `m.place.naver.com`은 데스크톱 UA를 429로 차단한다(실측: 데스크톱 429 / 모바일 200). `config.NAVER_REQUEST_HEADERS`는 모바일 UA + `Accept-Language`. ② GraphQL 인트로스펙션 절대 금지(즉시 429 + 지속 차단), 429 응답은 무재시도 즉시 실패(`ReviewCollectError`). ③ 엔드포인트·파라미터는 실측 덤프로 확정된 값만 사용, 요청 간 `RATE_LIMIT_DELAY`(0.5초) 준수. (참고: Referer는 필수 아니나 유지, 응답은 전부 UTF-8 — CP949 미관측.)
11. **PII 최소화 로깅**: 리뷰 본문·chat_id 전문을 INFO 로그에 남기지 않는다.
12. **네이밍**: 변수·함수 `snake_case`, 클래스 `PascalCase`, 상수 `UPPER_SNAKE_CASE`. 줄임말 대신 목적이 드러나는 이름(`data` 대신 `review_list`). 한글 식별자 금지.
13. **언어**: 주석·docstring·로그·커밋 메시지는 한국어. 단 `requirements.txt` 주석만 ASCII 유지 (`sam build` 시 cp949 로케일 pip 실패 방지).
14. **웹 진입점(naver-review-web 스택 — 2026-07-07 배포)**: ① 배포 대상 Python은 **`src/`**에 둔다(루트 금지 — `.venv`·`web-frontend`·`.git` 때문에 Lambda 패키지 **250MB 초과**로 배포 실패. `sam build`는 .gitignore 무시). Telegram·웹 두 템플릿 모두 `CodeUri: src/`. ② 웹은 **별도 SAM 스택**(`template-web.yaml`) — Telegram 스택 무영향(제약 재확인). 응답은 **비동기 잡+폴링**. WebWorker는 prod 캐시를 **읽기전용 read-through**만. ③ 웹 배포는 `sam build -t template-web.yaml` 후 **`sam deploy`를 `-t` 없이**(빌드 산출물 사용) + **`--stack-name naver-review-web`·명시 `--parameter-overrides`** 필수 (samconfig는 Telegram 전용 → CLI가 전면 대체. 누락 시 기존 봇 스택을 건드림). ④ 웹 시크릿은 `naver-review/web`(아래 스키마). ⑤ **재배포(코드만 변경) 시 `--parameter-overrides`에 현재 파라미터 전량을 명시한다** — CLI가 생략된 파라미터를 template **기본값으로 되돌려** `AllowedOrigin`이 `*`로 CORS 원복되고 `MonthlyCostBudget`이 삭제된다. 배포 전 `aws cloudformation describe-stacks --stack-name naver-review-web ...`로 현행값을 조회해 그대로 넘기고, 비대화식은 `--no-confirm-changeset`. 스모크는 sandbox가 curl을 막으므로 `aws lambda invoke`(무인증 `/admin/stats`→401)로 확인. 상세·함정: `docs/setup-guide.md` §8.

15. **웹 관리자 사용량 통계(일별 시계열)**: `web_store.log_usage`는 `web_usage`(PK `identity`) 항목에 누적 합계와 함께 **일별 최상위 카운터** `req#YYYY-MM-DD`·`llm#YYYY-MM-DD`를 DynamoDB `ADD`로 누적한다(없는 속성 0 자동 초기화 → 새 테이블·`template-web.yaml` 변경 불필요, 스키마리스). `/admin/stats`는 `summarize_usage_item`으로 `daily` 배열을 정돈해 내려주고, 프론트(`web-frontend` `/admin`)가 구간 필터·recharts 꺾은선으로 렌더한다. 변경 이전 데이터엔 일별 카운터가 없어 구간 필터 시 0으로 보일 수 있다(누적 합계엔 반영됨).

## 명령어

```powershell
# 가상환경 (Windows)
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt   # 개발용 (런타임 -r src/requirements.txt 포함 + pytest/moto)
# src/requirements.txt 는 Lambda 배포용 최소 의존성 — sam build 는 이것만 설치한다 (배포 코드는 src/ 폴더)

# 테스트
pytest tests/                       # 단위 테스트 (외부 API mock)
pytest tests/ -m live               # 실측 통합 테스트 (옵트인, 실제 네이버 호출)

# 배포 (Telegram 스택)
sam validate
sam build
sam deploy

# 배포 (웹 스택 naver-review-web — 별도 스택. build 후 deploy는 -t 없이, --stack-name·--parameter-overrides 명시)
sam build -t template-web.yaml
sam deploy --stack-name naver-review-web --profile naver-review --region ap-northeast-2 `
  --capabilities CAPABILITY_IAM --resolve-s3 `
  --parameter-overrides "SecretsName=naver-review/web TablePrefix=prod_ ProdReviewCacheTable=prod_review_cache BudgetNotificationEmail=..."
# 웹 배포 함정(-t/--stack-name/samconfig)·Vercel·CORS: docs/setup-guide.md §8
```

## 시크릿 스키마 (`.env` / Secrets Manager 공통)

Telegram 스택 시크릿(`naver-review/production`): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`(JSON 배열 문자열), `TELEGRAM_DEVELOPER_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`

웹 스택 시크릿(`naver-review/web`): `ANTHROPIC_API_KEY`(재사용), `WEB_SESSION_SECRET`, `WEB_INVITE_CODES`(`{"코드":"표시이름"}` JSON 문자열), `WEB_ADMIN_TOKEN`

> `config._SECRET_KEYS`는 두 스택 키의 **상위집합**이다. 각 스택 시크릿은 자기 키만 담고, 부재 키는 `_secret.get(k, "")`로 빈 문자열이 되어 무해하다(격리의 핵심).

추가 로컬 환경변수: `LOCAL_DEV=true`, `SECRETS_NAME`, `DYNAMO_TABLE_PREFIX`, `AWS_DEFAULT_REGION`. 웹 전용: `PROD_REVIEW_CACHE_TABLE`, `LLM_COMMENTARY_ENABLED`(킬 스위치)

## 참조 구현

`ref/` 폴더는 이전 골격의 읽기 전용 참조본이다. 패턴 참고는 자유이나 **직접 수정 금지**, 배포 대상 프로덕션 코드는 `src/`에 둔다(제약 #14).
