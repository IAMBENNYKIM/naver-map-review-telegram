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

> Claude Code 세션에서의 반복 배포는 `/deploy-telegram` 스킬(`.claude/skills/deploy-telegram/`)이 이 절차를 검증 단계까지 포함해 수행한다.

```powershell
sam validate --lint      # 템플릿 검증 (자격증명 불필요)
sam build                # src/requirements.txt(런타임 최소)만 설치해 패키징
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

## 8. 웹 진입점 배포 (naver-review-web 스택 + Vercel)

Telegram 봇과 **완전히 격리된 별도 SAM 스택**으로 웹(PWA) 진입점을 배포한다(제약: 기존 봇 영향 0). 응답 구조는 **비동기 잡+폴링**(캐시 미스 파이프라인 ~30초 > API GW 30초 타임아웃 회피). 프론트는 정적 Next.js(`web-frontend/`)로 Vercel에 올린다.

### 8-1. 웹 전용 시크릿 `naver-review/web` 생성

Telegram 시크릿과 분리한다. 키 4종: `ANTHROPIC_API_KEY`(기존 값 재사용), `WEB_SESSION_SECRET`, `WEB_INVITE_CODES`(`{"초대코드":"표시이름"}` JSON 문자열 — 표시이름이 `/admin` 통계에 뜸), `WEB_ADMIN_TOKEN`.

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"   # WEB_SESSION_SECRET, WEB_ADMIN_TOKEN 각각 1회
```

콘솔 Secrets Manager → Store a new secret → *Plaintext*에 JSON 붙여넣기 → 이름 `naver-review/web`.
(`WEB_INVITE_CODES` 값은 JSON 문자열 안의 JSON이라 따옴표 이스케이프 필요.)

### 8-2. 백엔드 배포 (sam build/deploy) — ⚠️ 함정 3가지 (이 세션 실측)

> Claude Code 세션에서의 반복 배포는 `/deploy-web` 스킬(`.claude/skills/deploy-web/`)이 아래 함정 회피와 검증(변경 범위·Telegram 무손상·스모크)을 절차화해 수행한다.

1. **`sam deploy`에 `-t`를 붙이지 마라.** `sam build -t template-web.yaml`이 산출물을 `.aws-sam/build/`(deps 포함)에 만들고, **`-t` 없는** `sam deploy`가 그걸 배포한다. `-t template-web.yaml`로 소스를 직접 배포하면 httpx/anthropic 누락 → 런타임 ImportError.
2. **`--stack-name naver-review-web` 필수.** `samconfig.toml`은 Telegram 전용(`stack_name=naver-map-review-telegram`)이라, 빠뜨리면 웹 템플릿이 **기존 봇 스택을 덮어쓴다**.
3. **`--parameter-overrides`로 `SecretsName=naver-review/web` 명시.** CLI 오버라이드가 samconfig의 `SecretsName=naver-review/production`을 **전면 대체**한다(안 하면 웹이 Telegram 시크릿을 읽어 WEB_* 키가 비어 인증이 깨짐).

```powershell
sam build -t template-web.yaml
sam deploy --stack-name naver-review-web `
  --profile naver-review --region ap-northeast-2 --capabilities CAPABILITY_IAM --resolve-s3 `
  --parameter-overrides "SecretsName=naver-review/web TablePrefix=prod_ ProdReviewCacheTable=prod_review_cache BudgetNotificationEmail=본인이메일@example.com"
```

- `confirm_changeset=true`라 배포 전 변경셋 확인 → **Stack이 `naver-review-web`이고 리소스가 Add/CREATE면 `y`**. `naver-map-review-telegram`이 보이거나 기존 리소스 Modify/Delete면 **`N`으로 즉시 중단**.
- 배포 실패로 **ROLLBACK_COMPLETE** 상태가 되면 재배포 전 삭제 필수: `sam delete --stack-name naver-review-web --profile naver-review --region ap-northeast-2`.
- `sam build`가 Python 버전으로 실패하면 `--use-container`(Docker 필요) 추가.
- 출력 **`WebApiUrl`** 복사 → Vercel 환경변수에 사용.
- (선택 스모크) `Invoke-RestMethod -Method Post -Uri "<WebApiUrl>/invite" -ContentType "application/json" -Body '{"code":"..."}'` → `token` 반환 확인.

배포 리소스: `WebApiFunction`(256MB/10s), `WebWorkerFunction`(512MB/120s), `web_review_cache`·`web_jobs`(TTL 1h)·`web_usage`, 조건부 `MonthlyCostBudget`. prod 캐시는 **읽기전용 read-through**(이름 참조, 이 스택이 소유하지 않음).

**⚠️ 재배포(코드만 변경) 시 파라미터 전량 명시** — CLI `--parameter-overrides`는 **생략한 파라미터를 template 기본값으로 되돌린다**. 그냥 코드만 다시 올리려고 파라미터를 비우면 `AllowedOrigin`이 `*`로 **CORS가 원복**되고 `MonthlyCostBudget`이 **삭제**된다. 배포 전 현행값을 조회해 그대로 넘겨라:

```bash
# 1) 현재 파라미터 조회
aws cloudformation describe-stacks --stack-name naver-review-web --profile naver-review --region ap-northeast-2 --query 'Stacks[0].Parameters' --output json
# 2) build 후 조회한 값 전량 명시 + 비대화식(--no-confirm-changeset)
sam build -t template-web.yaml
sam deploy --stack-name naver-review-web --profile naver-review --region ap-northeast-2 --capabilities CAPABILITY_IAM --resolve-s3 --no-confirm-changeset \
  --parameter-overrides "SecretsName=naver-review/web TablePrefix=prod_ ProdReviewCacheTable=prod_review_cache AllowedOrigin=https://benny-naver-review.vercel.app BudgetLimitAmount=30 BudgetNotificationEmail=본인이메일 LlmCommentaryEnabled=true SearchLlmEnabled=true WebDailyLlmLimit=100"
```

