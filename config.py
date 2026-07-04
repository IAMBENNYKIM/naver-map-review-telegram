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

# ---------------------------------------------------------------------------
# 전역 상수 (모든 모듈 공유)
# ---------------------------------------------------------------------------
RETRY_COUNT: int = 2              # 외부 API 호출 재시도 횟수
RATE_LIMIT_DELAY: float = 0.5     # 외부(네이버) 요청 간 딜레이(초) — Rate Limit 대비

# ---------------------------------------------------------------------------
# Claude API 리뷰 분석 (review_analyst)
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL: str = "claude-sonnet-4-5"   # 분석 생성 모델 (변경 시 이 상수만 수정)
LLM_COMMENTARY_ENABLED: bool = True          # 분석 기능 킬 스위치 (False면 호출 생략)
LLM_MAX_OUTPUT_TOKENS: int = 2000            # 분석 응답 max_tokens

# ---------------------------------------------------------------------------
# 네이버 지도 리뷰 수집기 (naver_review_collector)
# ---------------------------------------------------------------------------
# 네이버 지도(place)는 iframe·비공식 JSON API 구조 — 실제 엔드포인트/셀렉터는 Phase 1 실측으로 확정.
# 스크래핑 함정: (1) Referer 헤더 필수(없으면 빈 응답) (2) 인코딩 CP949 가능 (3) 본문 iframe.
NAVER_MAP_BASE_URL: str = "https://map.naver.com"
NAVER_REQUEST_TIMEOUT: float = 15.0          # 수집 httpx 타임아웃(초)
# 네이버 요청 시 반드시 함께 보낼 헤더(Referer 없으면 0건 — 외부 소스 함정)
NAVER_REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://map.naver.com/",
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

# get_secret()가 추출하는 자격증명 키 목록 (.env / Secrets Manager 공통 스키마)
# ★ .env.example 의 키 목록과 정확히 일치시킨다.
_SECRET_KEYS: tuple[str, ...] = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_IDS",
    "TELEGRAM_DEVELOPER_CHAT_ID",
    "TELEGRAM_WEBHOOK_SECRET",
    "ANTHROPIC_API_KEY",
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
