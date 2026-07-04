# ROADMAP.md — 개발 로드맵 (진행 상태의 단일 진실 공급원)

작업 완료 시 체크박스를 갱신한다. 태스크 담당: A=Advisor 직접, D=worker-dev, S=worker-scraper.

## Phase 0 — 문서·골격 재구축

- [x] 0-1 (A) 명세 문서 작성: CLAUDE.md, REQUIREMENTS.md, PRD.md, ROADMAP.md, ARCHITECTURE.md
- [x] 0-2 (A) Worker 에이전트 정의: `.claude/agents/worker-dev.md`, `.claude/agents/worker-scraper.md`
- [x] 0-3 (D) ref 모듈 이식 + 2-Lambda 반영: `config.py`, `telegram_sender.py`, `review_formatter.py`, `webhook_handler.py`, `worker_handler.py`(신규), `dynamo_writer.py`, `template.yaml`, `samconfig.toml`, `requirements.txt`, `.env.example`, `tests/` 기본
- [x] 0-4 (A) 검증: `pytest tests/` 41개 통과, `sam validate --lint` 통과, diff 확인 → 커밋

## Phase 1 — 스크래핑 확정 ⚠️ 게이트

- [ ] 1-1 (S) naver.me 리다이렉트 추적 → place_id 추출 규칙 실측 확정
- [ ] 1-2 (S) 리뷰 엔드포인트·페이지네이션·응답 스키마 실측 확정 (덤프 `experiments/dumps/`)
- [ ] 1-3 (A) 조사 보고서 검증: 덤프 확인, httpx 구현 가능 판정 (불가 시 Playwright 전환 결정)
- [ ] 1-4 (D) `naver_review_collector.py` 구현: place_id 해석 + 리뷰 50개 수집 + 파서, mock 단위 테스트 + `-m live` 실측 테스트
- [ ] 1-5 (A) 검증: 실제 URL(돈멜 본점)로 리뷰 50개 수집을 직접 실행 확인 → 커밋

## Phase 2 — 분석·응답 파이프라인

- [ ] 2-1 (D) `review_analyst.py`: Claude JSON 구조화 출력(총평·장단점·메뉴별 추천도), 파싱 실패 폴백
- [ ] 2-2 (D) `review_formatter.py`: 분석 JSON → MarkdownV2 응답 포맷 (캐시 히트 문구 포함)
- [ ] 2-3 (D) `command_router.py`: URL 추출, /update·/start·/help 라우팅, Worker 이벤트 계약
- [ ] 2-4 (A) 검증: 실측 리뷰 덤프로 Claude 호출해 요약·메뉴 추천 품질 육안 확인, 이스케이프 테스트 통과 → 커밋

## Phase 3 — 캐시·/update 흐름

- [ ] 3-1 (D) `dynamo_writer.py`: 캐시 read/write, `last#<chat_id>` 항목, float→Decimal
- [ ] 3-2 (D) `worker_handler.py` 통합: 캐시 히트/미스/update 분기 완성
- [ ] 3-3 (A) 검증: moto mock으로 3개 시나리오(신규/히트/update) 테스트 통과 → 커밋

## Phase 4 — 배포·E2E

- [ ] 4-1 (D) SAM 템플릿 최종화: 2-Lambda, IAM 최소권한(invoke·dynamo·secrets), Outputs
- [ ] 4-2 (D) `docs/setup-guide.md` 갱신 (2-Lambda 기준)
- [ ] 4-3 (A) 배포: Secrets Manager 등록 → `sam build && sam deploy` → setWebhook
- [ ] 4-4 (A) 실기기 E2E: ① URL 공유→요약 수신 ② 재조회→캐시 응답 ③ /update→갱신 → 커밋·완료 보고

## 백로그 (MVP 이후, VOC 기반 결정)

- 장소명 텍스트 검색 (URL 없이)
- 개인 리뷰 기록/조회 (/review, /review_update — UC-3)
- 블로그 리뷰 수집 확대
- 캐시 자동 만료(TTL) 재검토
