"""인바운드 Webhook Lambda 핸들러 (WebhookFunction 진입점).

API Gateway로 들어온 Telegram update를 검증·파싱해, 무거운 처리는 WorkerFunction으로
비동기 invoke(InvocationType="Event")한 뒤 즉시 "분석 중" 응답을 발송하고 200을 반환한다.

필수 패턴: `async def lambda_handler` 금지 → 동기 래퍼에서 asyncio.run 호출.
Webhook은 어떤 경우에도 200을 반환한다(예외 흡수 → Telegram 재시도 폭주 방지).

검증 순서:
  1) X-Telegram-Bot-Api-Secret-Token 헤더 == config.TELEGRAM_WEBHOOK_SECRET (불일치 403)
  2) message.text 없는 update(스티커·콜백 등) → 무시(200)
  3) chat_id가 config.TELEGRAM_CHAT_IDS 허용 목록에 없으면 → 무시(200)
"""

import asyncio
import hmac
import json
import logging

import command_router
import config
import review_formatter
import telegram_sender

logger = logging.getLogger(__name__)

_SECRET_HEADER = "x-telegram-bot-api-secret-token"

# 분석 요청 접수 시 사용자에게 보내는 즉답 문구(원문 — 발송 직전 이스케이프)
_ACK_MESSAGE = "🔍 리뷰를 분석하고 있어요. 잠시만 기다려 주세요."


def lambda_handler(event, context):
    """API Gateway 진입점(동기 래퍼). asyncio.run으로 실행."""
    return asyncio.run(_async_main(event, context))


def _get_header(headers, name: str) -> str:
    """헤더를 대소문자 무시로 조회한다(API Gateway는 보통 소문자 키)."""
    if not headers:
        return ""
    lowered = {str(key).lower(): value for key, value in headers.items()}
    return str(lowered.get(name, ""))


async def _async_main(event, context) -> dict:
    """update 검증·파싱 후 WorkerFunction 비동기 invoke + 즉답. 항상(예외 포함) 200 반환."""
    # 1) Secret Token 검증 (설정돼 있을 때만 — 미설정 환경은 통과)
    expected = config.TELEGRAM_WEBHOOK_SECRET
    if expected:
        provided = _get_header(event.get("headers"), _SECRET_HEADER)
        # 상수 시간 비교 — 타이밍 공격으로 secret을 추론하지 못하도록(값은 로그에 남기지 않음)
        if not hmac.compare_digest(provided, expected):
            logger.warning("Webhook secret token 불일치 — 요청 거부(403)")
            return {"statusCode": 403, "body": "forbidden"}

    # 2) body 파싱
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError) as error:
        logger.warning("Webhook body 파싱 실패(무시): %s", error)
        return {"statusCode": 200, "body": "bad request ignored"}

    message = body.get("message") or {}
    text = message.get("text")
    chat_id = str((message.get("chat") or {}).get("id", ""))

    # 3) text·chat_id 없는 update(스티커·콜백·채널 등) 무시. 빈 chat_id가 허용목록을
    #    우연히 통과하지 않도록 명시적으로 차단한다.
    if not text or not chat_id:
        return {"statusCode": 200, "body": "no text/chat_id ignored"}

    # 4) chat_id 허용 목록 검증 — 외부면 조용히 무시
    if chat_id not in config.TELEGRAM_CHAT_IDS:
        logger.warning("허용 목록 외 chat_id(%s) — 무시", chat_id)
        return {"statusCode": 200, "body": "unauthorized ignored"}

    # 5) 파싱·라우팅. 예외도 흡수해 항상 200 — Telegram 재시도 폭주 방지.
    try:
        _route(text, chat_id)
    except Exception as error:  # noqa: BLE001
        logger.error("webhook 라우팅 처리 실패(chat_id=%s): %s", chat_id, error)

    return {"statusCode": 200, "body": "ok"}


def _route(text: str, chat_id: str) -> None:
    """파싱 결과에 따라 WorkerFunction 비동기 invoke 또는 도움말 즉답을 수행한다."""
    parsed = command_router.parse_message(text)
    action = parsed.get("action")

    if action in ("analyze", "update"):
        _invoke_worker(chat_id, parsed)
        telegram_sender.send_reply(
            chat_id, review_formatter.build_simple_message(_ACK_MESSAGE)
        )
        return

    # help
    telegram_sender.send_reply(
        chat_id, review_formatter.build_simple_message(command_router.HELP_MESSAGE)
    )


def _invoke_worker(chat_id: str, parsed: dict) -> None:
    """WorkerFunction을 InvocationType="Event"로 비동기 invoke한다.

    이벤트 계약(PRD §6): {"chat_id", "action", "naver_url", "shared_place_name"}.
    """
    import boto3

    worker_payload = {
        "chat_id": chat_id,
        "action": parsed["action"],
        "naver_url": parsed.get("naver_url"),
        "shared_place_name": parsed.get("shared_place_name"),
    }
    lambda_client = boto3.client("lambda", region_name=config.AWS_REGION)
    lambda_client.invoke(
        FunctionName=config.WORKER_FUNCTION_NAME,
        InvocationType="Event",
        Payload=json.dumps(worker_payload).encode("utf-8"),
    )
    logger.info("WorkerFunction 비동기 invoke 완료 (action=%s)", parsed["action"])
