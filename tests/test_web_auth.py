"""web_auth 단위 테스트 (순수 로직 — 외부 호출 없음)."""

import base64
import time

import pytest

import config
import web_auth


class TestSessionTokenRoundTrip:
    def test_발급_후_검증하면_identity가_나온다(self):
        token = web_auth.issue_session_token("친구A")

        assert web_auth.verify_session_token(token) == "친구A"

    def test_콜론_포함_identity도_왕복된다(self):
        # identity에 ':'가 포함돼도 rsplit 파싱으로 정확히 복원돼야 한다.
        token = web_auth.issue_session_token("친구:A:B")

        assert web_auth.verify_session_token(token) == "친구:A:B"

    def test_변조된_토큰은_거부된다(self):
        token = web_auth.issue_session_token("친구A")
        # base64 디코드 후 한 글자를 바꿔 서명 불일치를 유발한다.
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        tampered_raw = raw[:-1] + ("0" if raw[-1] != "0" else "1")
        tampered_token = base64.urlsafe_b64encode(
            tampered_raw.encode("utf-8")
        ).decode("ascii")

        assert web_auth.verify_session_token(tampered_token) is None

    def test_만료된_토큰은_거부된다(self, monkeypatch):
        # TTL을 음수로 만들어 이미 만료된(exp가 과거) 토큰을 발급한다.
        monkeypatch.setattr(config, "WEB_SESSION_TTL_SECONDS", -10)
        expired_token = web_auth.issue_session_token("친구A")

        assert web_auth.verify_session_token(expired_token) is None

    def test_잘못된_base64는_거부된다(self):
        assert web_auth.verify_session_token("!!!not-base64!!!") is None

    def test_빈_토큰은_거부된다(self):
        assert web_auth.verify_session_token("") is None

    def test_다른_시크릿으로_서명된_토큰은_거부된다(self, monkeypatch):
        token = web_auth.issue_session_token("친구A")
        # 검증 시점에 시크릿이 바뀌면 서명이 불일치해야 한다.
        monkeypatch.setattr(config, "WEB_SESSION_SECRET", "다른-시크릿")

        assert web_auth.verify_session_token(token) is None


class TestValidateInviteCode:
    def test_유효한_초대코드는_표시이름을_반환한다(self):
        assert web_auth.validate_invite_code("invite-code-1") == "친구A"
        assert web_auth.validate_invite_code("invite-code-2") == "친구B"

    def test_없는_초대코드는_none을_반환한다(self):
        assert web_auth.validate_invite_code("no-such-code") is None

    def test_빈_초대코드는_none을_반환한다(self):
        assert web_auth.validate_invite_code("") is None


class TestVerifyAdminToken:
    def test_일치하는_토큰은_true(self):
        assert web_auth.verify_admin_token("test-web-admin-token") is True

    def test_불일치_토큰은_false(self):
        assert web_auth.verify_admin_token("wrong-token") is False

    def test_빈_제공값은_false(self):
        assert web_auth.verify_admin_token("") is False

    def test_admin_토큰_미설정이면_항상_false(self, monkeypatch):
        # WEB_ADMIN_TOKEN이 빈 값이면 빈 provided로도 우회할 수 없어야 한다.
        monkeypatch.setattr(config, "WEB_ADMIN_TOKEN", "")

        assert web_auth.verify_admin_token("") is False
        assert web_auth.verify_admin_token("anything") is False
