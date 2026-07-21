"""web_api_handler.lambda_handler 단위 테스트 (외부 API·web_store 전부 mock)."""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

import config
import naver_review_collector
import web_api_handler
import web_auth

# conftest.py가 주입한 테스트 값과 일치해야 한다
VALID_INVITE_CODE = "invite-code-1"
INVITE_IDENTITY = "친구A"
ADMIN_TOKEN = "test-web-admin-token"


@pytest.fixture(autouse=True)
def _stub_daily_llm_count():
    """일일 LLM 카운트를 기본 0으로 고정한다(상한 미달 = 통과).

    /analyze 워커 경로는 상한 검사에서 web_store.get_daily_llm_count를 호출하는데,
    모의(mock)가 없으면 실제 DynamoDB 접근을 시도한다(느림·비결정적). 상한 자체를
    검증하는 테스트는 이 반환값을 자기 with 블록에서 재지정해 덮어쓴다(내부 patch 우선).
    """
    with patch("web_store.get_daily_llm_count", return_value=0):
        yield


@pytest.fixture(autouse=True)
def _stub_history_writes():
    """조회 이력 쓰기(record_history·trim_history)를 no-op로 고정한다.

    캐시 히트 직결 경로가 이 두 함수를 호출하는데, 모의가 없으면 실제 DynamoDB
    접근을 시도한다(비크리티컬이라 흡수되지만 불필요). 호출 여부를 검증하는 테스트는
    자기 with 블록에서 재패치해 덮어쓴다(내부 patch 우선).
    """
    with patch("web_store.record_history"), patch("web_store.trim_history"):
        yield


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


