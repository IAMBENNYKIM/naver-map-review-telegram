"""리뷰 캐시 DynamoDB 읽기/쓰기 (비크리티컬 공유 모듈).

같은 장소를 짧은 시간에 반복 조회할 때 네이버 재수집·LLM 재호출을 아끼기 위한 캐시.
쓰기 실패는 **비크리티컬** — 로깅만 하고 예외를 raise하지 않는다(응답 파이프라인 유지).
TTL(config.REVIEW_CACHE_TTL)로 만료된 항목은 DynamoDB가 자동 삭제한다.
"""

import logging
import time

import config

logger = logging.getLogger(__name__)


def _table():
    """review_cache 테이블 리소스를 반환한다(lazy import — config 패턴)."""
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return dynamodb.Table(config.DYNAMO_TABLE_REVIEW_CACHE)


def get_cached_review(place_key: str) -> dict | None:
    """캐시된 리뷰/요약 항목을 조회한다. 실패·미스는 None(비크리티컬)."""
    try:
        response = _table().get_item(Key={"place_key": place_key})
    except Exception as error:  # noqa: BLE001 (캐시 조회 실패는 미스로 간주)
        logger.warning("리뷰 캐시 조회 실패(무시, place_key=%s): %s", place_key, error)
        return None

    item = response.get("Item")
    # TTL 만료가 아직 물리 삭제되지 않은 항목은 방어적으로 무시
    if item and item.get("ttl", 0) and int(item["ttl"]) < int(time.time()):
        return None
    return item


def put_cached_review(place_key: str, summary: str | None, reviews: list[dict]) -> None:
    """리뷰/요약을 캐시에 저장한다. 실패는 로깅만(비크리티컬)."""
    item = {
        "place_key": place_key,
        "summary": summary or "",
        "reviews": reviews,
        "ttl": int(time.time()) + config.REVIEW_CACHE_TTL,
    }
    try:
        _table().put_item(Item=item)
    except Exception as error:  # noqa: BLE001 (이력 저장 실패는 발송을 막지 않는다)
        logger.warning("리뷰 캐시 저장 실패(무시, place_key=%s): %s", place_key, error)
