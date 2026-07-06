"""웹 진입점 전용 DynamoDB 계층 (비크리티컬 저장·조회 모듈).

별도 SAM 스택 ``naver-review-web`` 이 사용하는 3개 테이블 + 기존 Telegram 캐시
테이블(read-through) 접근을 담당한다. ``dynamo_writer`` 와 동일한 규약을 따른다.

  - lazy boto3 import (config 패턴)
  - 쓰기 실패는 **비크리티컬** — 로깅만 하고 예외를 raise하지 않는다.
  - 조회 실패·미스는 ``None`` / ``[]`` 를 반환한다.
  - float → Decimal 변환은 ``dynamo_writer.convert_floats_to_decimal`` 을 재사용한다.

테이블 개요:
  - config.WEB_JOBS_TABLE   PK job_id(S),    TTL 속성 ttl(N)  — 비동기 분석 잡
  - config.WEB_CACHE_TABLE  PK place_key(S)                   — 웹 전용 요약 캐시
  - config.WEB_USAGE_TABLE  PK identity(S)                    — 사용량 통계
  - config.PROD_REVIEW_CACHE_TABLE PK place_key(S)            — 기존 캐시(읽기 전용)

PII 최소화(CLAUDE.md #11): 리뷰 본문·원문 chat_id를 INFO 로그에 남기지 않는다.
identity(표시이름)는 PII가 아니므로 로깅 가능하다.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

import config
from dynamo_writer import convert_floats_to_decimal

logger = logging.getLogger(__name__)

# 한국 표준시(KST) — created_at/updated_at/last_used_at ISO 8601 표기에 사용
_KST = timezone(timedelta(hours=9))

# 잡 상태 상수
_STATUS_PROCESSING = "processing"
_STATUS_DONE = "done"
_STATUS_ERROR = "error"


def _now_kst_iso() -> str:
    """현재 시각을 ISO 8601 KST 문자열로 반환한다."""
    return datetime.now(_KST).isoformat()


def _dynamodb_resource():
    """DynamoDB 리소스를 반환한다(lazy import — config 패턴)."""
    import boto3

    return boto3.resource("dynamodb", region_name=config.AWS_REGION)


def _jobs_table():
    """web_jobs 테이블 리소스를 반환한다."""
    return _dynamodb_resource().Table(config.WEB_JOBS_TABLE)


def _cache_table():
    """web_review_cache 테이블 리소스를 반환한다."""
    return _dynamodb_resource().Table(config.WEB_CACHE_TABLE)


def _prod_cache_table():
    """기존 Telegram 캐시 테이블 리소스를 반환한다(읽기 전용)."""
    return _dynamodb_resource().Table(config.PROD_REVIEW_CACHE_TABLE)


def _usage_table():
    """web_usage 테이블 리소스를 반환한다."""
    return _dynamodb_resource().Table(config.WEB_USAGE_TABLE)


# ---------------------------------------------------------------------------
# Jobs (비동기 분석 잡 상태)
# ---------------------------------------------------------------------------
def create_job(job_id: str, identity: str, naver_url: str) -> None:
    """새 분석 잡을 ``processing`` 상태로 생성한다. 실패는 로깅만(비크리티컬).

    ttl 속성에 만료 epoch(now + WEB_JOB_TTL_SECONDS)을 기록해 자동 정리한다.
    """
    item = convert_floats_to_decimal(
        {
            "job_id": job_id,
            "status": _STATUS_PROCESSING,
            "identity": identity,
            "naver_url": naver_url,
            "created_at": _now_kst_iso(),
            "ttl": int(time.time()) + config.WEB_JOB_TTL_SECONDS,
        }
    )
    try:
        _jobs_table().put_item(Item=item)
    except Exception as error:  # noqa: BLE001 (잡 생성 실패는 비크리티컬)
        logger.warning("잡 생성 실패(무시, job_id=%s): %s", job_id, error)


def get_job(job_id: str) -> dict | None:
    """job_id의 잡 항목을 조회한다. 실패·미스는 None(비크리티컬)."""
    try:
        response = _jobs_table().get_item(Key={"job_id": job_id})
    except Exception as error:  # noqa: BLE001 (조회 실패는 미스로 간주)
        logger.warning("잡 조회 실패(무시, job_id=%s): %s", job_id, error)
        return None
    return response.get("Item")


def complete_job(
    job_id: str,
    summary_json: str,
    place_name: str,
    address: str,
    review_count: int,
    cache_hit: bool,
) -> None:
    """잡을 ``done`` 상태로 갱신하고 분석 결과를 기록한다. 실패는 로깅만(비크리티컬)."""
    try:
        _jobs_table().update_item(
            Key={"job_id": job_id},
            UpdateExpression=(
                "SET #status = :status, summary_json = :summary_json, "
                "place_name = :place_name, address = :address, "
                "review_count = :review_count, cache_hit = :cache_hit, "
                "completed_at = :completed_at"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=convert_floats_to_decimal(
                {
                    ":status": _STATUS_DONE,
                    ":summary_json": summary_json,
                    ":place_name": place_name,
                    ":address": address,
                    ":review_count": review_count,
                    ":cache_hit": cache_hit,
                    ":completed_at": _now_kst_iso(),
                }
            ),
        )
    except Exception as error:  # noqa: BLE001 (잡 완료 기록 실패는 비크리티컬)
        logger.warning("잡 완료 기록 실패(무시, job_id=%s): %s", job_id, error)


def fail_job(job_id: str, error_message: str) -> None:
    """잡을 ``error`` 상태로 갱신하고 오류 메시지를 기록한다. 실패는 로깅만(비크리티컬)."""
    try:
        _jobs_table().update_item(
            Key={"job_id": job_id},
            UpdateExpression=(
                "SET #status = :status, error_message = :error_message, "
                "completed_at = :completed_at"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": _STATUS_ERROR,
                ":error_message": error_message,
                ":completed_at": _now_kst_iso(),
            },
        )
    except Exception as error:  # noqa: BLE001 (잡 실패 기록 실패는 비크리티컬)
        logger.warning("잡 실패 기록 실패(무시, job_id=%s): %s", job_id, error)


# ---------------------------------------------------------------------------
# 웹 캐시 (dynamo_writer.get_cached_summary/save_summary와 동일 스키마)
# ---------------------------------------------------------------------------
def get_web_cached_summary(place_id: str) -> dict | None:
    """웹 캐시에서 place_id의 요약 항목을 조회한다. 실패·미스는 None(비크리티컬)."""
    try:
        response = _cache_table().get_item(Key={"place_key": place_id})
    except Exception as error:  # noqa: BLE001 (조회 실패는 미스로 간주)
        logger.warning("웹 캐시 조회 실패(무시, place_id=%s): %s", place_id, error)
        return None
    return response.get("Item")


def save_web_summary(
    place_id: str,
    place_name: str,
    address: str,
    summary_json: str,
    review_count: int,
) -> None:
    """분석 요약을 웹 캐시에 저장한다. 실패는 로깅만(비크리티컬).

    updated_at은 ISO 8601 KST로 자동 기록한다.
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
        _cache_table().put_item(Item=item)
    except Exception as error:  # noqa: BLE001 (저장 실패는 응답을 막지 않는다)
        logger.warning("웹 캐시 저장 실패(무시, place_id=%s): %s", place_id, error)


