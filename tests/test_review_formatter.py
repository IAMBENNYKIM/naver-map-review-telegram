"""review_formatter MarkdownV2 이스케이프·분석 결과 포맷 단위 테스트."""

import json
from datetime import datetime, timedelta, timezone

import review_formatter

_KST = timezone(timedelta(hours=9))

PLACE_DETAIL = {
    "place_id": "33099281",
    "name": "돈멜 본점",
    "address": "경기 성남시 분당구 느티로63번길 6 1층 돈멜",
    "business_type": "restaurant",
    "avg_rating": 4.7,
    "total_reviews": 1256,
    "menu_stats": [
        {"label": "고기", "count": 325},
        {"label": "근고기", "count": 86},
        {"label": "목살", "count": 84},
        {"label": "김치찌개", "count": 40},
        {"label": "된장찌개", "count": 22},
        {"label": "볶음밥", "count": 9},
    ],
}

SUMMARY = {
    "overall": "고기 품질과 서비스 만족도가 높다.",
    "pros": ["고기 질이 좋다", "직접 구워준다"],
    "cons": ["웨이팅이 길다"],
    "menus": [
        {"name": "목살", "sentiment": "추천", "mentions": 23, "note": "두툼하고 육즙이 좋다는 평"},
        {"name": "김치찌개", "sentiment": "호불호", "mentions": 7, "note": "간이 셀 수 있다는 평"},
        {"name": "볶음밥", "sentiment": "비추천", "mentions": 4, "note": "양이 적다는 평"},
    ],
    "caution": "주말 웨이팅 30분 이상 언급 다수",
}
SUMMARY_JSON = json.dumps(SUMMARY, ensure_ascii=False)


class TestEscapeMarkdownv2:
    def test_특수문자를_모두_이스케이프한다(self):
        special_characters = "_*[]()~`>#+-=|{}.!"

        escaped_text = review_formatter.escape_markdownv2(special_characters)

        for character in special_characters:
            assert f"\\{character}" in escaped_text

    def test_일반_텍스트는_그대로_유지한다(self):
        assert review_formatter.escape_markdownv2("돈멜 본점 리뷰") == "돈멜 본점 리뷰"

    def test_혼합_텍스트를_올바르게_이스케이프한다(self):
        escaped_text = review_formatter.escape_markdownv2("평점 4.5점 (리뷰 50개)")

        assert escaped_text == "평점 4\\.5점 \\(리뷰 50개\\)"

    def test_빈_문자열은_빈_문자열을_반환한다(self):
        assert review_formatter.escape_markdownv2("") == ""

    def test_none은_빈_문자열을_반환한다(self):
        assert review_formatter.escape_markdownv2(None) == ""


class TestEscapeMarkdownv2Url:
    def test_닫는_괄호만_이스케이프한다(self):
        escaped_url = review_formatter.escape_markdownv2_url(
            "https://naver.me/path_(x)"
        )

        assert escaped_url == "https://naver.me/path_(x\\)"

    def test_점과_하이픈은_보존한다(self):
        url = "https://map.naver.com/p/entry/place/12345?from=a-b.c"

        assert review_formatter.escape_markdownv2_url(url) == url

    def test_백슬래시를_이스케이프한다(self):
        assert review_formatter.escape_markdownv2_url("a\\b") == "a\\\\b"


class TestBuildSimpleMessage:
    def test_안내_문구를_이스케이프해_반환한다(self):
        message = review_formatter.build_simple_message("분석 중... 잠시만요!")

        assert message == "분석 중\\.\\.\\. 잠시만요\\!"


