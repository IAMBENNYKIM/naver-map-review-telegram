"""전역 설정·시크릿 로드 (공유 모듈).

모든 모듈이 참조하는 전역 상수와 자격증명을 단일 진입점에서 관리한다.
로컬 개발은 `.env`(환경변수 ``LOCAL_DEV=true``), 프로덕션(Lambda)은
AWS Secrets Manager(시크릿 이름 ``SECRETS_NAME``)에서 이중 로드한다.

보안: 키/토큰을 코드에 평문 하드코딩하지 않는다. 자격증명은 모두
`get_secret()` 결과에서 추출하여 모듈 레벨 변수로 노출한다.
"""

import json
import logging
import os

# ---------------------------------------------------------------------------
# 로깅 보안 하드닝 (전역 — config를 import하는 모든 모듈/핸들러에 적용)
# ---------------------------------------------------------------------------
# httpx의 INFO 레벨 요청 로그는 요청 URL을 그대로 출력하므로, Telegram sendMessage
# URL(`/bot<TOKEN>/...`)의 봇 토큰이 평문으로 로그(로컬·CloudWatch)에 노출된다.
# httpx 로거 레벨을 WARNING으로 올려 토큰 유출을 차단한다.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Lambda 파이썬 런타임의 루트 로거 기본 레벨은 WARNING이라 운영·계측 INFO 로그가
# CloudWatch에 출력되지 않는다. 애플리케이션 INFO 로그가 보이도록 레벨을 명시한다.
logging.getLogger().setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# 전역 상수 (모든 모듈 공유)
# ---------------------------------------------------------------------------
RETRY_COUNT: int = 2              # 외부 API 호출 재시도 횟수
RATE_LIMIT_DELAY: float = 0.5     # 외부(네이버) 요청 간 딜레이(초) — Rate Limit 대비

# ---------------------------------------------------------------------------
# Claude API 리뷰 분석 (review_analyst)
# ---------------------------------------------------------------------------
# 분석 생성 모델 (변경 시 이 상수만 수정)
# Sonnet 4.5 대비 응답 42% 단축·품질 동등 (2026-07-17 실측)으로 Haiku 4.5 채택.
ANTHROPIC_MODEL: str = "claude-haiku-4-5"
# 분석 기능 킬 스위치 — 기본 true라 기존 동작 불변, 환경변수로 끌 수 있다(비용 차단용).
LLM_COMMENTARY_ENABLED: bool = os.getenv("LLM_COMMENTARY_ENABLED", "true").lower() == "true"
LLM_MAX_OUTPUT_TOKENS: int = 2000            # 분석 응답 max_tokens

# 검색어 정규화(search_normalizer) — 자연어 프롬프트를 네이버 검색어로 변환하는 저비용 LLM.
# 분석용(ANTHROPIC_MODEL)과 별개의 경량 모델·짧은 max_tokens를 쓴다(비용·지연 최소화).
SEARCH_LLM_MODEL: str = "claude-haiku-4-5"   # 검색어 정규화용 저비용 모델
SEARCH_LLM_MAX_TOKENS: int = 100             # 정규화 응답 max_tokens (한 줄 검색어면 충분)
# 검색어 정규화 킬 스위치 — 기본 true. off여도 원문 프롬프트로 검색이 동작한다(개선 수단).
SEARCH_LLM_ENABLED: bool = os.getenv("SEARCH_LLM_ENABLED", "true").lower() == "true"

# ---------------------------------------------------------------------------
# 네이버 지도 리뷰 수집기 (naver_review_collector)
# ---------------------------------------------------------------------------
# 네이버 지도(place)는 iframe·비공식 JSON API 구조 — 실제 엔드포인트/셀렉터는 Phase 1 실측으로 확정.
# 스크래핑 함정: (1) Referer 헤더 필수(없으면 빈 응답) (2) 인코딩 CP949 가능 (3) 본문 iframe.
NAVER_MAP_BASE_URL: str = "https://map.naver.com"
NAVER_REQUEST_TIMEOUT: float = 15.0          # 수집 httpx 타임아웃(초)
# 네이버 요청 시 반드시 함께 보낼 헤더.
# ★ m.place.naver.com(모바일 호스트)은 데스크톱 User-Agent를 429로 차단한다(실측 확정).
#   반드시 모바일 Chrome UA를 사용한다. Accept-Language도 함께 보낸다.
NAVER_REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; SM-S911N) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": "https://map.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
REVIEW_FETCH_LIMIT: int = 50                 # 분석에 사용할 최대 리뷰 수

