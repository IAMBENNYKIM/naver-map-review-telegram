"""naver_review_collector 단위 테스트 (httpx.MockTransport — 네트워크 완전 차단)."""

import json
import os

import httpx
import pytest

import config
import naver_review_collector

PLACE_ID = "33099281"
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load_fixture_text(filename: str) -> str:
    with open(os.path.join(FIXTURES_DIR, filename), encoding="utf-8") as file:
        return file.read()


@pytest.fixture(autouse=True)
def no_rate_limit_delay(monkeypatch):
    """테스트에서는 Rate Limit 대기를 생략한다."""
    monkeypatch.setattr(config, "RATE_LIMIT_DELAY", 0)


@pytest.fixture()
def install_transport(monkeypatch):
    """MockTransport를 collector에 주입하는 헬퍼를 반환한다."""

    def _install(handler):
        monkeypatch.setattr(
            naver_review_collector, "_transport", httpx.MockTransport(handler)
        )

    return _install


# ---------------------------------------------------------------------------
# resolve_place
# ---------------------------------------------------------------------------

class TestResolvePlace:
    def test_히스토리_중간_url의_pinId를_추출한다(self, install_transport):
        # pinId는 중간 리다이렉트 URL에만 있고 최종 URL에는 없다 (실측 체인 재현)
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.startswith("https://naver.me/"):
                return httpx.Response(
                    307,
                    headers={
                        "Location": (
                            "https://map.naver.com/p/entry/place"
                            f"?pinType=site&pinId={PLACE_ID}&c=15.00"
                        )
                    },
                )
            if url.startswith("https://map.naver.com/"):
                return httpx.Response(
                    302, headers={"Location": "https://m.map.naver.com/app-landing"}
                )
            return httpx.Response(200, text="app landing page")

        install_transport(handler)

        result = naver_review_collector.resolve_place("https://naver.me/GB3423bX")

        assert result == {"place_id": PLACE_ID}

    def test_최종_url의_pinId도_추출한다(self, install_transport):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.startswith("https://naver.me/"):
                return httpx.Response(
                    302,
                    headers={
                        "Location": f"https://m.map.naver.com/?pinId={PLACE_ID}"
                    },
                )
            return httpx.Response(200, text="final")

        install_transport(handler)

        result = naver_review_collector.resolve_place("https://naver.me/xyz")

        assert result == {"place_id": PLACE_ID}

    def test_pinId가_없으면_ReviewCollectError(self, install_transport):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="no redirect, no pin")

        install_transport(handler)

        with pytest.raises(naver_review_collector.ReviewCollectError):
            naver_review_collector.resolve_place("https://naver.me/nopin")

    def test_429면_즉시_ReviewCollectError_재시도_없음(self, install_transport):
        call_counter = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_counter["count"] += 1
            return httpx.Response(429, text="rate limited")

        install_transport(handler)

        with pytest.raises(naver_review_collector.ReviewCollectError, match="429"):
            naver_review_collector.resolve_place("https://naver.me/blocked")

        assert call_counter["count"] == 1  # 재시도 금지 확인


# ---------------------------------------------------------------------------
# fetch_place_detail
# ---------------------------------------------------------------------------

def place_detail_handler(request: httpx.Request) -> httpx.Response:
    """/place/... → 302 → /restaurant/... → 200 픽스처 HTML (실측 체인 재현)."""
    path = request.url.path
    if path.startswith("/place/"):
        return httpx.Response(
            302,
            headers={
                "Location": f"https://m.place.naver.com/restaurant/{PLACE_ID}/review/visitor"
            },
        )
    if path.startswith("/restaurant/"):
        return httpx.Response(200, text=load_fixture_text("place_detail.html"))
    return httpx.Response(404, text="not found")


