---
name: deploy-web
description: 웹 스택(naver-review-web) 배포 런북. 파라미터 원복·samconfig 누출·-t 함정을 자동으로 회피한다. 웹 백엔드(src/ 웹 모듈·template-web.yaml) 변경을 AWS에 반영할 때 사용.
---

# 웹 스택 배포 (naver-review-web)

절차 원천: `docs/setup-guide.md` §8-2. 아래 단계를 **순서대로, 생략 없이** 수행한다.

## 절대 규칙 (위반 시 기존 Telegram 봇이 훼손된다)

- `sam deploy`에 **`--stack-name naver-review-web`을 반드시 명시** (samconfig.toml은 Telegram 전용 — 누락 시 봇 스택을 덮어씀)
- `sam deploy`에 **`-t` 옵션 금지** (build 산출물 대신 소스를 직배포해 deps 누락 ImportError)
- **`--parameter-overrides`에 파라미터 9종 전량 명시** (생략분은 template 기본값으로 원복 — CORS `*` 개방·예산 삭제 사고)
- **Git Bash에서 `sam`을 직접 부르지 말고 `powershell.exe -NoProfile -Command "..."` 경유** (`sam.cmd` 배치 래퍼가 특수문자·공백 인자를 재해석해 `'C:\Program'` 오류로 실패 — 상세 `docs/setup-guide.md` §8-2)

## 절차

### 1. 사전조건 확인
- [ ] `pytest tests/` 그린 (실패 상태로 배포 금지)
- [ ] 배포할 변경이 커밋되어 있는지 `git status` 확인
- [ ] `template-web.yaml` 변경이 있다면 `sam validate --lint -t template-web.yaml` 통과

### 2. 현행 파라미터 조회 (원복 방지의 핵심)
```bash
aws cloudformation describe-stacks --stack-name naver-review-web --profile naver-review --region ap-northeast-2 --query 'Stacks[0].Parameters' --output json
```
조회된 9종(`SecretsName`·`TablePrefix`·`ProdReviewCacheTable`·`AllowedOrigin`·`BudgetLimitAmount`·`BudgetNotificationEmail`·`LlmCommentaryEnabled`·`SearchLlmEnabled`·`WebDailyLlmLimit`)의 **현행값을 그대로** 4단계에 넘긴다. 의도적으로 바꾸려는 파라미터만 새 값으로. 템플릿에 새로 추가돼 아직 스택에 없는 파라미터는 조회에 나오지 않는다 — 그 경우 템플릿 기본값 또는 의도한 값을 명시한다.
**중단 조건**: 조회 실패 또는 스택 상태가 `*_COMPLETE`가 아니면 배포하지 말고 사용자에게 보고. (`ROLLBACK_COMPLETE`면 `sam delete` 후 재생성 필요 — setup-guide §8-2)

### 3. 빌드
이 스킬은 Bash 도구에서 실행되므로 `sam`은 **PowerShell을 경유**해 부른다(Git Bash 직접 호출 시 `sam.cmd`가 인자를 깨뜨림 — 절대 규칙 참조).
```bash
powershell.exe -NoProfile -Command "sam build -t template-web.yaml"
```

### 4. 배포 (`-t` 없이, 파라미터 9종 전량 명시)
```bash
powershell.exe -NoProfile -Command "sam deploy --stack-name naver-review-web --profile naver-review --region ap-northeast-2 --capabilities CAPABILITY_IAM --resolve-s3 --no-confirm-changeset --parameter-overrides 'SecretsName=<조회값> TablePrefix=<조회값> ProdReviewCacheTable=<조회값> AllowedOrigin=<조회값> BudgetLimitAmount=<조회값> BudgetNotificationEmail=<조회값> LlmCommentaryEnabled=<조회값> SearchLlmEnabled=<조회값> WebDailyLlmLimit=<조회값>'"
```

### 5. 변경 범위 검증
```bash
aws cloudformation describe-stack-events --stack-name naver-review-web --profile naver-review --region ap-northeast-2 --max-items 12
```
- [ ] 코드만 변경한 배포라면 `WebApiFunction`·`WebWorkerFunction`만 UPDATE여야 한다. 테이블·API GW·IAM이 변경됐다면 원인을 규명해 보고
- [ ] Telegram 스택 무손상 대조: `aws cloudformation describe-stacks --stack-name naver-map-review-telegram --profile naver-review --region ap-northeast-2 --query 'Stacks[0].LastUpdatedTime'` — 배포 전과 동일해야 함

### 6. 스모크 테스트
sandbox가 curl을 막으므로 `aws lambda invoke`로 확인한다. 무인증 `/admin/stats` 이벤트(API GW v2 형식)를 담은 임시 파일을 만들어:
```bash
aws lambda invoke --function-name naver-review-web-api --profile naver-review --region ap-northeast-2 --cli-binary-format raw-in-base64-out --payload file://<이벤트파일> <출력파일>
```
- [ ] StatusCode 200 + 함수 응답 `statusCode: 401` → 새 코드가 ImportError 없이 기동·인증 로직 정상

### 7. 보고
배포 커밋 해시, 변경된 리소스 목록, Telegram 스택 무손상 여부, 스모크 결과를 사용자에게 보고한다. 프론트(`web-frontend/`) 변경이 함께 있었다면 `main` push로 Vercel 자동 배포됨을 안내.
