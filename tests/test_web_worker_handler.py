"""web_worker_handler 단위 테스트 (수집기·분석기·web_store 전부 monkeypatch).

asyncio 경로는 lambda_handler를 직접 호출해 커버한다(내부에서 asyncio.run 실행).
"""

from unittest.mock import MagicMock

import naver_review_collector
import web_worker_handler

JOB_ID = "job-123"
IDENTITY = "친구A"
NAVER_URL = "https://naver.me/GB3423bX"
PLACE_ID = "1234567890"

# 신규 분석 경로에서 사용할 장소 상세·리뷰 스텁
PLACE_DETAIL = {
    "place_id": PLACE_ID,
    "name": "돈멜 본점",
    "address": "성남시 분당구",
    "business_type": "restaurant",
    "avg_rating": 4.5,
    "total_reviews": 100,
    "menu_stats": [],
}
REVIEW_LIST = [{"text": "맛있어요"}, {"text": "괜찮아요"}]
SUMMARY_JSON = '{"summary": "좋음"}'


def _event() -> dict:
    return {"job_id": JOB_ID, "identity": IDENTITY, "naver_url": NAVER_URL}


def _patch_common(monkeypatch):
    """resolve_place를 고정하고 web_store 함수를 MagicMock으로 대체해 반환한다."""
    monkeypatch.setattr(
        naver_review_collector,
        "resolve_place",
        lambda url: {"place_id": PLACE_ID},
    )
    mocks = {
        "get_web_cached_summary": MagicMock(return_value=None),
        "get_prod_cached_summary": MagicMock(return_value=None),
        "save_web_summary": MagicMock(),
        "complete_job": MagicMock(),
        "fail_job": MagicMock(),
        "log_usage": MagicMock(),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(web_worker_handler.web_store, name, mock)
    return mocks


def _patch_pipeline(monkeypatch, summary_json=SUMMARY_JSON):
    """fetch_place_detail·fetch_reviews·analyze_reviews를 스텁으로 대체한다."""
    monkeypatch.setattr(
        naver_review_collector, "fetch_place_detail", lambda pid: PLACE_DETAIL
    )
    monkeypatch.setattr(
        naver_review_collector,
        "fetch_reviews",
        lambda pid, business_type, limit: REVIEW_LIST,
    )
    monkeypatch.setattr(
        web_worker_handler.review_analyst,
        "analyze_reviews",
        lambda detail, reviews: summary_json,
    )


class TestCacheHit:
    def test_web_캐시_히트면_파이프라인을_호출하지_않고_완료한다(self, monkeypatch):
        mocks = _patch_common(monkeypatch)
        mocks["get_web_cached_summary"].return_value = {
            "summary_json": SUMMARY_JSON,
            "place_name": "돈멜 본점",
            "address": "성남시 분당구",
            "review_count": 42,
        }
        # 파이프라인이 호출되면 실패하도록 지뢰를 심는다
        monkeypatch.setattr(
            naver_review_collector,
            "fetch_place_detail",
            MagicMock(side_effect=AssertionError("파이프라인이 호출되면 안 됨")),
        )

        web_worker_handler.lambda_handler(_event(), None)

        mocks["complete_job"].assert_called_once()
        assert mocks["complete_job"].call_args.kwargs["cache_hit"] is True
        mocks["log_usage"].assert_called_once_with(IDENTITY, cache_hit=True)
        # prod 캐시는 조회하지 않는다(web 히트로 조기 반환)
        mocks["get_prod_cached_summary"].assert_not_called()
        mocks["fail_job"].assert_not_called()

    def test_prod_캐시_히트면_web_캐시에_워밍하고_완료한다(self, monkeypatch):
        mocks = _patch_common(monkeypatch)
        mocks["get_prod_cached_summary"].return_value = {
            "summary_json": SUMMARY_JSON,
            "place_name": "돈멜 본점",
            "address": "성남시 분당구",
            "review_count": 7,
        }

        web_worker_handler.lambda_handler(_event(), None)

        # prod 히트를 web 캐시로 워밍(save_web_summary 호출)
        mocks["save_web_summary"].assert_called_once()
        warm_args = mocks["save_web_summary"].call_args.args
        assert warm_args[0] == PLACE_ID
        mocks["complete_job"].assert_called_once()
        assert mocks["complete_job"].call_args.kwargs["cache_hit"] is True
        mocks["log_usage"].assert_called_once_with(IDENTITY, cache_hit=True)


class TestFreshAnalysis:
    def test_캐시_미스면_수집_분석_후_저장하고_완료한다(self, monkeypatch):
        mocks = _patch_common(monkeypatch)
        _patch_pipeline(monkeypatch)

        web_worker_handler.lambda_handler(_event(), None)

        # 웹 캐시 저장 확인
        mocks["save_web_summary"].assert_called_once()
        save_args = mocks["save_web_summary"].call_args.args
        assert save_args[0] == PLACE_ID
        assert save_args[3] == SUMMARY_JSON
        assert save_args[4] == len(REVIEW_LIST)

        # 잡 완료 기록 확인
        mocks["complete_job"].assert_called_once()
        complete_kwargs = mocks["complete_job"].call_args.kwargs
        assert complete_kwargs["cache_hit"] is False
        assert complete_kwargs["summary_json"] == SUMMARY_JSON
        assert complete_kwargs["review_count"] == len(REVIEW_LIST)

        mocks["log_usage"].assert_called_once_with(IDENTITY, cache_hit=False)
        mocks["fail_job"].assert_not_called()

    def test_분석_결과가_None이면_잡을_실패_처리한다(self, monkeypatch):
        mocks = _patch_common(monkeypatch)
        _patch_pipeline(monkeypatch, summary_json=None)

        web_worker_handler.lambda_handler(_event(), None)

        mocks["fail_job"].assert_called_once()
        assert mocks["fail_job"].call_args.args[0] == JOB_ID
        # 미스 사용량은 기록하되 complete_job·save_web_summary는 호출하지 않는다
        mocks["log_usage"].assert_called_once_with(IDENTITY, cache_hit=False)
        mocks["complete_job"].assert_not_called()
        mocks["save_web_summary"].assert_not_called()


class TestFailurePaths:
    def test_ReviewCollectError면_수집_실패_메시지로_잡을_실패_처리한다(self, monkeypatch):
        mocks = _patch_common(monkeypatch)

        def _raise(url):
            raise naver_review_collector.ReviewCollectError("429 차단")

        monkeypatch.setattr(naver_review_collector, "resolve_place", _raise)

        web_worker_handler.lambda_handler(_event(), None)

        mocks["fail_job"].assert_called_once_with(JOB_ID, "리뷰를 가져오지 못했어요")
        mocks["complete_job"].assert_not_called()

    def test_예상치_못한_예외면_일반_실패_메시지로_잡을_실패_처리한다(self, monkeypatch):
        mocks = _patch_common(monkeypatch)

        def _raise(url):
            raise RuntimeError("알 수 없는 오류")

        monkeypatch.setattr(naver_review_collector, "resolve_place", _raise)

        web_worker_handler.lambda_handler(_event(), None)

        mocks["fail_job"].assert_called_once_with(JOB_ID, "분석 중 문제가 발생했어요")

    def test_job_id가_없으면_아무것도_하지_않고_종료한다(self, monkeypatch):
        mocks = _patch_common(monkeypatch)

        result = web_worker_handler.lambda_handler(
            {"identity": IDENTITY, "naver_url": NAVER_URL}, None
        )

        assert result["statusCode"] == 200
        mocks["complete_job"].assert_not_called()
        mocks["fail_job"].assert_not_called()
