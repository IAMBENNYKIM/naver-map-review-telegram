# 초기 설정 가이드 (2-Lambda 구조)

봇을 처음부터 배포·구동하는 전체 절차. (Windows / PowerShell 기준, 리전 `ap-northeast-2`)

```
Telegram ─ webhook → API Gateway → WebhookFunction(검증·즉답·비동기 invoke)
                                        └→ WorkerFunction(수집→Claude 분석→발송→캐시 저장)
                                              └ DynamoDB prod_review_cache
```

## 0. 사전 준비

- Python 3.12, AWS CLI(자격증명 구성 완료: `aws configure`), AWS SAM CLI 설치
- AWS 계정(리전 `ap-northeast-2`), Anthropic API 키

## 1. Telegram 봇 생성 (BotFather)

1. Telegram에서 **@BotFather** 대화 → `/newbot` → 이름·username 지정
2. 발급된 **봇 토큰**을 복사 → `TELEGRAM_BOT_TOKEN`

## 2. 내 chat_id 확인

1. 방금 만든 봇에게 아무 메시지나 보낸다
2. 브라우저에서 `https://api.telegram.org/bot<봇토큰>/getUpdates` 접속
3. 응답 JSON의 `message.chat.id` 값 → `TELEGRAM_CHAT_IDS`(허용 목록, JSON 배열 문자열),
   에러 알림 수신자는 `TELEGRAM_DEVELOPER_CHAT_ID`
4. **webhook secret 값**을 임의의 긴 랜덤 문자열로 정한다 → `TELEGRAM_WEBHOOK_SECRET`
   (PowerShell 예: `[guid]::NewGuid().ToString("N")`)

## 3. 로컬 개발 설정 (.env)

```powershell
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements-dev.txt     # 런타임 + pytest/moto (개발용)
Copy-Item .env.example .env
```

`.env`에 위에서 얻은 값들과 `ANTHROPIC_API_KEY`를 채운다. `.env.example` 기준 키:

| 키 | 값 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather 발급 토큰 |
| `TELEGRAM_CHAT_IDS` | 허용 chat_id JSON 배열 문자열, 예: `["123456789"]` |
| `TELEGRAM_DEVELOPER_CHAT_ID` | 에러 알림 수신 chat_id |
| `TELEGRAM_WEBHOOK_SECRET` | 임의 랜덤 문자열 (6단계 setWebhook과 동일 값) |
| `ANTHROPIC_API_KEY` | Claude API 키 |
| `LOCAL_DEV` | `true` 유지 (로컬은 .env, Lambda는 Secrets Manager) |
| `DYNAMO_TABLE_PREFIX` | 로컬 `dev_` (배포는 template 파라미터가 `prod_` 주입) |
| `WORKER_FUNCTION_NAME` | 로컬 기본 `naver-review-worker` (Lambda는 template이 주입) |

단위 테스트로 환경 확인:

```powershell
pytest tests/            # 외부 API 전부 mock — 네트워크 불필요
```

## 4. AWS Secrets Manager 시크릿 생성 (프로덕션)

Lambda는 `.env` 대신 Secrets Manager에서 읽는다. JSON 키 5종은 `config._SECRET_KEYS`와
정확히 일치해야 한다: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`,
`TELEGRAM_DEVELOPER_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`.

```powershell
aws secretsmanager create-secret `
  --name naver-review/production `
  --region ap-northeast-2 `
  --secret-string '{\"TELEGRAM_BOT_TOKEN\":\"...\",\"TELEGRAM_CHAT_IDS\":\"[\\\"123456789\\\"]\",\"TELEGRAM_DEVELOPER_CHAT_ID\":\"123456789\",\"TELEGRAM_WEBHOOK_SECRET\":\"...\",\"ANTHROPIC_API_KEY\":\"...\"}'
```

> 따옴표 이스케이프가 번거로우면 AWS 콘솔 Secrets Manager UI에서 키/값으로 입력해도 된다.
> 시크릿 이름을 바꾸려면 `samconfig.toml`의 `SecretsName` 파라미터도 함께 바꾼다.

## 5. 배포 (sam build && sam deploy)

```powershell
sam validate --lint      # 템플릿 검증 (자격증명 불필요)
sam build                # requirements.txt(런타임 최소)만 설치해 패키징
sam deploy               # samconfig.toml 설정으로 배포 (최초에도 동일)
```

