"""web_store 단위 테스트 (moto로 DynamoDB mock)."""

from decimal import Decimal
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

import config
import web_store


def _create_table(dynamodb, table_name: str, partition_key: str):
    """단일 파티션 키 테이블을 생성하는 헬퍼."""
    return dynamodb.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": partition_key, "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": partition_key, "AttributeType": "S"}
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture()
def web_tables():
    """moto 가상 DynamoDB에 web 3개 테이블 + prod 캐시 테이블을 생성한다."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
        jobs = _create_table(dynamodb, config.WEB_JOBS_TABLE, "job_id")
        cache = _create_table(dynamodb, config.WEB_CACHE_TABLE, "place_key")
        usage = _create_table(dynamodb, config.WEB_USAGE_TABLE, "identity")
        prod_cache = _create_table(
            dynamodb, config.PROD_REVIEW_CACHE_TABLE, "place_key"
        )
        yield {
            "jobs": jobs,
            "cache": cache,
            "usage": usage,
            "prod_cache": prod_cache,
        }


# ---------------------------------------------------------------------------
# Jobs 생명주기
# ---------------------------------------------------------------------------
class TestJobLifecycle:
    def test_생성_후_조회하면_processing_상태다(self, web_tables):
        web_store.create_job("job-1", "친구A", "https://naver.me/abc")

        job = web_store.get_job("job-1")

        assert job is not None
        assert job["job_id"] == "job-1"
        assert job["status"] == "processing"
        assert job["identity"] == "친구A"
        assert job["naver_url"] == "https://naver.me/abc"
        assert "+09:00" in job["created_at"]
        assert int(job["ttl"]) > 0

    def test_complete_하면_done_상태와_결과가_기록된다(self, web_tables):
        web_store.create_job("job-2", "친구A", "https://naver.me/abc")

        web_store.complete_job(
            job_id="job-2",
            summary_json='{"overall": "총평"}',
            place_name="돈멜 본점",
            address="경기 성남시",
            review_count=50,
            cache_hit=True,
            updated_at="2026-07-07T12:00:00+09:00",
        )

        job = web_store.get_job("job-2")
        assert job["status"] == "done"
        assert job["summary_json"] == '{"overall": "총평"}'
        assert job["place_name"] == "돈멜 본점"
        assert job["address"] == "경기 성남시"
        assert job["review_count"] == 50
        assert job["cache_hit"] is True
        # updated_at(요약 갱신 시점)이 그대로 기록돼야 한다.
        assert job["updated_at"] == "2026-07-07T12:00:00+09:00"
        assert "+09:00" in job["completed_at"]
        # 생성 시 필드는 보존돼야 한다.
        assert job["identity"] == "친구A"

    def test_fail_하면_error_상태와_메시지가_기록된다(self, web_tables):
        web_store.create_job("job-3", "친구A", "https://naver.me/abc")

        web_store.fail_job("job-3", "수집 실패")

        job = web_store.get_job("job-3")
        assert job["status"] == "error"
        assert job["error_message"] == "수집 실패"
        assert "+09:00" in job["completed_at"]

    def test_없는_job은_none을_반환한다(self, web_tables):
        assert web_store.get_job("no-such-job") is None

    def test_생성_실패는_예외를_전파하지_않는다(self):
        with patch.object(
            web_store, "_jobs_table", side_effect=RuntimeError("연결 실패")
        ):
            web_store.create_job("job-x", "친구A", "https://naver.me/abc")

    def test_조회_실패는_none으로_흡수한다(self):
        with patch.object(
            web_store, "_jobs_table", side_effect=RuntimeError("연결 실패")
        ):
            assert web_store.get_job("job-x") is None


# ---------------------------------------------------------------------------
# 웹 캐시
# ---------------------------------------------------------------------------
class TestWebCache:
    def test_저장_후_조회하면_같은_내용이_나온다(self, web_tables):
        web_store.save_web_summary(
            place_id="place-123",
            place_name="돈멜 본점",
            address="경기 성남시",
            summary_json='{"overall": "총평"}',
            review_count=50,
        )

        cached = web_store.get_web_cached_summary("place-123")
        assert cached is not None
        assert cached["place_key"] == "place-123"
        assert cached["place_name"] == "돈멜 본점"
        assert cached["address"] == "경기 성남시"
        assert cached["summary_json"] == '{"overall": "총평"}'
        assert cached["review_count"] == 50
        assert "+09:00" in cached["updated_at"]

    def test_저장하면_갱신시점_문자열을_반환한다(self, web_tables):
        returned_updated_at = web_store.save_web_summary(
            place_id="place-return",
            place_name="돈멜 본점",
            address="경기 성남시",
            summary_json='{"overall": "총평"}',
            review_count=50,
        )

        assert "+09:00" in returned_updated_at
        # 반환값과 실제 저장된 updated_at이 일치해야 한다.
        cached = web_store.get_web_cached_summary("place-return")
        assert cached["updated_at"] == returned_updated_at

    def test_저장_실패해도_갱신시점_문자열은_반환한다(self):
        with patch.object(
            web_store, "_cache_table", side_effect=RuntimeError("연결 실패")
        ):
            returned_updated_at = web_store.save_web_summary(
                place_id="place-x",
                place_name="이름",
                address="주소",
                summary_json="{}",
                review_count=1,
            )

        assert "+09:00" in returned_updated_at

    def test_없는_place_id는_none을_반환한다(self, web_tables):
        assert web_store.get_web_cached_summary("no-such-place") is None

    def test_저장_실패는_예외를_전파하지_않는다(self):
        with patch.object(
            web_store, "_cache_table", side_effect=RuntimeError("연결 실패")
        ):
            web_store.save_web_summary(
                place_id="place-123",
                place_name="이름",
                address="주소",
                summary_json="{}",
                review_count=1,
            )

    def test_float_포함_요약도_저장된다(self, web_tables):
        web_store.save_web_summary(
            place_id="place-float",
            place_name="이름",
            address="주소",
            summary_json='{"avg_rating": 4.5}',
            review_count=10,
        )

        assert web_store.get_web_cached_summary("place-float") is not None


# ---------------------------------------------------------------------------
# Read-through prod 캐시 (읽기 전용)
# ---------------------------------------------------------------------------
class TestProdCacheReadThrough:
    def test_prod에_있으면_조회된다(self, web_tables):
        # prod 캐시 테이블에 직접 항목을 넣어 read-through 조회를 확인한다.
        web_tables["prod_cache"].put_item(
            Item={
                "place_key": "place-prod",
                "place_name": "기존 장소",
                "summary_json": '{"overall": "기존 총평"}',
                "review_count": 30,
            }
        )

        cached = web_store.get_prod_cached_summary("place-prod")
        assert cached is not None
        assert cached["place_name"] == "기존 장소"

    def test_prod에_없으면_none을_반환한다(self, web_tables):
        assert web_store.get_prod_cached_summary("no-such-place") is None

    def test_조회_실패는_none으로_흡수한다(self):
        with patch.object(
            web_store, "_prod_cache_table", side_effect=RuntimeError("연결 실패")
        ):
            assert web_store.get_prod_cached_summary("place-prod") is None


# ---------------------------------------------------------------------------
# 사용량 통계
# ---------------------------------------------------------------------------
class TestUsage:
    def test_캐시_미스는_llm_count가_증가한다(self, web_tables):
        web_store.log_usage("친구A", cache_hit=False)

        usage = web_tables["usage"].get_item(
            Key={"identity": "친구A"}
        )["Item"]
        assert usage["total_count"] == 1
        assert usage["llm_call_count"] == 1
        assert "+09:00" in usage["last_used_at"]

    def test_캐시_히트는_llm_count가_불변이다(self, web_tables):
        web_store.log_usage("친구A", cache_hit=True)

        usage = web_tables["usage"].get_item(
            Key={"identity": "친구A"}
        )["Item"]
        assert usage["total_count"] == 1
        assert usage["llm_call_count"] == 0

    def test_누적_호출이_원자적으로_합산된다(self, web_tables):
        web_store.log_usage("친구A", cache_hit=False)  # total 1, llm 1
        web_store.log_usage("친구A", cache_hit=True)   # total 2, llm 1
        web_store.log_usage("친구A", cache_hit=False)  # total 3, llm 2

        usage = web_tables["usage"].get_item(
            Key={"identity": "친구A"}
        )["Item"]
        assert usage["total_count"] == 3
        assert usage["llm_call_count"] == 2

    def test_같은_날짜_호출은_일별_카운터에_누적된다(self, web_tables):
        from datetime import datetime, timezone, timedelta

        today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
        web_store.log_usage("친구A", cache_hit=True)   # req +1, llm +0
        web_store.log_usage("친구A", cache_hit=False)  # req +1, llm +1

        usage = web_tables["usage"].get_item(
            Key={"identity": "친구A"}
        )["Item"]
        # 누적 합계
        assert usage["total_count"] == 2
        assert usage["llm_call_count"] == 1
        # 일별 최상위 카운터
        assert usage[f"req#{today}"] == 2
        assert usage[f"llm#{today}"] == 1

    def test_검색_사용량은_search_count와_일별_카운터를_누적한다(self, web_tables):
        from datetime import datetime, timezone, timedelta

        today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
        web_store.log_search_usage("친구A")
        web_store.log_search_usage("친구A")

        usage = web_tables["usage"].get_item(Key={"identity": "친구A"})["Item"]
        assert usage["search_count"] == 2
        assert usage[f"search#{today}"] == 2
        assert "+09:00" in usage["last_used_at"]

    def test_검색_사용량은_분석_카운터와_독립적이다(self, web_tables):
        # log_usage(분석)와 log_search_usage(검색)가 서로 다른 속성을 쓴다.
        web_store.log_usage("친구A", cache_hit=False)  # total_count/llm_call_count
        web_store.log_search_usage("친구A")            # search_count

        usage = web_tables["usage"].get_item(Key={"identity": "친구A"})["Item"]
        assert usage["total_count"] == 1
        assert usage["llm_call_count"] == 1
        assert usage["search_count"] == 1

    def test_검색_기록_실패는_예외를_전파하지_않는다(self):
        with patch.object(
            web_store, "_usage_table", side_effect=RuntimeError("연결 실패")
        ):
            web_store.log_search_usage("친구A")

    def test_기록_실패는_예외를_전파하지_않는다(self):
        with patch.object(
            web_store, "_usage_table", side_effect=RuntimeError("연결 실패")
        ):
            web_store.log_usage("친구A", cache_hit=False)

    def test_전체_사용량을_scan으로_조회한다(self, web_tables):
        web_store.log_usage("친구A", cache_hit=False)
        web_store.log_usage("친구B", cache_hit=True)

        all_usage = web_store.get_all_usage()
        identities = {row["identity"] for row in all_usage}
        assert identities == {"친구A", "친구B"}

    def test_scan_실패는_빈_리스트를_반환한다(self):
        with patch.object(
            web_store, "_usage_table", side_effect=RuntimeError("연결 실패")
        ):
            assert web_store.get_all_usage() == []


# ---------------------------------------------------------------------------
# 일별 시계열 정돈 (summarize_usage_item)
# ---------------------------------------------------------------------------
class TestSummarizeUsageItem:
    def test_일별_카운터를_날짜별로_묶는다(self):
        item = {
            "identity": "벤",
            "total_count": Decimal(3),
            "llm_call_count": Decimal(1),
            "search_count": Decimal(4),
            "last_used_at": "2026-07-07T12:00:00+09:00",
            "req#2026-07-05": Decimal(1),
            "llm#2026-07-05": Decimal(1),
            "req#2026-07-07": Decimal(2),
            "search#2026-07-07": Decimal(4),
        }

        summary = web_store.summarize_usage_item(item)

        assert summary["identity"] == "벤"
        assert summary["total_count"] == Decimal(3)
        assert summary["llm_call_count"] == Decimal(1)
        assert summary["search_count"] == Decimal(4)
        assert summary["last_used_at"] == "2026-07-07T12:00:00+09:00"
        # 오름차순 정렬 + 없는 지표(2026-07-07의 llm, 2026-07-05의 search)는 0으로 채움
        assert summary["daily"] == [
            {"date": "2026-07-05", "total": Decimal(1), "llm": Decimal(1), "search": 0},
            {"date": "2026-07-07", "total": Decimal(2), "llm": 0, "search": Decimal(4)},
        ]

    def test_일별_키가_없으면_daily는_빈_리스트다(self):
        item = {
            "identity": "벤",
            "total_count": Decimal(0),
            "llm_call_count": Decimal(0),
        }

        summary = web_store.summarize_usage_item(item)

        assert summary["daily"] == []
        # 없는 필드는 기본값으로 채운다
        assert summary["last_used_at"] == ""

    def test_유사하지만_다른_키는_무시한다(self):
        # "req#"·"llm#" 접두라도 날짜 형식이 아니면 매칭하지 않는다
        item = {
            "identity": "벤",
            "req#not-a-date": Decimal(9),
            "requests": Decimal(9),
        }

        summary = web_store.summarize_usage_item(item)

        assert summary["daily"] == []


# ---------------------------------------------------------------------------
# config.WEB_INVITE_CODES 파싱
# ---------------------------------------------------------------------------
class TestParseInviteCodes:
    def test_정상_json_객체를_파싱한다(self):
        parsed = config._parse_invite_codes('{"c1": "이름1", "c2": "이름2"}')
        assert parsed == {"c1": "이름1", "c2": "이름2"}

    def test_이미_dict면_그대로_정규화한다(self):
        parsed = config._parse_invite_codes({"c1": "이름1"})
        assert parsed == {"c1": "이름1"}

    def test_빈_값은_빈_dict다(self):
        assert config._parse_invite_codes("") == {}
        assert config._parse_invite_codes("{}") == {}
        assert config._parse_invite_codes(None) == {}

    def test_깨진_json은_빈_dict다(self):
        assert config._parse_invite_codes('{"c1": ') == {}

    def test_객체가_아닌_json은_빈_dict다(self):
        # 배열·문자열 등 dict가 아니면 빈 dict로 안전 처리한다.
        assert config._parse_invite_codes('["c1", "c2"]') == {}
        assert config._parse_invite_codes('"just-a-string"') == {}

    def test_conftest_주입값이_로드돼있다(self):
        # conftest가 주입한 초대코드가 config에 반영돼 있어야 한다.
        assert config.WEB_INVITE_CODES == {
            "invite-code-1": "친구A",
            "invite-code-2": "친구B",
        }
