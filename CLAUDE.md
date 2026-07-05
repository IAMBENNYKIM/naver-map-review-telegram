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

## 명령어

```powershell
# 가상환경 (Windows)
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt   # 개발용 (런타임 -r requirements.txt 포함 + pytest/moto)
# requirements.txt 는 Lambda 배포용 최소 의존성 — sam build 는 이것만 설치한다

# 테스트
pytest tests/                       # 단위 테스트 (외부 API mock)
pytest tests/ -m live               # 실측 통합 테스트 (옵트인, 실제 네이버 호출)

# 배포
sam validate
sam build
sam deploy
```

## 시크릿 스키마 (`.env` / Secrets Manager 공통)

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`(JSON 배열 문자열), `TELEGRAM_DEVELOPER_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`

추가 로컬 환경변수: `LOCAL_DEV=true`, `SECRETS_NAME`, `DYNAMO_TABLE_PREFIX`, `AWS_DEFAULT_REGION`

## 참조 구현

`ref/` 폴더는 이전 골격의 읽기 전용 참조본이다. 패턴 참고는 자유이나 **직접 수정 금지**, 프로덕션 코드는 루트에 새로 둔다.
