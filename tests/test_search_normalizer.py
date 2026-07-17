"""search_normalizer 단위 테스트 (anthropic SDK mock — 네트워크 불필요).

어떤 실패에도 원문 prompt.strip()을 반환하는 폴백 계약을 검증한다.
"""

from unittest.mock import MagicMock, patch

import config
import search_normalizer


def _fake_text_block(text: str):
    """response.content 원소(텍스트 블록)를 모사한다."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _patch_anthropic(response_text: str):
    """anthropic.Anthropic를 mock해 messages.create가 지정 텍스트를 반환하게 한다."""
    fake_response = MagicMock()
    fake_response.content = [_fake_text_block(response_text)]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response
    return patch("anthropic.Anthropic", return_value=fake_client)


class TestNormalizeSearchQuery:
    def test_정상_변환은_LLM_결과를_반환한다(self):
        with _patch_anthropic("강남 양식"):
            result = search_normalizer.normalize_search_query(
                "강남에서 데이트하기 좋은 양식집"
            )

        assert result == "강남 양식"

    def test_클라이언트를_유계로_생성한다(self):
        # Lambda 타임아웃 초과 방지 — timeout·max_retries를 짧게 자른다.
        fake_response = MagicMock()
        fake_response.content = [_fake_text_block("강남 양식")]
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_response

        with patch("anthropic.Anthropic", return_value=fake_client) as mock_ctor:
            search_normalizer.normalize_search_query("강남 데이트 양식집")

        ctor_kwargs = mock_ctor.call_args.kwargs
        assert ctor_kwargs["timeout"] == 5.0
        assert ctor_kwargs["max_retries"] == 0

    def test_킬스위치_off면_원문을_반환한다(self, monkeypatch):
        monkeypatch.setattr(config, "SEARCH_LLM_ENABLED", False)

        # LLM이 호출되면 실패하도록 지뢰를 심는다.
        with patch("anthropic.Anthropic", side_effect=AssertionError("호출되면 안 됨")):
            result = search_normalizer.normalize_search_query("  강남 양식집  ")

        assert result == "강남 양식집"  # strip된 원문

    def test_API_예외면_원문을_반환한다(self, monkeypatch):
        monkeypatch.setattr(config, "SEARCH_LLM_ENABLED", True)

        with patch("anthropic.Anthropic", side_effect=RuntimeError("API 오류")):
            result = search_normalizer.normalize_search_query("판교 카페 추천")

        assert result == "판교 카페 추천"

    def test_빈_응답이면_원문을_반환한다(self, monkeypatch):
        monkeypatch.setattr(config, "SEARCH_LLM_ENABLED", True)

        with _patch_anthropic("   "):  # strip 후 빈 문자열
            result = search_normalizer.normalize_search_query("성수 브런치")

        assert result == "성수 브런치"

    def test_과도하게_긴_응답이면_원문을_반환한다(self, monkeypatch):
        monkeypatch.setattr(config, "SEARCH_LLM_ENABLED", True)

        long_text = "가" * 100  # _MAX_KEYWORD_LENGTH(40) 초과
        with _patch_anthropic(long_text):
            result = search_normalizer.normalize_search_query("긴 설명 프롬프트")

        assert result == "긴 설명 프롬프트"

    def test_키가_없으면_원문을_반환한다(self, monkeypatch):
        monkeypatch.setattr(config, "SEARCH_LLM_ENABLED", True)
        monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")

        with patch("anthropic.Anthropic", side_effect=AssertionError("호출되면 안 됨")):
            result = search_normalizer.normalize_search_query("강남 양식")

        assert result == "강남 양식"