class TestSearch:
    def test_토큰이_없으면_401을_반환한다(self):
        event = build_event("POST", "/search", body={"prompt": "강남 양식"})

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 401

    def test_prompt이_없으면_400을_반환한다(self):
        event = build_event(
            "POST", "/search", body={}, headers=bearer(session_token())
        )

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"] == "prompt is required"

    def test_prompt이_공백뿐이면_400을_반환한다(self):
        event = build_event(
            "POST", "/search", body={"prompt": "   "}, headers=bearer(session_token())
        )

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 400

    def test_정상이면_정규화_검색_후_200을_반환한다(self):
        event = build_event(
            "POST",
            "/search",
            body={"prompt": "강남에서 데이트하기 좋은 양식집"},
            headers=bearer(session_token()),
        )
        places = [
            {
                "place_id": "33099281",
                "name": "돈멜 본점",
                "category": "돼지고기구이",
                "road_address": "경기 성남시 분당구",
                "review_count": 1258,
            }
        ]
        with patch(
            "search_normalizer.normalize_search_query", return_value="강남 양식"
        ) as mock_normalize, patch(
            "naver_review_collector.search_places", return_value=places
        ) as mock_search, patch(
            "web_store.log_search_usage"
        ) as mock_log:
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["keyword"] == "강남 양식"
        assert body["places"] == places
        mock_normalize.assert_called_once_with("강남에서 데이트하기 좋은 양식집")
        mock_search.assert_called_once_with("강남 양식")
        # 검색 사용량이 identity로 기록된다.
        mock_log.assert_called_once_with(INVITE_IDENTITY)

    def test_결과가_없으면_빈_places로_200을_반환한다(self):
        event = build_event(
            "POST", "/search", body={"prompt": "없는곳"}, headers=bearer(session_token())
        )
        with patch(
            "search_normalizer.normalize_search_query", return_value="없는곳"
        ), patch(
            "naver_review_collector.search_places", return_value=[]
        ), patch("web_store.log_search_usage"):
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200
        assert json.loads(result["body"])["places"] == []

    def test_수집_실패는_502를_반환한다(self):
        event = build_event(
            "POST", "/search", body={"prompt": "강남 양식"}, headers=bearer(session_token())
        )
        with patch(
            "search_normalizer.normalize_search_query", return_value="강남 양식"
        ), patch(
            "naver_review_collector.search_places",
            side_effect=naver_review_collector.ReviewCollectError("429 차단"),
        ), patch("web_store.log_search_usage") as mock_log:
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 502
        # 검색 실패 시 사용량은 기록하지 않는다.
        mock_log.assert_not_called()


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

    def test_place_id로_잡을_생성하고_worker에_전달한다(self):
        event = build_event(
            "POST",
            "/analyze",
            body={"place_id": "33099281"},
            headers=bearer(session_token()),
        )

        mock_lambda_client = MagicMock()
        with patch(
            "web_store.lookup_cached_summary", return_value=None
        ), patch("web_store.create_job") as mock_create_job, patch(
            "boto3.client", return_value=mock_lambda_client
        ):
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 202
        job_id = json.loads(result["body"])["job_id"]

        # create_job(job_id, identity, naver_url="", place_id="33099281")
        create_args = mock_create_job.call_args.args
        assert create_args[0] == job_id
        assert create_args[1] == INVITE_IDENTITY
        assert create_args[2] == ""  # place_id 경로는 naver_url 빈 문자열
        assert create_args[3] == "33099281"

        # worker payload에 place_id 전달
        invoke_kwargs = mock_lambda_client.invoke.call_args.kwargs
        payload = json.loads(invoke_kwargs["Payload"].decode("utf-8"))
        assert payload["place_id"] == "33099281"
        assert payload["naver_url"] == ""

    def test_place_id_형식이_틀리면_400을_반환한다(self):
        event = build_event(
            "POST",
            "/analyze",
            body={"place_id": "abc123; DROP"},
            headers=bearer(session_token()),
        )

        with patch("web_store.create_job") as mock_create_job:
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"] == "invalid place_id"
        mock_create_job.assert_not_called()

    def test_place_id와_naver_url_둘다_없으면_400을_반환한다(self):
        event = build_event(
            "POST", "/analyze", body={}, headers=bearer(session_token())
        )

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 400

    def test_place_id가_naver_url보다_우선한다(self):
        event = build_event(
            "POST",
            "/analyze",
            body={"place_id": "33099281", "naver_url": "https://naver.me/x"},
            headers=bearer(session_token()),
        )

        mock_lambda_client = MagicMock()
        with patch(
            "web_store.lookup_cached_summary", return_value=None
        ), patch("web_store.create_job"), patch(
            "boto3.client", return_value=mock_lambda_client
        ):
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 202
        invoke_kwargs = mock_lambda_client.invoke.call_args.kwargs
        payload = json.loads(invoke_kwargs["Payload"].decode("utf-8"))
        # place_id 우선 — naver_url은 빈 문자열로 무시된다.
        assert payload["place_id"] == "33099281"
        assert payload["naver_url"] == ""


