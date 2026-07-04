"""Telegram 발송 (공유 모듈).

온디맨드 응답용 send_reply + 실패 시 RETRY_COUNT 재시도, 최종 실패 시 개발자에게 에러 알림.
"""

import logging
import time

import httpx

import config

logger = logging.getLogger(__name__)

# Telegram API 엔드포인트 기본 주소
TELEGRAM_API_BASE_URL: str = "https://api.telegram.org"

# 재시도 대기 시간(초) — 일반 실패 시 적용
RETRY_WAIT_SECONDS: int = 2

# 단일 httpx 요청 타임아웃(초)
REQUEST_TIMEOUT: float = 10.0

# Telegram sendMessage 본문 최대 길이 — 초과 시 400 (발송 전 안전 절단)
TELEGRAM_MESSAGE_LIMIT: int = 4096

# 절단 시 덧붙일 안내 꼬리 (MarkdownV2 특수문자 사전 이스케이프 완료 문자열)
_TRUNCATION_SUFFIX: str = "\n…\\(내용이 길어 일부 생략\\)"


class TelegramSendError(Exception):
    """RETRY_COUNT 재시도 후에도 발송에 실패했을 때 raise."""


def _build_send_message_url() -> str:
    """sendMessage 엔드포인트 URL을 생성한다."""
    return f"{TELEGRAM_API_BASE_URL}/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"


def _truncate_message(text: str) -> str:
    """4096자 초과 메시지를 Telegram 한도 내로 안전하게 절단한다.

    MarkdownV2 이스케이프 시퀀스(``\\X``) 중간을 자르면 꼬리에 백슬래시가 남아
    파싱 400이 발생하므로, 절단 지점 끝의 홀수 개 백슬래시를 제거한 뒤
    사전 이스케이프된 안내 꼬리를 덧붙인다.
    """
    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        return text

    allowed_length = TELEGRAM_MESSAGE_LIMIT - len(_TRUNCATION_SUFFIX)
    truncated = text[:allowed_length]

    # 끝의 백슬래시 연속 개수가 홀수면 이스케이프가 반토막 — 하나 제거
    trailing_backslashes = len(truncated) - len(truncated.rstrip("\\"))
    if trailing_backslashes % 2 == 1:
        truncated = truncated[:-1]

    logger.warning(
        "Telegram 메시지 %d자 → %d자로 절단 (한도 %d자)",
        len(text),
        len(truncated) + len(_TRUNCATION_SUFFIX),
        TELEGRAM_MESSAGE_LIMIT,
    )
    return truncated + _TRUNCATION_SUFFIX


def _post_message(chat_id: str, text: str) -> None:
    """단일 Chat ID에 메시지 1건을 발송한다.

    HTTP 상태 코드에 따라 특수 처리를 수행하며, 실패 시 예외를 raise한다.

    Raises:
        httpx.HTTPStatusError: 400/403/기타 4xx~5xx 응답 시.
        httpx.HTTPError: 연결·타임아웃 등 네트워크 수준 오류 시.
    """
    url = _build_send_message_url()
    payload = {
        "chat_id": chat_id,
        "text": _truncate_message(text),
        "parse_mode": "MarkdownV2",
    }
    response = httpx.post(url, json=payload, timeout=REQUEST_TIMEOUT)

    # HTTP 429 Too Many Requests: Retry-After 헤더 값만큼 대기 후 호출자에게 예외 전파
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", RETRY_WAIT_SECONDS))
        logger.warning(
            "Telegram API 429 Too Many Requests — %d초 대기 후 재시도 (chat_id=%s)",
            retry_after,
            chat_id,
        )
        time.sleep(retry_after)
        # 재시도는 호출자(_send_with_retry)가 담당하므로 여기서는 예외 raise
        response.raise_for_status()

    # HTTP 403 Forbidden: 봇이 채팅에서 차단됨
    if response.status_code == 403:
        logger.error(
            "Telegram API 403 Forbidden — 봇이 채팅에서 차단됨 (chat_id=%s)",
            chat_id,
        )
        response.raise_for_status()

    # HTTP 400 Bad Request: MarkdownV2 이스케이프 문제 가능성 — 본문을 로깅
    if response.status_code == 400:
        logger.error(
            "Telegram API 400 Bad Request — MarkdownV2 이스케이프 오류 가능성 "
            "(chat_id=%s, 응답 본문=%s)",
            chat_id,
            response.text,
        )
        response.raise_for_status()

    # 기타 4xx/5xx 상태 코드 일괄 처리
    response.raise_for_status()


def _send_with_retry(chat_id: str, text: str) -> bool:
    """단일 메시지를 최대 RETRY_COUNT회 재시도하며 발송한다.

    Returns:
        True — 발송 성공, False — RETRY_COUNT회 모두 실패.
    """
    last_error: Exception | None = None

    for attempt in range(1, config.RETRY_COUNT + 2):  # 최초 1회 + 재시도 RETRY_COUNT회
        try:
            _post_message(chat_id, text)
            if attempt > 1:
                logger.info(
                    "Telegram 발송 성공 (재시도 %d회 후, chat_id=%s)", attempt - 1, chat_id
                )
            return True
        except Exception as error:  # noqa: BLE001
            last_error = error
            # RETRY_COUNT회가 모두 소진되면 더 이상 대기하지 않는다
            if attempt <= config.RETRY_COUNT:
                logger.warning(
                    "Telegram 발송 실패 (시도 %d/%d, chat_id=%s, 오류=%s) — %d초 후 재시도",
                    attempt,
                    config.RETRY_COUNT + 1,
                    chat_id,
                    error,
                    RETRY_WAIT_SECONDS,
                )
                time.sleep(RETRY_WAIT_SECONDS)
            else:
                logger.error(
                    "Telegram 발송 최종 실패 (chat_id=%s, 오류=%s)",
                    chat_id,
                    last_error,
                )

    return False


def send_reply(chat_id: str, message: str) -> bool:
    """온디맨드 응답용 — 특정 Chat ID 한 곳에 메시지 1건을 발송한다.

    허용 목록 검증은 호출자(webhook_handler)가 담당하므로 여기서는 발송만 한다.
    기존 _send_with_retry(RETRY_COUNT 재시도)를 재사용한다.

    Returns:
        True — 발송 성공, False — RETRY_COUNT회 모두 실패.
    """
    return _send_with_retry(chat_id, message)


def send_error_alert(error_message: str) -> None:
    """개발자 Chat ID(TELEGRAM_DEVELOPER_CHAT_ID)에만 에러 알림을 발송한다.

    이 함수 자체의 실패는 로깅만 하고 예외를 raise하지 않는다.
    (에러 알림 실패로 인해 상위 호출 흐름이 중단되는 것을 방지)
    """
    developer_chat_id = config.TELEGRAM_DEVELOPER_CHAT_ID
    if not developer_chat_id:
        logger.error("TELEGRAM_DEVELOPER_CHAT_ID가 설정되지 않아 에러 알림을 발송할 수 없습니다.")
        return

    try:
        url = _build_send_message_url()
        alert_text = f"[에러 알림]\n{error_message}"
        payload = {
            "chat_id": developer_chat_id,
            "text": alert_text,
        }
        response = httpx.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        logger.info("개발자에게 에러 알림 발송 완료 (chat_id=%s)", developer_chat_id)
    except Exception as error:  # noqa: BLE001
        # 에러 알림 발송 실패는 로깅만 하고 예외를 전파하지 않는다
        logger.error(
            "개발자 에러 알림 발송 실패 — 로깅 후 무시 (chat_id=%s, 오류=%s)",
            developer_chat_id,
            error,
        )
