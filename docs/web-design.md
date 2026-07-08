# web-design.md — 웹 진입점 설계 결정 기록

웹 진입점(`naver-review-web` 스택 + Vercel 프론트, 2026-07-07 라이브)의 **설계 결정과 그 근거**를 기록한다.
"무엇이 배포돼 있는가"는 `ARCHITECTURE.md`, "어떻게 배포하는가"는 `docs/setup-guide.md` §8이 원천이다. 이 문서는 "왜 이렇게 설계했는가"만 담는다.

## 배경과 절대 제약

Telegram 봇은 개인용으로 잘 동작하나, 주변에 Telegram 미사용자가 많아 공유 진입장벽이 있었다. 웹 진입점을 추가하되 두 가지 절대 제약을 둔다:

1. **기존 Telegram 봇 영향 0** — 다운타임·회귀·리소스 경합 금지.
2. **비용 통제** — Telegram은 chat_id 화이트리스트로 LLM 호출자가 한정되지만, URL 기반 웹은 링크가 퍼지면 토큰 비용이 폭증할 수 있다.

## 결정 1 — 격리 전략: 별도 SAM 스택 + 코어 소스 재사용

**채택**: 별도 CloudFormation 스택 `naver-review-web`(별도 Lambda·API GW·IAM·테이블). 코어 모듈(`naver_review_collector`·`review_analyst`·`config`)은 소스 레벨 공유.

**근거**:
- 같은 스택에 라우트를 추가하면 웹 재배포가 기존 함수를 건드려 제약 1 위반. 별도 스택이면 배포·런타임·IAM이 자연 격리된다.
- 완전 분리(코어 복제)는 격리가 최고지만 스크래핑 로직 이중 유지보수 비용이 크다. 코어 파이프라인이 이미 Telegram 비의존(`telegram_sender`·`review_formatter`만 Telegram 전용)이라 소스 재사용이 안전했다.
- **보안 공백 봉쇄**: Telegram `WorkerFunction`은 무인증이라 직접 invoke가 가능하면 전 방어를 우회한다. 웹 스택 IAM에 Telegram WorkerFunction invoke 권한을 **부여하지 않음**으로써 자연 차단.
- `config.py`는 부재 시크릿 키를 빈 문자열로 처리(`_secret.get(k, "")`)하므로, 웹 스택이 자체 시크릿(`naver-review/web`)만 담아도 크래시 없음 — 시크릿 격리의 핵심.

## 결정 2 — 응답 구조: 비동기 잡 + 폴링

**채택**: `POST /analyze`가 잡 생성 후 즉시 `job_id` 반환 → WebWorker가 비동기로 파이프라인 수행·잡에 결과 기록 → 프론트가 `GET /result/{job_id}` 폴링.

**근거**: 캐시 미스 파이프라인이 ~30초(수집+Claude 분석)로 **API Gateway 30초 타임아웃을 초과**한다. Telegram 스택의 2-Lambda 비동기 패턴(즉답 + Event invoke)을 웹에 맞게 계승한 형태. 잡은 `web_jobs` 테이블(TTL 1시간)에 저장.

## 결정 3 — 접근 제어·비용 방어 계층 (안쪽→바깥쪽)

| 계층 | 상태 | 내용 |
|---|---|---|
| ① 초대코드 게이트 | 운영 중 | `WEB_INVITE_CODES`(`{"코드":"표시이름"}`)로 유입 자체를 지인으로 한정. 코드 폐기·회전 가능, PII 불필요 |
| ② 서버측 세션 재검증 | 운영 중 | 매 API 호출마다 HMAC 세션 토큰 검증(`web_auth`) — 무인증 공백을 웹에서는 반드시 메움 |
| ③ read-through 공유 캐시 | 운영 중 | 웹 캐시 미스 시 Telegram `prod_review_cache`를 **읽기전용**으로 조회 → 워밍된 캐시 재사용으로 히트율↑·비용↓. 쓰기 경합 없음(웹은 자체 `web_review_cache`에만 씀) |
| ④ AWS Budget 알림 | 운영 중 | 월 예산 50/80/100% 알림 + 킬 스위치(`LLM_COMMENTARY_ENABLED=false`). 링크 유출 시 최후 방어 |
| ⑤ per-identity 일일 쿼터 | **Phase 6 백로그** | 확산 시 도입. ③의 사용량 카운터(아래 결정 4)를 그대로 재사용하면 재구현 불필요 |

