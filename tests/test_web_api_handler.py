"""web_api_handler.lambda_handler 단위 테스트 (외부 API·web_store 전부 mock)."""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import web_api_handler
import web_auth

# conftest.py가 주입한 테스트 값과 일치해야 한다
VALID_INVITE_CODE = "invite-code-1"
INVITE_IDENTITY = "친구A"
ADMIN_TOKEN = "test-web-admin-token"


def build_event(
    method: str,
    path: str,
    body: dict | str | None = None,
    headers: dict | None = None,
    path_parameters: dict | None = None,
) -> dict:
    """HttpApi payload v2 형태의 이벤트를 생성한다."""
    if isinstance(body, dict):
        raw_body = json.dumps(body)
    else:
        raw_body = body
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "headers": headers or {},
        "pathParameters": path_parameters,
        "body": raw_body,
    }


def bearer(token: str) -> dict:
    """Authorization Bearer 헤더 dict를 생성한다."""
    return {"authorization": f"Bearer {token}"}


def session_token() -> str:
    """유효한 세션 토큰을 발급한다(실제 web_auth 서명 사용)."""
    return web_auth.issue_session_token(INVITE_IDENTITY)


class TestInvite:
    def test_유효한_초대코드는_토큰을_발급하고_200을_반환한다(self):
        event = build_event("POST", "/invite", body={"code": VALID_INVITE_CODE})

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        # 발급된 토큰이 실제로 해당 identity로 검증되는지 확인
        assert web_auth.verify_session_token(body["token"]) == INVITE_IDENTITY

    def test_무효한_초대코드는_401을_반환한다(self):
        event = build_event("POST", "/invite", body={"code": "wrong-code"})

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 401
        assert json.loads(result["body"])["error"] == "invalid invite code"

    def test_body가_json이_아니면_400을_반환한다(self):
        event = build_event("POST", "/invite", body="not-json{{{")

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 400


class TestAnalyze:
    def test_토큰이_없으면_401을_반환한다(self):
        event = build_event(
            "POST", "/analyze", body={"naver_url": "https://naver.me/x"}
        )

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 401

    def test_naver_url이_없으면_400을_반환한다(self):
        event = build_event(
            "POST", "/analyze", body={}, headers=bearer(session_token())
        )

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 400

    def test_유효토큰이면_create_job과_worker_invoke_후_202를_반환한다(self):
        naver_url = "https://naver.me/GB3423bX"
        event = build_event(
            "POST",
            "/analyze",
            body={"naver_url": naver_url},
            headers=bearer(session_token()),
        )

        mock_lambda_client = MagicMock()
        with patch("web_store.create_job") as mock_create_job, patch(
            "boto3.client", return_value=mock_lambda_client
        ) as mock_boto_client:
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 202
        job_id = json.loads(result["body"])["job_id"]
        assert job_id

        # create_job(job_id, identity, naver_url) 호출 확인
        mock_create_job.assert_called_once()
        create_args = mock_create_job.call_args.args
        assert create_args[0] == job_id
        assert create_args[1] == INVITE_IDENTITY
        assert create_args[2] == naver_url

        # WebWorkerFunction 비동기 invoke 확인
        mock_boto_client.assert_called_once()
        mock_lambda_client.invoke.assert_called_once()
        invoke_kwargs = mock_lambda_client.invoke.call_args.kwargs
        assert invoke_kwargs["InvocationType"] == "Event"
        payload = json.loads(invoke_kwargs["Payload"].decode("utf-8"))
        assert payload["job_id"] == job_id
        assert payload["identity"] == INVITE_IDENTITY
        assert payload["naver_url"] == naver_url
        # force_refresh 미지정 시 기본 False로 전달된다.
        assert payload["force_refresh"] is False

    def test_force_refresh를_worker_payload로_전달한다(self):
        naver_url = "https://naver.me/GB3423bX"
        event = build_event(
            "POST",
            "/analyze",
            body={"naver_url": naver_url, "force_refresh": True},
            headers=bearer(session_token()),
        )

        mock_lambda_client = MagicMock()
        with patch("web_store.create_job"), patch(
            "boto3.client", return_value=mock_lambda_client
        ):
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 202
        invoke_kwargs = mock_lambda_client.invoke.call_args.kwargs
        payload = json.loads(invoke_kwargs["Payload"].decode("utf-8"))
        assert payload["force_refresh"] is True


