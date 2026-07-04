"""worker_handler 통합 테스트 (collector·analyst·dynamo·telegram 전부 mock)."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import config
import worker_handler

_KST = timezone(timedelta(hours=9))

CHAT_ID = "123456789"
PLACE_ID = "33099281"

PLACE_DETAIL = {
    "place_id": PLACE_ID,
    "name": "돈멜 본점",
    "address": "경기 성남시 분당구 느티로63번길 6 1층 돈멜",
    "business_type": "restaurant",
    "avg_rating": 4.7,
    "total_reviews": 1256,
    "menu_stats": [{"label": "고기", "count": 325}],
}

REVIEW_LIST = [
    {"text": "맛있어요", "rating": None, "date": "2026-06-28T09:19:36.000Z", "keywords": []},
    {"text": "친절해요", "rating": None, "date": "2026-06-25T11:02:10.000Z", "keywords": []},
]

SUMMARY_JSON = json.dumps(
    {
        "overall": "전반적으로 만족도가 높다.",
        "pros": ["고기 질이 좋다"],
        "cons": ["웨이팅이 길다"],
        "menus": [{"name": "목살", "sentiment": "추천", "mentions": 12, "note": "호평"}],
        "caution": None,
    },
    ensure_ascii=False,
)


def build_event(action: str, naver_url: str | None = None) -> dict:
    return {
        "chat_id": CHAT_ID,
        "action": action,
        "naver_url": naver_url,
        "shared_place_name": "돈멜 본점",
    }


class TestAnalyzeFlow:
    def test_분석_성공이면_발송하고_캐시와_최근기록을_저장한다(self):
        with patch(
            "naver_review_collector.resolve_place", return_value={"place_id": PLACE_ID}
        ) as mock_resolve, patch(
            "dynamo_writer.get_cached_summary", return_value=None
        ) as mock_get_cache, patch(
            "naver_review_collector.fetch_place_detail", return_value=PLACE_DETAIL
        ) as mock_detail, patch(
            "naver_review_collector.fetch_reviews", return_value=REVIEW_LIST
        ) as mock_reviews, patch(
            "review_analyst.analyze_reviews", return_value=SUMMARY_JSON
        ) as mock_analyze, patch(
            "telegram_sender.send_reply"
        ) as mock_send, patch(
            "dynamo_writer.save_summary"
        ) as mock_save_summary, patch(
            "dynamo_writer.save_last_place_id"
        ) as mock_save_last:
            result = worker_handler.lambda_handler(
                build_event("analyze", "https://naver.me/GB3423bX"), None
            )

        assert result["statusCode"] == 200
        mock_resolve.assert_called_once_with("https://naver.me/GB3423bX")
        mock_get_cache.assert_called_once_with(PLACE_ID)
        mock_detail.assert_called_once_with(PLACE_ID)
        mock_reviews.assert_called_once_with(
            PLACE_ID, "restaurant", config.REVIEW_FETCH_LIMIT
        )
        mock_analyze.assert_called_once_with(PLACE_DETAIL, REVIEW_LIST)

        # 실제 formatter 경유 — PRD 레이아웃 요소 확인
        sent_message = mock_send.call_args.args[1]
        assert "🍽 돈멜 본점" in sent_message
        assert "■ 총평" in sent_message
        assert "📌" not in sent_message  # 신규 분석에는 캐시 안내 없음

        save_kwargs = mock_save_summary.call_args.kwargs
        assert save_kwargs["place_id"] == PLACE_ID
        assert save_kwargs["place_name"] == "돈멜 본점"
        assert save_kwargs["address"] == "경기 성남시 분당구 느티로63번길 6 1층 돈멜"
        assert save_kwargs["summary_json"] == SUMMARY_JSON
        assert save_kwargs["review_count"] == 2
        mock_save_last.assert_called_once_with(CHAT_ID, PLACE_ID)

    def test_분석_실패면_폴백_발송하고_캐시는_저장하지_않는다(self):
        with patch(
            "naver_review_collector.resolve_place", return_value={"place_id": PLACE_ID}
        ), patch("dynamo_writer.get_cached_summary", return_value=None), patch(
            "naver_review_collector.fetch_place_detail", return_value=PLACE_DETAIL
        ), patch(
            "naver_review_collector.fetch_reviews", return_value=REVIEW_LIST
        ), patch(
            "review_analyst.analyze_reviews", return_value=None
        ), patch(
            "telegram_sender.send_reply"
        ) as mock_send, patch(
            "telegram_sender.send_error_alert"
        ) as mock_alert, patch(
            "dynamo_writer.save_summary"
        ) as mock_save_summary, patch(
            "dynamo_writer.save_last_place_id"
        ) as mock_save_last:
            result = worker_handler.lambda_handler(
                build_event("analyze", "https://naver.me/GB3423bX"), None
            )

        assert result["statusCode"] == 200
        # 폴백 메시지(장소 정보 + 실패 안내) 발송
        sent_message = mock_send.call_args.args[1]
        assert "🍽 돈멜 본점" in sent_message
        assert "AI 요약 생성에 실패했어요" in sent_message
        # 실패 요약은 캐시에 저장하지 않는다
        mock_save_summary.assert_not_called()
        # /update 재시도를 위해 최근 조회 기록은 저장한다
        mock_save_last.assert_called_once_with(CHAT_ID, PLACE_ID)
        mock_alert.assert_called_once()

    def test_캐시_히트면_수집_없이_캐시_요약을_발송한다(self):
        cached_item = {
            "place_key": PLACE_ID,
            "place_name": "돈멜 본점",
            "address": "경기 성남시 분당구 느티로63번길 6 1층 돈멜",
            "summary_json": SUMMARY_JSON,
            "review_count": Decimal("50"),  # DynamoDB는 숫자를 Decimal로 반환
            "updated_at": (datetime.now(_KST) - timedelta(days=14)).isoformat(),
        }

        with patch(
            "naver_review_collector.resolve_place", return_value={"place_id": PLACE_ID}
        ), patch(
            "dynamo_writer.get_cached_summary", return_value=cached_item
        ), patch(
            "naver_review_collector.fetch_place_detail"
        ) as mock_detail, patch(
            "telegram_sender.send_reply"
        ) as mock_send, patch(
            "dynamo_writer.save_last_place_id"
        ) as mock_save_last:
            result = worker_handler.lambda_handler(
                build_event("analyze", "https://naver.me/GB3423bX"), None
            )

        assert result["statusCode"] == 200
        mock_detail.assert_not_called()  # 캐시 히트 — 재수집 없음

        sent_message = mock_send.call_args.args[1]
        assert "🍽 돈멜 본점" in sent_message
        assert "📌" in sent_message  # 캐시 안내 문구
        assert "/update" in sent_message
        assert "\\(14일 전\\)" in sent_message
        mock_save_last.assert_called_once_with(CHAT_ID, PLACE_ID)

    def test_수집_실패면_실패_안내와_개발자_알림을_보내고_정상_종료한다(self):
        import naver_review_collector

        with patch(
            "naver_review_collector.resolve_place",
            side_effect=naver_review_collector.ReviewCollectError("429 차단"),
        ), patch("telegram_sender.send_reply") as mock_send, patch(
            "telegram_sender.send_error_alert"
        ) as mock_alert:
            result = worker_handler.lambda_handler(
                build_event("analyze", "https://naver.me/GB3423bX"), None
            )

        assert result["statusCode"] == 200
        assert "문제가 발생" in mock_send.call_args.args[1]
        mock_alert.assert_called_once()


class TestUpdateFlow:
    def test_직전_조회_기록이_없으면_안내만_보낸다(self):
        with patch(
            "dynamo_writer.get_last_place_id", return_value=None
        ), patch("telegram_sender.send_reply") as mock_send, patch(
            "naver_review_collector.fetch_place_detail"
        ) as mock_detail:
            result = worker_handler.lambda_handler(build_event("update"), None)

        assert result["statusCode"] == 200
        assert "먼저 음식점 URL" in mock_send.call_args.args[1]
        mock_detail.assert_not_called()

    def test_직전_기록이_있으면_캐시를_무시하고_재수집한다(self):
        with patch(
            "dynamo_writer.get_last_place_id", return_value=PLACE_ID
        ), patch("dynamo_writer.get_cached_summary") as mock_get_cache, patch(
            "naver_review_collector.fetch_place_detail", return_value=PLACE_DETAIL
        ) as mock_detail, patch(
            "naver_review_collector.fetch_reviews", return_value=REVIEW_LIST
        ) as mock_reviews, patch(
            "review_analyst.analyze_reviews", return_value=SUMMARY_JSON
        ), patch(
            "telegram_sender.send_reply"
        ), patch(
            "dynamo_writer.save_summary"
        ) as mock_save_summary, patch(
            "dynamo_writer.save_last_place_id"
        ):
            result = worker_handler.lambda_handler(build_event("update"), None)

        assert result["statusCode"] == 200
        mock_get_cache.assert_not_called()  # update는 캐시 무시
        mock_detail.assert_called_once_with(PLACE_ID)
        mock_reviews.assert_called_once_with(
            PLACE_ID, "restaurant", config.REVIEW_FETCH_LIMIT
        )
        mock_save_summary.assert_called_once()


class TestInvalidEvent:
    def test_잘못된_action은_무시하고_정상_종료한다(self):
        with patch("telegram_sender.send_reply") as mock_send:
            result = worker_handler.lambda_handler(
                {"chat_id": CHAT_ID, "action": "unknown"}, None
            )

        assert result["statusCode"] == 200
        mock_send.assert_not_called()
