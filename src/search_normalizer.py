"""자연어 검색 프롬프트 → 네이버 지도 검색어 정규화 (Claude LLM, 웹 진입점 전용).

instant-search는 autocomplete 성격이라 "지역+업종" 또는 "상호명"은 잘 소화하나
"데이트" 같은 상황어가 섞인 자연어 다중개념 질의는 빈 결과를 준다(findings.md §6-3).
그래서 자연어 프롬프트를 검색 가능한 형태로 축약하는 전처리가 필요하다.

LLM 호출은 **개선 수단이지 필수 경로가 아니다** — 킬 스위치 off·키 미설정·호출 실패·
빈 응답·과도하게 긴 응답 등 어떤 실패에도 원문 ``prompt.strip()`` 을 반환한다.
review_analyst.py의 lazy import·전체 예외 흡수 패턴을 따른다.
"""

import logging

import config

logger = logging.getLogger(__name__)

# 정규화 결과 최대 길이 — 이보다 길면 LLM이 검색어가 아닌 설명을 뱉은 것으로 보고 원문 반환.
_MAX_KEYWORD_LENGTH = 40

# 검색어 정규화 프롬프트 — "지역+업종" 또는 "상호명" 한 줄만 출력하도록 강제한다.
# 조정은 이 상수만 수정한다.
_SYSTEM_PROMPT = (
    "너는 네이버 지도 검색어 변환기다. 사용자의 자연어 요청을 네이버 지도에서 검색 가능한 "
    "검색어로 변환하라. '지역+업종'(예: '강남 양식') 또는 '상호명'(예: '스타벅스') 형태의 "
    "한 줄만 출력한다. 설명·따옴표·문장부호를 붙이지 말고 검색어만 출력하라.\n"
    "예시:\n"
    "- '강남에서 데이트하기 좋은 양식집' -> '강남 양식'\n"
    "- '판교 근처 조용한 카페 추천해줘' -> '판교 카페'"
)


def normalize_search_query(prompt: str) -> str:
    """자연어 프롬프트를 네이버 검색어로 정규화한다.

    Args:
        prompt: 사용자가 입력한 자연어 검색 프롬프트.

    Returns:
        정규화된 검색어. LLM이 유효한 결과를 주지 못하면 원문 ``prompt.strip()``.
    """
    fallback = prompt.strip()

    if not config.SEARCH_LLM_ENABLED:
        logger.info("SEARCH_LLM_ENABLED=False — 검색어 정규화 생략(원문 사용)")
        return fallback
    if not config.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY 미설정 — 검색어 정규화 생략(원문 사용)")
        return fallback
    if not fallback:
        return fallback

    try:
        keyword = _call_claude(fallback)
    except Exception as error:  # noqa: BLE001 (non-critical — 원문 폴백)
        logger.warning("검색어 정규화 호출 실패(원문 사용): %s", error)
        return fallback

    # 빈 응답·과도하게 긴 응답이면 원문을 신뢰한다.
    if not keyword or len(keyword) > _MAX_KEYWORD_LENGTH:
        logger.warning("검색어 정규화 결과가 유효하지 않음(원문 사용)")
        return fallback
    return keyword


def _call_claude(prompt: str) -> str:
    """anthropic SDK로 검색어 정규화를 수행한다(lazy import — config 패턴)."""
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.SEARCH_LLM_MODEL,
        max_tokens=config.SEARCH_LLM_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    # content 블록에서 텍스트만 이어붙인다.
    return "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    ).strip()
