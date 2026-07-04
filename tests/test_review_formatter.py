"""review_formatter MarkdownV2 이스케이프 단위 테스트."""

import review_formatter


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
