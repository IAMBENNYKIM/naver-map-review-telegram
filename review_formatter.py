"""리뷰 응답 포맷 + MarkdownV2 이스케이프 헬퍼 (공유 모듈).

Telegram MarkdownV2로 발송하므로 안내 문구·본문은 모두 escape_markdownv2로 이스케이프한다.
인라인 링크 '(url)' 부분만 escape_markdownv2_url로 별도 처리(URL이 깨지지 않도록).

분석 결과(PRD §4 JSON) → MarkdownV2 포맷 함수는 Phase 2에서 구현한다.
지금은 이스케이프 헬퍼 + 단순 텍스트 포맷만 제공한다.
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


def build_simple_message(text: str) -> str:
    """단순 텍스트를 MarkdownV2 응답 문자열로 변환한다(안내·상태 문구용).

    분석 결과 포맷은 Phase 2에서 별도 함수로 구현한다. 지금은 이스케이프만 적용한다.
    """
    return escape_markdownv2(text)
