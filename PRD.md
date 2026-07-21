# PRD.md — MVP 명세

REQUIREMENTS.md의 기능을 구현 가능한 수준으로 구체화한다.

## 1. 사용자 흐름

### 신규 조회
```
사용자: (네이버지도 공유 텍스트)
        [네이버지도]
        돈멜 본점
        경기 성남시 분당구 느티로63번길 6 1층 돈멜
        https://naver.me/GB3423bX

봇(즉시): 🔍 돈멜 본점 리뷰를 분석하고 있어요. 잠시만 기다려 주세요.
봇(10~30초 후):
        🍽 돈멜 본점
        📍 경기 성남시 분당구 …

        ■ 총평
        (2~3문장)

        👍 장점  / 👎 단점 (불릿 각 2~4개)

        🍜 메뉴별 추천도
        ✅ 돈카츠 — 추천 (23회 언급) : 두툼하고 육즙…
        ⚠️ 카레 — 호불호 (7회 언급) : 향이 강하다는 평…
        ❌ 우동 — 비추천 (4회 언급) : 불어서 나온다는 평…

        ⚠️ 주의: 웨이팅 30분 이상이라는 언급 다수
        (리뷰 50개 기준 · 2026-07-04 갱신)
```

### 캐시 히트
```
봇: (저장된 요약 그대로) + "📌 2026-06-20에 분석한 결과예요 (14일 전).
    최신 리뷰로 다시 분석하려면 /update 를 보내주세요."
```

### /update
직전에 조회한 음식점(chat별 기억)을 캐시 무시하고 재수집·재요약.

## 2. 기능 명세

| ID | 기능 | 동작 상세 |
|----|------|-----------|
| F1 | URL 처리 | 메시지 텍스트에서 `https://naver.me/...` 정규식 추출. 없으면 사용법 안내. 공유 텍스트의 장소명·주소는 표시용으로 활용하되, 신뢰 원천은 스크래핑 결과 |
| F2 | 리뷰 수집 | place_id 해석 → 방문자 리뷰 최신순 50개. 50개 미만이면 있는 만큼 (10개 미만 시 응답에 표본 부족 문구) |
| F3+F4 | 분석 | Claude 1회 호출, 아래 §4 JSON 계약으로 구조화 출력 |
| F5 | 캐시 | place_id 키로 **전역 저장(모든 사용자 공유)**, 만료 없음. 히트 시 Claude·리뷰수집 없이 즉시 응답(place_id 해석 1회만 수행) |
| F6 | /update | `last#<chat_id>` 항목에서 직전 place_id 조회. 없으면 "먼저 음식점 URL을 보내주세요" |
| F7 | 접근 제어 | 허용목록 외 chat_id 무시(200), secret token 불일치 403 |
| F8 | 안내 | /start·/help·URL 없는 텍스트 → 사용법 메시지 |

## 3. 데이터 모델 (DynamoDB)

테이블: `${prefix}review_cache`, PK `place_key`(S), PAY_PER_REQUEST, TTL 미사용.

**캐시 범위**: 요약 캐시 항목(`place_key = <place_id>`)은 **전역 공유** — chat_id를 키에 넣지 않으므로 A가 조회한 식당을 B가 조회하면 A의 캐시를 그대로 받는다(식당당 1개, last-write-wins). 사용자별로 분리되는 것은 `/update` 대상 포인터(`last#<chat_id>`)뿐이다.

### 캐시 항목 (`place_key = <place_id>`)
| 속성 | 타입 | 설명 |
|------|------|------|
| place_key | S | 네이버 place_id |
| place_name | S | 음식점명 |
| address | S | 주소 |
| summary_json | S | §4 분석 결과 JSON 직렬화 |
| review_count | N | 분석에 사용한 리뷰 수 |
| updated_at | S | ISO 8601 (KST) |

### 최근 조회 항목 (`place_key = "last#<chat_id>"`)
| 속성 | 타입 | 설명 |
|------|------|------|
| place_key | S | `last#<chat_id>` |
| last_place_id | S | 직전 조회 place_id |
| updated_at | S | ISO 8601 |

