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

- ~~네이버 리뷰 엔드포인트·페이지네이션·응답 스키마~~ → **확정**: naver.me 리다이렉트 `pinId` → m.place HTML(Apollo state) → pcmap-api GraphQL `getVisitorReviews` `size=50` 1회. httpx 단독 가능, Playwright 불필요. 전문은 `experiments/findings.md`.
- ~~`visited_menus` 제공 여부~~ → 개별 리뷰에는 없음. F4는 **리뷰 본문 텍스트 + 장소 레벨 `menu_stats`** 를 함께 근거로 집계.
- 운영 주의: GraphQL 인트로스펙션 금지(즉시 429 차단), 429 시 무재시도 즉시 실패 처리.
- **모바일 UA 필수** (2026-07-05 실기기 E2E에서 발견): `m.place.naver.com`이 데스크톱 UA를 429로 차단 → `config.NAVER_REQUEST_HEADERS`는 모바일 Chrome UA 사용. AWS Lambda IP도 정상 동작 확인.

## 9. 요청당 비용 (2026-07-05 실측 기준)

- **모델** `claude-sonnet-4-5`($3/$15 per MTok). 신규 분석 1건 입력 ≈ 9,515토큰(리뷰 48개), 출력 ≈ 900토큰.
- **신규 조회 / `/update`**: Claude ≈ **$0.04(약 55~60원)**. 리뷰 개수에 비례(20개면 ~$0.02).
- **캐시 히트 / 안내 메시지**: Claude 호출 없음 → **사실상 0원**.
- **AWS**: Lambda·API Gateway·DynamoDB는 프리 티어·소액으로 요청당 반올림 0원. 고정비는 Secrets Manager ≈ **$0.40/월**.
- 비용 절감 레버: 모델 다운그레이드(`ANTHROPIC_MODEL`), `REVIEW_FETCH_LIMIT` 축소, 전역 캐시로 식당당 1회만 과금.
