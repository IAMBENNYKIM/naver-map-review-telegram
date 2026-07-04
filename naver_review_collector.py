"""네이버 지도 장소 리뷰 수집기 (외부 수집기 골격).

httpx로 요청하고 BeautifulSoup로 파싱한다(HTTP 클라이언트는 httpx로 통일 — 다른 것 추가 금지).

⚠️ 외부 소스 함정 (봇 기동 시 반드시 확인):
  1) Referer 헤더 필수 — 없으면 응답이 비거나 0건이 된다. config.NAVER_REQUEST_HEADERS 사용.
  2) 인코딩 — 페이지에 따라 CP949일 수 있다. response.encoding 확인 후 디코딩.
  3) iframe — 네이버 지도 place 상세는 iframe(entry) 안에 실제 콘텐츠가 있다. iframe src를
     따라 재요청해야 리뷰 본문이 나온다. place는 비공식 JSON(GraphQL) API를 쓰는 경우가 많다.

이 파일은 계약(함수 시그니처)·요청 관례·파싱 골격만 제공한다. 실제 엔드포인트/셀렉터는
`# TODO` 지점에서 네이버 응답을 실제로 덤프해 확정한다(하드코딩 전 실제 응답 검증).
"""

import logging
import time

import httpx
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)


class ReviewCollectError(Exception):
    """리뷰 수집 실패(네트워크·구조 변경 등) 시 raise."""


def fetch_reviews(place: str, limit: int | None = None) -> list[dict]:
    """장소명 또는 네이버 지도 URL로 리뷰를 수집한다.

    Args:
        place: 장소명(예: "성수동 카페") 또는 네이버 지도 place URL.
        limit: 최대 수집 개수(기본 config.REVIEW_FETCH_LIMIT).

    Returns:
        리뷰 dict 리스트. 각 dict 키(계약):
          - text (str): 리뷰 본문
          - rating (float | None): 별점(없으면 None)
          - author (str): 작성자(선택)
          - date (str): 작성일(선택)
        결과가 없으면 빈 리스트.

    Raises:
        ReviewCollectError: 네트워크 오류·구조 변경 등 수집 실패 시.
    """
    max_count = limit or config.REVIEW_FETCH_LIMIT

    try:
        place_id = _resolve_place_id(place)
        if not place_id:
            return []
        html = _fetch_place_html(place_id)
    except httpx.HTTPError as error:
        raise ReviewCollectError(f"네이버 요청 실패: {error}") from error

    reviews = _parse_reviews(html)
    return reviews[:max_count]


def _resolve_place_id(place: str) -> str | None:
    """장소명/URL을 네이버 place id로 변환한다.

    # TODO: URL이면 정규식으로 place id 추출, 장소명이면 검색 API로 최상위 place id 조회.
    #       (네이버 지도 검색 엔드포인트/응답 구조를 실제 덤프로 확정한 뒤 구현)
    """
    raise NotImplementedError(
        "place id 해석 미구현 — 네이버 지도 검색 응답 구조를 확정한 뒤 채운다."
    )


def _fetch_place_html(place_id: str) -> str:
    """place 상세(리뷰 탭) HTML/JSON을 가져온다.

    Referer 헤더 필수(config.NAVER_REQUEST_HEADERS). Rate Limit 대비 딜레이 적용.
    # TODO: 실제 리뷰 엔드포인트(iframe entry URL 또는 GraphQL)로 교체.
    """
    time.sleep(config.RATE_LIMIT_DELAY)
    url = f"{config.NAVER_MAP_BASE_URL}/p/entry/place/{place_id}"  # TODO: 실제 경로 확정
    response = httpx.get(
        url,
        headers=config.NAVER_REQUEST_HEADERS,
        timeout=config.NAVER_REQUEST_TIMEOUT,
        follow_redirects=True,
    )
    response.raise_for_status()
    # 인코딩 함정: 응답 인코딩을 신뢰(CP949 가능). httpx는 charset 미지정 시 utf-8 가정.
    return response.text


def _parse_reviews(html: str) -> list[dict]:
    """리뷰 HTML을 파싱해 dict 리스트로 변환한다.

    # TODO: 실제 리뷰 카드 셀렉터 확정. 아래는 골격 예시(셀렉터는 반드시 실제 응답으로 교체).
    """
    soup = BeautifulSoup(html, "html.parser")
    reviews: list[dict] = []
    for card in soup.select("li.review_item"):  # TODO: 실제 셀렉터로 교체
        text = card.get_text(strip=True)
        if not text:
            continue
        reviews.append({"text": text, "rating": None, "author": "", "date": ""})
    return reviews