class TestAnalyzeCacheHitDirect:
    """place_id 경로 캐시 히트 직결 — 워커 invoke 없이 완료 잡을 즉시 생성한다."""

    _CACHED = {
        "summary_json": '{"overall": "총평"}',
        "place_name": "돈멜 본점",
        "address": "경기 성남시",
        "review_count": 42,
        "updated_at": "2026-07-07T12:00:00+09:00",
    }

    def test_히트면_완료잡_생성_후_워커없이_202를_반환한다(self):
        event = build_event(
            "POST",
            "/analyze",
            body={"place_id": "33099281"},
            headers=bearer(session_token()),
        )

        mock_lambda_client = MagicMock()
        with patch(
            "web_store.lookup_cached_summary", return_value=self._CACHED
        ) as mock_lookup, patch(
            "web_store.create_completed_job"
        ) as mock_create_completed, patch(
            "web_store.create_job"
        ) as mock_create_job, patch(
            "web_store.log_usage"
        ) as mock_log_usage, patch(
            "web_store.record_history"
        ) as mock_record_history, patch(
            "web_store.trim_history"
        ) as mock_trim_history, patch(
            "boto3.client", return_value=mock_lambda_client
        ):
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 202
        job_id = json.loads(result["body"])["job_id"]
        assert job_id

        mock_lookup.assert_called_once_with("33099281")

        # 완료 잡이 캐시 내용으로 생성된다.
        mock_create_completed.assert_called_once()
        completed_args = mock_create_completed.call_args
        assert completed_args.args[0] == job_id
        assert completed_args.args[1] == INVITE_IDENTITY
        assert completed_args.args[2] == "33099281"
        assert completed_args.kwargs["summary_json"] == self._CACHED["summary_json"]
        assert completed_args.kwargs["updated_at"] == self._CACHED["updated_at"]
        assert completed_args.kwargs["review_count"] == 42

        # 캐시 히트 사용량 기록(cache_hit=True).
        mock_log_usage.assert_called_once_with(INVITE_IDENTITY, cache_hit=True)

        # 조회 이력(보관함) 기록 + 정리가 캐시 내용으로 호출된다.
        mock_record_history.assert_called_once_with(
            INVITE_IDENTITY,
            "33099281",
            self._CACHED["place_name"],
            self._CACHED["address"],
        )
        mock_trim_history.assert_called_once_with(INVITE_IDENTITY)

        # 워커 invoke·create_job(processing)은 호출되지 않는다.
        mock_lambda_client.invoke.assert_not_called()
        mock_create_job.assert_not_called()

    def test_미스면_기존_흐름대로_워커를_invoke한다(self):
        event = build_event(
            "POST",
            "/analyze",
            body={"place_id": "33099281"},
            headers=bearer(session_token()),
        )

        mock_lambda_client = MagicMock()
        with patch(
            "web_store.lookup_cached_summary", return_value=None
        ) as mock_lookup, patch(
            "web_store.create_completed_job"
        ) as mock_create_completed, patch(
            "web_store.create_job"
        ) as mock_create_job, patch(
            "boto3.client", return_value=mock_lambda_client
        ):
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 202
        mock_lookup.assert_called_once_with("33099281")
        # 미스 → 완료 잡 없이 기존 흐름(잡 생성 + 워커 invoke).
        mock_create_completed.assert_not_called()
        mock_create_job.assert_called_once()
        mock_lambda_client.invoke.assert_called_once()

    def test_force_refresh면_lookup을_건너뛴다(self):
        event = build_event(
            "POST",
            "/analyze",
            body={"place_id": "33099281", "force_refresh": True},
            headers=bearer(session_token()),
        )

        mock_lambda_client = MagicMock()
        with patch(
            "web_store.lookup_cached_summary"
        ) as mock_lookup, patch("web_store.create_job") as mock_create_job, patch(
            "boto3.client", return_value=mock_lambda_client
        ):
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 202
        # force_refresh면 캐시를 조회하지 않고 곧바로 워커 경로를 탄다.
        mock_lookup.assert_not_called()
        mock_create_job.assert_called_once()
        mock_lambda_client.invoke.assert_called_once()

    def test_naver_url_경로는_lookup을_호출하지_않는다(self):
        # place_id를 모르는 naver_url 경로는 캐시 직결 대상이 아니다(워커가 resolve 후 조회).
        event = build_event(
            "POST",
            "/analyze",
            body={"naver_url": "https://naver.me/GB3423bX"},
            headers=bearer(session_token()),
        )

        mock_lambda_client = MagicMock()
        with patch(
            "web_store.lookup_cached_summary"
        ) as mock_lookup, patch("web_store.create_job") as mock_create_job, patch(
            "boto3.client", return_value=mock_lambda_client
        ):
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 202
        mock_lookup.assert_not_called()
        mock_create_job.assert_called_once()
        mock_lambda_client.invoke.assert_called_once()


