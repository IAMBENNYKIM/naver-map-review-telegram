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
UPDATED_AT = "2026-07-07T12:00:00+09:00"


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
        "save_web_summary": MagicMock(return_value=UPDATED_AT),
        "complete_job": MagicMock(),
        "fail_job": MagicMock(),
        "log_usage": MagicMock(),
        "update_job_stage": MagicMock(),
        "record_history": MagicMock(),
        "trim_history": MagicMock(),
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
            "updated_at": UPDATED_AT,
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
        # 캐시의 updated_at이 잡 완료 기록으로 전파된다.
        assert mocks["complete_job"].call_args.kwargs["updated_at"] == UPDATED_AT
        mocks["log_usage"].assert_called_once_with(IDENTITY, cache_hit=True)
        # 캐시의 place_name·address로 조회 이력을 기록하고 정리한다.
        mocks["record_history"].assert_called_once_with(
            IDENTITY, PLACE_ID, "돈멜 본점", "성남시 분당구"
        )
        mocks["trim_history"].assert_called_once_with(IDENTITY)
        # prod 캐시는 조회하지 않는다(web 히트로 조기 반환)
        mocks["get_prod_cached_summary"].assert_not_called()
        mocks["fail_job"].assert_not_called()
        # 캐시 히트는 즉시 done이므로 단계 전이가 없다.
        mocks["update_job_stage"].assert_not_called()

    def test_prod_캐시_히트면_web_캐시에_워밍하고_완료한다(self, monkeypatch):
        mocks = _patch_common(monkeypatch)
        mocks["get_prod_cached_summary"].return_value = {
            "summary_json": SUMMARY_JSON,
            "place_name": "돈멜 본점",
            "address": "성남시 분당구",
            "review_count": 7,
            "updated_at": UPDATED_AT,
        }

        web_worker_handler.lambda_handler(_event(), None)

        # prod 히트를 web 캐시로 워밍(save_web_summary 호출)
        mocks["save_web_summary"].assert_called_once()
        warm_args = mocks["save_web_summary"].call_args.args
        assert warm_args[0] == PLACE_ID
        mocks["complete_job"].assert_called_once()
        assert mocks["complete_job"].call_args.kwargs["cache_hit"] is True
        # prod 캐시 항목의 updated_at이 잡 완료 기록으로 전파된다.
        assert mocks["complete_job"].call_args.kwargs["updated_at"] == UPDATED_AT
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
        # save_web_summary가 반환한 updated_at이 잡 완료 기록으로 전파된다.
        assert complete_kwargs["updated_at"] == UPDATED_AT

        mocks["log_usage"].assert_called_once_with(IDENTITY, cache_hit=False)
        # 신규 분석 결과의 place_name·address로 조회 이력을 기록하고 정리한다.
        mocks["record_history"].assert_called_once_with(
            IDENTITY, PLACE_ID, PLACE_DETAIL["name"], PLACE_DETAIL["address"]
        )
        mocks["trim_history"].assert_called_once_with(IDENTITY)
        mocks["fail_job"].assert_not_called()

    def test_캐시_미스면_collecting_summarizing_단계를_순서대로_전이한다(self, monkeypatch):
        from unittest.mock import call

        mocks = _patch_common(monkeypatch)
        _patch_pipeline(monkeypatch)

        web_worker_handler.lambda_handler(_event(), None)

        # collecting(수집 직전) → summarizing(분석 직전) 순으로 단계를 갱신한다.
        assert mocks["update_job_stage"].call_args_list == [
            call(JOB_ID, "collecting"),
            call(JOB_ID, "summarizing"),
        ]

    def test_force_refresh면_캐시를_건너뛰고_신규_분석한다(self, monkeypatch):
        mocks = _patch_common(monkeypatch)
        _patch_pipeline(monkeypatch)
        # 캐시가 히트해도(web 캐시 존재) force_refresh면 무시하고 신규 분석해야 한다.
        mocks["get_web_cached_summary"].return_value = {
            "summary_json": "STALE",
            "place_name": "옛 이름",
            "address": "옛 주소",
            "review_count": 1,
            "updated_at": "2020-01-01T00:00:00+09:00",
        }

        event = dict(_event(), force_refresh=True)
        web_worker_handler.lambda_handler(event, None)

        # 캐시 조회를 아예 건너뛴다(web·prod 모두 조회하지 않음).
        mocks["get_web_cached_summary"].assert_not_called()
        mocks["get_prod_cached_summary"].assert_not_called()

        # 신규 수집·분석 경로를 타고, cache_hit=False로 기록한다.
        mocks["save_web_summary"].assert_called_once()
        mocks["complete_job"].assert_called_once()
        complete_kwargs = mocks["complete_job"].call_args.kwargs
        assert complete_kwargs["cache_hit"] is False
        assert complete_kwargs["summary_json"] == SUMMARY_JSON
        mocks["log_usage"].assert_called_once_with(IDENTITY, cache_hit=False)

    def test_place_id_수신시_resolve_place를_생략한다(self, monkeypatch):
        mocks = _patch_common(monkeypatch)
        _patch_pipeline(monkeypatch)
        # resolve_place가 호출되면 실패하도록 MagicMock으로 교체한다.
        resolve_place_mock = MagicMock(
            side_effect=AssertionError("place_id 경로에서 호출되면 안 됨")
        )
        monkeypatch.setattr(
            naver_review_collector, "resolve_place", resolve_place_mock
        )

        event = dict(_event(), place_id="9998887776", naver_url="")
        web_worker_handler.lambda_handler(event, None)

        resolve_place_mock.assert_not_called()
        # 전달된 place_id로 수집·저장이 진행된다.
        mocks["save_web_summary"].assert_called_once()
        assert mocks["save_web_summary"].call_args.args[0] == "9998887776"
        mocks["complete_job"].assert_called_once()

    def test_naver_url_경로는_resolve_place를_호출한다(self, monkeypatch):
        # place_id 없는 기존 경로 회귀 — resolve_place가 호출돼 place_id를 얻는다.
        mocks = _patch_common(monkeypatch)
        _patch_pipeline(monkeypatch)
        resolve_place_mock = MagicMock(return_value={"place_id": PLACE_ID})
        monkeypatch.setattr(
            naver_review_collector, "resolve_place", resolve_place_mock
        )

        web_worker_handler.lambda_handler(_event(), None)

        resolve_place_mock.assert_called_once_with(NAVER_URL)
        assert mocks["save_web_summary"].call_args.args[0] == PLACE_ID

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
        # 실패 잡은 조회 이력을 기록하지 않는다.
        mocks["record_history"].assert_not_called()
        mocks["trim_history"].assert_not_called()


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


class TestWarmup:
    def test_warmup_이벤트는_파이프라인_없이_즉시_반환한다(self, monkeypatch):
        mocks = _patch_common(monkeypatch)
        # 워밍 이벤트에서는 resolve_place조차 호출되면 안 된다.
        monkeypatch.setattr(
            naver_review_collector,
            "resolve_place",
            MagicMock(side_effect=AssertionError("워밍 경로에서 호출되면 안 됨")),
        )

        result = web_worker_handler.lambda_handler({"warmup": True}, None)

        assert result["statusCode"] == 200
        mocks["complete_job"].assert_not_called()
        mocks["fail_job"].assert_not_called()
        mocks["log_usage"].assert_not_called()
