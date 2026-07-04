"""리뷰 응답 포맷 + MarkdownV2 이스케이프 헬퍼 (공유 모듈).

Telegram MarkdownV2로 발송하므로 안내 문구·본문은 모두 escape_markdownv2로 이스케이프한다.
인라인 링크 '(url)' 부분만 escape_markdownv2_url로 별도 처리(URL이 깨지지 않도록).
"""

import re

# MarkdownV2에서 이스케이프가 필요한 특수문자 목록 (코드블록 바깥 영역에만 적용)
_MARKDOWNV2_ESCAPE_PATTERN = re.compile(r'([_\*\[\]\(\)~`>#+\-=|{}\.!])')

# MarkdownV2 인라인 링크 '(url)' 부분 전용 — '\'와 ')'만 이스케이프한다(나머지 보존).
_MARKDOWNV2_URL_ESCAPE_PATTERN = re.compile(r'([\\)])')


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


def build_review_report(place_name: str, summary: str | None, reviews: list[dict]) -> str:
    """장소명·요약·리뷰 리스트를 Telegram MarkdownV2 응답 문자열로 변환한다.

    Args:
        place_name: 조회한 장소명.
        summary: review_analyst.summarize_reviews 결과(요약). None이면 요약 섹션 생략.
        reviews: naver_review_collector.fetch_reviews 반환값(dict 리스트).

    Returns:
        MarkdownV2 이스케이프가 적용된 응답 문자열.
    """
    lines = [f"📍 {escape_markdownv2(place_name)} 리뷰", ""]

    if summary:
        lines.append(escape_markdownv2(summary))
        lines.append("")

    lines.append(escape_markdownv2(f"— 최근 리뷰 {len(reviews)}건 —"))
    for review in reviews[:5]:  # 원문은 상위 5건만 노출(요약이 본체)
        rating = review.get("rating")
        rating_prefix = f"⭐{rating} " if rating else ""
        body = escape_markdownv2(str(review.get("text", "")).strip())
        lines.append(f"• {escape_markdownv2(rating_prefix)}{body}")

    return "\n".join(lines).rstrip()
