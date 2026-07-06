"""리뷰 분석 (Claude LLM, 공유 모듈).

수집한 장소 상세·리뷰 리스트를 Claude 1회 호출로 분석해 PRD §4 JSON 계약 문자열을
반환한다. LLM 호출은 **non-critical** — 킬 스위치·키 미설정·리뷰 없음·호출 실패·
파싱 실패 전부 None을 반환하고, 호출자(worker_handler)가 폴백 응답을 발송한다.
"""

import json
import logging

import config

logger = logging.getLogger(__name__)

# sentiment 허용값 (PRD §4)
_VALID_SENTIMENTS = ("추천", "비추천", "호불호")

# 분석 결과 필수 키 (PRD §4 — caution은 null 허용이나 키 자체는 존재해야 함)
_REQUIRED_KEYS = ("overall", "pros", "cons", "menus", "caution")

# 분석 프롬프트 — JSON 강제·객관 요약. 조정은 이 상수만 수정한다.
_SYSTEM_PROMPT = (
    "너는 네이버 지도 음식점 리뷰 분석 도우미다. 주어진 장소 정보·메뉴 언급 통계·"
    "방문자 리뷰를 분석해 아래 JSON 스키마로만 응답하라. 코드펜스(```)나 설명 문장 등 "
    "JSON 외의 출력을 절대 포함하지 마라.\n"
    "\n"
    '{"overall": "총평 2~3문장", "pros": ["장점 불릿"], "cons": ["단점 불릿"], '
    '"menus": [{"name": "메뉴명", "sentiment": "추천", "mentions": 23, '
    '"note": "한 줄 근거"}], "caution": "주의사항 또는 null"}\n'
    "\n"
    "규칙:\n"
    "- 여러 리뷰에서 반복 언급되는 내용 위주로, 과장 없이 객관적으로 요약한다.\n"
    "- menus는 언급 2회 이상인 메뉴만, 최대 8개, mentions 내림차순으로 정렬한다.\n"
    '- sentiment는 반드시 "추천"/"비추천"/"호불호" 중 하나만 사용한다.\n'
    "- pros/cons는 각각 2~4개 불릿로 작성한다.\n"
    "- caution은 여러 리뷰에서 반복되는 주의사항(웨이팅 등)이 있을 때만 쓰고, 없으면 null."
)


def analyze_reviews(place_detail: dict, review_list: list[dict]) -> str | None:
    """장소 상세·리뷰 리스트를 Claude로 분석해 PRD §4 JSON 문자열을 반환한다.

    Args:
        place_detail: naver_review_collector.fetch_place_detail 반환값.
        review_list: naver_review_collector.fetch_reviews 반환값.

    Returns:
        정규화 재직렬화된 JSON 문자열 (캐시 저장 원문).
        킬 스위치·키 미설정·리뷰 없음·호출/파싱/검증 실패 시 None (호출자가 폴백).
    """
    if not config.LLM_COMMENTARY_ENABLED:
        logger.info("LLM_COMMENTARY_ENABLED=False — 리뷰 분석 생략")
        return None
    if not config.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY 미설정 — 리뷰 분석 생략")
        return None
    if not review_list:
        logger.info("리뷰가 없어 분석을 생략합니다")
        return None

    try:
        raw_response_text = _call_claude(place_detail, review_list)
    except Exception as error:  # noqa: BLE001 (non-critical — 폴백)
        logger.warning("Claude 분석 호출 실패(폴백): %s", error)
        return None

    summary = _parse_and_validate(raw_response_text)
    if summary is None:
        return None
    # 정규화된 JSON 재직렬화 — 캐시에 저장할 원문
    return json.dumps(summary, ensure_ascii=False)


def _call_claude(place_detail: dict, review_list: list[dict]) -> str:
    """anthropic SDK로 분석을 생성한다(lazy import — config 패턴)."""
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.LLM_MAX_OUTPUT_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_content(place_detail, review_list)}],
    )
    # content 블록에서 텍스트만 이어붙인다.
    return "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    ).strip()


def _build_user_content(place_detail: dict, review_list: list[dict]) -> str:
    """장소 정보·메뉴 통계·리뷰 목록을 분석용 사용자 메시지로 조립한다."""
    lines: list[str] = []

    place_name = place_detail.get("name") or "이름 미상"
    header = f"장소: {place_name}"
    avg_rating = place_detail.get("avg_rating")
    total_reviews = place_detail.get("total_reviews")
    if avg_rating is not None:
        header += f" (평균 별점 {avg_rating}"
        if total_reviews is not None:
            header += f", 리뷰 총 {total_reviews}개"
        header += ")"
    lines.append(header)

    menu_stats = place_detail.get("menu_stats") or []
    if menu_stats:
        stats_text = ", ".join(
            f"{menu.get('label')} {menu.get('count')}회" for menu in menu_stats
        )
        lines.append(
            "메뉴 언급 통계(장소 레벨 — 메뉴 추천도 판단의 보조 근거로 사용): "
            + stats_text
        )

    lines.append("")
    lines.append(f"방문자 리뷰 목록 ({len(review_list)}건):")
    for review in review_list:
        review_line = f"- {review.get('text', '').strip()}"
        keywords = review.get("keywords") or []
        if keywords:
            review_line += f" [태그: {', '.join(keywords)}]"
        lines.append(review_line)

    return "\n".join(lines)


def _parse_and_validate(raw_text: str) -> dict | None:
    """응답 텍스트를 파싱·검증한다. 실패 시 None (사유는 로깅)."""
    cleaned_text = _strip_code_fence(raw_text)
    try:
        summary = json.loads(cleaned_text)
    except json.JSONDecodeError as error:
        logger.warning("분석 응답 JSON 파싱 실패(폴백): %s", error)
        return None

    if not isinstance(summary, dict):
        logger.warning("분석 응답이 JSON 객체가 아님(폴백)")
        return None

    missing_keys = [key for key in _REQUIRED_KEYS if key not in summary]
    if missing_keys:
        logger.warning("분석 응답 필수 키 누락(폴백): %s", missing_keys)
        return None

    if not isinstance(summary.get("pros"), list) or not isinstance(
        summary.get("cons"), list
    ):
        logger.warning("분석 응답 pros/cons 타입 오류(폴백)")
        return None

    menus = summary.get("menus")
    if not isinstance(menus, list):
        logger.warning("분석 응답 menus 타입 오류(폴백)")
        return None
    for menu in menus:
        if not isinstance(menu, dict) or not menu.get("name"):
            logger.warning("분석 응답 menus 항목 구조 오류(폴백)")
            return None
        if menu.get("sentiment") not in _VALID_SENTIMENTS:
            logger.warning(
                "분석 응답 sentiment 이상값(폴백): %r", menu.get("sentiment")
            )
            return None

    return summary


def _strip_code_fence(text: str) -> str:
    """모델이 규칙을 어기고 코드펜스로 감쌌을 때 방어적으로 제거한다."""
    stripped = (text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    # 첫 줄(``` 또는 ```json) 제거
    lines = lines[1:]
    # 마지막 ``` 줄 제거
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