# ---------------------------------------------------------------------------
# Read-through prod 캐시 (기존 Telegram 캐시 테이블 — 읽기 전용)
# ---------------------------------------------------------------------------
def get_prod_cached_summary(place_id: str) -> dict | None:
    """기존 Telegram 캐시에서 place_id의 요약 항목을 조회한다(읽기 전용).

    실패·미스는 None(비크리티컬). 이 함수는 절대 쓰기를 수행하지 않는다.
    """
    try:
        response = _prod_cache_table().get_item(Key={"place_key": place_id})
    except Exception as error:  # noqa: BLE001 (조회 실패는 미스로 간주)
        logger.warning("prod 캐시 조회 실패(무시, place_id=%s): %s", place_id, error)
        return None
    return response.get("Item")


# ---------------------------------------------------------------------------
# 사용량 통계 (identity별)
# ---------------------------------------------------------------------------
def log_usage(identity: str, cache_hit: bool) -> None:
    """identity의 사용량을 원자적으로 누적한다. 실패는 로깅만(비크리티컬).

    - total_count: 호출마다 +1
    - llm_call_count: 캐시 미스(cache_hit=False)일 때만 +1 (미스 = 실제 LLM 호출 = 비용)
    - last_used_at: 최근 사용 시각(KST ISO)
    """
    llm_increment = 0 if cache_hit else 1
    try:
        _usage_table().update_item(
            Key={"identity": identity},
            UpdateExpression=(
                "ADD total_count :one, llm_call_count :llm_increment "
                "SET last_used_at = :last_used_at"
            ),
            ExpressionAttributeValues={
                ":one": 1,
                ":llm_increment": llm_increment,
                ":last_used_at": _now_kst_iso(),
            },
        )
    except Exception as error:  # noqa: BLE001 (사용량 기록 실패는 비크리티컬)
        logger.warning("사용량 기록 실패(무시, identity=%s): %s", identity, error)


def get_all_usage() -> list[dict]:
    """web_usage 테이블 전체를 Scan한다(관리자 통계용). 실패 시 빈 리스트."""
    try:
        collected_items: list[dict] = []
        response = _usage_table().scan()
        collected_items.extend(response.get("Items", []))
        # 페이지네이션 처리 — 대량 항목도 모두 수집
        while "LastEvaluatedKey" in response:
            response = _usage_table().scan(
                ExclusiveStartKey=response["LastEvaluatedKey"]
            )
            collected_items.extend(response.get("Items", []))
        return collected_items
    except Exception as error:  # noqa: BLE001 (통계 조회 실패는 빈 리스트로 흡수)
        logger.warning("사용량 전체 조회 실패(무시): %s", error)
        return []