class TestAnalyzeSsrf:
    """naver_url 서버 측 허용목록 검증(SSRF 방어)."""

    def _analyze(self, naver_url: str) -> dict:
        return build_event(
            "POST",
            "/analyze",
            body={"naver_url": naver_url},
            headers=bearer(session_token()),
        )

    def test_허용호스트_https는_통과해_워커를_invoke한다(self):
        mock_lambda_client = MagicMock()
        with patch("web_store.create_job") as mock_create_job, patch(
            "boto3.client", return_value=mock_lambda_client
        ):
            result = web_api_handler.lambda_handler(
                self._analyze("https://naver.me/GB3423bX"), None
            )

        assert result["statusCode"] == 202
        mock_create_job.assert_called_once()
        mock_lambda_client.invoke.assert_called_once()

    def test_허용호스트_서브도메인도_통과한다(self):
        mock_lambda_client = MagicMock()
        with patch("web_store.create_job") as mock_create_job, patch(
            "boto3.client", return_value=mock_lambda_client
        ):
            result = web_api_handler.lambda_handler(
                self._analyze("https://m.place.naver.com/restaurant/33099281"), None
            )

        assert result["statusCode"] == 202
        mock_create_job.assert_called_once()

    def test_http_스킴은_400으로_차단한다(self):
        with patch("web_store.create_job") as mock_create_job, patch(
            "boto3.client"
        ) as mock_boto_client:
            result = web_api_handler.lambda_handler(
                self._analyze("http://naver.me/GB3423bX"), None
            )

        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"] == "invalid url"
        mock_create_job.assert_not_called()
        mock_boto_client.assert_not_called()

    def test_타호스트는_400으로_차단한다(self):
        with patch("web_store.create_job") as mock_create_job:
            result = web_api_handler.lambda_handler(
                self._analyze("https://evil.example.com/x"), None
            )

        assert result["statusCode"] == 400
        mock_create_job.assert_not_called()

    def test_허용호스트를_접미사로_위장한_도메인은_차단한다(self):
        # "naver.me.evil.com"·"evilnaver.me" 등은 허용 호스트와 정확히 같지도,
        # 그 서브도메인(".naver.me"·".naver.com"로 끝남)도 아니므로 차단돼야 한다.
        with patch("web_store.create_job") as mock_create_job:
            result = web_api_handler.lambda_handler(
                self._analyze("https://naver.me.evil.com/x"), None
            )

        assert result["statusCode"] == 400
        mock_create_job.assert_not_called()

    def test_파싱불가_문자열은_400으로_차단한다(self):
        with patch("web_store.create_job") as mock_create_job:
            result = web_api_handler.lambda_handler(self._analyze("not a url"), None)

        assert result["statusCode"] == 400
        mock_create_job.assert_not_called()

    def test_헬퍼_함수_판정(self):
        # 헬퍼 단위 검증 — True/False 경계.
        assert web_api_handler._is_allowed_naver_url("https://naver.me/abc") is True
        assert web_api_handler._is_allowed_naver_url("https://map.naver.com/p") is True
        assert web_api_handler._is_allowed_naver_url("https://NAVER.ME/abc") is True
        assert web_api_handler._is_allowed_naver_url("http://naver.me/abc") is False
        assert web_api_handler._is_allowed_naver_url("https://naver.com.evil.io") is False
        assert web_api_handler._is_allowed_naver_url("ftp://naver.me/abc") is False
        assert web_api_handler._is_allowed_naver_url("https:///nohost") is False


