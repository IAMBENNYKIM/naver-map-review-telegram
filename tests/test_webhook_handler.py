"""webhook_handler.lambda_handler 단위 테스트 (외부 API 전부 mock)."""

import json
from unittest.mock import MagicMock, patch

import webhook_handler

# conftest.py가 주입한 테스트 값과 일치해야 한다
VALID_SECRET = "test-webhook-secret"
ALLOWED_CHAT_ID = 123456789


def build_event(
    text: str | None = "hello",
    chat_id: int | None = ALLOWED_CHAT_ID,
    secret: str | None = VALID_SECRET,
) -> dict:
    """API Gateway 형태의 Telegram webhook 이벤트를 생성한다."""
    headers = {}
    if secret is not None:
        headers["x-telegram-bot-api-secret-token"] = secret

    message: dict = {}
    if chat_id is not None:
        message["chat"] = {"id": chat_id}
    if text is not None:
        message["text"] = text

    return {"headers": headers, "body": json.dumps({"message": message})}


class TestSecretValidation:
    def test_secret_불일치면_403을_반환한다(self):
        event = build_event(secret="wrong-secret")

        result = webhook_handler.lambda_handler(event, None)

        assert result["statusCode"] == 403

    def test_secret_헤더가_없으면_403을_반환한다(self):
        event = build_event(secret=None)

        result = webhook_handler.lambda_handler(event, None)

        assert result["statusCode"] == 403


class TestChatIdAllowlist:
    def test_허용목록_외_chat_id는_무시하고_200을_반환한다(self):
        event = build_event(chat_id=555000555)

        with patch("telegram_sender.send_reply") as mock_send_reply, patch(
            "boto3.client"
        ) as mock_boto_client:
            result = webhook_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200
        mock_send_reply.assert_not_called()
        mock_boto_client.assert_not_called()

    def test_text_없는_update는_무시하고_200을_반환한다(self):
        event = build_event(text=None)

        result = webhook_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200


class TestWorkerInvoke:
    def test_analyze_요청이면_worker를_비동기_invoke하고_즉답을_보낸다(self):
        event = build_event(
            text=(
                "[네이버지도]\n"
                "돈멜 본점\n"
                "경기 성남시 분당구 느티로63번길 6 1층 돈멜\n"
                "https://naver.me/GB3423bX"
            )
        )

        mock_lambda_client = MagicMock()
        with patch(
            "boto3.client", return_value=mock_lambda_client
        ) as mock_boto_client, patch("telegram_sender.send_reply") as mock_send_reply:
            result = webhook_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200
        mock_boto_client.assert_called_once()

        mock_lambda_client.invoke.assert_called_once()
        invoke_kwargs = mock_lambda_client.invoke.call_args.kwargs
        assert invoke_kwargs["FunctionName"] == "test-worker-function"
        assert invoke_kwargs["InvocationType"] == "Event"

        payload = json.loads(invoke_kwargs["Payload"].decode("utf-8"))
        assert payload["chat_id"] == str(ALLOWED_CHAT_ID)
        assert payload["action"] == "analyze"
        assert payload["naver_url"] == "https://naver.me/GB3423bX"
        assert payload["shared_place_name"] == "돈멜 본점"

        # 즉답("분석 중") 발송 확인
        mock_send_reply.assert_called_once()
        assert mock_send_reply.call_args.args[0] == str(ALLOWED_CHAT_ID)

    def test_update_요청이면_worker를_invoke한다(self):
        event = build_event(text="/update")

        mock_lambda_client = MagicMock()
        with patch("boto3.client", return_value=mock_lambda_client), patch(
            "telegram_sender.send_reply"
        ):
            result = webhook_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200
        payload = json.loads(
            mock_lambda_client.invoke.call_args.kwargs["Payload"].decode("utf-8")
        )
        assert payload["action"] == "update"
        assert payload["naver_url"] is None

    def test_help_요청이면_worker를_호출하지_않고_도움말을_보낸다(self):
        event = build_event(text="/help")

        with patch("boto3.client") as mock_boto_client, patch(
            "telegram_sender.send_reply"
        ) as mock_send_reply:
            result = webhook_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200
        mock_boto_client.assert_not_called()
        mock_send_reply.assert_called_once()


class TestAlways200:
    def test_처리_중_예외가_발생해도_200을_반환한다(self):
        event = build_event(text="https://naver.me/GB3423bX")

        with patch("boto3.client", side_effect=RuntimeError("invoke 실패")), patch(
            "telegram_sender.send_reply"
        ):
            result = webhook_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200

    def test_body가_json이_아니어도_200을_반환한다(self):
        event = {
            "headers": {"x-telegram-bot-api-secret-token": VALID_SECRET},
            "body": "not-json{{{",
        }

        result = webhook_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200
