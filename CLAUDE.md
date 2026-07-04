# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 저장소 현재 상태

이 저장소는 **신규 spec-driven 프로젝트**다(목표 리전 `ap-northeast-2`, 아직 미배포).
`finance-notice-telegram`의 검증된 서버리스 골격을 이식해 시작했다. 신규 작업은 spec-driven으로
진행하고 문서를 함께 갱신한다.

문서 위계(상위 → 하위):
- `REQUIREMENTS.md` — 사용자 원본 요구사항 (문제 정의, 유스케이스, 인터랙션 모델)
- `PRD.md` — 구현 가능한 MVP 명세 (기능 ID, 모듈별 상세, 데이터 모델, 리스크)
- `ROADMAP.md` — Phase별 계획 + 개발 워크플로우. **작업 시작 전 반드시 읽을 단일 진실 공급원**
- `tasks/NNN-*.md` — 개별 작업 명세. 선행 Task·구현 사항·완료 조건·테스트 체크리스트 포함. `000-sample.md`가 템플릿
- `ARCHITECTURE.md` — 코드 구조 지도(진입점·흐름도·모듈 카탈로그). 코드 위치 파악의 진입점

작업 방식: ROADMAP의 Task 순서(낮은 번호 우선)대로 구현하고, 완료 시 ROADMAP에 ✅와
`See: /tasks/NNN-*.md`를 표시한다. 모든 신규 문서·작업 파일·코드 주석은 **한국어**로 작성한다.

## 무엇을 만드는가 (아키텍처 큰 그림)

네이버 지도 장소 리뷰를 Telegram으로 요약해주는 개인용 서버리스 봇. **단일 온디맨드(요청-응답)
흐름**이다:

```
사용자 메시지 → Telegram Webhook → API Gateway → webhook_handler
  → (권한 검증: secret token + chat_id 허용목록)
  → command_router 명령 분기(/review·기본=장소명, /help)
  → naver_review_collector(리뷰 수집, httpx+BeautifulSoup)
  → review_analyst(Claude 요약, non-critical)
  → review_formatter(MarkdownV2 포맷)
  → telegram_sender.send_reply(응답 발송)
```

- **DynamoDB `review_cache`**: 같은 장소 반복 조회 시 재수집·재요약을 아끼는 캐시(TTL 자동 만료).
- **진입점은 `webhook_handler.py` 하나**. 스케줄 푸시·EventBridge는 사용하지 않는다.

핵심 설계 원칙: `config`(설정/시크릿)·`telegram_sender`(발송)·`review_formatter`(포맷/이스케이프)를
공유 모듈로 재사용한다. 새 기능을 추가할 때 이들을 중복 구현하지 말 것.

기술 스택: **Python 3.12 / Telegram Bot API / Anthropic Claude API(리뷰 요약) /
AWS Lambda·API Gateway·DynamoDB·Secrets Manager / boto3 · httpx · anthropic · beautifulsoup4 /
SAM CLI · pytest**. 웹/모바일 프론트엔드 없음 — Telegram이 곧 UI다.

## 반드시 지켜야 할 구현 제약

위반 시 동작하지 않거나 재작업이 발생한다:

- **Lambda 핸들러는 `async def lambda_handler` 금지.** `def lambda_handler(event, context):
  return asyncio.run(_async_main(...))` 래퍼 패턴을 쓰고 비동기 처리는 `_async_main` 내부에서 한다.
- **Telegram Webhook 3초 응답 제한**: `webhook_handler`는 즉시 200을 반환한다. 처리 중 예외도
  200으로 흡수해 Telegram 재시도 폭주(중복 발송)를 막는다. 수집·요약이 3초를 크게 넘길 우려가
  커지면 별도 Lambda 비동기 invoke(InvocationType="Event")로 분리하고 즉시 ack를 보낸다.
- **온디맨드 응답 권한**: 등록된 Chat ID(`TELEGRAM_CHAT_IDS` 허용 목록) 외 요청은 무시한다.
  Webhook은 `X-Telegram-Bot-Api-Secret-Token` 헤더를 `config.TELEGRAM_WEBHOOK_SECRET`와
  **상수 시간 비교**(`hmac.compare_digest`)로 검증한다.
- **설정 이중 로드**: 로컬은 `.env`(`LOCAL_DEV=true`), 프로덕션은 Secrets Manager(`SECRETS_NAME`).
  `config.py`가 담당한다. `config._SECRET_KEYS`와 `.env.example` 키 목록을 **항상 일치**시킨다.
- **DynamoDB 테이블 접두사**: `DYNAMO_TABLE_PREFIX`(로컬 `dev_`, 프로덕션 `prod_`)로 구분한다.
  캐시 쓰기 실패는 **비크리티컬** — 로깅만 하고 응답 파이프라인을 막지 않는다.
- **외부 API 호출**: Rate Limit 대비 `RATE_LIMIT_DELAY` 딜레이 + `RETRY_COUNT` 재시도.
- **네이버 스크래핑 함정** (`naver_review_collector`): ① **Referer 헤더 필수**
  (`config.NAVER_REQUEST_HEADERS` — 없으면 0건) ② 인코딩 CP949 가능 ③ place 상세는 **iframe**
  내부/비공식 JSON API. 실제 엔드포인트·셀렉터는 하드코딩 전 **응답을 실제로 덤프해 확정**한다
  (`# TODO` 지점).
- **HTTP 클라이언트는 `httpx`로 통일**. 다른 HTTP 라이브러리를 추가하지 않는다.
- **로깅 시 PII 최소화**: 사용자 원문(장소명) 대신 정규화 키(`_place_key`)만 로깅한다.

## 명령어

환경 설정 (Windows / PowerShell):
```powershell
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env    # 이후 .env 값 채우기
```

테스트:
```powershell
pytest tests/                          # 전체
pytest tests/test_command_router.py    # 단일 파일
```

배포 (SAM):
```powershell
sam validate --lint        # 템플릿 검증(자격증명 불필요)
sam build
sam deploy --guided        # 최초 배포
sam deploy                 # 이후 배포
```
- Lambda: `python3.12`, 512MB, 타임아웃 300초. Webhook 핸들러 `webhook_handler.lambda_handler`.
- 리전: `ap-northeast-2`. 초기 설정 전체 절차는 `docs/setup-guide.md` 참조.

## 설정·시크릿 규약

- 로컬: `.env`(`.env.example` 참조). 프로덕션: AWS Secrets Manager(시크릿 이름
  `naver-review/production`)에서 런타임 로드. `config.py`가 이 이중 로드를 담당한다.
- 시크릿 키 스키마(`.env`/Secrets 공통): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`(JSON 배열),
  `TELEGRAM_DEVELOPER_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`.

## 참고 외부 문서

- Telegram Bot API: https://core.telegram.org/bots/api
- AWS SAM CLI: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/
- Anthropic Claude API: https://docs.anthropic.com
