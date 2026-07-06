"""웹 진입점 인증 로직 (순수 함수 + HMAC — 외부 호출 없음).

세션 토큰 발급/검증, 초대코드 검증, 관리자 토큰 검증을 담당한다.
모든 서명·비교는 상수시간(``hmac.compare_digest``)으로 수행하고, 어떤 예외에도
검증 함수는 실패(None/False)를 반환하도록 견고하게 작성한다.

보안: 시크릿·토큰 원문 값을 로그에 남기지 않는다.
"""

import base64
import binascii
import hashlib
import hmac
import logging
import time

import config

logger = logging.getLogger(__name__)


def _sign(payload: str) -> str:
    """payload를 WEB_SESSION_SECRET으로 HMAC-SHA256 서명해 hex digest를 반환한다."""
    return hmac.new(
        config.WEB_SESSION_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def issue_session_token(identity: str) -> str:
    """identity에 대한 세션 토큰을 발급한다.

    payload = ``"{identity}:{exp}"`` (exp = now + WEB_SESSION_TTL_SECONDS epoch),
    sig = HMAC-SHA256(payload, WEB_SESSION_SECRET) hexdigest,
    토큰 = base64url(``"{payload}:{sig}"``).

    identity에 ``:`` 가 포함될 수 있으므로 검증 시에는 rsplit으로 끝에서 분리한다.
    """
    expiration_epoch = int(time.time()) + config.WEB_SESSION_TTL_SECONDS
    payload = f"{identity}:{expiration_epoch}"
    signature = _sign(payload)
    raw_token = f"{payload}:{signature}"
    return base64.urlsafe_b64encode(raw_token.encode("utf-8")).decode("ascii")


def verify_session_token(token: str) -> str | None:
    """세션 토큰을 검증하고 유효하면 identity를 반환한다. 무효면 None.

    검증 절차: base64url 디코드 → 끝에서 sig·exp 분리 → 서명 재계산 후
    상수시간 비교 → 만료 확인 → identity 반환. 어떤 예외에도 None을 반환한다.
    """
    if not token:
        return None
    try:
        raw_token = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        # 끝에서부터 sig, exp를 분리한다 (identity에 ':'가 포함될 수 있음).
        payload, signature = raw_token.rsplit(":", 1)
        identity, expiration_text = payload.rsplit(":", 1)

        expected_signature = _sign(payload)
        if not hmac.compare_digest(signature, expected_signature):
            return None

        if int(expiration_text) <= int(time.time()):
            return None

        return identity
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        # 손상된 토큰·형식 오류는 모두 검증 실패로 처리한다(원문은 로그에 남기지 않음).
        logger.warning("세션 토큰 검증 실패(무효 처리): %s", type(error).__name__)
        return None


def validate_invite_code(code: str) -> str | None:
    """초대코드를 검증하고 매핑된 표시이름(identity)을 반환한다. 없으면 None.

    초대코드는 열거(enumeration) 대상이 아니므로 단순 dict.get으로 조회한다.
    """
    if not code:
        return None
    return config.WEB_INVITE_CODES.get(code)


def verify_admin_token(provided: str) -> bool:
    """관리자 토큰 일치 여부를 상수시간으로 검증한다.

    WEB_ADMIN_TOKEN이 비어 있으면(미설정) 항상 False — 빈 토큰 우회를 차단한다.
    """
    if not config.WEB_ADMIN_TOKEN:
        return False
    if not provided:
        return False
    return hmac.compare_digest(provided, config.WEB_ADMIN_TOKEN)
