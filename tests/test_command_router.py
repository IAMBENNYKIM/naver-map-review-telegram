"""command_router.parse_message 단위 테스트."""

import command_router

# PRD §1 예시 공유 텍스트
SHARED_TEXT = (
    "[네이버지도]\n"
    "돈멜 본점\n"
    "경기 성남시 분당구 느티로63번길 6 1층 돈멜\n"
    "https://naver.me/GB3423bX"
)


class TestParseMessageAnalyze:
    """네이버 URL 포함 메시지 → analyze 액션."""

    def test_공유_텍스트에서_url과_장소명을_추출한다(self):
        result = command_router.parse_message(SHARED_TEXT)

        assert result["action"] == "analyze"
        assert result["naver_url"] == "https://naver.me/GB3423bX"
        assert result["shared_place_name"] == "돈멜 본점"

    def test_url만_보내면_장소명은_none이다(self):
        result = command_router.parse_message("https://naver.me/GB3423bX")

        assert result["action"] == "analyze"
        assert result["naver_url"] == "https://naver.me/GB3423bX"
        assert result["shared_place_name"] is None

    def test_앞뒤_잡담이_있어도_url을_추출한다(self):
        result = command_router.parse_message(
            "여기 어때? https://naver.me/GB3423bX 가보자"
        )

        assert result["action"] == "analyze"
        assert result["naver_url"] == "https://naver.me/GB3423bX"

    def test_머리글_없는_형식이면_장소명_추출을_포기한다(self):
        result = command_router.parse_message(
            "돈멜 본점\nhttps://naver.me/GB3423bX"
        )

        assert result["action"] == "analyze"
        assert result["shared_place_name"] is None


class TestParseMessageUpdate:
    """/update 명령 → update 액션."""

    def test_update_명령을_인식한다(self):
        assert command_router.parse_message("/update") == {"action": "update"}

    def test_대소문자_무시하고_인식한다(self):
        assert command_router.parse_message("/UPDATE") == {"action": "update"}

    def test_공백이_있어도_인식한다(self):
        assert command_router.parse_message("  /update  ") == {"action": "update"}


class TestParseMessageHelp:
    """그 외 입력 → help 액션."""

    def test_start_명령은_help다(self):
        assert command_router.parse_message("/start") == {"action": "help"}

    def test_help_명령은_help다(self):
        assert command_router.parse_message("/help") == {"action": "help"}

    def test_url_없는_일반_텍스트는_help다(self):
        assert command_router.parse_message("안녕하세요") == {"action": "help"}

    def test_빈_입력은_help다(self):
        assert command_router.parse_message("") == {"action": "help"}

    def test_none_입력은_help다(self):
        assert command_router.parse_message(None) == {"action": "help"}

    def test_미인식_명령어는_help다(self):
        assert command_router.parse_message("/foo") == {"action": "help"}
