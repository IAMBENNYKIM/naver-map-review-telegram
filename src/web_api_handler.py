"""웹 진입점 API Lambda 핸들러 (WebApiFunction 진입점).

HttpApi(payload v2)로 들어온 요청을 검증·라우팅해 빠르게(<3초) 응답한다.
무거운 분석 파이프라인은 여기서 실행하지 않고 WebWorkerFunction으로 비동기
invoke(InvocationType="Event")한 뒤 job_id를 즉시 반환한다(비동기 잡+폴링 구조).

핸들러는 동기(`def lambda_handler`) — 이 함수 안에서는 무거운 I/O가 없으므로
asyncio 래퍼를 두지 않는다(webhook_handler와 달리 파이프라인 호출 없음).

라우트:
  - POST /invite          초대코드 검증 → 세션 토큰 발급
  - POST /search          세션 검증 → 검색어 정규화 + 장소 검색 → 후보 리스트 (동기)
  - POST /analyze         세션 검증 → 잡 생성 + WebWorkerFunction 비동기 invoke → 202
  - GET  /result/{job_id} 세션 검증 + 소유권 확인 → 잡 상태 반환
  - GET  /admin/stats     관리자 토큰 검증 → 사용량 통계

보안: 토큰·시크릿 원문 값을 로그에 남기지 않는다. 타인 잡 노출을 막기 위해
소유권 불일치는 404(존재를 숨김)로 응답한다. 내부 예외는 흡수해 500만 반환한다.
"""

import json
import logging
import os
import re
import time
import uuid
from decimal import Decimal

import config
import naver_review_collector
import search_normalizer
import web_auth
import web_store

logger = logging.getLogger(__name__)

_JSON_HEADERS = {"content-type": "application/json"}

# place_id 형식 검증 — 숫자만 허용 (네이버 place_id 체계)
_PLACE_ID_PATTERN = re.compile(r"^\d+$")


def lambda_handler(event, context):
    """WebApiFunction 진입점(동기). 메서드·경로로 내부 라우팅한다.

    최상위에서 모든 예외를 흡수해 내부 상세를 노출하지 않고 500을 반환한다.
    """
    # 워밍 핑(EventBridge 5분 주기) — 콜드스타트 방지용. 라우팅 없이 즉시 반환한다.
    # 5분마다 INFO 로그를 남기지 않도록 DEBUG로만 기록한다.
    if isinstance(event, dict) and event.get("warmup"):
        logger.debug("워밍 핑 수신 — 즉시 반환")
        return {"statusCode": 200}
    try:
        http_context = (event.get("requestContext") or {}).get("http") or {}
        method = str(http_context.get("method", "")).upper()
        path = str(http_context.get("path", ""))
        return _route(method, path, event)
    except Exception as error:  # noqa: BLE001 — 내부 상세 비노출, 로그만 남기고 500
        logger.error("웹 API 처리 중 예기치 못한 오류: %s", error)
        return _response(500, {"error": "internal error"})


# ---------------------------------------------------------------------------
# 라우팅
# ---------------------------------------------------------------------------
def _route(method: str, path: str, event: dict) -> dict:
    """메서드·경로에 따라 개별 핸들러로 분기한다. 미지원이면 404."""
    if method == "POST" and path == "/invite":
        return _handle_invite(event)
    if method == "POST" and path == "/search":
        return _handle_search(event)
    if method == "POST" and path == "/analyze":
        return _handle_analyze(event)
    if method == "GET" and path == "/admin/stats":
        return _handle_admin_stats(event)
    # /result/{job_id} — path 파라미터로 job_id 확보(prefix 매칭)
    if method == "GET" and path.startswith("/result/"):
        return _handle_result(event)
    return _response(404, {"error": "not found"})


def _handle_invite(event: dict) -> dict:
    """POST /invite — 초대코드 검증 후 세션 토큰을 발급한다."""
    body = _parse_json_body(event)
    if body is None:
        return _response(400, {"error": "invalid json body"})

    code = body.get("code", "")
    identity = web_auth.validate_invite_code(code)
    if not identity:
        # 초대코드 원문은 로그에 남기지 않는다.
        logger.warning("초대코드 검증 실패 — 401")
        return _response(401, {"error": "invalid invite code"})

    token = web_auth.issue_session_token(identity)
    logger.info("세션 토큰 발급 (identity=%s)", identity)
    return _response(200, {"token": token})


