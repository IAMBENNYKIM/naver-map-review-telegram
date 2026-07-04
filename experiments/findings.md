# 네이버 지도 리뷰 스크래핑 탐사 보고서 (실측 기반)

- 탐사일: 2026-07-04 / 대상: https://naver.me/GB3423bX → 돈멜 본점 (place_id `33099281`)
- 도구: Python + httpx 단독, 총 12회 요청. 원본 덤프: `experiments/dumps/` (gitignore)
- **최종 판정: httpx 단독 구현 가능. Playwright 불필요.** 전 구간 UTF-8 (CP949 함정 미발견), 로그인·JS·captcha 없음.

## 1. 확정된 요청 시퀀스 (프로덕션 조회당 총 3회)

### 단계 A — naver.me → place_id
`GET https://naver.me/{code}` (follow_redirects=True). 리다이렉트 체인의 URL 쿼리에서 추출:

```
307 naver.me/... → map.naver.com?...pinType=site&pinId=33099281...
302 → m.map.naver.com/?...pinId=33099281... → (최종 200은 앱 유도 페이지, 본문 무용)
```

**추출 규칙: 정규식 `[?&]pinId=(\d+)`** 를 리다이렉트 히스토리 URL들에 적용.

### 단계 B — 장소 상세 HTML (장소명·주소·통계·businessType)
`GET https://m.place.naver.com/restaurant/{place_id}/review/visitor` → 200, UTF-8.

- `/place/{id}/review/visitor` 로 요청하면 302로 `/restaurant/{id}/...` 도착 → **최종 URL 첫 세그먼트가 businessType** (restaurant/cafe 등, GraphQL input에 필요).
- HTML 내 `window.__APOLLO_STATE__` SSR JSON. **비탐욕 정규식으로는 추출 실패** — 문자열 이스케이프 고려한 중괄호 균형 매칭 필요 (`experiments/step3_parse_apollo.py`의 `extract_apollo()` 재사용).
- 리뷰 20건도 함께 포함되나 50건 수집은 단계 C 사용.

### 단계 C — GraphQL 리뷰 50건 (1회 호출)
`POST https://pcmap-api.place.naver.com/graphql` — 바디는 **JSON 배열(배치 형식)**:

```json
[{"operationName":"getVisitorReviews",
  "variables":{"input":{"businessId":"33099281","businessType":"restaurant","item":"0","size":50,"includeContent":true,"getUserStats":true,"includeReceiptPhotos":true,"isPhotoUsed":false}},
  "query":"query getVisitorReviews($input: VisitorReviewsInput) { visitorReviews(input: $input) { items { id reviewId rating author { id nickname } body visited created visitCount originType votedKeywords { name } representativeVisitDateTime } total } }"}]
```

- 실측: 200, 50건 전부 고유 id, total 895. input 원형은 Apollo `ROOT_QUERY."visitorReviews({...})"`의 실서비스 파라미터.
- 헤더: `Content-Type: application/json` + 모바일 Chrome UA. **Referer는 제거해도 정상 동작** (비용 없으니 유지 권장).

## 2. 응답 스키마 (근거: `dumps/step5_B_full_p1s50.json`)

루트 `[0].data.visitorReviews`:

| 항목 | 경로 | 실측 비고 |
|---|---|---|
| 총 리뷰 수 | `.total` | 895 |
| 본문 | `.items[].body` | 48/50 존재, **2건 빈 문자열 → 필터 필요** |
| 별점 | `.items[].rating` | **50/50 전부 null** — 개별 리뷰 별점 없음. 통계 avgRating(4.7)만 존재 |
| 방문일 | `.items[].representativeVisitDateTime` | ISO 형식 50/50 — 날짜는 이 필드 사용 (`visited`는 "6.2.화" 혼재) |
| 키워드 태그 | `.items[].votedKeywords[].name` | 50/50 ("음식이 맛있어요" 등) |

개별 리뷰에 방문 메뉴 태그 없음(`tags: null`). **메뉴 언급 통계는 장소 레벨** — HTML Apollo state의 `VisitorReviewStatsResult:{id}.analysis.menus[]{label,count}`.

HTML Apollo state (근거: `dumps/step3_apollo.json`, `dumps/step4_fields.txt`):
- 장소명 `PlaceDetailBase:{id}.name`, 도로명 `.roadAddress`, 지번 `.address`, 카테고리 `.category`
- 평균 별점 `.visitorReviewsScore`(4.7), 리뷰 총계 `.visitorReviewsTotal`(1256)
- 별점 분포 `VisitorReviewStatsResult:{id}.review.starDistribution[]`, 키워드 통계 `.analysis.votedKeyword.details[]`

## 3. 페이지네이션

- **`size=50` 1회 호출로 50건 확보 (실측 완료).** `page` 파라미터는 조용히 무시됨 (step5_A vs step5_D 완전 동일).
- 50건 초과는 커서 방식 추정이나 미확정 — 본 프로젝트(50건)에는 불필요.

## 4. 실패한 시도 (반복 금지)

1. **GraphQL 인트로스펙션(`__type`) → 즉시 429 + 지속 차단** (4.5분+ 쿨다운 미회복). **인트로스펙션 절대 금지.** 일반 쿼리는 0.6초 간격 4연속까지 무사.
2. `__APOLLO_STATE__` 비탐욕 정규식 추출 실패 → 중괄호 균형 매칭으로 해결.
3. `page` 파라미터 페이지네이션 — 에러 없이 무시됨. size 확대가 정답.
4. 개별 리뷰 `rating` 기대 — 전부 null. 별점은 통계 레벨에서만.
5. 429 중 재시도 2회 모두 429 — **차단 시 무재시도 즉시 중단**하고 에러 처리할 것.

## 5. 구현 가이드

- 조회당 요청 3회 (단축URL 1 + HTML 1 + GraphQL 1), 요청 간 `RATE_LIMIT_DELAY` 0.5초.
- 429 응답 시 재시도 금지, `ReviewCollectError`로 즉시 실패 처리.
- 캐시 정책은 프로젝트 결정(만료 없음 + /update)을 따른다.

실험 스크립트: `step1_redirect.py`(리다이렉트) / `step2_place_html.py`(HTML) / `step3_parse_apollo.py`(Apollo 추출 — 프로덕션 재사용 대상) / `step4_fields.py`(필드 덤프) / `step5_graphql.py`(GraphQL 검증) / `step6_pagination.py`(인트로스펙션 — **재실행 금지**).