> ⚠️ **Git Bash에서 `sam` 직접 호출 금지 — `sam.cmd` 배치 래퍼가 인자를 재해석한다** (2026-07-21 실사고). Git Bash 도구로 위 `sam deploy`를 직접 실행하면 `sam.cmd` 배치 래퍼가 `--parameter-overrides`의 값(URL·이메일 등 특수문자·공백 포함)을 재파싱하다가 `'C:\Program'은(는) 내부 또는 외부 명령이 아닙니다`로 실패한다(경로 `C:\Program Files\...`가 공백에서 쪼개짐). 처방: PowerShell을 경유해 실행한다.
> ```bash
> powershell.exe -NoProfile -Command "sam deploy --stack-name naver-review-web --profile naver-review --region ap-northeast-2 --capabilities CAPABILITY_IAM --resolve-s3 --no-confirm-changeset --parameter-overrides 'SecretsName=naver-review/web TablePrefix=prod_ ProdReviewCacheTable=prod_review_cache AllowedOrigin=https://benny-naver-review.vercel.app BudgetLimitAmount=30 BudgetNotificationEmail=본인이메일 LlmCommentaryEnabled=true SearchLlmEnabled=true WebDailyLlmLimit=100'"
> ```

배포 후 **변경 범위 확인**(코드만이어야 함): `aws cloudformation describe-stack-events --stack-name naver-review-web ... --max-items 12` → `WebApiFunction`·`WebWorkerFunction`만 UPDATE, 테이블·API GW·IAM 무변경, Telegram 스택(`naver-map-review-telegram`)은 `LastUpdatedTime` 불변인지 대조. **스모크**: sandbox가 `curl`을 막으면 `aws lambda invoke`로 대체 — 무인증 `/admin/stats` 이벤트를 던져 `statusCode 401`이 오면 새 코드가 ImportError 없이 기동한 것.

### 8-3. 프론트 배포 (Vercel)

1. vercel.com → GitHub 로그인(무료 Hobby) → **Add New → Project → Import Git Repository**(⚠️ 클론/템플릿 생성 아님).
2. **Root Directory = `web-frontend`**(모노레포라 하위 폴더 지정 필수). Framework는 Next.js 자동 감지.
3. **Environment Variables**: `NEXT_PUBLIC_API_BASE_URL` = 8-2의 `WebApiUrl`. → Deploy.
4. **배포 대상 브랜치에 코드가 있어야 한다.** `main`이 비어 있으면 PR 병합하거나 Vercel Production Branch를 코드 있는 브랜치로 지정.

### 8-4. CORS 좁히기 (보안 하드닝)

백엔드 기본 `AllowedOrigin=*`(전체 허용) → 배포 후 Vercel 도메인으로 좁혀 재배포(8-2 명령에 `AllowedOrigin=https://프로젝트명.vercel.app` 추가).

### 8-5. 검증

① Telegram 봇 무손상(기존 봇에 URL → 정상 응답) ② 웹 초대코드→URL 분석→결과 카드 ③ 같은 URL 재요청 → "캐시" 배지(LLM 미호출) ④ `URL/admin` → `WEB_ADMIN_TOKEN`으로 표시이름별 사용량 통계.

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
| 웹 배포 `Unzipped size must be smaller than 262144000` | `CodeUri`가 `.venv`·`web-frontend/node_modules`·`.git`를 포함. 배포 Python은 `src/`에 있어야 하고 두 템플릿 `CodeUri: src/`인지 확인(sam build는 .gitignore 무시) |
| 웹 배포가 Telegram 스택을 건드림 | `--stack-name naver-review-web` 누락(samconfig가 Telegram stack_name 사용). 8-2 함정 2·3 참조 |
| 웹 배포 후 함수 ImportError(httpx 등) | `sam deploy`에 `-t`를 붙여 소스를 배포함. build 후 `-t` 없이 배포(8-2 함정 1) |
| Git Bash에서 `sam` 실행 시 `'C:\Program'은(는) 내부 또는 외부 명령이 아닙니다` | `sam.cmd` 배치 래퍼가 `--parameter-overrides`의 특수문자·공백 인자를 재해석해 실패 → `powershell.exe -NoProfile -Command "sam deploy ..."` 경유 실행(8-2) |
| PowerShell `curl` 파라미터 바인딩 에러 | `curl`은 `Invoke-WebRequest` 별칭 — `curl.exe` 또는 `Invoke-RestMethod` 사용 |
| 웹 "API 서버 주소가 설정되지 않았어요" | Vercel env `NEXT_PUBLIC_API_BASE_URL` 미설정 — Settings → Environment Variables 추가 후 Redeploy |
| 웹 "서버에 연결하지 못했어요"(CORS) | 백엔드 `AllowedOrigin`이 프론트 도메인을 허용하는지(기본 `*`는 허용). 좁힌 뒤 도메인 오타 확인 |

> 운영 주의: 네이버 GraphQL **인트로스펙션 금지**(즉시 429 + 지속 차단),
> 429 응답 시 무재시도 즉시 실패가 설계 정책이다 (`experiments/findings.md` §4).
