# 초기 설정 가이드

봇을 처음부터 배포·구동하는 전체 절차. (Windows / PowerShell 기준)

## 0. 사전 준비
- Python 3.12, AWS CLI(자격증명 구성 완료), AWS SAM CLI 설치
- AWS 계정(리전 `ap-northeast-2`), Anthropic API 키

## 1. Telegram 봇 생성 (BotFather)
1. Telegram에서 **@BotFather** 대화 → `/newbot` → 이름·username 지정
2. 발급된 **봇 토큰**을 복사 → `TELEGRAM_BOT_TOKEN`

## 2. 내 chat_id 확인
1. 방금 만든 봇에게 아무 메시지나 보낸다
2. 브라우저에서 `https://api.telegram.org/bot<봇토큰>/getUpdates` 접속
3. 응답 JSON의 `message.chat.id` 값 → `TELEGRAM_CHAT_IDS`(허용 목록, JSON 배열),
   에러 알림 수신자는 `TELEGRAM_DEVELOPER_CHAT_ID`
4. **webhook secret 값**을 임의의 긴 랜덤 문자열로 정한다 → `TELEGRAM_WEBHOOK_SECRET`
   (PowerShell 예: `[guid]::NewGuid().ToString("N")`)

## 3. 로컬 개발 설정
```powershell
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```
`.env`에 위에서 얻은 값들과 `ANTHROPIC_API_KEY`를 채운다. (`LOCAL_DEV=true` 유지)

## 4. AWS Secrets Manager 시크릿 생성 (프로덕션)
Lambda는 `.env` 대신 Secrets Manager에서 읽는다. 아래 JSON 키는 `config._SECRET_KEYS`와 일치해야 한다.
```powershell
aws secretsmanager create-secret `
  --name naver-review/production `
  --region ap-northeast-2 `
  --secret-string '{\"TELEGRAM_BOT_TOKEN\":\"...\",\"TELEGRAM_CHAT_IDS\":\"[\\\"123456789\\\"]\",\"TELEGRAM_DEVELOPER_CHAT_ID\":\"123456789\",\"TELEGRAM_WEBHOOK_SECRET\":\"...\",\"ANTHROPIC_API_KEY\":\"...\"}'
```
> 따옴표 이스케이프가 번거로우면 AWS 콘솔의 Secrets Manager UI에서 키/값으로 입력해도 된다.

## 5. 배포
```powershell
sam validate --lint
sam build
sam deploy --guided     # 최초 1회 (이후 sam deploy)
```
배포 완료 후 출력(Outputs)의 **`WebhookApiUrl`** 값을 복사한다.

## 6. Telegram Webhook 등록
```powershell
curl.exe -X POST "https://api.telegram.org/bot<봇토큰>/setWebhook" `
  -d "url=<WebhookApiUrl>" `
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```
`secret_token`은 `.env`/Secrets의 `TELEGRAM_WEBHOOK_SECRET`과 **동일**해야 한다(불일치 시 403).

## 7. 동작 확인
- 봇에게 `/help` → 사용법 응답
- 봇에게 장소명(예: `성수동 카페`) → 리뷰 요약 응답
- 문제 시 CloudWatch Logs(`/aws/lambda/naver-review-webhook`) 확인

## 문제 해결 체크리스트
- 응답이 없다 → setWebhook 성공 여부(`getWebhookInfo`), secret_token 일치, chat_id 허용목록 포함 확인
- 400 Bad Request(발송 실패) → MarkdownV2 이스케이프 누락 가능 → `review_formatter.escape_markdownv2` 적용 확인
- 리뷰 0건 → 네이버 요청 Referer 헤더·엔드포인트/셀렉터(`naver_review_collector`의 `# TODO`) 확인
