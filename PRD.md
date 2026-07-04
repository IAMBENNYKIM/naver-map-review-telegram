# PRD.md — 구현 가능한 MVP 명세

> `REQUIREMENTS.md`를 구현 가능한 명세로 구체화한다. 기능 ID(`F0xx`)·모듈 상세·데이터 모델·리스크.
> (아래는 골격 스텁 — 실제 명세로 채운다.)

## 1. MVP 범위

Telegram으로 장소명/링크를 받아 네이버 리뷰를 수집하고 Claude로 요약해 응답하는 온디맨드 봇.

## 2. 기능 목록

| ID | 기능 | 모듈 | 상태 |
|----|------|------|------|
| F001 | Webhook 수신·검증(secret token, chat_id 허용목록) | `webhook_handler.py` | 골격 완료 |
| F002 | 명령 라우팅(/review·기본=장소명, /help) | `command_router.py` | 골격 완료 |
| F003 | 네이버 리뷰 수집 | `naver_review_collector.py` | **TODO: 엔드포인트/셀렉터 확정** |
| F004 | Claude 리뷰 요약(non-critical) | `review_analyst.py` | 골격 완료 |
| F005 | MarkdownV2 응답 포맷 | `review_formatter.py` | 골격 완료 |
| F006 | 리뷰 캐시(DynamoDB, TTL) | `dynamo_writer.py` | 골격 완료 |
| F007 | Telegram 발송·재시도·에러 알림 | `telegram_sender.py` | 골격 완료 |

## 3. 데이터 모델 (DynamoDB)

### `review_cache` (PK=`place_key`, TTL=`ttl`)
| 속성 | 타입 | 설명 |
|------|------|------|
| place_key | S | 정규화 장소 키(sha256 앞 16자) — PK |
| summary | S | Claude 요약(없으면 빈 문자열) |
| reviews | L | 수집 리뷰 dict 리스트 |
| ttl | N | 만료 epoch(초) — DynamoDB 자동 삭제 |

## 4. 리뷰 dict 계약 (수집기 반환)

- `text` (str, 필수): 리뷰 본문
- `rating` (float | None): 별점
- `author` (str), `date` (str): 선택

## 5. 리스크 / 미확정 (`[UNCERTAIN]`)

- **네이버 지도 리뷰 엔드포인트/셀렉터** — place는 iframe·비공식 JSON(GraphQL)일 수 있다.
  Task에서 실제 응답을 덤프해 확정 후 `naver_review_collector`의 `# TODO`를 채운다.
  (Referer 필수·CP949 인코딩 주의 — `CLAUDE.md` 구현 제약 참조)
- 스크래핑 안정성(구조 변경 시 파싱 실패) — 실패는 사용자 안내 문구로 흡수.

## 6. 성공 기준

- 장소명 입력 → 5초 내 요약 응답(캐시 히트 시 즉시).
- 허용목록 외/무효 요청은 조용히 무시(200).
