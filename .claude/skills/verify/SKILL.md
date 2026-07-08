---
name: verify
description: 커밋 전 검증 게이트. Worker 완료 보고를 승인하거나 코드 변경을 커밋하기 전에 실행 — 테스트·빌드·제약 위반 스캔을 일괄 수행한다.
---

# 커밋 전 검증 게이트

Worker 완료 보고는 **그대로 믿지 않는다**. 아래를 직접 실행·확인한 결과만 근거로 승인한다.

## 1. 자동 검증 (변경 범위에 해당하는 것만)

| 변경 대상 | 명령 | 기준 |
|---|---|---|
| Python (`src/`·`tests/`) | `pytest tests/` | 전체 그린 (skip 제외 실패 0) |
| 프론트 (`web-frontend/`) | `cd web-frontend && npm run build && npm run lint` | 둘 다 그린 |
| SAM 템플릿 | `sam validate --lint` (웹은 `-t template-web.yaml` 추가) | valid |

## 2. diff 제약 위반 스캔

`git diff` (또는 `git diff --staged`)를 직접 읽으며 아래를 점검한다. 하나라도 발견 시 **커밋 금지 → 수정 브리프로 재위임**.

- [ ] **httpx 외 HTTP 라이브러리** 유입 없음 (`requests`·`urllib3`·`aiohttp` import 금지)
- [ ] **`async def lambda_handler` 없음** — 핸들러는 `def` + 내부 `asyncio.run()`
- [ ] **시크릿 하드코딩 없음** — 토큰·키 리터럴, `.env` 값 복사 흔적. 시크릿은 config 이중 로드만
- [ ] **`config._SECRET_KEYS` ↔ `.env.example` 정합** — 키 추가/삭제 시 양쪽 동시 갱신됐는지
- [ ] **MarkdownV2 이스케이프 우회 없음** — Telegram 발송 동적 텍스트가 `review_formatter` 헬퍼를 경유하는지
- [ ] **PII 로깅 없음** — 리뷰 본문·chat_id 전문이 INFO 로그에 노출되지 않는지
- [ ] **배포 코드가 `src/` 밖에 없음** — 루트에 새 배포 Python 생성 금지 (250MB 함정)
- [ ] **네이버 요청 규약** — 스크래핑 경로 변경 시 모바일 UA(`config.NAVER_REQUEST_HEADERS`)·429 무재시도 유지, 인트로스펙션 쿼리 없음
- [ ] **웹-Telegram 격리** — 웹 코드가 Telegram 리소스에 쓰기·invoke 권한을 요구하지 않는지 (prod 캐시는 읽기전용 read-through만)
- [ ] **브리프 범위 준수** — 브리프에 없는 파일 변경·리팩터링이 섞이지 않았는지

## 3. 문서 정합 (문서를 함께 바꿨다면)

- [ ] CLAUDE.md "문서 지도"의 단일 원천 원칙 준수 — 같은 사실이 두 문서에 상세 서술되지 않았는지
- [ ] 새로 언급한 파일·섹션 포인터가 실존하는지

## 4. 결과 보고

- **통과**: 실행한 명령과 결과 요약(테스트 수·빌드 상태) + "커밋 가능" 판정
- **실패**: 실패 항목·재현 출력 + 수정 브리프 초안(무엇을 어떻게 고칠지)을 제시