class TestAnalyzeDailyLimit:
    """identity별 일일 LLM 상한 강제(캐시 미스 = 비용 발생 경로에만 적용)."""

    def _place_event(self) -> dict:
        return build_event(
            "POST",
            "/analyze",
            body={"place_id": "33099281"},
            headers=bearer(session_token()),
        )

    def test_상한_미만이면_워커를_invoke한다(self):
        mock_lambda_client = MagicMock()
        with patch(
            "web_store.get_daily_llm_count",
            return_value=config.WEB_DAILY_LLM_LIMIT - 1,
        ), patch(
            "web_store.lookup_cached_summary", return_value=None
        ), patch("web_store.create_job") as mock_create_job, patch(
            "boto3.client", return_value=mock_lambda_client
        ):
            result = web_api_handler.lambda_handler(self._place_event(), None)

        assert result["statusCode"] == 202
        mock_create_job.assert_called_once()
        mock_lambda_client.invoke.assert_called_once()

    def test_상한_이상이면_429로_막고_워커를_invoke하지_않는다(self):
        mock_lambda_client = MagicMock()
        with patch(
            "web_store.get_daily_llm_count",
            return_value=config.WEB_DAILY_LLM_LIMIT,
        ), patch(
            "web_store.lookup_cached_summary", return_value=None
        ), patch("web_store.create_job") as mock_create_job, patch(
            "boto3.client", return_value=mock_lambda_client
        ):
            result = web_api_handler.lambda_handler(self._place_event(), None)

        assert result["statusCode"] == 429
        assert json.loads(result["body"])["error"] == "daily limit exceeded"
        mock_create_job.assert_not_called()
        mock_lambda_client.invoke.assert_not_called()

    def test_force_refresh_경로에도_상한이_걸린다(self):
        event = build_event(
            "POST",
            "/analyze",
            body={"place_id": "33099281", "force_refresh": True},
            headers=bearer(session_token()),
        )
        mock_lambda_client = MagicMock()
        with patch(
            "web_store.get_daily_llm_count",
            return_value=config.WEB_DAILY_LLM_LIMIT,
        ), patch(
            "web_store.lookup_cached_summary"
        ) as mock_lookup, patch("web_store.create_job") as mock_create_job, patch(
            "boto3.client", return_value=mock_lambda_client
        ):
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 429
        # force_refresh는 캐시 조회를 건너뛰므로 lookup은 호출되지 않는다.
        mock_lookup.assert_not_called()
        mock_create_job.assert_not_called()
        mock_lambda_client.invoke.assert_not_called()

    def test_캐시_히트는_상한을_우회한다(self):
        cached = {
            "summary_json": '{"overall": "총평"}',
            "place_name": "돈멜 본점",
            "address": "경기 성남시",
            "review_count": 42,
            "updated_at": "2026-07-07T12:00:00+09:00",
        }
        mock_lambda_client = MagicMock()
        mock_get_count = MagicMock(return_value=config.WEB_DAILY_LLM_LIMIT + 100)
        with patch(
            "web_store.lookup_cached_summary", return_value=cached
        ), patch(
            "web_store.get_daily_llm_count", mock_get_count
        ), patch("web_store.create_completed_job") as mock_create_completed, patch(
            "web_store.log_usage"
        ), patch("boto3.client", return_value=mock_lambda_client):
            result = web_api_handler.lambda_handler(self._place_event(), None)

        # 캐시 히트는 비용 0 — 상한 검사 이전에 202로 종료된다.
        assert result["statusCode"] == 202
        mock_create_completed.assert_called_once()
        mock_lambda_client.invoke.assert_not_called()
        # 상한 검사는 아예 수행되지 않는다.
        mock_get_count.assert_not_called()


class TestWarmup:
    def test_warmup_이벤트는_라우팅없이_200을_반환한다(self):
        with patch("web_store.create_job") as mock_create_job:
            result = web_api_handler.lambda_handler({"warmup": True}, None)

        assert result["statusCode"] == 200
        mock_create_job.assert_not_called()


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

    def test_processing_응답에_현재_단계를_포함한다(self):
        # 진행 중 잡의 세부 단계(stage)가 폴링 응답에 노출된다.
        job = {
            "identity": INVITE_IDENTITY,
            "status": "processing",
            "stage": "collecting",
        }
        with patch("web_store.get_job", return_value=job):
            result = web_api_handler.lambda_handler(
                self._event("job-1", session_token()), None
            )

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "processing"
        assert body["stage"] == "collecting"

    def test_stage_필드가_없는_잡은_빈_문자열로_폴백한다(self):
        # 구버전·전이 전 잡은 stage 필드가 없으므로 빈 문자열로 폴백한다.
        job = {"identity": INVITE_IDENTITY, "status": "processing"}
        with patch("web_store.get_job", return_value=job):
            result = web_api_handler.lambda_handler(
                self._event("job-1", session_token()), None
            )

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "processing"
        assert body["stage"] == ""

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
            {
                "identity": "친구A",
                "total_count": Decimal("3"),
                "llm_call_count": Decimal("1"),
                "last_used_at": "2026-07-07T12:00:00+09:00",
                "req#2026-07-05": Decimal("1"),
                "llm#2026-07-05": Decimal("1"),
                "req#2026-07-07": Decimal("2"),
            }
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
        # 일별 시계열이 정돈돼 포함되고 Decimal이 JSON 정수로 직렬화된다.
        assert body["usage"][0]["daily"] == [
            {"date": "2026-07-05", "total": 1, "llm": 1, "search": 0},
            {"date": "2026-07-07", "total": 2, "llm": 0, "search": 0},
        ]
        # 원시 일별 키는 최상위에 노출되지 않는다(정돈된 형태만).
        assert "req#2026-07-05" not in body["usage"][0]

    def test_토큰이_틀리면_401을_반환한다(self):
        event = build_event(
            "GET", "/admin/stats", headers=bearer("wrong-admin-token")
        )
        with patch("web_store.get_all_usage") as mock_get_all_usage:
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 401
        mock_get_all_usage.assert_not_called()


