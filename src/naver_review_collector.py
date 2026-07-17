"""네이버 지도 장소 해석·리뷰 수집기 (2026-07-04 실측 확정 구현).

httpx 단독으로 조회당 3회 요청 (근거: experiments/findings.md):
  1) resolve_place      — naver.me 리다이렉트 체인에서 pinId(=place_id) 추출
  2) fetch_place_detail — m.place HTML의 __APOLLO_STATE__ 에서 장소 상세·메뉴 통계
  3) fetch_reviews      — pcmap-api GraphQL getVisitorReviews (size=limit, 1회)

⚠️ 운영 규칙 (findings.md §4·§5 실측):
  - 요청 간 config.RATE_LIMIT_DELAY(0.5초) 대기, config.NAVER_REQUEST_HEADERS 사용
  - 429 응답 시 재시도 금지 — 즉시 ReviewCollectError (재시도 2회 모두 429 실측)
  - GraphQL 인트로스펙션(__type) 절대 금지 — 즉시 429 + 지속 차단
  - 리뷰어 닉네임 등 식별 정보는 반환 dict에 포함하지 않는다 (PII 최소화)
"""

import json
import logging
import re
import time
from urllib.parse import quote

import httpx

import config

logger = logging.getLogger(__name__)

# 리다이렉트 체인 URL에서 place_id 추출 (findings.md §1 단계 A)
_PIN_ID_PATTERN = re.compile(r"[?&]pinId=(\d+)")

# 장소 상세(리뷰 탭) 모바일 URL — /place/... 요청 시 302로 /restaurant/... 등 도착
_MOBILE_PLACE_URL_TEMPLATE = "https://m.place.naver.com/place/{place_id}/review/visitor"

# GraphQL 리뷰 엔드포인트 (findings.md §1 단계 C)
_GRAPHQL_ENDPOINT = "https://pcmap-api.place.naver.com/graphql"

# 장소 텍스트 검색(instant-search) 엔드포인트 (findings.md §6-1 실측 확정)
# Referer 필수(없으면 403) — config.NAVER_REQUEST_HEADERS가 이미 포함한다.
_INSTANT_SEARCH_ENDPOINT = "https://map.naver.com/p/api/search/instant-search"
# 검색 요청 고정 좌표(강남역 근방 lat,lng) — 근접도 정렬 기준일 뿐이나
# coords 생략 시 HTTP 500 (2026-07-17 실측). 지역명이 query에 포함되는 전제라 고정값 사용.
_SEARCH_DEFAULT_COORDS = "37.4979,127.0276"

# 실측 검증된 쿼리 원문 (실서비스 파라미터 원형 — 임의 확장 금지)
_VISITOR_REVIEWS_QUERY = (
    "query getVisitorReviews($input: VisitorReviewsInput) { "
    "visitorReviews(input: $input) { "
    "items { id reviewId rating author { id nickname } body visited created "
    "visitCount originType votedKeywords { name } representativeVisitDateTime } "
    "total } }"
)

# 테스트에서 httpx.MockTransport 주입용 (프로덕션에서는 None → 기본 전송 계층)
_transport: httpx.BaseTransport | None = None


class ReviewCollectError(Exception):
    """리뷰 수집 실패(네트워크·429 차단·구조 변경·place 해석 실패 등) 시 raise."""


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

def resolve_place(naver_url: str) -> dict:
    """네이버 지도 공유 URL(naver.me)을 place_id로 해석한다.

    리다이렉트 체인(follow_redirects=True)의 히스토리 + 최종 URL에서
    정규식 `[?&]pinId=(\\d+)` 로 place_id를 추출한다 (findings.md §1 단계 A).

    Returns:
        {"place_id": str}

    Raises:
        ReviewCollectError: 네트워크 오류·429·pinId 미발견 시.
    """
    response = _http_get(naver_url, context="naver.me 리다이렉트")

    candidate_urls = [str(item.url) for item in response.history] + [str(response.url)]
    for url in candidate_urls:
        match = _PIN_ID_PATTERN.search(url)
        if match:
            place_id = match.group(1)
            logger.info("place_id 해석 완료 (place_id=%s)", place_id)
            return {"place_id": place_id}

    raise ReviewCollectError(
        f"리다이렉트 체인에서 pinId를 찾지 못했습니다 (최종 상태={response.status_code})"
    )


