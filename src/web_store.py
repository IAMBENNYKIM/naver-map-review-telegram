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
import re
import time
from datetime import datetime, timedelta, timezone

import config
from dynamo_writer import convert_floats_to_decimal

logger = logging.getLogger(__name__)

# 일별 카운터 최상위 속성명 패턴 — "req#YYYY-MM-DD"(총요청)·"llm#YYYY-MM-DD"(LLM 호출)·
# "search#YYYY-MM-DD"(검색 요청)
_DAILY_KEY_PATTERN = re.compile(r"^(req|llm|search)#(\d{4}-\d{2}-\d{2})$")

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
def create_job(
    job_id: str, identity: str, naver_url: str, place_id: str = ""
) -> None:
    """새 분석 잡을 ``processing`` 상태로 생성한다. 실패는 로깅만(비크리티컬).

    naver_url·place_id는 둘 중 쓰지 않는 쪽이 빈 문자열이다(place_id 경로는 검색
    결과에서 직접 분석). place_id는 하위호환을 위해 기본값 ""을 둔다.
    ttl 속성에 만료 epoch(now + WEB_JOB_TTL_SECONDS)을 기록해 자동 정리한다.
    """
    item = convert_floats_to_decimal(
        {
            "job_id": job_id,
            "status": _STATUS_PROCESSING,
            "identity": identity,
            "naver_url": naver_url,
            "place_id": place_id,
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
    updated_at: str,
) -> None:
    """잡을 ``done`` 상태로 갱신하고 분석 결과를 기록한다. 실패는 로깅만(비크리티컬).

    updated_at은 요약 캐시의 갱신 시점(KST ISO)으로, /result 응답까지 전파된다.
    """
    try:
        _jobs_table().update_item(
            Key={"job_id": job_id},
            UpdateExpression=(
                "SET #status = :status, summary_json = :summary_json, "
                "place_name = :place_name, address = :address, "
                "review_count = :review_count, cache_hit = :cache_hit, "
                "updated_at = :updated_at, completed_at = :completed_at"
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
                    ":updated_at": updated_at,
                    ":completed_at": _now_kst_iso(),
                }
            ),
        )
    except Exception as error:  # noqa: BLE001 (잡 완료 기록 실패는 비크리티컬)
        logger.warning("잡 완료 기록 실패(무시, job_id=%s): %s", job_id, error)


def create_completed_job(
    job_id: str,
    identity: str,
    place_id: str,
    summary_json: str,
    place_name: str,
    address: str,
    review_count: int,
    updated_at: str,
    naver_url: str = "",
) -> None:
    """캐시 히트를 곧바로 ``done`` 상태 잡으로 생성한다(워커 우회용). 실패는 로깅만(비크리티컬).

    create_job(``processing``)+complete_job(``done``)을 거친 잡과 **동일한 아이템 형태**가
    되도록 두 함수가 쓰는 필드를 모두 채운다(cache_hit=True 포함). created_at·completed_at은
    즉시 완료이므로 같은 시각으로 기록한다. /result 응답은 이 잡과 워커 완료 잡을 구분하지 못한다.
    """
    now = _now_kst_iso()
    item = convert_floats_to_decimal(
        {
            "job_id": job_id,
            "status": _STATUS_DONE,
            "identity": identity,
            "naver_url": naver_url,
            "place_id": place_id,
            "created_at": now,
            "ttl": int(time.time()) + config.WEB_JOB_TTL_SECONDS,
            "summary_json": summary_json,
            "place_name": place_name,
            "address": address,
            "review_count": review_count,
            "cache_hit": True,
            "updated_at": updated_at,
            "completed_at": now,
        }
    )
    try:
        _jobs_table().put_item(Item=item)
    except Exception as error:  # noqa: BLE001 (완료 잡 생성 실패는 비크리티컬)
        logger.warning("완료 잡 생성 실패(무시, job_id=%s): %s", job_id, error)


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
) -> str:
    """분석 요약을 웹 캐시에 저장하고 갱신 시점(updated_at)을 반환한다.

    updated_at은 ISO 8601 KST로 자동 기록한다. 저장 실패는 로깅만(비크리티컬)
    하되, 생성한 updated_at 문자열은 항상 반환한다(호출부가 잡 완료 기록에 쓴다).
    """
    updated_at = _now_kst_iso()
    item = convert_floats_to_decimal(
        {
            "place_key": place_id,
            "place_name": place_name,
            "address": address,
            "summary_json": summary_json,
            "review_count": review_count,
            "updated_at": updated_at,
        }
    )
    try:
        _cache_table().put_item(Item=item)
    except Exception as error:  # noqa: BLE001 (저장 실패는 응답을 막지 않는다)
        logger.warning("웹 캐시 저장 실패(무시, place_id=%s): %s", place_id, error)
    return updated_at


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


