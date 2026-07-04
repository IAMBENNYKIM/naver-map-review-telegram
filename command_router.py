"""명령어 파싱·라우팅.

webhook_handler가 권한 검증을 마친 메시지 텍스트를 받아 명령어로 분기한다.
  - `/review <장소명|URL>` 또는 명령어 없는 `<장소명>` → 리뷰 수집·요약 응답
  - `/start`·`/help`·빈 입력·미인식 → 사용법 안내

응답은 telegram_sender.send_reply로 발송한다(공유 모듈 재사용). 모든 응답은 MarkdownV2라
안내 문구도 review_formatter.escape_markdownv2로 이스케이프한다.
"""

import hashlib
import logging

import config
import dynamo_writer
import naver_review_collector
import review_analyst
import review_formatter
import telegram_sender

logger = logging.getLogger(__name__)

_NOT_FOUND_MESSAGE = "장소를 찾을 수 없습니다. 이름이나 링크를 확인해 주세요."
_NO_REVIEW_MESSAGE = "리뷰를 찾을 수 없습니다."
_ERROR_MESSAGE = "일시적인 오류로 조회에 실패했습니다. 잠시 후 다시 시도해 주세요."
_EMPTY_QUERY_MESSAGE = "장소명을 입력해 주세요. 예: 성수동 카페 또는 /review 성수동 카페"
_HELP_MESSAGE = (
    "📌 사용법\n"
    "• 장소명 또는 /review 장소명 → 리뷰 요약 (예: 성수동 카페)\n"
    "• 네이버 지도 링크를 붙여넣어도 됩니다\n"
    "• /help → 이 안내"
)


def route(text: str, chat_id: str) -> None:
    """텍스트를 파싱해 적절한 핸들러로 분기한다(응답은 각 핸들러가 발송)."""
    command, argument = _parse(text)
    if command in ("/review", ""):  # "/review" 또는 명령어 없음(기본=리뷰)
        _handle_review(argument, chat_id)
    else:  # "/start"·"/help"·빈 입력·미인식 명령어
        _handle_help(chat_id)


def _parse(text: str) -> tuple[str, str]:
    """텍스트를 (command, argument)로 분해한다.

    - 빈 입력 → ("/help", "")
    - "/review·/help·/start <인자>" → (명령어, 인자)
    - 미인식 명령어(`/foo`) → ("/help", "")
    - 명령어 없는 텍스트 → ("", 전체 텍스트)  # 기본=리뷰
    """
    stripped = (text or "").strip()
    if not stripped:
        return "/help", ""
    if stripped.startswith("/"):
        parts = stripped.split(maxsplit=1)
        command = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""
        if command in ("/review", "/help", "/start"):
            return command, argument
        return "/help", ""  # 미인식 명령어 → 안내
    return "", stripped


def _escape(text: str) -> str:
    """안내 문구 MarkdownV2 이스케이프."""
    return review_formatter.escape_markdownv2(text)


def _place_key(place: str) -> str:
    """캐시 PK·로그용 정규화 키(원문 대신 사용 — PII 최소화)."""
    normalized = place.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _handle_review(place: str, chat_id: str) -> None:
    """장소명/URL → (캐시 or 수집) → 요약 → 응답."""
    if not place.strip():
        telegram_sender.send_reply(chat_id, _escape(_EMPTY_QUERY_MESSAGE))
        return

    place_key = _place_key(place)
    try:
        # 1) 캐시 우선 조회(비크리티컬 — 미스/실패면 수집)
        cached = dynamo_writer.get_cached_review(place_key)
        if cached and cached.get("reviews"):
            message = review_formatter.build_review_report(
                place, cached.get("summary") or None, cached["reviews"]
            )
            telegram_sender.send_reply(chat_id, message)
            return

        # 2) 수집 → 요약
        reviews = naver_review_collector.fetch_reviews(place)
        if not reviews:
            telegram_sender.send_reply(chat_id, _escape(_NO_REVIEW_MESSAGE))
            return
        summary = review_analyst.summarize_reviews(place, reviews)

        # 3) 캐시 저장(비크리티컬) → 응답
        dynamo_writer.put_cached_review(place_key, summary, reviews)
        message = review_formatter.build_review_report(place, summary, reviews)
        telegram_sender.send_reply(chat_id, message)
    except Exception as error:  # noqa: BLE001 (온디맨드 — 사용자 안내 후 종료)
        # 사용자 원문(PII 가능) 대신 정규화 키만 로깅
        logger.error("리뷰 조회 실패(place_key=%s): %s", place_key, error)
        telegram_sender.send_reply(chat_id, _escape(_ERROR_MESSAGE))


def _handle_help(chat_id: str) -> None:
    telegram_sender.send_reply(chat_id, _escape(_HELP_MESSAGE))
