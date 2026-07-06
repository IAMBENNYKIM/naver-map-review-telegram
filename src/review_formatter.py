"""리뷰 응답 포맷 + MarkdownV2 이스케이프 헬퍼 (공유 모듈).

Telegram MarkdownV2로 발송하므로 모든 응답 문자열은 escape_markdownv2를 경유한다.
format_analysis / format_fallback은 메시지 전체를 평문으로 조립한 뒤 마지막에
한 번 이스케이프한다 — 동적 텍스트가 이스케이프를 우회할 경로가 없다.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# 한국 표준시(KST) — 캐시 갱신 시점 표기·경과일 계산에 사용
_KST = timezone(timedelta(hours=9))

# MarkdownV2에서 이스케이프가 필요한 특수문자 목록 (코드블록 바깥 영역에만 적용)
_MARKDOWNV2_ESCAPE_PATTERN = re.compile(r'([_\*\[\]\(\)~`>#+\-=|{}\.!])')

# MarkdownV2 인라인 링크 '(url)' 부분 전용 — '\'와 ')'만 이스케이프한다(나머지 보존).
_MARKDOWNV2_URL_ESCAPE_PATTERN = re.compile(r'([\\)])')

# sentiment → 아이콘 (PRD §1)
_SENTIMENT_ICONS = {"추천": "✅", "호불호": "⚠️", "비추천": "❌"}

# 표본 부족 기준 (PRD F2 — 10개 미만이면 안내 문구)
_SMALL_SAMPLE_THRESHOLD = 10

# summary_json 파싱 실패 시 폴백 문구
_BROKEN_SUMMARY_MESSAGE = "분석 결과를 불러오지 못했어요. /update 로 다시 분석해 주세요."


def escape_markdownv2(text: str) -> str:
    """MarkdownV2 특수문자를 백슬래시 이스케이프한다.

    코드블록(```) 바깥에서 사용한다. 코드블록 내부는 이스케이프가 불필요하다.
    """
    return _MARKDOWNV2_ESCAPE_PATTERN.sub(r'\\\1', text or "")


def escape_markdownv2_url(url: str) -> str:
    """MarkdownV2 인라인 링크 '(url)' 부분 전용 이스케이프.

    링크 텍스트와 달리 '.', '-', '=' 등은 그대로 둬야 URL이 유효하다.
    Telegram 명세상 '\\'와 ')'만 이스케이프하면 된다.
    """
    return _MARKDOWNV2_URL_ESCAPE_PATTERN.sub(r'\\\1', url or "")


def build_simple_message(text: str) -> str:
    """단순 텍스트를 MarkdownV2 응답 문자열로 변환한다(안내·상태 문구용)."""
    return escape_markdownv2(text)


def format_analysis(
    place_detail: dict,
    summary_json: str,
    review_count: int,
    updated_at: str | None = None,
    is_cached: bool = False,
) -> str:
    """분석 결과 JSON을 PRD §1 레이아웃의 MarkdownV2 메시지로 변환한다.

    Args:
        place_detail: 장소 상세 dict (캐시 재구성 시 avg_rating 등은 None 허용 — 생략 처리).
        summary_json: review_analyst가 반환한 PRD §4 JSON 문자열.
        review_count: 분석에 사용한 리뷰 수.
        updated_at: 분석 시점 ISO 8601 문자열 (None이면 현재 KST).
        is_cached: True면 캐시 안내 문구(📌 ... /update)를 덧붙인다.

    Returns:
        MarkdownV2 이스케이프가 적용된 응답 문자열.
        summary_json 파싱 실패 시 예외 대신 폴백 단순 메시지를 반환한다.
    """
    try:
        summary = json.loads(summary_json)
        if not isinstance(summary, dict):
            raise ValueError("분석 JSON이 객체가 아님")
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        logger.warning("summary_json 파싱 실패 — 폴백 메시지 반환: %s", error)
        return build_simple_message(_BROKEN_SUMMARY_MESSAGE)

    lines: list[str] = []

    # 표본 부족 안내 (10개 미만 — PRD F2)
    if review_count < _SMALL_SAMPLE_THRESHOLD:
        lines.append(f"⚠️ 리뷰 표본이 적어({review_count}개) 참고만 해주세요")
        lines.append("")

    lines.extend(_build_place_header(place_detail))
    lines.append("")

    overall = summary.get("overall")
    if overall:
        lines.append("■ 총평")
        lines.append(str(overall))
        lines.append("")

    pros = summary.get("pros") or []
    if pros:
        lines.append("👍 장점")
        lines.extend(f"• {item}" for item in pros)
        lines.append("")

    cons = summary.get("cons") or []
    if cons:
        lines.append("👎 단점")
        lines.extend(f"• {item}" for item in cons)
        lines.append("")

    menus = summary.get("menus") or []
    if menus:
        lines.append("🍜 메뉴별 추천도")
        for menu in menus:
            lines.append(_build_menu_line(menu))
        lines.append("")

    caution = summary.get("caution")
    if caution:
        lines.append(f"⚠️ 주의: {caution}")
        lines.append("")

    # 꼬리 + 캐시 안내
    updated_date, days_ago = _parse_updated_at(updated_at)
    if updated_date is None and not is_cached:
        updated_date = datetime.now(_KST).date()
        days_ago = 0

    if updated_date is not None:
        lines.append(f"(리뷰 {review_count}개 기준 · {updated_date.isoformat()} 갱신)")
    else:
        lines.append(f"(리뷰 {review_count}개 기준)")

    if is_cached:
        lines.append("")
        if updated_date is not None:
            lines.append(
                f"📌 {updated_date.isoformat()}에 분석한 결과예요 ({days_ago}일 전). "
                "최신 리뷰로 다시 분석하려면 /update 를 보내주세요."
            )
        else:
            # updated_at 파싱 실패 — 날짜 문구 생략
            lines.append(
                "📌 이전에 분석한 결과예요. "
                "최신 리뷰로 다시 분석하려면 /update 를 보내주세요."
            )

    return escape_markdownv2("\n".join(lines).rstrip())


def format_fallback(place_detail: dict, review_count: int) -> str:
    """분석(LLM) 실패 시 발송할 폴백 메시지 — 수집 성공 사실 + 장소 정보만 전달한다."""
    lines: list[str] = []
    lines.extend(_build_place_header(place_detail))

    menu_stats = place_detail.get("menu_stats") or []
    if menu_stats:
        lines.append("")
        lines.append("🍜 자주 언급된 메뉴")
        for menu in menu_stats[:5]:
            lines.append(f"• {menu.get('label')} ({menu.get('count')}회 언급)")

    lines.append("")
    lines.append(
        f"리뷰 {review_count}개는 수집했지만 AI 요약 생성에 실패했어요. "
        "/update 로 다시 시도할 수 있어요."
    )

    return escape_markdownv2("\n".join(lines).rstrip())


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _build_place_header(place_detail: dict) -> list[str]:
    """🍽 장소명 / 📍 주소 / ⭐ 별점 헤더 줄들을 생성한다 (없는 값은 생략)."""
    lines = [f"🍽 {place_detail.get('name') or '이름 미상'}"]

    address = place_detail.get("address")
    if address:
        lines.append(f"📍 {address}")

    avg_rating = place_detail.get("avg_rating")
    if avg_rating is not None:
        rating_line = f"⭐ {avg_rating}"
        total_reviews = place_detail.get("total_reviews")
        if total_reviews is not None:
            rating_line += f" (리뷰 {total_reviews}개)"
        lines.append(rating_line)

    return lines


def _build_menu_line(menu: dict) -> str:
    """메뉴 항목 한 줄: '✅ 이름 — 추천 (N회 언급) : note'."""
    icon = _SENTIMENT_ICONS.get(menu.get("sentiment"), "•")
    line = f"{icon} {menu.get('name', '?')} — {menu.get('sentiment', '')}"
    mentions = menu.get("mentions")
    if mentions is not None:
        line += f" ({mentions}회 언급)"
    note = menu.get("note")
    if note:
        line += f" : {note}"
    return line


def _parse_updated_at(updated_at: str | None):
    """updated_at ISO 문자열 → (KST 날짜, 경과일). 실패 시 (None, None)."""
    if not updated_at:
        return None, None
    try:
        parsed = datetime.fromisoformat(str(updated_at))
    except (ValueError, TypeError):
        logger.warning("updated_at 파싱 실패 — 날짜 문구 생략: %r", updated_at)
        return None, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_KST)
    parsed_kst = parsed.astimezone(_KST)
    days_ago = (datetime.now(_KST).date() - parsed_kst.date()).days
    return parsed_kst.date(), days_ago