class TestFetchPlaceDetail:
    def test_apollo_state에서_장소_상세를_파싱한다(self, install_transport):
        install_transport(place_detail_handler)

        detail = naver_review_collector.fetch_place_detail(PLACE_ID)

        assert detail["place_id"] == PLACE_ID
        assert detail["name"] == "돈멜 본점"
        # roadAddress 우선
        assert detail["address"] == "경기 성남시 분당구 느티로63번길 6 1층 돈멜"
        assert detail["business_type"] == "restaurant"  # 최종 URL 첫 세그먼트
        assert detail["avg_rating"] == 4.7
        assert detail["total_reviews"] == 1256

    def test_menu_stats를_label_count로_추출한다(self, install_transport):
        install_transport(place_detail_handler)

        detail = naver_review_collector.fetch_place_detail(PLACE_ID)

        assert detail["menu_stats"] == [
            {"label": "고기", "count": 325},
            {"label": "근고기", "count": 86},
            {"label": "목살", "count": 84},
        ]

    def test_roadAddress_없으면_지번_주소로_폴백한다(self, install_transport):
        html = load_fixture_text("place_detail.html").replace(
            '"roadAddress":"경기 성남시 분당구 느티로63번길 6 1층 돈멜",', ""
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/place/"):
                return httpx.Response(
                    302,
                    headers={
                        "Location": f"https://m.place.naver.com/restaurant/{PLACE_ID}/review/visitor"
                    },
                )
            return httpx.Response(200, text=html)

        install_transport(handler)

        detail = naver_review_collector.fetch_place_detail(PLACE_ID)

        assert detail["address"] == "경기 성남시 분당구 정자동 66-16"

    def test_menus_없으면_빈_리스트다(self, install_transport):
        html = load_fixture_text("place_detail.html").replace(
            f'"VisitorReviewStatsResult:{PLACE_ID}"', '"VisitorReviewStatsResult:0"'
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/place/"):
                return httpx.Response(
                    302,
                    headers={
                        "Location": f"https://m.place.naver.com/restaurant/{PLACE_ID}/review/visitor"
                    },
                )
            return httpx.Response(200, text=html)

        install_transport(handler)

        detail = naver_review_collector.fetch_place_detail(PLACE_ID)

        assert detail["menu_stats"] == []

    def test_apollo_state가_없으면_ReviewCollectError(self, install_transport):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html><body>no apollo</body></html>")

        install_transport(handler)

        with pytest.raises(naver_review_collector.ReviewCollectError):
            naver_review_collector.fetch_place_detail(PLACE_ID)

    def test_429면_즉시_ReviewCollectError(self, install_transport):
        call_counter = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_counter["count"] += 1
            return httpx.Response(429, text="rate limited")

        install_transport(handler)

        with pytest.raises(naver_review_collector.ReviewCollectError, match="429"):
            naver_review_collector.fetch_place_detail(PLACE_ID)

        assert call_counter["count"] == 1


# ---------------------------------------------------------------------------
# fetch_reviews
# ---------------------------------------------------------------------------

class TestFetchReviews:
    def graphql_handler(self, captured_requests: list):
        graphql_response_text = load_fixture_text("graphql_reviews.json")

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(
                200,
                text=graphql_response_text,
                headers={"Content-Type": "application/json"},
            )

        return handler

    def test_리뷰를_계약_dict로_매핑하고_빈_본문을_제외한다(self, install_transport):
        captured: list = []
        install_transport(self.graphql_handler(captured))

        review_list = naver_review_collector.fetch_reviews(
            PLACE_ID, "restaurant", limit=50
        )

        # 픽스처 3건 중 빈 본문 1건 제외 → 2건
        assert len(review_list) == 2

        first_review = review_list[0]
        assert first_review["text"] == "고기가 정말 맛있고 직원분들이 직접 구워주셔서 편했어요."
        assert first_review["rating"] is None
        assert first_review["date"] == "2026-06-28T09:19:36.000Z"
        assert first_review["keywords"] == ["음식이 맛있어요", "친절해요", "직접 잘 구워줘요"]

        # 앞뒤 공백 strip + votedKeywords null → 빈 리스트
        second_review = review_list[1]
        assert second_review["text"] == "웨이팅이 30분 정도 있었지만 목살이 두툼해서 만족."
        assert second_review["keywords"] == []

    def test_리뷰_dict에_닉네임_등_식별_정보가_없다(self, install_transport):
        captured: list = []
        install_transport(self.graphql_handler(captured))

        review_list = naver_review_collector.fetch_reviews(PLACE_ID, "restaurant", 50)

        for review in review_list:
            assert set(review.keys()) == {"text", "rating", "date", "keywords"}

    def test_요청_바디가_실측_배치_형식이고_size에_limit이_반영된다(self, install_transport):
        captured: list = []
        install_transport(self.graphql_handler(captured))

        naver_review_collector.fetch_reviews(PLACE_ID, "restaurant", limit=50)

        assert len(captured) == 1
        request = captured[0]
        assert str(request.url) == "https://pcmap-api.place.naver.com/graphql"
        assert request.headers["Content-Type"] == "application/json"

        body = json.loads(request.content.decode("utf-8"))
        assert isinstance(body, list) and len(body) == 1  # 배치 배열 형식
        assert body[0]["operationName"] == "getVisitorReviews"
        graphql_input = body[0]["variables"]["input"]
        assert graphql_input["businessId"] == PLACE_ID
        assert graphql_input["businessType"] == "restaurant"
        assert graphql_input["size"] == 50
        assert graphql_input["item"] == "0"
        # 인트로스펙션 금지 — 쿼리에 __type 등이 없어야 한다
        assert "__type" not in body[0]["query"]

    def test_limit이_반환_개수에도_반영된다(self, install_transport):
        captured: list = []
        install_transport(self.graphql_handler(captured))

        review_list = naver_review_collector.fetch_reviews(
            PLACE_ID, "restaurant", limit=1
        )

        body = json.loads(captured[0].content.decode("utf-8"))
        assert body[0]["variables"]["input"]["size"] == 1
        assert len(review_list) == 1  # 응답이 더 많아도 limit으로 자른다

    def test_429면_즉시_ReviewCollectError_재시도_없음(self, install_transport):
        call_counter = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_counter["count"] += 1
            return httpx.Response(429, text="rate limited")

        install_transport(handler)

        with pytest.raises(naver_review_collector.ReviewCollectError, match="429"):
            naver_review_collector.fetch_reviews(PLACE_ID, "restaurant", 50)

        assert call_counter["count"] == 1

    def test_응답_구조가_다르면_ReviewCollectError(self, install_transport):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": True})

        install_transport(handler)

        with pytest.raises(naver_review_collector.ReviewCollectError):
            naver_review_collector.fetch_reviews(PLACE_ID, "restaurant", 50)