def fetch_place_detail(place_id: str) -> dict:
    """장소 상세 HTML의 __APOLLO_STATE__ 에서 장소 정보·메뉴 통계를 추출한다.

    /place/{id}/review/visitor 요청 → 302로 /restaurant/{id}/... 도착.
    최종 URL 첫 세그먼트가 business_type (GraphQL input에 필요).

    Returns:
        {"place_id", "name", "address"(roadAddress 우선), "business_type",
         "avg_rating", "total_reviews", "menu_stats": [{"label", "count"}]}

    Raises:
        ReviewCollectError: 네트워크 오류·429·Apollo state 추출/파싱 실패 시.
    """
    url = _MOBILE_PLACE_URL_TEMPLATE.format(place_id=place_id)
    response = _http_get(url, context="장소 상세 HTML")
    _raise_for_http_status(response, context="장소 상세 HTML")

    business_type = _extract_business_type(response.url)
    apollo_state = _parse_apollo_state(response.text)

    base = apollo_state.get(f"PlaceDetailBase:{place_id}")
    if not isinstance(base, dict):
        raise ReviewCollectError(
            f"Apollo state에 PlaceDetailBase:{place_id} 항목이 없습니다 (구조 변경 가능성)"
        )

    stats = apollo_state.get(f"VisitorReviewStatsResult:{place_id}") or {}
    analysis = stats.get("analysis") or {}
    raw_menus = analysis.get("menus") or []
    menu_stats = [
        {"label": menu.get("label"), "count": menu.get("count")}
        for menu in raw_menus
        if isinstance(menu, dict) and menu.get("label")
    ]

    return {
        "place_id": place_id,
        "name": base.get("name", ""),
        "address": base.get("roadAddress") or base.get("address") or "",
        "business_type": business_type,
        "avg_rating": base.get("visitorReviewsScore"),
        "total_reviews": base.get("visitorReviewsTotal"),
        "menu_stats": menu_stats,
    }


