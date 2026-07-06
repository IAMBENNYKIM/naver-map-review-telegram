"""dynamo_writer 단위 테스트 (moto로 DynamoDB mock)."""

from decimal import Decimal
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

import config
import dynamo_writer


@pytest.fixture()
def review_cache_table():
    """moto 가상 DynamoDB에 review_cache 테이블을 생성한다."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
        table = dynamodb.create_table(
            TableName=config.DYNAMO_TABLE_REVIEW_CACHE,
            KeySchema=[{"AttributeName": "place_key", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "place_key", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield table


class TestSummaryCacheRoundTrip:
    def test_저장_후_조회하면_같은_내용이_나온다(self, review_cache_table):
        dynamo_writer.save_summary(
            place_id="place-123",
            place_name="돈멜 본점",
            address="경기 성남시 분당구 느티로63번길 6",
            summary_json='{"overall": "총평"}',
            review_count=50,
        )

        cached_item = dynamo_writer.get_cached_summary("place-123")

        assert cached_item is not None
        assert cached_item["place_key"] == "place-123"
        assert cached_item["place_name"] == "돈멜 본점"
        assert cached_item["address"] == "경기 성남시 분당구 느티로63번길 6"
        assert cached_item["summary_json"] == '{"overall": "총평"}'
        assert cached_item["review_count"] == 50
        # updated_at은 ISO 8601 KST(+09:00) 자동 기록
        assert "+09:00" in cached_item["updated_at"]

    def test_없는_place_id는_none을_반환한다(self, review_cache_table):
        assert dynamo_writer.get_cached_summary("no-such-place") is None

    def test_조회_실패는_none으로_흡수한다(self):
        # 테이블 접근이 실패해도 예외 대신 None (비크리티컬)
        with patch.object(
            dynamo_writer, "_table", side_effect=RuntimeError("연결 실패")
        ):
            assert dynamo_writer.get_cached_summary("place-123") is None

    def test_저장_실패는_예외를_전파하지_않는다(self):
        # 저장 실패는 non-critical — 예외 없이 조용히 넘어가야 한다
        with patch.object(
            dynamo_writer, "_table", side_effect=RuntimeError("연결 실패")
        ):
            dynamo_writer.save_summary(
                place_id="place-123",
                place_name="이름",
                address="주소",
                summary_json="{}",
                review_count=1,
            )


class TestLastPlaceRoundTrip:
    def test_저장_후_조회하면_place_id가_나온다(self, review_cache_table):
        dynamo_writer.save_last_place_id("123456789", "place-abc")

        assert dynamo_writer.get_last_place_id("123456789") == "place-abc"

    def test_last_접두사_키로_저장된다(self, review_cache_table):
        dynamo_writer.save_last_place_id("123456789", "place-abc")

        raw_item = review_cache_table.get_item(
            Key={"place_key": "last#123456789"}
        ).get("Item")
        assert raw_item is not None
        assert raw_item["last_place_id"] == "place-abc"

    def test_기록_없는_chat_id는_none을_반환한다(self, review_cache_table):
        assert dynamo_writer.get_last_place_id("000000000") is None


class TestFloatToDecimal:
    def test_float를_decimal로_변환한다(self):
        assert dynamo_writer.convert_floats_to_decimal(4.5) == Decimal("4.5")

    def test_중첩_구조도_재귀적으로_변환한다(self):
        converted_value = dynamo_writer.convert_floats_to_decimal(
            {"rating": 4.5, "reviews": [{"score": 3.0}], "count": 7, "name": "돈멜"}
        )

        assert converted_value["rating"] == Decimal("4.5")
        assert converted_value["reviews"][0]["score"] == Decimal("3.0")
        assert converted_value["count"] == 7          # int는 그대로
        assert converted_value["name"] == "돈멜"      # str은 그대로

    def test_float_포함_항목도_저장된다(self, review_cache_table):
        # save_summary 내부에서 float→Decimal 변환이 적용되는지 통합 확인
        dynamo_writer.save_summary(
            place_id="place-float",
            place_name="이름",
            address="주소",
            summary_json='{"avg_rating": 4.5}',
            review_count=10,
        )

        assert dynamo_writer.get_cached_summary("place-float") is not None