## 4. 분석 출력 계약 (review_analyst → formatter)

```json
{
  "overall": "총평 2~3문장",
  "pros": ["장점 불릿"],
  "cons": ["단점 불릿"],
  "menus": [
    {"name": "돈카츠", "sentiment": "추천", "mentions": 23, "note": "한 줄 근거"}
  ],
  "caution": "주의사항 또는 null"
}
```

- `sentiment` ∈ {추천, 비추천, 호불호}. `menus`는 언급 수 내림차순, 최대 8개, 2회 이상 언급만.
- 모델: `config.ANTHROPIC_MODEL = "claude-sonnet-4-5"` (상수로만 교체).
- 파싱 실패·API 실패 시 `None` 반환 → 호출자가 폴백 응답 발송 (non-critical).

## 5. 리뷰 dict 계약 (collector → analyst) — 2026-07-04 실측 확정

| 키 | 타입 | 필수 |
|----|------|------|
| text | str | ✅ 리뷰 본문 (빈 본문 리뷰는 수집 단계에서 제외) |
| rating | None | 실측상 개별 리뷰 별점은 항상 null — 필드는 유지하되 None |
| date | str \| None | 방문일 (`representativeVisitDateTime`, ISO) |
| keywords | list[str] | 리뷰어가 선택한 키워드 태그 ("음식이 맛있어요" 등) |

추가로 collector는 **장소 상세 dict**를 제공한다: `place_id`, `name`, `address`, `business_type`, `avg_rating`, `total_reviews`, `menu_stats`(장소 레벨 메뉴 언급 통계 `[{"label", "count"}]` — F4 메뉴 추천도의 보조 근거).

리뷰어 닉네임 등 식별 정보는 수집·저장하지 않는다. 상세 근거는 `experiments/findings.md`.

## 6. Lambda 구성

| 함수 | 역할 | Timeout |
|------|------|---------|
| WebhookFunction | 검증(secret·허용목록) → URL/명령 파싱 → WorkerFunction `InvocationType="Event"` invoke → "분석 중" 발송 → 200 | 10초 |
| WorkerFunction | place 해석 → 캐시 조회 → (미스 시) 수집 → 분석 → 포맷 → 발송 → 캐시 저장 | 120초 |

Webhook payload → Worker 전달 이벤트: `{"chat_id": int, "action": "analyze"|"update", "naver_url": str|null, "shared_place_name": str|null}`

## 7. 성공 기준

- 신규 조회 30초 이내, 캐시 히트 3초 이내 응답.
- MarkdownV2 파싱 오류(400) 0건 — 이스케이프 헬퍼 강제 경유로 보장.
- 스크래핑 실패 시 개발자 chat으로 에러 알림, 사용자에겐 정중한 실패 안내.

## 8. 미확정 사항 해소 (2026-07-04 실측 완료)

- ~~네이버 리뷰 엔드포인트·페이지네이션·응답 스키마~~ → **확정: httpx 단독 가능, Playwright 불필요.** 요청 시퀀스·스키마·운영 주의(모바일 UA·인트로스펙션 금지·429 무재시도)의 원천은 `experiments/findings.md`.
- ~~`visited_menus` 제공 여부~~ → 개별 리뷰에는 없음. F4는 **리뷰 본문 텍스트 + 장소 레벨 `menu_stats`** 를 함께 근거로 집계.

## 9. 요청당 비용 (2026-07-05 실측 기준)

- **모델** `claude-sonnet-4-5`($3/$15 per MTok). 신규 분석 1건 입력 ≈ 9,515토큰(리뷰 48개), 출력 ≈ 900토큰.
- **신규 조회 / `/update`**: Claude ≈ **$0.04(약 55~60원)**. 리뷰 개수에 비례(20개면 ~$0.02).
- **캐시 히트 / 안내 메시지**: Claude 호출 없음 → **사실상 0원**.
- **AWS**: Lambda·API Gateway·DynamoDB는 프리 티어·소액으로 요청당 반올림 0원. 고정비는 Secrets Manager ≈ **$0.40/월**.
- 비용 절감 레버: 모델 다운그레이드(`ANTHROPIC_MODEL`), `REVIEW_FETCH_LIMIT` 축소, 전역 캐시로 식당당 1회만 과금.

