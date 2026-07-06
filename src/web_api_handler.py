"""웹 진입점 API Lambda 핸들러 (WebApiFunction 진입점).

HttpApi(payload v2)로 들어온 요청을 검증·라우팅해 빠르게(<3초) 응답한다.
무거운 분석 파이프라인은 여기서 실행하지 않고 WebWorkerFunction으로 비동기
invoke(InvocationType="Event")한 뒤 job_id를 즉시 반환한다(비동기 잡+폴링 구조).

핸들러는 동기(`def lambda_handler`) — 이 함수 안에서는 무거운 I/O가 없으므로
asyncio 래퍼를 두지 않는다(webhook_handler와 달리 파이프라인 호출 없음).

라우트:
  - POST /invite          초대코드 검증 → 세션 토큰 발급
  - POST /analyze         세션 검증 → 잡 생성 + WebWorkerFunction 비동기 invoke → 202
  - GET  /result/{job_id} 세션 검증 + 소유권 확인 → 잡 상태 반환
  - GET  /admin/stats     관리자 토큰 검증 → 사용량 통계

보안: 토큰·시크릿 원문 값을 로그에 남기지 않는다. 타인 잡 노출을 막기 위해
소유권 불일치는 404(존재를 숨김)로 응답한다. 내부 예외는 흡수해 500만 반환한다.
"""

import json
import logging
import os
import uuid
from decimal import Decimal

import config
import web_auth
import web_store

logger = logging.getLogger(__name__)

_JSON_HEADERS = {"content-type": "application/json"}


def lambda_handler(event, context):
    """WebApiFunction 진입점(동기). 메서드·경로로 내부 라우팅한다.

    최상위에서 모든 예외를 흡수해 내부 상세를 노출하지 않고 500을 반환한다.
    """
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


def _handle_analyze(event: dict) -> dict:
    """POST /analyze — 세션 검증 후 잡 생성 + WebWorkerFunction 비동기 invoke."""
    identity = _authenticate_session(event)
    if not identity:
        return _response(401, {"error": "unauthorized"})

    body = _parse_json_body(event)
    if body is None:
        return _response(400, {"error": "invalid json body"})

    naver_url = body.get("naver_url")
    if not naver_url:
        return _response(400, {"error": "naver_url is required"})

    # force_refresh: 캐시를 무시하고 강제 재분석(Telegram /update와 동일 의미)
    force_refresh = bool(body.get("force_refresh", False))

    job_id = uuid.uuid4().hex
    web_store.create_job(job_id, identity, naver_url)
    _invoke_web_worker(job_id, identity, naver_url, force_refresh)
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

    usage = web_store.get_all_usage()
    return _response(200, {"usage": _to_jsonable(usage)})


# ---------------------------------------------------------------------------
# 비동기 invoke
# ---------------------------------------------------------------------------
def _invoke_web_worker(
    job_id: str, identity: str, naver_url: str, force_refresh: bool
) -> None:
    """WebWorkerFunction을 InvocationType="Event"로 비동기 invoke한다.

    이벤트 계약: {"job_id", "identity", "naver_url", "force_refresh"}.
    (webhook_handler._invoke_worker 패턴 참고.)
    """
    import boto3

    worker_payload = {
        "job_id": job_id,
        "identity": identity,
        "naver_url": naver_url,
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
