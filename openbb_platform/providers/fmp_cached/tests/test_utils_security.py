"""Tests for openbb_fmp_cached.utils.security — apikey redaction helpers.

Locks in the behavior of ``redact_apikey_qs`` and ``raise_for_status_
redacted`` so any regression that reintroduces plaintext apikey in an
HTTPError message (or in the URL a redacted response reports) fails a
test loudly.

Regression coverage for bd-6641 (fix/qc-api-key-in-url) and the
Phase-6 self-QC hardening on top of it.
"""

from __future__ import annotations

import pytest
from openbb_fmp_cached.utils.security import (
    raise_for_status_redacted,
    redact_apikey_qs,
)


class TestRedactApikeyQs:
    """The regex-based URL rewriter."""

    def test_simple_leading_apikey(self):
        """``?apikey=SECRET`` → ``?apikey=__redacted__``."""
        result = redact_apikey_qs("https://api.example.com/x?apikey=SECRET")
        assert result == "https://api.example.com/x?apikey=__redacted__"

    def test_apikey_after_other_params(self):
        """``?symbol=A&apikey=SECRET`` — anchor on ``&``, preserve other params."""
        result = redact_apikey_qs("https://api.example.com/x?symbol=A&apikey=SECRET")
        assert result == "https://api.example.com/x?symbol=A&apikey=__redacted__"

    def test_apikey_followed_by_other_params(self):
        """``?apikey=SECRET&other=y`` — terminate on ``&``, preserve rest."""
        result = redact_apikey_qs("https://api.example.com/x?apikey=SECRET&other=y")
        assert result == "https://api.example.com/x?apikey=__redacted__&other=y"

    def test_case_insensitive(self):
        """``APIKEY``, ``ApiKey``, ``apikey`` all redact."""
        for variant in ("APIKEY", "ApiKey", "apikey", "apiKEY"):
            result = redact_apikey_qs(f"https://api.example.com/x?{variant}=SECRET")
            assert (
                "SECRET" not in result
            ), f"Variant {variant!r} failed to redact: {result!r}"
            assert "__redacted__" in result

    def test_does_not_match_myapikey_prefix(self):
        """``?myapikey=`` must NOT be treated as ``apikey=`` — no over-redact."""
        url = "https://api.example.com/x?myapikey=IS_NOT_SECRET"
        assert redact_apikey_qs(url) == url

    def test_empty_string_passthrough(self):
        """Empty input returns empty output."""
        assert redact_apikey_qs("") == ""

    def test_none_input_passthrough(self):
        """None input returns None (no crash)."""
        assert redact_apikey_qs(None) is None  # type: ignore[arg-type]

    def test_url_without_apikey_unchanged(self):
        """A URL that never carried apikey is returned unchanged."""
        url = "https://api.example.com/x?symbol=A&interval=1d"
        assert redact_apikey_qs(url) == url


class TestRaiseForStatusRedacted:
    """The convenience wrapper that mutates resp.url before raising."""

    def _fake_response(self, status_code: int, url: str):
        """Build a stub Response object that mimics ``requests.Response`` shape."""
        import requests

        class FakeRequest:
            def __init__(self, url):
                self.url = url

        class FakeResponse:
            def __init__(self, status_code, url):
                self.status_code = status_code
                self.url = url
                self.request = FakeRequest(url)
                self.reason = "Simulated Error"

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError(
                        f"{self.status_code} Client Error: "
                        f"{self.reason} for url: {self.url}",
                        response=self,
                    )

        return FakeResponse(status_code, url)

    def test_2xx_no_op(self):
        """200 response is not touched; no exception raised."""
        resp = self._fake_response(200, "https://api.example.com/x?apikey=SECRET")
        raise_for_status_redacted(resp)  # must not raise
        # url is unchanged for 2xx
        assert "SECRET" in resp.url

    def test_4xx_message_has_redacted_url(self):
        """4xx HTTPError message contains ``__redacted__`` not the plaintext key."""
        import requests

        resp = self._fake_response(
            429, "https://api.example.com/x?symbol=A&apikey=SECRET"
        )
        with pytest.raises(requests.HTTPError) as excinfo:
            raise_for_status_redacted(resp)
        assert "SECRET" not in str(
            excinfo.value
        ), f"HTTPError leaked apikey: {excinfo.value!s}"
        assert "__redacted__" in str(excinfo.value)

    def test_4xx_response_url_is_redacted(self):
        """After raise, ``exc.response.url`` is redacted (Sentry breadcrumb field)."""
        import requests

        resp = self._fake_response(500, "https://api.example.com/x?apikey=SECRET")
        with pytest.raises(requests.HTTPError) as excinfo:
            raise_for_status_redacted(resp)
        assert "SECRET" not in str(excinfo.value.response.url)
        assert "__redacted__" in str(excinfo.value.response.url)

    def test_4xx_request_url_is_redacted(self):
        """After raise, ``exc.response.request.url`` is also redacted."""
        import requests

        resp = self._fake_response(500, "https://api.example.com/x?apikey=SECRET")
        with pytest.raises(requests.HTTPError) as excinfo:
            raise_for_status_redacted(resp)
        assert "SECRET" not in str(excinfo.value.response.request.url)

    def test_frozen_response_still_raises(self):
        """A Response with read-only url still raises (redact fails silently)."""
        import requests

        class FrozenResp:
            status_code = 500
            reason = "Boom"
            request = None

            @property
            def url(self):
                return "https://api.example.com/x?apikey=SECRET"

            def raise_for_status(self):
                raise requests.HTTPError(
                    f"500 Server Error: {self.reason} for url: {self.url}",
                    response=self,
                )

        # We can't redact if url is read-only; the wrapper should still
        # call raise_for_status (the exception's message will leak, but
        # that's a caller-Response problem, not a wrapper bug).
        with pytest.raises(requests.HTTPError):
            raise_for_status_redacted(FrozenResp())
