"""실측 통합 테스트 — 실제 네이버 호출 (옵트인 전용).

⚠️ 기본 pytest 실행에서는 제외된다 (pytest.ini: addopts = -m "not live").
실행: pytest tests/ -m live

주의:
  - 실제 네이버에 조회당 3회 요청을 보낸다. 연속 실행 금지 (Rate Limit).
  - GraphQL 429 쿨다운 중이면 실패할 수 있다 — 시간을 두고 재시도.
  - 탐사 근거 대상: https://naver.me/GB3423bX → 돈멜 본점 (place_id 33099281)
"""

import pytest

import naver_review_collector

LIVE_SHARE_URL = "https://naver.me/GB3423bX"
EXPECTED_PLACE_ID = "33099281"


@pytest.mark.live
class TestLiveNaverCollector:
    def test_전체_수집_파이프라인_실측(self):
        # 1) naver.me → place_id
        resolved = naver_review_collector.resolve_place(LIVE_SHARE_URL)
        assert resolved["place_id"] == EXPECTED_PLACE_ID

        # 2) 장소 상세 (Apollo state)
        place_detail = naver_review_collector.fetch_place_detail(
            resolved["place_id"]
        )
        assert place_detail["name"]  # 장소명 존재
        assert place_detail["address"]
        assert place_detail["business_type"]  # restaurant 등
        assert isinstance(place_detail["menu_stats"], list)

        # 3) GraphQL 리뷰 50건
        review_list = naver_review_collector.fetch_reviews(
            place_detail["place_id"],
            place_detail["business_type"],
            limit=50,
        )
        assert 0 < len(review_list) <= 50
        for review in review_list:
            assert review["text"].strip()  # 빈 본문 필터 확인
            assert review["rating"] is None
            assert set(review.keys()) == {"text", "rating", "date", "keywords"}
