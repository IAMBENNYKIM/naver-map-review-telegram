"""리뷰 요약 생성 (Claude LLM, 공유 모듈).

수집한 리뷰 리스트를 Claude로 초보 친화 요약한다. LLM 호출은 non-critical —
실패하거나 킬 스위치(LLM_COMMENTARY_ENABLED=False)면 None을 반환하고, 호출자
(command_router)가 요약 없이 원문 리뷰만 발송하도록 폴백한다.
"""

import logging

import config

logger = logging.getLogger(__name__)

# 요약 프롬프트 — 초보 친화·객관적 톤. 상세 조정은 이 상수만 수정한다.
_SYSTEM_PROMPT = (
    "너는 네이버 지도 리뷰를 요약하는 도우미다. 주어진 리뷰들을 바탕으로 이 장소의 "
    "장점·단점·방문 팁을 3~5줄로 객관적으로 요약해라. 과장 없이, 여러 리뷰에서 반복되는 "
    "내용 위주로. 마크다운 특수문자·이모지 남용은 피하고 담백한 한국어 평문으로 작성해라."
)


def summarize_reviews(place_name: str, reviews: list[dict]) -> str | None:
    """리뷰 리스트를 Claude로 요약한다.

    Args:
        place_name: 장소명(프롬프트 맥락).
        reviews: naver_review_collector.fetch_reviews 반환값.

    Returns:
        요약 문자열. 킬 스위치·키 미설정·리뷰 없음·호출 실패 시 None(호출자가 폴백).
    """
    if not config.LLM_COMMENTARY_ENABLED:
        logger.info("LLM_COMMENTARY_ENABLED=False — 리뷰 요약 생략")
        return None
    if not config.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY 미설정 — 리뷰 요약 생략")
        return None
    if not reviews:
        return None

    try:
        return _call_claude(place_name, reviews)
    except Exception as error:  # noqa: BLE001 (non-critical — 원문 폴백)
        logger.warning("리뷰 요약 실패(원문 폴백): %s", error)
        return None


def _call_claude(place_name: str, reviews: list[dict]) -> str:
    """anthropic SDK로 요약을 생성한다(lazy import — config 패턴)."""
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    review_lines = "\n".join(
        f"- {str(review.get('text', '')).strip()}" for review in reviews if review.get("text")
    )
    user_content = f"장소: {place_name}\n\n리뷰 목록:\n{review_lines}"

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.LLM_MAX_OUTPUT_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    # content 블록에서 텍스트만 이어붙인다.
    return "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    ).strip()
