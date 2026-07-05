# ARCHITECTURE.md — 코드 구조 지도

## 배포 현황 (운영 중, 2026-07-05)

- CloudFormation 스택 `naver-map-review-telegram` (리전 ap-northeast-2), 배포 프로파일 `naver-review`(전용 IAM 사용자).
- Webhook 엔드포인트: `https://5q69qs7tq3.execute-api.ap-northeast-2.amazonaws.com/webhook` (Telegram setWebhook 등록 완료).
- 함수: `naver-review-webhook`, `naver-review-worker` / 테이블: `prod_review_cache` / 시크릿: `naver-review/production`.
- 로그: `aws logs tail /aws/lambda/naver-review-worker --profile naver-review --region ap-northeast-2` (Windows Git Bash는 `MSYS_NO_PATHCONV=1` 필요).

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
| `naver_review_collector.py` | place_id 해석, 리뷰 50개 수집·파싱 (조회당 3요청: naver.me 리다이렉트 → m.place Apollo → pcmap-api GraphQL) | httpx only, **모바일 UA 필수**(데스크톱 429), 429 무재시도 |
| `review_analyst.py` | Claude 1회 호출, PRD §4 JSON 계약 출력 | non-critical, 실패 시 None |
| `review_formatter.py` | 분석 JSON → MarkdownV2, 이스케이프 헬퍼 | 모든 동적 텍스트 이스케이프 강제 |
| `dynamo_writer.py` | 캐시·last_query read/write | 쓰기 non-critical, float→Decimal |
| `telegram_sender.py` | 발송·재시도(429/403/400)·개발자 에러 알림 | MarkdownV2 |

## 인프라 (template.yaml)

- **WebhookFunction**: python3.12, 256MB, Timeout 10s, `POST /webhook`. 권한: WorkerFunction invoke, Secrets read.
- **WorkerFunction**: python3.12, 512MB, Timeout 120s. 권한: DynamoDB Get/Put(review_cache만), Secrets read.
- **ReviewCacheTable**: `${TablePrefix}review_cache`, PK `place_key`(S), PAY_PER_REQUEST, TTL 없음.
- Parameters: `TablePrefix`(dev_/prod_), `SecretsName`. Region: ap-northeast-2.

## 디렉토리

```
├── *.py                  # 프로덕션 모듈 (루트 평면 구조 — Lambda 패키징 단순화)
├── tests/                # pytest (외부 API mock, -m live 실측 옵트인)
├── experiments/          # 스크래핑 탐사 스크립트·덤프 (배포 제외)
├── docs/setup-guide.md   # 배포 절차
├── ref/                  # 이전 구현 참조본 (읽기 전용)
├── template.yaml / samconfig.toml
└── CLAUDE.md / REQUIREMENTS.md / PRD.md / ROADMAP.md / ARCHITECTURE.md
```
