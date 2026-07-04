"""메시지 파싱·액션 결정 (순수 로직 모듈).

webhook_handler가 검증을 마친 메시지 텍스트를 받아 어떤 액션을 수행할지 결정한다.
발송이나 외부 호출은 하지 않는다 — 순수하게 텍스트 → 액션 dict 변환만 담당한다.

액션 종류:
  - analyze: 네이버 지도 공유 URL(naver.me) 포함 → 리뷰 분석 요청
  - update:  `/update` 명령 → 직전 조회 음식점 재분석 요청
  - help:    `/start`·`/help`·그 외 → 사용법 안내
"""

import re

# 네이버 지도 단축 URL(naver.me) 추출 정규식
_NAVER_URL_PATTERN = re.compile(r"https?://naver\.me/\S+")

# 도움말 안내 메시지 (원문 — 발송 직전 review_formatter로 이스케이프한다)
HELP_MESSAGE: str = (
    "📌 네이버 지도 리뷰 요약 봇 사용법\n"
    "\n"
    "• 네이버 지도 앱에서 음식점을 '공유'해 여기로 붙여넣어 주세요.\n"
    "  (예: 공유 텍스트에 https://naver.me/... 링크가 포함됩니다)\n"
    "• /update → 직전에 조회한 음식점을 최신 리뷰로 다시 분석\n"
    "• /help → 이 안내"
)


def parse_message(text: str) -> dict:
    """메시지 텍스트를 파싱해 액션 dict로 변환한다.

    Args:
        text: 사용자가 보낸 메시지 원문(빈 문자열/None 허용).

    Returns:
        아래 셋 중 하나의 dict:
          - {"action": "analyze", "naver_url": str, "shared_place_name": str | None}
          - {"action": "update"}
          - {"action": "help"}
    """
    stripped = (text or "").strip()

    # 1) 네이버 지도 공유 URL 포함 → 분석 요청
    url_match = _NAVER_URL_PATTERN.search(stripped)
    if url_match:
        return {
            "action": "analyze",
            "naver_url": url_match.group(0),
            "shared_place_name": _extract_place_name(stripped),
        }

    # 2) /update 명령 → 직전 음식점 재분석
    if stripped.lower().startswith("/update"):
        return {"action": "update"}

    # 3) /start·/help·그 외 → 사용법 안내
    return {"action": "help"}


def _extract_place_name(text: str) -> str | None:
    """네이버 지도 공유 텍스트에서 장소명을 추출한다(표시용, 신뢰 원천 아님).

    공유 형식은 아래와 같은 여러 줄 구조다:
        [네이버지도]
        돈멜 본점            <- 장소명(둘째 줄)
        경기 성남시 분당구 ...  <- 주소
        https://naver.me/... <- URL

    첫 줄이 '[네이버지도]' 계열 머리글이면 그다음 비어 있지 않은 줄을 장소명으로 본다.
    형식이 다르면 추출을 포기하고 None을 반환한다(스크래핑 결과가 신뢰 원천).
    """
    lines = [line.strip() for line in (text or "").splitlines()]
    non_empty_lines = [line for line in lines if line]

    if not non_empty_lines:
        return None

    first_line = non_empty_lines[0]
    # '[네이버지도]' 또는 '[네이버 지도]' 형태의 머리글인지 확인
    if first_line.startswith("[") and "네이버" in first_line and "지도" in first_line:
        for line in non_empty_lines[1:]:
            # URL 줄은 장소명이 아니므로 건너뛴다
            if _NAVER_URL_PATTERN.search(line):
                continue
            return line
        return None

    return None