class TestResult:
    def _event(self, job_id: str, token: str) -> dict:
        return build_event(
            "GET",
            f"/result/{job_id}",
            headers=bearer(token),
            path_parameters={"job_id": job_id},
        )

    def test_토큰이_없으면_401을_반환한다(self):
        event = build_event(
            "GET", "/result/abc", path_parameters={"job_id": "abc"}
        )

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 401

    def test_잡이_없으면_404를_반환한다(self):
        with patch("web_store.get_job", return_value=None):
            result = web_api_handler.lambda_handler(
                self._event("no-job", session_token()), None
            )

        assert result["statusCode"] == 404

    def test_타인_잡은_404를_반환한다(self):
        # 소유자가 다른 identity인 잡 — 존재를 노출하지 않고 404
        other_job = {"identity": "다른사람", "status": "processing"}
        with patch("web_store.get_job", return_value=other_job):
            result = web_api_handler.lambda_handler(
                self._event("job-1", session_token()), None
            )

        assert result["statusCode"] == 404

    def test_processing_상태를_반환한다(self):
        job = {"identity": INVITE_IDENTITY, "status": "processing"}
        with patch("web_store.get_job", return_value=job):
            result = web_api_handler.lambda_handler(
                self._event("job-1", session_token()), None
            )

        assert result["statusCode"] == 200
        assert json.loads(result["body"])["status"] == "processing"

    def test_done_상태와_Decimal을_직렬화해_반환한다(self):
        job = {
            "identity": INVITE_IDENTITY,
            "status": "done",
            "summary_json": '{"a": 1}',
            "place_name": "돈멜",
            "address": "성남시",
            "review_count": Decimal("42"),  # DynamoDB Decimal
            "cache_hit": False,
            "updated_at": "2026-07-07T12:00:00+09:00",
        }
        with patch("web_store.get_job", return_value=job):
            result = web_api_handler.lambda_handler(
                self._event("job-1", session_token()), None
            )

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "done"
        assert body["review_count"] == 42  # Decimal → int
        assert body["place_name"] == "돈멜"
        # updated_at(요약 갱신 시점)이 done 응답에 포함된다.
        assert body["updated_at"] == "2026-07-07T12:00:00+09:00"

    def test_error_상태를_반환한다(self):
        job = {
            "identity": INVITE_IDENTITY,
            "status": "error",
            "error_message": "리뷰를 가져오지 못했어요",
        }
        with patch("web_store.get_job", return_value=job):
            result = web_api_handler.lambda_handler(
                self._event("job-1", session_token()), None
            )

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "error"
        assert body["error_message"] == "리뷰를 가져오지 못했어요"


class TestAdminStats:
    def test_관리자_토큰이면_사용량을_반환한다(self):
        usage = [
            {"identity": "친구A", "total_count": Decimal("3"), "llm_call_count": Decimal("1")}
        ]
        event = build_event(
            "GET", "/admin/stats", headers=bearer(ADMIN_TOKEN)
        )
        with patch("web_store.get_all_usage", return_value=usage):
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        # Decimal 직렬화 확인
        assert body["usage"][0]["total_count"] == 3
        assert body["usage"][0]["llm_call_count"] == 1

    def test_토큰이_틀리면_401을_반환한다(self):
        event = build_event(
            "GET", "/admin/stats", headers=bearer("wrong-admin-token")
        )
        with patch("web_store.get_all_usage") as mock_get_all_usage:
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 401
        mock_get_all_usage.assert_not_called()


class TestRouting:
    def test_미지원_경로는_404를_반환한다(self):
        event = build_event("GET", "/unknown")

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 404

    def test_미지원_메서드는_404를_반환한다(self):
        event = build_event("DELETE", "/invite")

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 404

    def test_내부_예외는_500을_반환한다(self):
        event = build_event("POST", "/invite", body={"code": VALID_INVITE_CODE})

        # issue_session_token에서 예외를 강제해 최상위 흡수를 검증
        with patch(
            "web_auth.validate_invite_code", side_effect=RuntimeError("boom")
        ):
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 500
        assert json.loads(result["body"])["error"] == "internal error"