def _handle_search(event: dict) -> dict:
    """POST /search — 세션 검증 후 검색어 정규화 + 장소 검색을 동기 처리한다.

    처리 순서: 세션 검증 → normalize_search_query → search_places →
    log_search_usage → 응답. 네이버 검색 실패는 502로, 그 외는 최상위(500)에서 흡수.

    PII 주의: prompt 원문·keyword를 INFO 로그에 남기지 않는다(사용자 입력 텍스트).
    건수·identity만 로깅한다.
    """
    identity = _authenticate_session(event)
    if not identity:
        return _response(401, {"error": "unauthorized"})

    body = _parse_json_body(event)
    if body is None:
        return _response(400, {"error": "invalid json body"})

    prompt = body.get("prompt")
    if not prompt or not str(prompt).strip():
        return _response(400, {"error": "prompt is required"})

    normalize_started = time.monotonic()
    keyword = search_normalizer.normalize_search_query(str(prompt))
    normalize_seconds = time.monotonic() - normalize_started

    search_started = time.monotonic()
    try:
        place_list = naver_review_collector.search_places(keyword)
    except naver_review_collector.ReviewCollectError as error:
        # keyword를 로그에 남기지 않는다(사용자 입력 파생 텍스트).
        logger.warning("장소 검색 실패 (identity=%s): %s", identity, error)
        return _response(502, {"error": "place search failed"})
    search_seconds = time.monotonic() - search_started

    usage_started = time.monotonic()
    web_store.log_search_usage(identity)
    usage_seconds = time.monotonic() - usage_started

    # 단계별 소요를 한 줄로 기록한다. prompt·keyword 내용은 절대 남기지 않는다(PII).
    logger.info(
        "검색 소요(identity=%s, normalize=%.2fs, search=%.2fs, usage=%.2fs, 결과=%d건)",
        identity,
        normalize_seconds,
        search_seconds,
        usage_seconds,
        len(place_list),
    )
    return _response(200, {"keyword": keyword, "places": place_list})


def _handle_analyze(event: dict) -> dict:
    """POST /analyze — 세션 검증 후 잡 생성 + WebWorkerFunction 비동기 invoke.

    입력: body에 ``naver_url`` 또는 ``place_id`` 중 하나 필수(둘 다 있으면 place_id 우선).
    place_id는 정규식 ``^\\d+$`` 로 검증한다(불일치 시 400).
    """
    identity = _authenticate_session(event)
    if not identity:
        return _response(401, {"error": "unauthorized"})

    body = _parse_json_body(event)
    if body is None:
        return _response(400, {"error": "invalid json body"})

    place_id = body.get("place_id")
    naver_url = body.get("naver_url")

    # place_id 우선. 형식 불일치는 400. 둘 다 없으면 400.
    if place_id:
        if not _PLACE_ID_PATTERN.match(str(place_id)):
            return _response(400, {"error": "invalid place_id"})
        place_id = str(place_id)
        naver_url = ""
    elif naver_url:
        naver_url = str(naver_url)
        place_id = ""
    else:
        return _response(400, {"error": "naver_url or place_id is required"})

    # force_refresh: 캐시를 무시하고 강제 재분석(Telegram /update와 동일 의미)
    force_refresh = bool(body.get("force_refresh", False))

    job_id = uuid.uuid4().hex

    # 캐시 히트 직결: place_id 경로이고 force_refresh가 아닐 때만 캐시를 먼저 조회한다.
    # 히트면 완료 잡을 즉시 생성하고 워커 invoke 없이 202를 반환한다(콜드스타트·invoke 왕복 절감).
    # naver_url 경로는 place_id를 모르므로 캐시 조회 없이 기존 흐름(워커가 resolve 후 조회)을 탄다.
    if place_id and not force_refresh:
        cached = web_store.lookup_cached_summary(place_id)
        if cached is not None:
            web_store.create_completed_job(
                job_id,
                identity,
                place_id,
                summary_json=cached["summary_json"],
                place_name=cached["place_name"],
                address=cached["address"],
                review_count=cached["review_count"],
                updated_at=cached["updated_at"],
            )
            # 워커의 캐시 히트 경로와 동일하게 사용량을 기록한다(cache_hit=True).
            web_store.log_usage(identity, cache_hit=True)
            logger.info(
                "캐시 히트 직결 잡 완료 (job_id=%s, identity=%s)", job_id, identity
            )
            return _response(202, {"job_id": job_id})

    web_store.create_job(job_id, identity, naver_url, place_id)
    _invoke_web_worker(job_id, identity, naver_url, place_id, force_refresh)
    logger.info("분석 잡 생성·invoke 완료 (job_id=%s, identity=%s)", job_id, identity)
    return _response(202, {"job_id": job_id})