def lookup_cached_summary(place_id: str) -> dict | None:
    """web 캐시 → prod 캐시(읽기전용 read-through) 순으로 요약을 조회한다.

    web 히트: 그대로 사용. prod 히트: web 캐시에도 저장(워밍)한다. 둘 다 미스면 None.
    반환 dict는 summary_json/place_name/address/review_count/updated_at 키로 정규화된다.
    (WebApiFunction 캐시 히트 직결·WebWorkerFunction 공용 진입점.)
    """
    web_item = get_web_cached_summary(place_id)
    if web_item:
        return _normalize_cache_item(web_item)

    prod_item = get_prod_cached_summary(place_id)
    if prod_item:
        normalized = _normalize_cache_item(prod_item)
        # prod 히트를 web 캐시로 워밍한다(다음 조회부터 web 캐시가 응답).
        save_web_summary(
            place_id,
            normalized["place_name"],
            normalized["address"],
            normalized["summary_json"],
            normalized["review_count"],
        )
        return normalized

    return None


def _normalize_cache_item(item: dict) -> dict:
    """캐시 항목에서 잡 완료에 필요한 필드를 추출한다(Decimal review_count는 int로)."""
    return {
        "summary_json": item.get("summary_json", ""),
        "place_name": item.get("place_name", ""),
        "address": item.get("address", ""),
        "review_count": int(item.get("review_count", 0)),
        "updated_at": item.get("updated_at", ""),
    }


# ---------------------------------------------------------------------------
# 사용량 통계 (identity별)
# ---------------------------------------------------------------------------
def log_usage(identity: str, cache_hit: bool) -> None:
    """identity의 사용량을 원자적으로 누적한다. 실패는 로깅만(비크리티컬).

    - total_count: 호출마다 +1 (누적 합계)
    - llm_call_count: 캐시 미스(cache_hit=False)일 때만 +1 (미스 = 실제 LLM 호출 = 비용)
    - req#YYYY-MM-DD: 오늘(KST) 총요청 카운터 +1 (일별 시계열)
    - llm#YYYY-MM-DD: 오늘(KST) LLM 호출 카운터 +1 (캐시 미스일 때만)
    - last_used_at: 최근 사용 시각(KST ISO)

    일별 카운터는 DynamoDB ``ADD``로 누적한다. ``ADD``는 없는 최상위 숫자 속성을
    0으로 자동 초기화하므로 별도 초기화 왕복 없이 1회 호출로 끝난다. 속성명에
    ``#``·``-``가 들어가므로 ``ExpressionAttributeNames`` 별칭을 반드시 쓴다.
    """
    llm_increment = 0 if cache_hit else 1
    today = datetime.now(_KST).date().isoformat()
    try:
        _usage_table().update_item(
            Key={"identity": identity},
            UpdateExpression=(
                "ADD total_count :one, llm_call_count :llm_increment, "
                "#req_day :one, #llm_day :llm_increment "
                "SET last_used_at = :last_used_at"
            ),
            ExpressionAttributeNames={
                "#req_day": f"req#{today}",
                "#llm_day": f"llm#{today}",
            },
            ExpressionAttributeValues={
                ":one": 1,
                ":llm_increment": llm_increment,
                ":last_used_at": _now_kst_iso(),
            },
        )
    except Exception as error:  # noqa: BLE001 (사용량 기록 실패는 비크리티컬)
        logger.warning("사용량 기록 실패(무시, identity=%s): %s", identity, error)


