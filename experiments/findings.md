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
- **기본 정렬 = 최신순(방문일 내림차순).** 요청에 정렬 파라미터를 넣지 않고 `item:"0"`만 보내면 네이버 서버 기본 정렬을 받는데, 이것이 **최신순**이다. 근거: `dumps/step5_B_full_p1s50.json`의 `representativeVisitDateTime`가 50건 완전 내림차순 + 라이브 재확인(2026-07-07, `naver.me/G58TjgA7`). ⚠️ **네이버 리뷰 탭 UI 기본값은 "추천순"이라 서로 다르다** — 사용자에게 "우리가 읽는 순서"를 안내할 땐 UI에서 정렬을 '최신순'으로 바꿔야 같아진다고 설명해야 한다.
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

## 6. 장소 텍스트 검색 (키워드 → place_id 후보 리스트)

- 탐사일: 2026-07-16 / 도구: Python + httpx 단독, 총 약 16회 요청, **429 0건**. 원본 덤프: `experiments/dumps/step7_*.json`.
- 목적: 웹 진입점의 "자연어 프롬프트 → 장소 후보 리스트 → 클릭 시 리뷰 분석" 흐름. §1~5의 "place_id → 리뷰"와 반대 방향(텍스트 → place_id).
- **판정: go — httpx 단독으로 텍스트 검색 → place_id 리스트 구현 가능.** 로그인·JS·captcha 없음, 전 구간 UTF-8.

### 6-1. 확정 엔드포인트

```
GET https://map.naver.com/p/api/search/instant-search?query={검색어}&coords={lat,lng}
```

- **필수 파라미터**: `query` (검색어) + `coords`("37.4979,127.0276" = lat,lng). ⚠️ **정정(2026-07-17)**: `coords`는 **사실상 필수** — 생략 시 쿼리·인코딩과 무관하게 **HTTP 500** (프로덕션 이식 중 로컬·Lambda 동일 재현). 2026-07-16 "선택 — 없어도 200" 기록은 **오판**이었다(당시 탐사 스크립트 `step7_place_search.py`가 항상 coords를 함께 보냈던 탓). coords 값은 근접도(`dist`)·정렬 기준일 뿐이라 지역명이 query에 포함되면 결과 자체엔 영향이 작으므로, 고정 좌표(강남역 근방)를 상수로 붙인다.
- **필수 헤더**: `Referer: https://map.naver.com/` — **없으면 403 Forbidden (nginx)** (근거: 실측, no-referer 요청이 403 text/html 548바이트 반환). §1~5의 pcmap-api GraphQL은 Referer 선택이었으나 **instant-search는 Referer 필수**로 정책이 다르다. `Accept-Language`도 유지.
- **User-Agent**: 데스크톱/모바일 **둘 다 200 허용** (근거: 데스크톱 UA로 `돈멜` 조회 시 200 + place 6건 + first id 33099281). m.place.naver.com(§1 데스크톱 UA 429 차단)과 정책이 다르다. 단 프로젝트 일관성상 `config.NAVER_REQUEST_HEADERS`(모바일 UA) 재사용 권장.
- 응답 최대 후보 수: place 섹션 6~10건 (autocomplete 성격 — 페이지네이션 없음). 후보 브라우징엔 충분.

### 6-2. 응답 스키마 (근거: `dumps/step7_instant_donmel.json`, `dumps/step7_instant_gangnam_yangsik.json`)

루트는 dict, 섹션 키: `meta, ac, bookingKeyword, place, address, bus, menu, menuForWeb, all`. 장소 후보는 `place[]` 배열.