**바리케이드(생년월일 등) 미채택 근거**: 추측·무차별 대입에 취약하고 개인정보를 서버가 보관하는 부담. 지인 대상엔 초대코드가 우월하다.

**방어 강화 트리거**: 월 예산 50% 도달, 일 신규장소 요청 급증(예: 100건/일 초과), 초대코드 유출 정황 → 쿼터 도입 / 모델 티어 다운(`ANTHROPIC_MODEL` 상수) / 신규 초대 동결 / 킬 스위치 순으로 검토.

**비용 노브(상시 가용)**: `REVIEW_FETCH_LIMIT` 축소, 모델 티어 다운. 프롬프트 캐싱은 무의미(시스템 프롬프트가 캐시 최소 토큰 미만 + 리뷰는 장소마다 상이) — **DynamoDB 장소 캐시가 유일한 실질 절감선**.

## 결정 4 — 관리자 사용량 통계 (Phase 6 쿼터의 골격)

- 요청당 `web_usage`(PK `identity`) 항목에 누적 합계(`total_count`·`llm_call_count`·`last_used_at`)와 **일별 최상위 카운터**(`req#YYYY-MM-DD`·`llm#YYYY-MM-DD`)를 단일 `update_item`의 `ADD`로 누적한다. DynamoDB `ADD`는 없는 숫자 속성을 0으로 자동 초기화 → 스키마리스라 테이블·템플릿 변경 불필요.
- `llm_call_count`(캐시 미스 = 실제 과금)가 비용 프록시. Phase 6 일일 쿼터는 일별 카운터에 임계값만 얹으면 된다 — 카운터 재구현 불필요.
- `/admin/stats`는 `WEB_ADMIN_TOKEN`으로 보호. identity는 초대코드 표시이름(PII 아님). 리뷰 본문·원문 식별자는 통계에 남기지 않는다(CLAUDE.md 제약 7).
- 주의: 일별 카운터 도입(2026-07-07) 이전 사용량에는 일자 데이터가 없어 구간 필터 시 0으로 보인다(누적 합계에는 반영됨).

## 결정 5 — 프론트: 정적 Next.js PWA + Vercel

**채택**: Next.js 15(App Router)·Tailwind·shadcn/ui 정적 export를 Vercel(Hobby)에 배포. `review_analyst`의 JSON 계약(PRD §4)을 카드 UI로 직접 렌더(MarkdownV2 우회).

**근거**: 설치 불필요·링크 하나로 접근(지인 접근성 최고), 사용자 기본 스택과 일치해 공수 최소, AWS 인프라와 물리 분리(격리 보너스). 정적 파일이라 추후 AWS 이전도 저비용.

## 진입점 확장 로드맵 (백로그 근거)

| 후보 | 판정 | 근거 |
|---|---|---|
| 카카오 소셜 로그인 | Phase 6+ | 초대코드 대체·신원 기반 쿼터 가능하나 비즈채널·심사 공수 큼 — 확산 신호 후 |
| 카카오 SDK 리치 공유 | 백로그 | 개발자 앱 등록·JS키·도메인 등록 필요. 현재는 Web Share API로 대체 중 |
| 카카오 채널 챗봇/알림톡 | 보류 | 접근성 최고지만 심사·운영 부담 최대 |
| 네이티브 앱/APK | 보류 | 설치 마찰 — PWA로 충분 |