def get_daily_llm_count(identity: str) -> int:
    """identity의 오늘(KST) LLM 호출 수(``llm#YYYY-MM-DD``)를 조회한다.

    일일 신규 분석(LLM 호출) 상한 강제용. ``GetItem`` 후 오늘 날짜 카운터 속성값을
    int로 반환한다. 항목·속성이 없으면 0을 반환한다(첫 사용자·오늘 첫 요청).

    조회 실패(네트워크·권한 등)도 0을 반환한다 — 상한 검사가 사용자 요청을 막지
    않도록(비크리티컬). 다만 "실패 시 0"은 상한을 우회시키므로, 조회 실패는
    ``logger.warning``으로 남겨 무음 우회를 방지한다. 날짜 키 생성은 ``log_usage``와
    동일하게 KST 기준을 사용한다.
    """
    today = datetime.now(_KST).date().isoformat()
    try:
        response = _usage_table().get_item(Key={"identity": identity})
    except Exception as error:  # noqa: BLE001 (조회 실패는 0으로 간주 — 상한 우회 방지 위해 경고)
        logger.warning(
            "일일 LLM 카운트 조회 실패(0으로 간주, identity=%s): %s", identity, error
        )
        return 0
    item = response.get("Item") or {}
    return int(item.get(f"llm#{today}", 0))


def log_search_usage(identity: str) -> None:
    """identity의 검색(정규화+장소검색) 사용량을 원자적으로 누적한다. 실패는 로깅만(비크리티컬).

    - search_count: 검색 호출마다 +1 (누적 합계)
    - search#YYYY-MM-DD: 오늘(KST) 검색 카운터 +1 (일별 시계열)
    - last_used_at: 최근 사용 시각(KST ISO)

    log_usage와 동일하게 DynamoDB ``ADD``로 누적한다(없는 최상위 숫자 속성을 0으로
    자동 초기화). 속성명에 ``#``이 들어가므로 ``ExpressionAttributeNames`` 별칭을 쓴다.
    """
    today = datetime.now(_KST).date().isoformat()
    try:
        _usage_table().update_item(
            Key={"identity": identity},
            UpdateExpression=(
                "ADD search_count :one, #search_day :one "
                "SET last_used_at = :last_used_at"
            ),
            ExpressionAttributeNames={"#search_day": f"search#{today}"},
            ExpressionAttributeValues={
                ":one": 1,
                ":last_used_at": _now_kst_iso(),
            },
        )
    except Exception as error:  # noqa: BLE001 (검색 사용량 기록 실패는 비크리티컬)
        logger.warning("검색 사용량 기록 실패(무시, identity=%s): %s", identity, error)


def summarize_usage_item(item: dict) -> dict:
    """원시 web_usage 항목을 관리자 응답용으로 정돈한다(일별 시계열 재구성).

    ``get_all_usage()``가 scan으로 반환한 원시 항목에서 ``req#*``·``llm#*``·``search#*``
    최상위 키를 파싱해 날짜별로 묶는다. 값 타입 변환(Decimal→JSON)은 여기서 하지 않고
    형태만 재구성한다 — 호출부(``web_api_handler._to_jsonable``)가 재귀 변환한다.

    반환 형태::

        {
            "identity": <str>,
            "total_count": <원시 값 또는 0>,
            "llm_call_count": <원시 값 또는 0>,
            "search_count": <원시 값 또는 0>,
            "last_used_at": <원시 값 또는 "">,
            "daily": [{"date": "YYYY-MM-DD", "total": <req>, "llm": <llm>, "search": <search>}, ...],
        }

    ``daily``는 date 문자열 오름차순(사전식 = 날짜순)으로 정렬하며, 어느 한 지표만
    있는 날짜는 없는 쪽을 0으로 채운다.
    """
    daily_by_date: dict[str, dict[str, int]] = {}
    for key, value in item.items():
        matched = _DAILY_KEY_PATTERN.match(str(key))
        if not matched:
            continue
        metric, date_string = matched.group(1), matched.group(2)
        bucket = daily_by_date.setdefault(
            date_string, {"total": 0, "llm": 0, "search": 0}
        )
        if metric == "req":
            bucket["total"] = value
        elif metric == "llm":
            bucket["llm"] = value
        else:
            bucket["search"] = value

    daily = [
        {
            "date": date_string,
            "total": daily_by_date[date_string]["total"],
            "llm": daily_by_date[date_string]["llm"],
            "search": daily_by_date[date_string]["search"],
        }
        for date_string in sorted(daily_by_date)
    ]

    return {
        "identity": item.get("identity"),
        "total_count": item.get("total_count", 0),
        "llm_call_count": item.get("llm_call_count", 0),
        "search_count": item.get("search_count", 0),
        "last_used_at": item.get("last_used_at", ""),
        "daily": daily,
    }


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
