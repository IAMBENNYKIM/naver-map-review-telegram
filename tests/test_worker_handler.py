"""worker_handler 통합 테스트 (collector·dynamo·telegram 전부 mock)."""

from unittest.mock import patch

import config
import worker_handler

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


def build_event(action: str, naver_url: str | None = None) -> dict:
    return {
        "chat_id": CHAT_ID,
        "action": action,
        "naver_url": naver_url,
        "shared_place_name": "돈멜 본점",
    }


class TestAnalyzeFlow:
    def test_캐시_미스면_수집후_분석_발송_저장까지_수행한다(self):
        with patch(
            "naver_review_collector.resolve_place", return_value={"place_id": PLACE_ID}
        ) as mock_resolve, patch(
            "dynamo_writer.get_cached_summary", return_value=None
        ) as mock_get_cache, patch(
            "naver_review_collector.fetch_place_detail", return_value=PLACE_DETAIL
        ) as mock_detail, patch(
            "naver_review_collector.fetch_reviews", return_value=REVIEW_LIST
        ) as mock_reviews, patch.object(
            worker_handler, "_analyze_reviews", return_value='{"overall": "총평"}'
        ) as mock_analyze, patch.object(
            worker_handler, "_format_summary", return_value="포맷된 메시지"
        ) as mock_format, patch(
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
        # business_type은 place_detail에서, limit은 config에서
        mock_reviews.assert_called_once_with(
            PLACE_ID, "restaurant", config.REVIEW_FETCH_LIMIT
        )
        mock_analyze.assert_called_once_with(PLACE_DETAIL, REVIEW_LIST)
        mock_format.assert_called_once_with(PLACE_DETAIL, '{"overall": "총평"}')
        mock_send.assert_called_once_with(CHAT_ID, "포맷된 메시지")
        # save_summary는 place_detail의 name/address 사용
        save_kwargs = mock_save_summary.call_args.kwargs
        assert save_kwargs["place_id"] == PLACE_ID
        assert save_kwargs["place_name"] == "돈멜 본점"
        assert save_kwargs["address"] == "경기 성남시 분당구 느티로63번길 6 1층 돈멜"
        assert save_kwargs["review_count"] == 2
        mock_save_last.assert_called_once_with(CHAT_ID, PLACE_ID)

    def test_분석_스텁_미구현이면_준비중_안내와_개발자_알림을_보낸다(self):
        with patch(
            "naver_review_collector.resolve_place", return_value={"place_id": PLACE_ID}
        ), patch("dynamo_writer.get_cached_summary", return_value=None), patch(
            "naver_review_collector.fetch_place_detail", return_value=PLACE_DETAIL
        ), patch(
            "naver_review_collector.fetch_reviews", return_value=REVIEW_LIST
        ), patch(
            "telegram_sender.send_reply"
        ) as mock_send, patch(
            "telegram_sender.send_error_alert"
        ) as mock_alert:
            result = worker_handler.lambda_handler(
                build_event("analyze", "https://naver.me/GB3423bX"), None
            )

        assert result["statusCode"] == 200
        assert "준비 중" in mock_send.call_args.args[1]
        mock_alert.assert_called_once()

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
        ) as mock_reviews, patch.object(
            worker_handler, "_analyze_reviews", return_value="{}"
        ), patch.object(
            worker_handler, "_format_summary", return_value="메시지"
        ), patch(
            "telegram_sender.send_reply"
        ), patch(
            "dynamo_writer.save_summary"
        ), patch(
            "dynamo_writer.save_last_place_id"
        ):
            result = worker_handler.lambda_handler(build_event("update"), None)

        assert result["statusCode"] == 200
        mock_get_cache.assert_not_called()  # update는 캐시 무시
        mock_detail.assert_called_once_with(PLACE_ID)
        mock_reviews.assert_called_once_with(
            PLACE_ID, "restaurant", config.REVIEW_FETCH_LIMIT
        )


class TestInvalidEvent:
    def test_잘못된_action은_무시하고_정상_종료한다(self):
        with patch("telegram_sender.send_reply") as mock_send:
            result = worker_handler.lambda_handler(
                {"chat_id": CHAT_ID, "action": "unknown"}, None
            )

        assert result["statusCode"] == 200
        mock_send.assert_not_called()
