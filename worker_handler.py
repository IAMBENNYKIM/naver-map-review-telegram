"""WorkerFunction Lambda 핸들러 (진입점).

WebhookFunction이 비동기 invoke한 이벤트를 받아 무거운 파이프라인을 오케스트레이션한다:
  place 해석 → 캐시 조회 → (미스/update 시) 수집 → 분석 → 포맷 → 발송 → 캐시 저장

이벤트 계약(PRD §6): {"chat_id": int|str, "action": "analyze"|"update",
                     "naver_url": str|null, "shared_place_name": str|null}

collector/analyst 미구현 구간(NotImplementedError)은 사용자에게 "준비 중" 안내를 보내고
개발자 알림을 발송한다. 전체 예외도 잡아 사용자 실패 안내 + 개발자 알림 후
Lambda 자체는 정상 종료한다(재시도 폭주 방지).
"""

import asyncio
import logging

import config
import dynamo_writer
import naver_review_collector
import review_formatter
import telegram_sender

logger = logging.getLogger(__name__)

# 사용자 안내 문구(원문 — 발송 직전 이스케이프)
_NOT_READY_MESSAGE = "아직 준비 중인 기능이에요. 조금만 기다려 주세요!"
_FAILURE_MESSAGE = "죄송해요, 분석 중 문제가 발생했어요. 잠시 후 다시 시도해 주세요."
_NO_LAST_PLACE_MESSAGE = "먼저 음식점 URL을 보내주세요. 그 후 /update 로 재분석할 수 있어요."


def lambda_handler(event, context):
    """WorkerFunction 진입점(동기 래퍼). asyncio.run으로 실행."""
    return asyncio.run(_async_main(event, context))


async def _async_main(event, context) -> dict:
    """이벤트 계약 파싱 후 파이프라인 실행. 예외는 흡수해 정상 종료한다."""
    chat_id = str(event.get("chat_id", ""))
    action = event.get("action", "")
    naver_url = event.get("naver_url")
    shared_place_name = event.get("shared_place_name")

    if not chat_id or action not in ("analyze", "update"):
        logger.error("잘못된 Worker 이벤트 — 무시 (action=%s)", action)
        return {"statusCode": 200, "body": "invalid event ignored"}

    try:
        _run_pipeline(chat_id, action, naver_url, shared_place_name)
    except NotImplementedError as error:
        # Phase 1(수집)·Phase 2(분석) 미구현 구간 — 사용자 안내 + 개발자 알림
        logger.warning("미구현 기능 호출 (action=%s): %s", action, error)
        telegram_sender.send_reply(
            chat_id, review_formatter.build_simple_message(_NOT_READY_MESSAGE)
        )
        telegram_sender.send_error_alert(f"미구현 기능 호출 (action={action}): {error}")
    except Exception as error:  # noqa: BLE001 — 전체 예외 흡수(사용자 안내 후 정상 종료)
        logger.error("Worker 파이프라인 실패 (action=%s): %s", action, error)
        telegram_sender.send_reply(
            chat_id, review_formatter.build_simple_message(_FAILURE_MESSAGE)
        )
        telegram_sender.send_error_alert(f"Worker 파이프라인 실패 (action={action}): {error}")

    return {"statusCode": 200, "body": "ok"}


def _run_pipeline(
    chat_id: str,
    action: str,
    naver_url: str | None,
    shared_place_name: str | None,
) -> None:
    """수집→분석→발송 파이프라인 본체. 미구현 구간은 NotImplementedError가 전파된다.

    shared_place_name은 표시 보조용으로만 전달받는다 — 신뢰 원천은 스크래핑 결과(F1).
    """
    # 1) place 해석 — analyze는 URL로, update는 직전 조회 기록으로
    if action == "update":
        place_id = dynamo_writer.get_last_place_id(chat_id)
        if not place_id:
            telegram_sender.send_reply(
                chat_id, review_formatter.build_simple_message(_NO_LAST_PLACE_MESSAGE)
            )
            return
    else:
        place_id = naver_review_collector.resolve_place(naver_url or "")["place_id"]

        # 2) 캐시 조회 — analyze일 때만 사용(update는 캐시 무시하고 재수집)
        cached_item = dynamo_writer.get_cached_summary(place_id)
        if cached_item:
            _send_cached_summary(chat_id, cached_item)
            dynamo_writer.save_last_place_id(chat_id, place_id)
            return

    # 3) 장소 상세 + 리뷰 수집 (business_type은 상세 조회 결과에서 확보)
    place_detail = naver_review_collector.fetch_place_detail(place_id)
    review_list = naver_review_collector.fetch_reviews(
        place_id, place_detail["business_type"], config.REVIEW_FETCH_LIMIT
    )

    # 4) Claude 분석 (Phase 2에서 구현 — review_analyst 모듈 예정)
    summary_json = _analyze_reviews(place_detail, review_list)

    # 5) 포맷 → 발송 (분석 결과 포맷 함수는 Phase 2에서 구현)
    message = _format_summary(place_detail, summary_json)
    telegram_sender.send_reply(chat_id, message)

    # 6) 캐시 저장 (non-critical — 실패해도 이미 발송 완료)
    dynamo_writer.save_summary(
        place_id=place_id,
        place_name=place_detail["name"],
        address=place_detail["address"],
        summary_json=summary_json,
        review_count=len(review_list),
    )
    dynamo_writer.save_last_place_id(chat_id, place_id)


def _send_cached_summary(chat_id: str, cached_item: dict) -> None:
    """캐시 히트 시 저장된 요약 + 갱신 시점 + /update 안내를 발송한다.

    저장 요약의 MarkdownV2 재구성은 Phase 2(포맷 함수 구현)에서 완성한다.
    """
    raise NotImplementedError(
        "캐시 요약 발송 미구현 — Phase 2에서 분석 결과 포맷 함수와 함께 구현한다."
    )


def _analyze_reviews(place_detail: dict, review_list: list[dict]) -> str:
    """장소 상세·리뷰 리스트를 Claude로 분석해 PRD §4 JSON 문자열을 반환한다.

    place_detail의 menu_stats는 F4 메뉴 추천도의 보조 근거로 사용한다.
    Phase 2에서 review_analyst 모듈로 구현한다.
    """
    raise NotImplementedError(
        "리뷰 분석 미구현 — Phase 2에서 review_analyst 모듈로 구현한다."
    )


def _format_summary(place_detail: dict, summary_json: str) -> str:
    """분석 결과 JSON을 MarkdownV2 응답 문자열로 변환한다.

    Phase 2에서 review_formatter의 분석 결과 포맷 함수로 구현한다.
    """
    raise NotImplementedError(
        "분석 결과 포맷 미구현 — Phase 2에서 review_formatter에 구현한다."
    )
