"""Provider-live evidence classification contracts."""

from types import SimpleNamespace

import pytest

from scripts.test_provider_live import _error_text, _is_entitlement_error


def test_error_text_is_normalized_without_printing_payload():
    """Error matching normalizes markers without logging provider text."""
    result = SimpleNamespace(
        content=[
            SimpleNamespace(text="403 Upgrade Required"),
            SimpleNamespace(text="ENTITLEMENT denied"),
        ]
    )

    assert _error_text(result) == "403 upgrade required entitlement denied"


@pytest.mark.parametrize(
    "message",
    (
        "403 invalid token",
        "authentication failed",
        "transport unavailable",
        "upgrade client version",
    ),
)
def test_generic_failures_are_not_entitlement_errors(message):
    """Authentication, transport, and client failures remain fatal."""
    assert not _is_entitlement_error(message)


@pytest.mark.parametrize(
    "message",
    (
        "provider entitlement denied",
        "endpoint plan limit reached",
        "upgrade plan to access premium endpoint",
        "subscription required",
    ),
)
def test_provider_plan_denials_are_entitlement_errors(message):
    """Only provider-plan denial language is classified as entitlement."""
    assert _is_entitlement_error(message)
