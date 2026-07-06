"""리뷰 캐시·최근 조회 기록 DynamoDB 읽기/쓰기 (비크리티컬 공유 모듈).

테이블: ${prefix}review_cache, PK place_key(S), TTL 미사용(캐시 만료 없음 — PRD §3).

항목 종류:
  - 캐시 항목:      place_key = <place_id>       (요약 JSON·장소 정보·갱신 시각)
  - 최근 조회 항목: place_key = "last#<chat_id>"  (/update용 직전 place_id)

쓰기 실패는 **비크리티컬** — 로깅만 하고 예외를 raise하지 않는다(응답 파이프라인 유지).
DynamoDB는 float를 지원하지 않으므로 저장 전 Decimal로 변환한다.
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import config

logger = logging.getLogger(__name__)

# 한국 표준시(KST) — updated_at ISO 8601 표기에 사용
_KST = timezone(timedelta(hours=9))

# 최근 조회 항목 place_key 접두사
_LAST_PLACE_KEY_PREFIX = "last#"


def _table():
    """review_cache 테이블 리소스를 반환한다(lazy import — config 패턴)."""
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return dynamodb.Table(config.DYNAMO_TABLE_REVIEW_CACHE)


def _now_kst_iso() -> str:
    """현재 시각을 ISO 8601 KST 문자열로 반환한다."""
    return datetime.now(_KST).isoformat()


def convert_floats_to_decimal(value):
    """dict/list 내부의 float를 재귀적으로 Decimal로 변환한다(DynamoDB 저장용)."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: convert_floats_to_decimal(item) for key, item in value.items()}
    if isinstance(value, list):
        return [convert_floats_to_decimal(item) for item in value]
    return value


def get_cached_summary(place_id: str) -> dict | None:
    """place_id의 캐시된 요약 항목을 조회한다. 실패·미스는 None(비크리티컬)."""
    try:
        response = _table().get_item(Key={"place_key": place_id})
    except Exception as error:  # noqa: BLE001 (캐시 조회 실패는 미스로 간주)
        logger.warning("리뷰 캐시 조회 실패(무시, place_id=%s): %s", place_id, error)
        return None
    return response.get("Item")


def save_summary(
    place_id: str,
    place_name: str,
    address: str,
    summary_json: str,
    review_count: int,
) -> None:
    """분석 요약을 캐시에 저장한다. 실패는 로깅만(비크리티컬).

    updated_at은 ISO 8601 KST로 자동 기록한다 (PRD §3 캐시 항목 스키마).
    """
    item = convert_floats_to_decimal(
        {
            "place_key": place_id,
            "place_name": place_name,
            "address": address,
            "summary_json": summary_json,
            "review_count": review_count,
            "updated_at": _now_kst_iso(),
        }
    )
    try:
        _table().put_item(Item=item)
    except Exception as error:  # noqa: BLE001 (저장 실패는 발송을 막지 않는다)
        logger.warning("리뷰 캐시 저장 실패(무시, place_id=%s): %s", place_id, error)


def get_last_place_id(chat_id: str) -> str | None:
    """chat_id가 직전에 조회한 place_id를 반환한다. 실패·미스는 None."""
    place_key = f"{_LAST_PLACE_KEY_PREFIX}{chat_id}"
    try:
        response = _table().get_item(Key={"place_key": place_key})
    except Exception as error:  # noqa: BLE001 (조회 실패는 미스로 간주)
        logger.warning("최근 조회 기록 조회 실패(무시, key=%s): %s", place_key, error)
        return None
    item = response.get("Item")
    if not item:
        return None
    return item.get("last_place_id")


def save_last_place_id(chat_id: str, place_id: str) -> None:
    """chat_id의 직전 조회 place_id를 저장한다. 실패는 로깅만(비크리티컬)."""
    item = {
        "place_key": f"{_LAST_PLACE_KEY_PREFIX}{chat_id}",
        "last_place_id": place_id,
        "updated_at": _now_kst_iso(),
    }
    try:
        _table().put_item(Item=item)
    except Exception as error:  # noqa: BLE001 (저장 실패는 발송을 막지 않는다)
        logger.warning(
            "최근 조회 기록 저장 실패(무시, place_id=%s): %s", place_id, error
        )
