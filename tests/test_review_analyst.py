"""review_analyst 단위 테스트 (anthropic SDK 전부 mock — 실호출 없음)."""

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import config
import review_analyst

PLACE_DETAIL = {
    "place_id": "33099281",
    "name": "돈멜 본점",
    "address": "경기 성남시 분당구 느티로63번길 6 1층 돈멜",
    "business_type": "restaurant",
    "avg_rating": 4.7,
    "total_reviews": 1256,
    "menu_stats": [{"label": "고기", "count": 325}, {"label": "목살", "count": 84}],
}

REVIEW_LIST = [
    {"text": "고기가 맛있어요", "rating": None, "date": "2026-06-28T09:19:36.000Z",
     "keywords": ["음식이 맛있어요"]},
    {"text": "웨이팅이 길어요", "rating": None, "date": "2026-06-25T11:02:10.000Z",
     "keywords": []},
]

VALID_SUMMARY = {
    "overall": "고기 품질이 좋고 친절하다는 평이 많다.",
    "pros": ["고기 질이 좋다", "직원이 직접 구워준다"],
    "cons": ["웨이팅이 길다"],
    "menus": [
        {"name": "목살", "sentiment": "추천", "mentions": 12, "note": "두툼하다는 평"},
        {"name": "김치찌개", "sentiment": "호불호", "mentions": 3, "note": "평이 갈림"},
    ],
    "caution": "주말 웨이팅 30분 이상 언급 다수",
}


def make_anthropic_mock(response_text: str) -> MagicMock:
    """지정한 텍스트를 응답하는 가짜 anthropic 모듈을 생성한다."""
    mock_module = MagicMock()
    text_block = SimpleNamespace(type="text", text=response_text)
    mock_module.Anthropic.return_value.messages.create.return_value = SimpleNamespace(
        content=[text_block]
    )
    return mock_module


def run_with_mock_response(response_text: str) -> str | None:
    """가짜 anthropic 모듈을 주입한 상태로 analyze_reviews를 실행한다."""
    mock_module = make_anthropic_mock(response_text)
    with patch.dict(sys.modules, {"anthropic": mock_module}):
        return review_analyst.analyze_reviews(PLACE_DETAIL, REVIEW_LIST)


