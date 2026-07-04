# ROADMAP.md — 개발 로드맵 (단일 진실 공급원)

> **작업 시작 전 반드시 이 파일을 읽는다.** Task는 낮은 번호부터 구현하고, 완료 시 ✅와
> `See: /tasks/NNN-*.md`를 표시한다. (아래는 골격 스텁 — Phase·Task를 실제 계획으로 채운다.)

## 개발 워크플로우

1. `ROADMAP.md`에서 다음 Task 확인 → `tasks/NNN-*.md` 작성(`000-sample.md` 복사)
2. 구현 + 테스트(`tests/`) 작성 → `pytest` 통과
3. `ARCHITECTURE.md`·관련 문서 갱신 → ROADMAP 항목에 ✅ 표시
4. 모든 문서·주석은 **한국어**

## Phase 0 — 골격 (완료)

- ✅ 서버리스 골격 이식(webhook·config·telegram_sender·formatter·template.yaml)
- ✅ 문서 위계·초기 설정 가이드(`docs/setup-guide.md`)

## Phase 1 — 리뷰 수집 확정 (핵심)

- [ ] Task 001: 네이버 지도 place id 해석 전략 확정(URL 파싱 + 검색 API)
- [ ] Task 002: 리뷰 엔드포인트(iframe/JSON) 응답 덤프 → 실제 구조 확정 **(게이트)**
- [ ] Task 003: `naver_review_collector` 파싱 구현 + 단위 테스트
  > ⚠️ 하드코딩 전 실제 응답 검증(Referer·CP949·iframe). `PRD.md` §5 참조.

## Phase 2 — 요약·응답 품질

- [ ] Task 004: `review_analyst` 프롬프트 튜닝(장점/단점/팁 구조)
- [ ] Task 005: `review_formatter` 출력 양식 확정 + MarkdownV2 이스케이프 테스트
- [ ] Task 006: 캐시 히트/미스 경로 통합 테스트

## Phase 3 — 배포·운영

- [ ] Task 007: Secrets Manager 시크릿 등록 + `sam deploy`
- [ ] Task 008: Telegram `setWebhook` 등록 + E2E 동작 확인
- [ ] Task 009: CloudWatch 로그·에러 알림 점검

## 검증 이슈 (구현 제약 — `CLAUDE.md`와 동기화)

- `async def lambda_handler` 금지(asyncio.run 래퍼)
- Webhook 3초 응답 제한(즉시 200, 예외 흡수)
- chat_id 허용목록 + secret token 상수시간 비교
- 설정 이중 로드, 테이블 접두사, 캐시 쓰기 비크리티컬
- 네이버 스크래핑 함정(Referer·CP949·iframe)
