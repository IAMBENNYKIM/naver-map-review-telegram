# ARCHITECTURE.md — 코드 구조 지도

> 코드 위치 파악의 진입점. 진입점·흐름도·모듈 카탈로그를 담는다.

## 진입점 (1개)

| 진입점 | 트리거 | 역할 |
|--------|--------|------|
| `webhook_handler.lambda_handler` | Telegram Webhook → API Gateway(HTTP API) | update 검증·라우팅 |

## 흐름도 (온디맨드 요청-응답)

```
Telegram 메시지
   │
   ▼
API Gateway (POST /webhook)
   │
   ▼
webhook_handler._async_main
   │  1) secret token 검증(hmac.compare_digest)
   │  2) body 파싱 / text·chat_id 확인
   │  3) chat_id 허용목록 검증
   │  4) 예외 흡수(항상 200 반환 — 3초 제한·재시도 폭주 방지)
   ▼
command_router.route  ──/help·미인식──▶ _handle_help ─▶ send_reply
   │ (/review·기본=장소명)
   ▼
command_router._handle_review
   │  dynamo_writer.get_cached_review ──히트──▶ 포맷·응답
   │  (미스)
   ▼
naver_review_collector.fetch_reviews  (httpx + BeautifulSoup, Referer 필수)
   ▼
review_analyst.summarize_reviews  (Claude, non-critical → 실패 시 None)
   ▼
dynamo_writer.put_cached_review  (비크리티컬)
   ▼
review_formatter.build_review_report  (MarkdownV2 이스케이프)
   ▼
telegram_sender.send_reply  (재시도 + 실패 시 개발자 에러 알림)
```

## 모듈 카탈로그

| 모듈 | 역할 | 비고 |
|------|------|------|
| `config.py` | 설정·시크릿 이중 로드, 전역 상수, 테이블명 | 모든 모듈이 import |
| `webhook_handler.py` | 진입점: 검증·라우팅 | `async def lambda_handler` 금지 |
| `command_router.py` | 명령 파싱·분기, 캐시/수집/요약 오케스트레이션 | PII 대신 정규화 키 로깅 |
| `naver_review_collector.py` | 네이버 리뷰 수집 | **`# TODO`: 엔드포인트/셀렉터 확정** |
| `review_analyst.py` | Claude 리뷰 요약 | non-critical(실패 시 None) |
| `review_formatter.py` | MarkdownV2 포맷·이스케이프 헬퍼 | `escape_markdownv2(_url)` |
| `dynamo_writer.py` | 리뷰 캐시 read/write | 쓰기 실패 비크리티컬 |
| `telegram_sender.py` | 발송·재시도·에러 알림 | `send_reply`/`send_all`/`send_error_alert` |

## 인프라 (`template.yaml`)

- `WebhookFunction` (python3.12, 512MB, 300s) + 암묵적 `ServerlessHttpApi`(`POST /webhook`)
- `ReviewCacheTable` (PK=`place_key`, TTL=`ttl`, PAY_PER_REQUEST)
- IAM 최소권한: review_cache Get/Put + Secrets 읽기