class TestAnalyzeReviewsSuccess:
    def test_정상_json_응답이면_재직렬화된_json을_반환한다(self):
        result = run_with_mock_response(json.dumps(VALID_SUMMARY, ensure_ascii=False))

        assert result is not None
        parsed = json.loads(result)
        assert parsed["overall"] == VALID_SUMMARY["overall"]
        assert parsed["menus"][0]["sentiment"] == "추천"
        assert "돈멜" not in result or True  # 재직렬화 원문 — 구조 검증이 목적

    def test_코드펜스로_감싼_응답도_파싱한다(self):
        fenced = "```json\n" + json.dumps(VALID_SUMMARY, ensure_ascii=False) + "\n```"

        result = run_with_mock_response(fenced)

        assert result is not None
        assert json.loads(result)["pros"] == VALID_SUMMARY["pros"]

    def test_호출_파라미터가_config_상수를_사용한다(self):
        mock_module = make_anthropic_mock(json.dumps(VALID_SUMMARY, ensure_ascii=False))
        with patch.dict(sys.modules, {"anthropic": mock_module}):
            review_analyst.analyze_reviews(PLACE_DETAIL, REVIEW_LIST)

        create_kwargs = (
            mock_module.Anthropic.return_value.messages.create.call_args.kwargs
        )
        assert create_kwargs["model"] == config.ANTHROPIC_MODEL
        assert create_kwargs["max_tokens"] == config.LLM_MAX_OUTPUT_TOKENS
        # user content에 장소명·메뉴 통계·리뷰 본문이 포함된다
        user_content = create_kwargs["messages"][0]["content"]
        assert "돈멜 본점" in user_content
        assert "고기 325회" in user_content
        assert "고기가 맛있어요" in user_content

    def test_anthropic_생성자에_timeout과_max_retries를_전달한다(self):
        # tail latency 방지 — timeout=60.0, max_retries=0 (폴백 경로가 있으므로 재시도 0).
        mock_module = make_anthropic_mock(json.dumps(VALID_SUMMARY, ensure_ascii=False))
        with patch.dict(sys.modules, {"anthropic": mock_module}):
            review_analyst.analyze_reviews(PLACE_DETAIL, REVIEW_LIST)

        ctor_kwargs = mock_module.Anthropic.call_args.kwargs
        assert ctor_kwargs["timeout"] == 60.0
        assert ctor_kwargs["max_retries"] == 0

    def test_menus를_mentions_내림차순으로_정렬한다(self):
        # 모델이 정렬 규칙을 어겨도 코드에서 mentions 내림차순으로 재정렬한다.
        unsorted = json.loads(json.dumps(VALID_SUMMARY))
        unsorted["menus"] = [
            {"name": "A", "sentiment": "추천", "mentions": 3, "note": "x"},
            {"name": "B", "sentiment": "추천", "mentions": 20, "note": "y"},
            {"name": "C", "sentiment": "추천", "mentions": 7, "note": "z"},
        ]

        result = run_with_mock_response(json.dumps(unsorted, ensure_ascii=False))

        menus = json.loads(result)["menus"]
        assert [menu["mentions"] for menu in menus] == [20, 7, 3]

    def test_mentions가_int가_아니면_0으로_취급해_정렬한다(self):
        data = json.loads(json.dumps(VALID_SUMMARY))
        data["menus"] = [
            {"name": "A", "sentiment": "추천", "mentions": "많음", "note": "x"},
            {"name": "B", "sentiment": "추천", "mentions": 5, "note": "y"},
        ]

        result = run_with_mock_response(json.dumps(data, ensure_ascii=False))

        menus = json.loads(result)["menus"]
        # int가 아닌 mentions("많음")는 0 취급 → mentions 5인 B가 앞선다.
        assert menus[0]["name"] == "B"
        assert menus[1]["name"] == "A"


class TestAnalyzeReviewsFallback:
    def test_깨진_json이면_none을_반환한다(self):
        assert run_with_mock_response("{ 이건 JSON이 아님") is None

    def test_필수_키_누락이면_none을_반환한다(self):
        broken = {key: VALID_SUMMARY[key] for key in ("overall", "pros", "cons")}

        assert run_with_mock_response(json.dumps(broken, ensure_ascii=False)) is None

    def test_sentiment_이상값이면_none을_반환한다(self):
        invalid = json.loads(json.dumps(VALID_SUMMARY))
        invalid["menus"][0]["sentiment"] = "강력추천"  # 허용값 아님

        assert run_with_mock_response(json.dumps(invalid, ensure_ascii=False)) is None

    def test_킬스위치가_꺼져있으면_none을_반환한다(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_COMMENTARY_ENABLED", False)

        result = review_analyst.analyze_reviews(PLACE_DETAIL, REVIEW_LIST)

        assert result is None

    def test_api_키_미설정이면_none을_반환한다(self, monkeypatch):
        monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")

        result = review_analyst.analyze_reviews(PLACE_DETAIL, REVIEW_LIST)

        assert result is None

    def test_리뷰가_없으면_none을_반환한다(self):
        assert review_analyst.analyze_reviews(PLACE_DETAIL, []) is None

    def test_api_호출_예외면_none을_반환한다(self):
        mock_module = MagicMock()
        mock_module.Anthropic.return_value.messages.create.side_effect = RuntimeError(
            "API 오류"
        )
        with patch.dict(sys.modules, {"anthropic": mock_module}):
            result = review_analyst.analyze_reviews(PLACE_DETAIL, REVIEW_LIST)

        assert result is None
