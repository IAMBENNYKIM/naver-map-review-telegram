"""telegram_sender 메시지 절단 단위 테스트 (네트워크 없음)."""

import telegram_sender


class TestTruncateMessage:
    def test_한도_이하는_그대로_반환한다(self):
        text = "짧은 메시지"

        assert telegram_sender._truncate_message(text) == text

    def test_한도_초과면_4096자_이내로_절단하고_안내_꼬리를_붙인다(self):
        text = "가" * 5000

        truncated = telegram_sender._truncate_message(text)

        assert len(truncated) <= telegram_sender.TELEGRAM_MESSAGE_LIMIT
        assert truncated.endswith(telegram_sender._TRUNCATION_SUFFIX)

    def test_절단_지점의_이스케이프_시퀀스가_반토막나지_않는다(self):
        # 허용 길이 경계 직전까지 채우고 경계에 "\\." 이스케이프가 걸리게 구성
        allowed_length = telegram_sender.TELEGRAM_MESSAGE_LIMIT - len(
            telegram_sender._TRUNCATION_SUFFIX
        )
        # allowed_length-1 위치에 백슬래시 → 절단 시 홀수 백슬래시로 끝나는 상황
        text = "a" * (allowed_length - 1) + "\\." * 100

        truncated = telegram_sender._truncate_message(text)

        assert len(truncated) <= telegram_sender.TELEGRAM_MESSAGE_LIMIT
        # 꼬리 제거 후 끝의 백슬래시 개수가 짝수(온전한 이스케이프)여야 한다
        body = truncated[: -len(telegram_sender._TRUNCATION_SUFFIX)]
        trailing_backslashes = len(body) - len(body.rstrip("\\"))
        assert trailing_backslashes % 2 == 0