# ---------------------------------------------------------------------------
# 실행 환경 분기
# ---------------------------------------------------------------------------
# LOCAL_DEV=true → .env 로드, 그 외 → AWS Secrets Manager
LOCAL_DEV: bool = os.getenv("LOCAL_DEV", "false").lower() == "true"
SECRETS_NAME: str = os.getenv("SECRETS_NAME", "naver-review/production")
AWS_REGION: str = os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2")

# WorkerFunction 함수명 (WebhookFunction이 비동기 invoke할 대상). template.yaml이 주입.
WORKER_FUNCTION_NAME: str = os.getenv("WORKER_FUNCTION_NAME", "")

# ---------------------------------------------------------------------------
# DynamoDB 테이블명 (DYNAMO_TABLE_PREFIX 접두사 결합 — 로컬 dev_ / 프로덕션 prod_)
# ---------------------------------------------------------------------------
DYNAMO_TABLE_PREFIX: str = os.getenv("DYNAMO_TABLE_PREFIX", "dev_")
DYNAMO_TABLE_REVIEW_CACHE: str = f"{DYNAMO_TABLE_PREFIX}review_cache"  # 장소별 리뷰/요약 캐시

# ---------------------------------------------------------------------------
# 웹 진입점 전용 테이블·상수 (별도 SAM 스택 naver-review-web — Telegram과 격리)
# ---------------------------------------------------------------------------
# 기존 DYNAMO_TABLE_PREFIX(로컬 dev_ / 프로덕션 prod_)를 재사용한다.
WEB_CACHE_TABLE: str = f"{DYNAMO_TABLE_PREFIX}web_review_cache"   # 웹 전용 리뷰/요약 캐시
WEB_JOBS_TABLE: str = f"{DYNAMO_TABLE_PREFIX}web_jobs"           # 비동기 분석 잡 상태
WEB_USAGE_TABLE: str = f"{DYNAMO_TABLE_PREFIX}web_usage"         # identity별 사용량 통계
WEB_HISTORY_TABLE: str = f"{DYNAMO_TABLE_PREFIX}web_history"     # identity별 조회 이력(보관함)
# 기존 Telegram 캐시 테이블 — read-through로 읽기 전용 조회만 한다.
PROD_REVIEW_CACHE_TABLE: str = os.getenv("PROD_REVIEW_CACHE_TABLE", "prod_review_cache")
# 웹 세션 토큰 유효기간(7일) / job 항목 TTL(1시간)
WEB_SESSION_TTL_SECONDS: int = 7 * 24 * 3600
WEB_JOB_TTL_SECONDS: int = 3600

# SSRF 방어: /analyze의 naver_url이 향할 수 있는 허용 호스트 집합.
# 매칭 규칙은 `hostname == h or hostname.endswith("." + h)` — 즉 정확히 이 호스트이거나
# 그 서브도메인일 때만 통과한다. "naver.com"이 map.naver.com·m.place.naver.com 등
# 리다이렉트 목적지 전부를 서브도메인으로 포괄하고, 공유 단축 URL은 "naver.me"가 담당한다.
WEB_ALLOWED_NAVER_HOSTS: frozenset[str] = frozenset({"naver.me", "naver.com"})

# identity별 1일 신규 분석(LLM 호출) 상한 — 비용 폭탄 방어. 캐시 히트는 제외한다
# (비용이 없으므로 상한 대상이 아니다). 환경변수 WEB_DAILY_LLM_LIMIT로 override 가능.
WEB_DAILY_LLM_LIMIT: int = int(os.getenv("WEB_DAILY_LLM_LIMIT", "100"))

# get_secret()가 추출하는 자격증명 키 목록 (.env / Secrets Manager 공통 스키마)
# ★ .env.example 의 키 목록과 정확히 일치시킨다.
_SECRET_KEYS: tuple[str, ...] = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_IDS",
    "TELEGRAM_DEVELOPER_CHAT_ID",
    "TELEGRAM_WEBHOOK_SECRET",
    "ANTHROPIC_API_KEY",
    # 웹 진입점(naver-review-web) 전용 시크릿. Telegram 시크릿 스토어에는 이 키들이
    # 없을 수 있으나, _secret.get(key, "")가 빈 문자열을 반환하므로 Telegram 런타임은
    # 영향받지 않는다(격리의 핵심 — 웹 스택만 이 키들을 실제로 채운다).
    "WEB_SESSION_SECRET",
    "WEB_INVITE_CODES",
    "WEB_ADMIN_TOKEN",
)