| 항목 | JSON 경로 | 실측 비고 |
|---|---|---|
| place_id | `place[].id` (== `.sid`) | 문자열 숫자 "33099281". 프로덕션 조회 place_id와 동일 체계 |
| 장소명 | `place[].title` | 하이라이트 마크업 없이 순수 텍스트 (`<b>` 등 없음 — 실측) |
| 카테고리 | `place[].ctg` | "돼지고기구이", "양식", "스페인음식" 등 |
| 도로명 주소 | `place[].roadAddress` | 전체 도로명 |
| 지번 주소 | `place[].jibunAddress` | 전체 지번 |
| 축약 주소 | `place[].shortAddress[]` | 배열, 1건 |
| 리뷰 수 | `place[].review.count` | 문자열 "1258" (방문자+블로그 합산 추정, §2 `.total`과 정확히 일치하진 않음) |
| 좌표 | `place[].x`(경도), `place[].y`(위도) | 문자열 |
| 기타 | `.cid`(카테고리 코드), `.totalScore`(랭킹 점수), `.dist`(coords 거리), `.hasBooking`, `.type`("place") | — |

- **평점·대표 이미지 URL 없음** — instant-search 응답에 별점/썸네일 필드 부재(선택 요구사항이라 미충족 무방). 필요 시 각 place_id로 §1 단계 B(HTML Apollo `visitorReviewsScore`) 재사용 또는 대표 이미지는 별도 조회 필요.

### 6-3. 자연어 질의 소화 수준 (LLM 정규화 필요성 근거 데이터)

| 키워드 | 결과 | 상위 3건 |
|---|---|---|
| `강남 양식` (지역+업종) | **10건** | 치스타리에 강남역점 / 을지다락 강남역 / 트라가 강남역점 |
| `돈멜` (상호 직접) | **6건**, **place_id 33099281 포함 확인(교차검증 통과)** | 돈멜 본점(33099281) / 돈멜 서현 직영점 / 돈멜 미금 직영점 |
| `강남 데이트 양식집` (자연어) | **0건** (place=[], all=[], len=194) | — |

- **핵심**: instant-search는 autocomplete 성격이라 "지역+업종" 또는 "상호명"은 잘 소화하나, **"데이트" 같은 상황어가 섞인 자연어 다중개념 질의는 빈 결과**. → **LLM으로 자연어를 "지역+업종/상호" 형태로 정규화하는 전처리가 필수**. (`강남 데이트 양식집` → `강남 양식` 수준으로 축약해야 결과가 나옴.)

### 6-4. 실패한 시도 (반복 금지)

1. **allSearch 엔드포인트 `GET https://map.naver.com/p/api/search/allSearch?query=...&type=all`** — 정상 질의(`강남 양식`)에도 `result.place: null` + `result.metaInfo.pageId: "ncaptcha-all-search-no-result"` + `ncaptcha`(`confirmRules: "CE_EMPTY_TOKEN"`) 반환. 별도 captcha/토큰을 요구해 **httpx 단독 불가**. captcha 유발 방지 위해 더 밀지 않음 (근거: `dumps/step7_allsearch_gangnam.json`, `dumps/step7_allsearch_nl.json`). → **instant-search로 충분하므로 allSearch 불필요.**
2. **Referer 생략** → 403 Forbidden. instant-search엔 Referer 필수.
3. 자연어 다중개념 질의 → 빈 결과 (위 6-3). 엔드포인트 문제 아님, 질의 형태 문제 → LLM 정규화로 해결.
4. **`coords` 생략 → HTTP 500** (2026-07-17 실측, 로컬·Lambda 동일). 6-1 정정 참조 — 반드시 coords를 함께 보낸다.

### 6-5. rate limit 실측

- Referer 포함 0.5초 간격 **4연속 호출 전부 200** (429 0건). instant-search도 §4의 pcmap-api와 동일하게 0.5초 간격이면 안전.
- 미탐사(불필요): allSearch 토큰 획득 경로, 후보 6~10건 초과 페이지네이션, 평점/이미지 보강 엔드포인트.

실험 스크립트: `step7_place_search.py`(확정 산출물 — 3종 키워드 후보 리스트 출력 + 돈멜 교차검증) / `step7_probe.py`(엔드포인트·헤더 대조 탐사 도구).
