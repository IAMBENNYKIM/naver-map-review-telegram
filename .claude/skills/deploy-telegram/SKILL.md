---
name: deploy-telegram
description: Telegram 봇 스택(naver-map-review-telegram) 배포 런북. src/ Telegram 모듈·template.yaml 변경을 AWS에 반영할 때 사용.
---

# Telegram 스택 배포 (naver-map-review-telegram)

절차 원천: `docs/setup-guide.md` §5. 이 스택은 samconfig.toml이 전담하므로 옵션 추가 없이 그대로 배포한다.

## 절차

### 1. 사전조건 확인
- [ ] `pytest tests/` 그린 (실패 상태로 배포 금지)
- [ ] 배포할 변경이 커밋되어 있는지 `git status` 확인

### 2. 검증·빌드
```bash
sam validate --lint     # 템플릿 검증
sam build               # src/requirements.txt만 설치해 패키징
```

### 3. 배포
```bash
sam deploy              # samconfig.toml 설정 사용 (stack_name=naver-map-review-telegram)
```
- `confirm_changeset=true`라 변경셋 확인 프롬프트가 뜬다. **Stack이 `naver-map-review-telegram`이고 변경 리소스가 의도한 범위(보통 함수 2개)인지 확인 후 승인.** 의도 밖 리소스(테이블 Replace/Delete 등)가 보이면 **N으로 중단**하고 사용자에게 보고
- `--guided` 금지 (samconfig `[default]`를 덮어써 설정 오염)
- 비대화식이 필요하면 `sam deploy --no-confirm-changeset` (변경 범위는 4단계에서 사후 검증)

### 4. 배포 후 검증
- [ ] 변경 범위 확인: `aws cloudformation describe-stack-events --stack-name naver-map-review-telegram --profile naver-review --region ap-northeast-2 --max-items 12` — 의도한 리소스만 UPDATE
- [ ] Webhook 정상: `https://api.telegram.org/bot<토큰>/getWebhookInfo` 응답에서 `url`이 WebhookApiUrl과 일치하고 `last_error_message` 없음 (토큰은 시크릿에서 — 절대 로그·출력에 남기지 않는다)
- [ ] 에러 로그 없음: `aws logs tail /aws/lambda/naver-review-worker --profile naver-review --region ap-northeast-2 --since 10m` (Git Bash는 `MSYS_NO_PATHCONV=1` 필요)

### 5. 보고
배포 커밋 해시, 변경 리소스, getWebhookInfo 결과를 보고하고, **실기기 확인(사용자 폰에서 naver.me URL 전송 → 요약 수신)**을 사용자에게 요청한다.