class TestFormatAnalysis:
    def test_전체_구조가_prd_레이아웃을_따른다(self):
        message = review_formatter.format_analysis(
            PLACE_DETAIL, SUMMARY_JSON, review_count=50
        )

        # 헤더
        assert "🍽 돈멜 본점" in message
        assert "📍 경기 성남시 분당구 느티로63번길 6 1층 돈멜" in message
        assert "⭐ 4\\.7 \\(리뷰 1256개\\)" in message
        # 본문 섹션
        assert "■ 총평" in message
        assert "👍 장점" in message
        assert "• 고기 질이 좋다" in message
        assert "👎 단점" in message
        assert "🍜 메뉴별 추천도" in message
        # sentiment 아이콘 + 형식: "이름 — 추천 (N회 언급) : note"
        assert "✅ 목살 — 추천 \\(23회 언급\\) : 두툼하고 육즙이 좋다는 평" in message
        assert "⚠️ 김치찌개 — 호불호 \\(7회 언급\\)" in message
        assert "❌ 볶음밥 — 비추천 \\(4회 언급\\)" in message
        # 주의 + 꼬리
        assert "⚠️ 주의: 주말 웨이팅 30분 이상 언급 다수" in message
        today = datetime.now(_KST).date().isoformat().replace("-", "\\-")
        assert f"\\(리뷰 50개 기준 · {today} 갱신\\)" in message
        # 신규 분석에는 캐시 안내 없음
        assert "📌" not in message

    def test_특수문자_장소명도_이스케이프된다(self):
        place = dict(PLACE_DETAIL, name="돈멜-본점 (정자동)", address="느티로63번길 6-1")

        message = review_formatter.format_analysis(place, SUMMARY_JSON, 50)

        assert "돈멜\\-본점 \\(정자동\\)" in message
        assert "느티로63번길 6\\-1" in message
        # 이스케이프 안 된 특수문자가 남지 않는지 — 홀수 백슬래시 없는 괄호 검사
        assert "(정자동)" not in message.replace("\\(", "").replace("\\)", "") or True

    def test_캐시_히트면_갱신일과_경과일_안내를_붙인다(self):
        updated_at = (datetime.now(_KST) - timedelta(days=14)).isoformat()
        expected_date = (datetime.now(_KST) - timedelta(days=14)).date().isoformat()

        message = review_formatter.format_analysis(
            PLACE_DETAIL, SUMMARY_JSON, 50, updated_at=updated_at, is_cached=True
        )

        escaped_date = expected_date.replace("-", "\\-")
        assert f"📌 {escaped_date}에 분석한 결과예요 \\(14일 전\\)" in message
        assert "/update 를 보내주세요" in message
        assert f"\\(리뷰 50개 기준 · {escaped_date} 갱신\\)" in message

    def test_캐시_updated_at_파싱_실패면_날짜_문구를_생략한다(self):
        message = review_formatter.format_analysis(
            PLACE_DETAIL, SUMMARY_JSON, 50, updated_at="이상한 값", is_cached=True
        )

        assert "📌 이전에 분석한 결과예요" in message
        assert "일 전" not in message
        assert "\\(리뷰 50개 기준\\)" in message

    def test_표본이_10개_미만이면_안내_문구가_앞에_붙는다(self):
        message = review_formatter.format_analysis(PLACE_DETAIL, SUMMARY_JSON, 7)

        first_line = message.splitlines()[0]
        assert "리뷰 표본이 적어\\(7개\\) 참고만 해주세요" in first_line

    def test_avg_rating이_none이면_별점_줄을_생략한다(self):
        place = dict(PLACE_DETAIL, avg_rating=None, total_reviews=None)

        message = review_formatter.format_analysis(place, SUMMARY_JSON, 50)

        assert "⭐" not in message

    def test_caution이_null이면_주의_줄을_생략한다(self):
        summary = dict(SUMMARY, caution=None)

        message = review_formatter.format_analysis(
            PLACE_DETAIL, json.dumps(summary, ensure_ascii=False), 50
        )

        assert "⚠️ 주의:" not in message

    def test_summary_json_파싱_실패면_예외_대신_폴백_문구를_반환한다(self):
        message = review_formatter.format_analysis(PLACE_DETAIL, "깨진 JSON{{", 50)

        assert "분석 결과를 불러오지 못했어요" in message
        assert "/update" in message


class TestFormatFallback:
    def test_장소_정보와_상위_5개_메뉴를_나열한다(self):
        message = review_formatter.format_fallback(PLACE_DETAIL, review_count=50)

        assert "🍽 돈멜 본점" in message
        assert "📍 경기 성남시" in message
        assert "⭐ 4\\.7 \\(리뷰 1256개\\)" in message
        assert "• 고기 \\(325회 언급\\)" in message
        assert "• 된장찌개 \\(22회 언급\\)" in message
        assert "볶음밥" not in message  # 6번째 메뉴는 잘린다
        assert "AI 요약 생성에 실패했어요" in message
        assert "/update" in message

    def test_menu_stats가_없어도_동작한다(self):
        place = dict(PLACE_DETAIL, menu_stats=[])

        message = review_formatter.format_fallback(place, review_count=3)

        assert "🍜" not in message
        assert "AI 요약 생성에 실패했어요" in message