def get_secret(secret_name: str = SECRETS_NAME) -> dict:
    """자격증명 dict를 반환한다. 실행 환경에 따라 소스가 분기된다.

    - ``LOCAL_DEV=true``: `python-dotenv`로 `.env`를 로드해 환경변수에서 조립.
    - 그 외(Lambda): `boto3` Secrets Manager에서 시크릿 JSON을 로드.

    Raises:
        RuntimeError: Secrets Manager 조회·파싱 실패 시 (명확한 메시지 포함).
    """
    if LOCAL_DEV:
        return _load_secret_from_dotenv()
    return _load_secret_from_secrets_manager(secret_name)


def _load_secret_from_dotenv() -> dict:
    """로컬 `.env`를 로드해 자격증명 dict를 조립한다.

    `load_dotenv()`는 기존 환경변수를 덮어쓰지 않으므로(override=False),
    테스트에서 미리 설정한 환경변수가 그대로 우선한다.
    """
    from dotenv import load_dotenv

    load_dotenv()
    return {key: os.getenv(key, "") for key in _SECRET_KEYS}


def _load_secret_from_secrets_manager(secret_name: str) -> dict:
    """AWS Secrets Manager에서 시크릿 JSON을 로드해 dict로 반환한다."""
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    client = boto3.client("secretsmanager", region_name=AWS_REGION)
    try:
        response = client.get_secret_value(SecretId=secret_name)
    except (BotoCoreError, ClientError) as error:
        raise RuntimeError(
            f"Secrets Manager 시크릿 로드 실패 (이름: {secret_name}): {error}"
        ) from error

    secret_string = response.get("SecretString")
    if not secret_string:
        raise RuntimeError(
            f"Secrets Manager 시크릿이 비어 있습니다 (이름: {secret_name})"
        )
    try:
        return json.loads(secret_string)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Secrets Manager 시크릿 JSON 파싱 실패 (이름: {secret_name}): {error}"
        ) from error


def _parse_chat_ids(value: object) -> list[str]:
    """JSON 배열 문자열 → ``list[str]`` 변환. 이미 list면 문자열로 정규화."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    return [str(item) for item in json.loads(value)]


def _parse_invite_codes(value: object) -> dict[str, str]:
    """JSON 객체 문자열 ``{"코드":"표시이름"}`` → ``dict[str, str]`` 변환.

    이미 dict면 그대로 정규화, 빈 값이면 ``{}``. 반환값은 초대코드 → 표시이름(alias)
    매핑이며, 표시이름이 사용량 통계의 identity가 된다(PII 아님).

    견고성: 파싱 실패·형식 오류 시 예외를 전파하지 않고 경고 로그 + 빈 dict를 반환한다
    (웹 설정 오류가 config import 전체를 막지 않도록).
    """
    if isinstance(value, dict):
        return {str(code): str(alias) for code, alias in value.items()}
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError) as error:
        logging.getLogger(__name__).warning(
            "WEB_INVITE_CODES 파싱 실패(빈 dict로 대체): %s", error
        )
        return {}
    if not isinstance(parsed, dict):
        logging.getLogger(__name__).warning(
            "WEB_INVITE_CODES가 객체(dict) 형식이 아님(빈 dict로 대체)"
        )
        return {}
    return {str(code): str(alias) for code, alias in parsed.items()}


# ---------------------------------------------------------------------------
# 자격증명 모듈 레벨 변수 (import 시 자동 로드)
# ---------------------------------------------------------------------------
_secret = get_secret()

TELEGRAM_BOT_TOKEN: str = _secret.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS: list[str] = _parse_chat_ids(_secret.get("TELEGRAM_CHAT_IDS", "[]"))
TELEGRAM_DEVELOPER_CHAT_ID: str = _secret.get("TELEGRAM_DEVELOPER_CHAT_ID", "")
# Webhook 무단 호출 차단용 Secret Token (인바운드 검증). setWebhook의 secret_token과 동일 값.
TELEGRAM_WEBHOOK_SECRET: str = _secret.get("TELEGRAM_WEBHOOK_SECRET", "")

# Claude API 키 (분석 기능 — 없으면 review_analyst가 None 반환해 분석만 생략)
ANTHROPIC_API_KEY: str = _secret.get("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# 웹 진입점 자격증명 (naver-review-web 스택 전용 — Telegram과 격리)
# ---------------------------------------------------------------------------
# 세션 토큰 서명 키(HMAC), 관리자 통계 조회 토큰.
WEB_SESSION_SECRET: str = _secret.get("WEB_SESSION_SECRET", "")
WEB_ADMIN_TOKEN: str = _secret.get("WEB_ADMIN_TOKEN", "")
# 초대코드 → 표시이름(identity) 매핑. JSON 객체 문자열을 파싱한다.
WEB_INVITE_CODES: dict[str, str] = _parse_invite_codes(
    _secret.get("WEB_INVITE_CODES", "{}")
)