class TestHistory:
    """GET /history — 본인 조회 이력 반환."""

    def test_토큰이_없으면_401을_반환한다(self):
        event = build_event("GET", "/history")

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 401

    def test_이력을_계약_형태로_반환한다(self):
        history_items = [
            {
                "identity": INVITE_IDENTITY,  # 내부 필드 — 응답에 노출되면 안 된다.
                "place_id": "33099281",
                "place_name": "돈멜 본점",
                "address": "경기 성남시",
                "last_viewed_at": "2026-07-20T10:00:00+09:00",
                "first_viewed_at": "2026-07-01T09:00:00+09:00",  # 내부 필드
                "view_count": Decimal("3"),  # Decimal → int 직렬화 확인
            }
        ]
        event = build_event(
            "GET", "/history", headers=bearer(session_token())
        )
        with patch("web_store.get_history", return_value=history_items) as mock_get:
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        mock_get.assert_called_once_with(INVITE_IDENTITY)
        assert body["history"] == [
            {
                "place_id": "33099281",
                "place_name": "돈멜 본점",
                "address": "경기 성남시",
                "last_viewed_at": "2026-07-20T10:00:00+09:00",
                "view_count": 3,
            }
        ]
        # 내부 필드(identity·first_viewed_at)는 노출되지 않는다.
        assert "identity" not in body["history"][0]
        assert "first_viewed_at" not in body["history"][0]

    def test_이력이_없으면_빈_리스트를_반환한다(self):
        event = build_event(
            "GET", "/history", headers=bearer(session_token())
        )
        with patch("web_store.get_history", return_value=[]):
            result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 200
        assert json.loads(result["body"])["history"] == []


class TestHistoryDelete:
    """DELETE /history/{place_id} — 본인 이력 1건 삭제."""

    def _event(self, place_id: str, token: str) -> dict:
        return build_event(
            "DELETE",
            f"/history/{place_id}",
            headers=bearer(token),
            path_parameters={"place_id": place_id},
        )

    def test_토큰이_없으면_401을_반환한다(self):
        event = build_event(
            "DELETE", "/history/33099281", path_parameters={"place_id": "33099281"}
        )

        result = web_api_handler.lambda_handler(event, None)

        assert result["statusCode"] == 401

    def test_정상이면_삭제하고_deleted_true를_반환한다(self):
        with patch("web_store.delete_history_entry") as mock_delete:
            result = web_api_handler.lambda_handler(
                self._event("33099281", session_token()), None
            )

        assert result["statusCode"] == 200
        assert json.loads(result["body"])["deleted"] is True
        mock_delete.assert_called_once_with(INVITE_IDENTITY, "33099281")

    def test_place_id_형식이_틀리면_400을_반환한다(self):
        with patch("web_store.delete_history_entry") as mock_delete:
            result = web_api_handler.lambda_handler(
                self._event("abc; DROP", session_token()), None
            )

        assert result["statusCode"] == 400
        assert json.loads(result["body"])["error"] == "invalid place_id"
        mock_delete.assert_not_called()


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
