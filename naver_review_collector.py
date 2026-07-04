"""네이버 지도 장소 해석·리뷰 수집기 (인터페이스만 정의).

httpx로 요청하고 BeautifulSoup로 파싱한다(HTTP 클라이언트는 httpx로 통일 — 다른 것 추가 금지).

⚠️ 외부 소스 함정 (구현 시 반드시 확인 — CLAUDE.md 제약 10):
  1) Referer 헤더 필수 — 없으면 응답이 비거나 0건. config.NAVER_REQUEST_HEADERS 사용.
  2) 인코딩 — 페이지에 따라 CP949일 수 있다. response.encoding 확인 후 디코딩.
  3) 엔드포인트·파라미터는 반드시 실측 덤프(experiments/dumps/)로 확정 후 하드코딩.
  4) 요청 간 config.RATE_LIMIT_DELAY(0.5초) 준수.

이 파일은 계약(함수 시그니처)만 제공한다. 실제 구현은 Phase 1에서
네이버 응답 실측(ROADMAP Task 1-1~1-3)을 확정한 뒤 진행한다.
"""

import logging

import config  # noqa: F401 — 구현 시 NAVER_REQUEST_HEADERS·RATE_LIMIT_DELAY 등 사용

logger = logging.getLogger(__name__)


class ReviewCollectError(Exception):
    """리뷰 수집 실패(네트워크·구조 변경·place 해석 실패 등) 시 raise."""


def resolve_place(naver_url: str) -> dict:
    """네이버 지도 공유 URL(naver.me)을 place 정보로 해석한다.

    Args:
        naver_url: 공유 텍스트에서 추출한 단축 URL (https://naver.me/...).

    Returns:
        place 정보 dict:
          - place_id (str): 네이버 place_id
          - name (str): 음식점명
          - address (str): 주소

    Raises:
        ReviewCollectError: 리다이렉트 추적·place_id 추출 실패 시.
        NotImplementedError: Phase 1 실측 확정 전까지.
    """
    raise NotImplementedError(
        "place 해석 미구현 — Phase 1에서 naver.me 리다이렉트 구조 실측 후 구현한다."
    )


def fetch_reviews(place_id: str, limit: int = config.REVIEW_FETCH_LIMIT) -> list[dict]:
    """place_id의 방문자 리뷰를 최신순으로 최대 limit개 수집한다.

    Args:
        place_id: resolve_place가 반환한 네이버 place_id.
        limit: 최대 수집 개수(기본 config.REVIEW_FETCH_LIMIT).

    Returns:
        리뷰 dict 리스트 (PRD §5 계약):
          - text (str): 리뷰 본문 (필수)
          - rating (float | None): 별점 (없으면 None)
          - date (str | None): 작성/방문일
          - visited_menus (list[str]): 리뷰에 태그된 방문 메뉴 (없으면 빈 리스트)
        결과가 없으면 빈 리스트. 리뷰어 닉네임 등 식별 정보는 수집하지 않는다.

    Raises:
        ReviewCollectError: 네트워크 오류·응답 구조 변경 등 수집 실패 시.
        NotImplementedError: Phase 1 실측 확정 전까지.
    """
    raise NotImplementedError(
        "리뷰 수집 미구현 — Phase 1에서 리뷰 엔드포인트·스키마 실측 후 구현한다."
    )