`samconfig.toml` 주요 파라미터:

| 항목 | 값 | 설명 |
|---|---|---|
| `stack_name` | `naver-map-review-telegram` | CloudFormation 스택명 |
| `region` | `ap-northeast-2` | 배포 리전 |
| `TablePrefix` | `prod_` | DynamoDB 테이블 접두사 → `prod_review_cache` |
| `SecretsName` | `naver-review/production` | 4단계에서 만든 시크릿 이름 |
| `confirm_changeset` | `true` | 배포 전 변경 사항 확인 프롬프트 |

배포가 만들어내는 리소스: `WebhookFunction`(256MB/10s, `POST /webhook`),
`WorkerFunction`(512MB/120s), `prod_review_cache` 테이블.

배포 완료 후 출력(Outputs)의 **`WebhookApiUrl`** 값을 복사한다.
(`WorkerFunctionName` 출력은 수동 test invoke 시 사용)

## 6. Telegram Webhook 등록 (setWebhook)

```powershell
curl.exe -X POST "https://api.telegram.org/bot<봇토큰>/setWebhook" `
  -d "url=<WebhookApiUrl>" `
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

- `secret_token`은 `.env`/Secrets의 `TELEGRAM_WEBHOOK_SECRET`과 **동일**해야 한다
  (불일치 시 WebhookFunction이 403으로 거부).
- 등록 확인: `https://api.telegram.org/bot<봇토큰>/getWebhookInfo`
  → `url`이 WebhookApiUrl과 일치하고 `last_error_message`가 없어야 정상.

## 7. 동작 확인 (3개 시나리오)

1. **URL 공유 (신규 조회)** — 네이버 지도 앱에서 음식점 → 공유 → Telegram 봇에 붙여넣기.
   즉시 "🔍 리뷰를 분석하고 있어요" 즉답 후 10~30초 내 분석 결과
   (🍽 장소명 / ■ 총평 / 👍👎 / 🍜 메뉴별 추천도) 수신.
2. **재조회 (캐시 히트)** — 같은 URL을 다시 보내면 3초 내 저장된 요약 +
   "📌 YYYY-MM-DD에 분석한 결과예요 (N일 전)" 안내 수신 (재수집·재분석 없음).
3. **/update (재분석)** — `/update` 전송 시 직전 조회 음식점을 캐시 무시하고
   재수집·재분석. 직전 조회가 없으면 "먼저 음식점 URL을 보내주세요" 안내.

추가: `/help` → 사용법 안내, 허용목록 외 chat에서 보내면 무응답(정상).

## 문제 해결 체크리스트

| 증상 | 확인 사항 |
|---|---|
| 응답이 전혀 없다 | `getWebhookInfo`의 `last_error_message` / secret_token 일치 / 보낸 계정 chat_id가 `TELEGRAM_CHAT_IDS`에 포함되는지 |
| 즉답만 오고 결과가 없다 | WorkerFunction 로그 확인: `aws logs tail /aws/lambda/naver-review-worker --region ap-northeast-2 --since 10m` |
| "분석 중 문제가 발생했어요" | Worker 로그의 `ReviewCollectError` 여부. **429(네이버 차단)면 봇은 정책상 재시도하지 않는다** — 몇 분 쿨다운 후 다시 시도. 반복되면 요청 빈도를 낮춘다 |
| "AI 요약 생성에 실패했어요" | 수집은 성공, Claude 호출/파싱 실패. `ANTHROPIC_API_KEY` 유효성·크레딧 확인 후 `/update` 재시도 (실패 요약은 캐시에 남지 않음) |
| Telegram 400 Bad Request | MarkdownV2 이스케이프 문제 — `review_formatter` 경유 여부 확인 (발송 로그에 응답 본문 기록됨) |
| Secrets 로드 실패로 Lambda 에러 | 시크릿 이름(`naver-review/production`)·리전·JSON 키 5종 일치 확인 |
| Webhook 로그 확인 | `aws logs tail /aws/lambda/naver-review-webhook --region ap-northeast-2 --since 10m` |

> 운영 주의: 네이버 GraphQL **인트로스펙션 금지**(즉시 429 + 지속 차단),
> 429 응답 시 무재시도 즉시 실패가 설계 정책이다 (`experiments/findings.md` §4).