def fetch_reviews(
    place_id: str,
    business_type: str,
    limit: int = config.REVIEW_FETCH_LIMIT,
) -> list[dict]:
    """pcmap-api GraphQL로 방문자 리뷰를 최신순 최대 limit개 수집한다.

    바디는 실측 확정된 배치 배열 형식 (findings.md §1 단계 C).
    빈 본문(strip 후 공백) 리뷰는 제외한다.

    Returns:
        리뷰 dict 리스트 (PRD §5 계약):
          - text (str): 리뷰 본문 (빈 본문 제외)
          - rating (None): 실측상 개별 리뷰 별점은 항상 null — 필드 유지
          - date (str | None): 방문일 (representativeVisitDateTime, ISO)
          - keywords (list[str]): 리뷰어 선택 키워드 태그
        리뷰어 닉네임 등 식별 정보는 포함하지 않는다.

    Raises:
        ReviewCollectError: 네트워크 오류·429·응답 구조 변경 시.
    """
    request_body = [
        {
            "operationName": "getVisitorReviews",
            "variables": {
                "input": {
                    "businessId": place_id,
                    "businessType": business_type,
                    "item": "0",
                    "size": limit,
                    "includeContent": True,
                    "getUserStats": True,
                    "includeReceiptPhotos": True,
                    "isPhotoUsed": False,
                }
            },
            "query": _VISITOR_REVIEWS_QUERY,
        }
    ]

    response = _http_post_json(_GRAPHQL_ENDPOINT, request_body, context="GraphQL 리뷰")
    _raise_for_http_status(response, context="GraphQL 리뷰")

    try:
        payload = response.json()
        items = payload[0]["data"]["visitorReviews"]["items"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise ReviewCollectError(
            f"GraphQL 응답 구조가 예상과 다릅니다 (스키마 변경 가능성): {error}"
        ) from error

    review_list: list[dict] = []
    for item in items:
        body_text = (item.get("body") or "").strip()
        if not body_text:
            continue  # 빈 본문 리뷰 제외 (실측: 50건 중 2건)
        keywords = [
            keyword.get("name")
            for keyword in (item.get("votedKeywords") or [])
            if isinstance(keyword, dict) and keyword.get("name")
        ]
        review_list.append(
            {
                "text": body_text,
                "rating": None,  # 실측상 개별 리뷰 별점은 항상 null
                "date": item.get("representativeVisitDateTime"),
                "keywords": keywords,
            }
        )

    logger.info("리뷰 수집 완료 (place_id=%s, 수집=%d건)", place_id, len(review_list))
    return review_list[:limit]


def search_places(keyword: str, limit: int = 10) -> list[dict]:
    """검색어로 네이버 지도 장소 후보 리스트를 조회한다 (findings.md §6 실측 확정).

    instant-search 엔드포인트에 query·coords 파라미터를 보낸다(coords 생략 시 HTTP 500 —
    지역명이 keyword에 포함되는 전제라 고정 좌표 사용). 응답 루트 dict의 ``place[]``
    배열에서 후보를 추출한다. ``place`` 키 부재·null이면 빈 리스트를 반환하며,
    limit 개수로 절단한다.

    Returns:
        후보 dict 리스트 (웹 /search API 계약):
          - place_id (str): 장소 ID (``place[].id``)
          - name (str): 장소명 (``place[].title``)
          - category (str): 카테고리 (``place[].ctg``)
          - road_address (str): 도로명 주소 (``place[].roadAddress``)
          - review_count (int | None): 리뷰 수 (``place[].review.count`` int 변환, 실패 시 None)

    Raises:
        ReviewCollectError: 네트워크 오류·429·4xx/5xx 응답 시 (기존 규약 준수).
            PII 보호: HTTP 오류 메시지에는 URL·keyword를 포함하지 않고 상태코드만 남긴다.
    """
    response = _http_get(
        f"{_INSTANT_SEARCH_ENDPOINT}?query={quote(keyword)}"
        f"&coords={quote(_SEARCH_DEFAULT_COORDS)}",
        context="장소 검색",
    )
    # 상태 오류 메시지에 URL(=인코딩된 keyword)이 새지 않도록 상태코드만 남긴다
    # (_raise_for_http_status는 error 문자열에 URL을 담으므로 search 경로에서는 미사용).
    if response.status_code >= 400:
        raise ReviewCollectError(f"장소 검색 HTTP {response.status_code} 응답")

    try:
        payload = response.json()
    except json.JSONDecodeError as error:
        raise ReviewCollectError(
            f"장소 검색 응답 JSON 파싱 실패 (구조 변경 가능성): {error}"
        ) from error

    raw_places = payload.get("place") if isinstance(payload, dict) else None
    if not raw_places:
        logger.info("장소 검색 결과 없음 (결과=0건)")
        return []

    place_list: list[dict] = []
    for place in raw_places[:limit]:
        if not isinstance(place, dict):
            continue
        review = place.get("review")
        review_count = None
        if isinstance(review, dict):
            try:
                review_count = int(review.get("count"))
            except (TypeError, ValueError):
                review_count = None  # 비숫자·부재 시 None
        place_list.append(
            {
                "place_id": place.get("id", ""),
                "name": place.get("title", ""),
                "category": place.get("ctg", ""),
                "road_address": place.get("roadAddress", ""),
                "review_count": review_count,
            }
        )

    logger.info("장소 검색 완료 (결과=%d건)", len(place_list))
    return place_list


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _build_client() -> httpx.Client:
    """공통 헤더·타임아웃·리다이렉트 설정을 적용한 httpx 클라이언트를 생성한다."""
    return httpx.Client(
        headers=config.NAVER_REQUEST_HEADERS,
        timeout=config.NAVER_REQUEST_TIMEOUT,
        follow_redirects=True,
        transport=_transport,
    )


def _http_get(url: str, context: str) -> httpx.Response:
    """Rate Limit 대기 후 GET 요청. 네트워크 오류·429는 ReviewCollectError."""
    time.sleep(config.RATE_LIMIT_DELAY)
    try:
        with _build_client() as client:
            response = client.get(url)
    except httpx.HTTPError as error:
        raise ReviewCollectError(f"{context} 요청 실패: {error}") from error
    _raise_if_rate_limited(response, context)
    return response


def _http_post_json(url: str, body: object, context: str) -> httpx.Response:
    """Rate Limit 대기 후 JSON POST 요청. 네트워크 오류·429는 ReviewCollectError."""
    time.sleep(config.RATE_LIMIT_DELAY)
    try:
        with _build_client() as client:
            response = client.post(
                url, json=body, headers={"Content-Type": "application/json"}
            )
    except httpx.HTTPError as error:
        raise ReviewCollectError(f"{context} 요청 실패: {error}") from error
    _raise_if_rate_limited(response, context)
    return response


def _raise_if_rate_limited(response: httpx.Response, context: str) -> None:
    """429면 재시도 없이 즉시 실패 처리한다 (findings.md §4 — 재시도 무의미)."""
    if response.status_code == 429:
        raise ReviewCollectError(
            f"{context} 429 Rate Limit — 재시도 금지, 즉시 중단 (쿨다운 필요)"
        )


def _raise_for_http_status(response: httpx.Response, context: str) -> None:
    """4xx/5xx 응답을 ReviewCollectError로 변환한다 (429는 이미 별도 처리)."""
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise ReviewCollectError(
            f"{context} HTTP {response.status_code} 응답: {error}"
        ) from error


def _extract_business_type(final_url: httpx.URL) -> str:
    """최종 URL 경로 첫 세그먼트를 business_type으로 추출한다.

    예: /restaurant/33099281/review/visitor → "restaurant"
    """
    segments = [segment for segment in str(final_url.path).split("/") if segment]
    if not segments:
        raise ReviewCollectError(
            f"최종 URL에서 business_type을 추출하지 못했습니다 (url={final_url})"
        )
    return segments[0]


def _extract_apollo_state_raw(html: str) -> str | None:
    """HTML에서 window.__APOLLO_STATE__ JSON 원문을 잘라낸다.

    비탐욕 정규식으로는 실패 (실측) — 문자열 이스케이프를 고려한
    중괄호 균형 매칭 사용. (experiments/step3_parse_apollo.py extract_apollo 이식)
    """
    match = re.search(r"__APOLLO_STATE__\s*=\s*", html)
    if not match:
        return None
    start = html.find("{", match.end())
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(html)):
        character = html[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return html[start : index + 1]
    return None


def _parse_apollo_state(html: str) -> dict:
    """__APOLLO_STATE__ 를 dict로 파싱한다. 실패 시 ReviewCollectError."""
    raw_state = _extract_apollo_state_raw(html)
    if not raw_state:
        raise ReviewCollectError(
            "__APOLLO_STATE__ 추출 실패 — HTML 구조 변경 가능성"
        )
    try:
        return json.loads(raw_state)
    except json.JSONDecodeError as error:
        raise ReviewCollectError(
            f"__APOLLO_STATE__ JSON 파싱 실패: {error}"
        ) from error