## 10. 웹 진입점 (MVP 이후 확장 — 2026-07-07 라이브)

Telegram 미사용 지인용 웹 진입점을 **별도 격리 스택**(`naver-review-web`) + Vercel 정적 PWA로 추가했다. 핵심: 초대코드→HMAC 세션, 비동기 잡+폴링(API GW 30초 타임아웃 회피), Telegram 캐시 읽기전용 read-through, 관리자 사용량 통계(누적+일별). 본 PRD의 §4 JSON 계약·§5 리뷰 dict 계약을 그대로 재사용하며 렌더만 카드 UI로 대체한다.

- 설계 결정·근거: `docs/web-design.md` / 코드·인프라: `ARCHITECTURE.md` / 배포: `docs/setup-guide.md` §8

### 10-1. 장소 텍스트 검색 (URL 없이 — 2026-07-17 라이브)

URL을 모르는 사용자를 위해 자연어 프롬프트로 장소를 찾아 분석까지 잇는 진입 경로. LLM은 **검색어 정규화만** 담당하고 후보 리스트는 네이버 검색 결과만 사용한다(환각 0). 상세 설계 근거는 `docs/web-design.md` 결정 6.

**사용자 흐름**: 프롬프트 입력("강남 데이트 양식집") → `/search`가 정규화 검색어 + 후보 리스트 반환 → 사용자가 후보 카드 클릭 → 해당 `place_id`로 `/analyze` 직행 → 기존 요약 카드 렌더(URL 붙여넣기 경로와 동일 파이프라인).

**`POST /search`** (Bearer 세션 필요, WebApiFunction 동기 처리 — 잡+폴링 아님)

요청:
```json
{ "prompt": "강남 데이트 양식집" }
```
응답 (200):
```json
{
  "keyword": "강남 양식",
  "places": [
    {"place_id": "1234567", "name": "...", "category": "양식", "road_address": "서울 강남구 ...", "review_count": 128}
  ]
}
```
- `keyword`: LLM이 정규화한 검색어(정규화 실패 시 원문 폴백). `places`: 최대 10개, 0건이면 빈 배열. `review_count`는 `int` 또는 `null`.
- 오류: 401(세션 무효)·400(prompt 누락/빈값)·502(네이버 검색 실패).
- LLM 정규화는 모델 `claude-haiku-4-5`, timeout 5초·재시도 0, 어떤 실패에도 원문 폴백(개선 수단이지 필수 경로 아님). 킬 스위치 `SEARCH_LLM_ENABLED` off여도 원문 키워드로 검색은 동작.
- 검색 실측(엔드포인트·coords 필수·자연어 소화 한계)의 원천은 `experiments/findings.md` §6.

**`POST /analyze` 확장**: 기존 `naver_url` **또는** `place_id`(정규식 `^\d+$`) 중 하나를 받는다(둘 다 오면 `place_id` 우선). `place_id` 수신 시 Worker 이벤트 계약에 `place_id`가 실려 `resolve_place`(naver.me 해석)를 생략하고, 이후 캐시·수집·분석은 URL 경로와 동일하다.

### 잡 폴링 계약 (`POST /analyze` · `GET /result/{job_id}`)

분석은 비동기 잡+폴링이다. `/analyze`는 잡을 만들고 즉시 `202 {"job_id"}`를 돌려주며, 프론트가 `/result/{job_id}`를 폴링해 상태를 받는다. (필드는 `src/web_api_handler.py`의 `_handle_analyze`·`_handle_result` 코드 기준.)

**`POST /analyze`** (Bearer 세션 필요)