def _handle_result(event: dict) -> dict:
    """GET /result/{job_id} — 세션 검증 + 소유권 확인 후 잡 상태를 반환한다."""
    identity = _authenticate_session(event)
    if not identity:
        return _response(401, {"error": "unauthorized"})

    job_id = (event.get("pathParameters") or {}).get("job_id", "")
    job = web_store.get_job(job_id)
    # 잡이 없거나 소유자가 다르면 동일하게 404 — 타인 잡의 존재를 노출하지 않는다.
    if not job or job.get("identity") != identity:
        return _response(404, {"error": "not found"})

    status = job.get("status")
    if status == "done":
        payload = {
            "status": "done",
            "summary_json": job.get("summary_json"),
            "place_name": job.get("place_name"),
            "address": job.get("address"),
            "review_count": job.get("review_count"),
            "cache_hit": job.get("cache_hit"),
            "updated_at": job.get("updated_at"),
        }
    elif status == "error":
        payload = {"status": "error", "error_message": job.get("error_message")}
    else:
        payload = {"status": "processing"}

    return _response(200, _to_jsonable(payload))


def _handle_admin_stats(event: dict) -> dict:
    """GET /admin/stats — 관리자 토큰 검증 후 사용량 통계를 반환한다."""
    provided = _extract_bearer_token(event)
    if not web_auth.verify_admin_token(provided):
        logger.warning("관리자 인증 실패 — 401")
        return _response(401, {"error": "unauthorized"})

    usage = [
        web_store.summarize_usage_item(item)
        for item in web_store.get_all_usage()
    ]
    return _response(200, {"usage": _to_jsonable(usage)})


# ---------------------------------------------------------------------------
# 비동기 invoke
# ---------------------------------------------------------------------------
def _invoke_web_worker(
    job_id: str,
    identity: str,
    naver_url: str,
    place_id: str,
    force_refresh: bool,
) -> None:
    """WebWorkerFunction을 InvocationType="Event"로 비동기 invoke한다.

    이벤트 계약: {"job_id", "identity", "naver_url", "place_id", "force_refresh"}.
    naver_url·place_id는 둘 중 쓰지 않는 쪽이 빈 문자열이다.
    (webhook_handler._invoke_worker 패턴 참고.)
    """
    import boto3

    worker_payload = {
        "job_id": job_id,
        "identity": identity,
        "naver_url": naver_url,
        "place_id": place_id,
        "force_refresh": force_refresh,
    }
    lambda_client = boto3.client("lambda", region_name=config.AWS_REGION)
    lambda_client.invoke(
        FunctionName=os.environ["WEB_WORKER_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps(worker_payload).encode("utf-8"),
    )


# ---------------------------------------------------------------------------
# 요청 파싱·인증 헬퍼
# ---------------------------------------------------------------------------
def _authenticate_session(event: dict) -> str | None:
    """Authorization: Bearer 토큰을 세션 검증해 identity를 반환한다. 실패 시 None."""
    token = _extract_bearer_token(event)
    if not token:
        return None
    return web_auth.verify_session_token(token)


def _extract_bearer_token(event: dict) -> str:
    """Authorization 헤더에서 Bearer 토큰을 추출한다(대소문자 무시). 없으면 빈 문자열."""
    authorization = _get_header(event.get("headers"), "authorization")
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def _get_header(headers, name: str) -> str:
    """헤더를 대소문자 무시로 조회한다(HttpApi는 보통 소문자 키)."""
    if not headers:
        return ""
    lowered = {str(key).lower(): value for key, value in headers.items()}
    return str(lowered.get(name, ""))


def _parse_json_body(event: dict) -> dict | None:
    """요청 body를 JSON dict로 파싱한다. 파싱 실패·비객체면 None."""
    raw_body = event.get("body")
    try:
        parsed = json.loads(raw_body or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


# ---------------------------------------------------------------------------
# 응답 헬퍼
# ---------------------------------------------------------------------------
def _response(status_code: int, body: object) -> dict:
    """HttpApi 형식의 JSON 응답 dict를 생성한다."""
    return {
        "statusCode": status_code,
        "headers": _JSON_HEADERS,
        "body": json.dumps(body, ensure_ascii=False),
    }


def _to_jsonable(value):
    """DynamoDB Decimal을 JSON 직렬화 가능한 값으로 재귀 변환한다.

    Decimal은 정수면 int, 아니면 float로 변환한다. dict/list는 재귀 처리하며
    그 외 타입은 그대로 반환한다.
    """
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value
