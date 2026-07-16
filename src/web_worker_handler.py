"""웹 진입점 WorkerFunction Lambda 핸들러 (WebWorkerFunction 진입점).

WebApiFunction이 비동기 invoke한 잡을 받아 무거운 파이프라인을 오케스트레이션한다:
  place 해석 → 캐시 조회(web → prod read-through) → (미스 시) 수집 → 분석 →
  잡 완료 기록 → 사용량 기록

이벤트 계약: {"job_id": str, "identity": str, "naver_url": str, "place_id": str,
             "force_refresh": bool}
  - place_id가 truthy면 그 값을 직접 사용(검색 후보 클릭 경로 — resolve_place 생략).
  - 아니면 naver_url을 resolve_place로 해석한다(공유 URL 입력 경로).

필수 패턴: `async def lambda_handler` 금지 → 동기 래퍼에서 asyncio.run 호출.
전체를 예외 흡수로 감싼다(비동기 재시도 폭주 방지) — 어떤 예외도 잡을 error 상태로
기록하고 정상 종료한다. Telegram·formatter·chat_id 개념은 없다(웹 프론트가 렌더).

분석 결과(review_analyst의 JSON 문자열)는 가공 없이 그대로 잡에 저장한다.
"""

import asyncio
import logging

import config
import naver_review_collector
import review_analyst
import web_store

logger = logging.getLogger(__name__)

# 사용자에게 노출되는 실패 안내 문구(웹 프론트가 표시)
_COLLECT_FAILURE_MESSAGE = "리뷰를 가져오지 못했어요"
_ANALYSIS_UNAVAILABLE_MESSAGE = "분석을 일시적으로 사용할 수 없어요"
_GENERIC_FAILURE_MESSAGE = "분석 중 문제가 발생했어요"


def lambda_handler(event, context):
    """WebWorkerFunction 진입점(동기 래퍼). asyncio.run으로 실행."""
    return asyncio.run(_async_main(event, context))


async def _async_main(event, context) -> dict:
    """이벤트 계약 파싱 후 파이프라인 실행. 예외는 흡수해 정상 종료한다."""
    job_id = event.get("job_id")
    identity = event.get("identity", "")
    naver_url = event.get("naver_url")
    place_id = event.get("place_id") or ""
    force_refresh = bool(event.get("force_refresh", False))

    if not job_id:
        logger.error("잘못된 웹 Worker 이벤트 — job_id 없음, 무시")
        return {"statusCode": 200, "body": "invalid event ignored"}

    try:
        _run_pipeline(
            job_id,
            identity,
            naver_url or "",
            place_id,
            force_refresh=force_refresh,
        )
    except naver_review_collector.ReviewCollectError as error:
        logger.warning("리뷰 수집 실패 (job_id=%s): %s", job_id, error)
        web_store.fail_job(job_id, _COLLECT_FAILURE_MESSAGE)
    except Exception as error:  # noqa: BLE001 — 전체 예외 흡수(재시도 폭주 방지)
        logger.error("웹 Worker 파이프라인 실패 (job_id=%s): %s", job_id, error)
        web_store.fail_job(job_id, _GENERIC_FAILURE_MESSAGE)

    return {"statusCode": 200, "body": "ok"}


def _run_pipeline(
    job_id: str,
    identity: str,
    naver_url: str,
    place_id: str = "",
    force_refresh: bool = False,
) -> None:
    """수집→분석→잡 완료 파이프라인 본체.

    place_id가 truthy면 그 값을 직접 사용하고(검색 후보 클릭 경로), 아니면 naver_url을
    resolve_place로 해석한다(공유 URL 입력 경로). 나머지 캐시·수집·분석 흐름은 동일하다.
    캐시 조회 순서: web 캐시 → prod 캐시(read-through, 히트 시 web 캐시로 워밍).
    force_refresh가 True면 캐시 조회를 건너뛰고 곧바로 신규 수집·분석 경로를 탄다
    (Telegram의 /update와 동일 의미).
    """
    # 1) place 해석 — place_id가 주어지면 resolve_place 생략, 아니면 URL을 해석한다.
    if not place_id:
        place_id = naver_review_collector.resolve_place(naver_url)["place_id"]

    # 2) 캐시 조회 — web 우선, 없으면 prod 캐시를 읽어 web 캐시에 워밍한다.
    #    force_refresh면 캐시를 무시하고 신규 분석 경로로 직행한다.
    cached = None if force_refresh else _lookup_cache(place_id)
    if cached is not None:
        web_store.complete_job(
            job_id,
            summary_json=cached["summary_json"],
            place_name=cached["place_name"],
            address=cached["address"],
            review_count=cached["review_count"],
            cache_hit=True,
            updated_at=cached["updated_at"],
        )
        web_store.log_usage(identity, cache_hit=True)
        logger.info("캐시 히트로 잡 완료 (job_id=%s)", job_id)
        return

    # 3) 캐시 미스 — 신규 수집·분석
    place_detail = naver_review_collector.fetch_place_detail(place_id)
    review_list = naver_review_collector.fetch_reviews(
        place_id, place_detail["business_type"], config.REVIEW_FETCH_LIMIT
    )
    summary_json = review_analyst.analyze_reviews(place_detail, review_list)

    # 분석 실패·킬스위치·리뷰 없음 → 잡 실패 기록 + 사용량은 미스로 기록 후 종료.
    if summary_json is None:
        logger.warning("분석 결과 없음 — 잡 실패 처리 (job_id=%s)", job_id)
        web_store.fail_job(job_id, _ANALYSIS_UNAVAILABLE_MESSAGE)
        web_store.log_usage(identity, cache_hit=False)
        return

    # 4) 웹 캐시 저장(비크리티컬) 후 잡 완료 기록
    place_name = place_detail["name"]
    address = place_detail["address"]
    review_count = len(review_list)
    updated_at = web_store.save_web_summary(
        place_id, place_name, address, summary_json, review_count
    )
    web_store.complete_job(
        job_id,
        summary_json=summary_json,
        place_name=place_name,
        address=address,
        review_count=review_count,
        cache_hit=False,
        updated_at=updated_at,
    )
    web_store.log_usage(identity, cache_hit=False)
    logger.info("신규 분석으로 잡 완료 (job_id=%s, 리뷰 %d건)", job_id, review_count)


def _lookup_cache(place_id: str) -> dict | None:
    """web 캐시 → prod 캐시 순으로 조회한다.

    web 히트: 그대로 사용. prod 히트: web 캐시에도 저장(워밍)한다. 둘 다 미스면 None.
    반환 dict는 summary_json/place_name/address/review_count 키로 정규화된다.
    """
    web_item = web_store.get_web_cached_summary(place_id)
    if web_item:
        return _normalize_cache_item(web_item)

    prod_item = web_store.get_prod_cached_summary(place_id)
    if prod_item:
        normalized = _normalize_cache_item(prod_item)
        # prod 히트를 web 캐시로 워밍한다(다음 조회부터 web 캐시가 응답).
        web_store.save_web_summary(
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