요청:
```json
{ "naver_url": "https://naver.me/...", "place_id": "1234567", "force_refresh": false }
```
- `naver_url` **또는** `place_id`(`^\d+$`) 중 하나 필수(둘 다 오면 `place_id` 우선). `force_refresh`(기본 `false`): 캐시를 무시하고 강제 재분석(Telegram `/update` 패리티).
- 응답 (202): `{ "job_id": "..." }`.
- 캐시 히트 직결: `place_id` 경로 + `force_refresh=false`에서 공유 캐시가 히트면 워커 invoke 없이 done 잡을 즉시 생성해 202를 반환한다(결정 7-① — `docs/web-design.md`).
- 오류: 401(세션 무효)·400(body JSON 파싱 실패 / `place_id` 형식 오류 / `naver_url` 허용호스트 위반 / 둘 다 누락)·429(일일 LLM 상한 초과 — 캐시 미스 경로만).

**`GET /result/{job_id}`** (Bearer 세션 필요, 소유권 확인 — 잡 부재·타인 잡 모두 404로 존재 숨김)

응답 (200)은 `status`에 따라 3형태:
```json
{ "status": "processing", "stage": "cache_check" }
```
- `stage` ∈ `"cache_check"` → `"collecting"` → `"summarizing"` → `""`(구버전·전이 전 폴백). 대기 중 현재 단계 표시용.
```json
{ "status": "done", "summary_json": "{...}", "place_name": "...", "address": "...",
  "review_count": 48, "cache_hit": false, "updated_at": "2026-07-21T..." }
```
- `summary_json`은 **JSON 문자열**(파싱하면 §4 분석 계약 구조 — 프론트가 `parseSummaryJson`으로 파싱). `cache_hit`은 캐시 응답 여부, `updated_at`은 분석 시각(ISO 8601·KST).
```json
{ "status": "error", "error_message": "..." }
```
- 오류: 401(세션 무효)·404(잡 부재 또는 소유자 불일치).

### 10-2. 보관함(조회 이력) — 2026-07-21 라이브

분석한 식당을 다시 찾을 수 있게 identity별 조회 이력을 남긴다.

**`GET /history`** (Bearer 세션 필요)
```json
{ "history": [
  {"place_id": "1234567", "place_name": "...", "address": "...", "last_viewed_at": "2026-07-21T...", "view_count": 3}
] }
```
- `last_viewed_at` 내림차순(최신순). `view_count`는 정수.

**`DELETE /history/{place_id}`** (Bearer 세션 필요, `place_id` `^\d+$` 위반 시 400) → `{ "deleted": true }`.

UI: 항목 클릭 시 재분석(place_id 경로라 캐시 히트 직결로 즉시 응답), 완료된 항목을 재클릭하면 결과 접기 토글, 보관함 내 검색(식당명·주소 로컬 필터 — 서버 호출 없음). 저장 스키마·identity당 50건 상한은 `ARCHITECTURE.md`, PII 최소화(리뷰 본문·summary 미저장) 근거는 `docs/web-design.md` 결정 9-③ 참조.

### 10-3. 일괄·다중 분석 — 2026-07-21 라이브

- **검색 배치 분석**: 검색 결과 상위 5곳을 "상위 5곳 분석하기"·"다음 5곳"으로 일괄 분석, 결과는 각 후보 항목 아래 인라인 표시.
- **다중 링크 붙여넣기**: 공유 텍스트에 섞인 네이버 링크를 최대 5개까지 순차 분석.
- **검색 결과 접기 토글**(2026-07-22): 완료된 후보 항목을 재클릭해 분석 결과를 접고 펼친다.

프론트가 한 번에 하나씩 순차 실행하고(동시 워커 ≤ 1 — 네이버 429 방어) 429 응답 시 잔여 대상을 조기 중단하는 설계 근거는 `docs/web-design.md` 결정 9-① 참조.

**일일 LLM 상한**: 캐시 미스(실과금) 경로는 identity별 일일 상한(`WEB_DAILY_LLM_LIMIT`, 기본 100 — 템플릿 파라미터 `WebDailyLlmLimit`로 코드 수정 없이 조정)으로 비용 폭탄을 사전 차단한다(근거 `docs/web-design.md` 결정 8-②). 캐시 히트는 비용 0이라 상한에서 제외된다.
