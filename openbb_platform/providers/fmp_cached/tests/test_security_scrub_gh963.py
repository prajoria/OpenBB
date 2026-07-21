"""Tests for openbb_fmp_cached.utils.security scrubbing (#963).

The existing `redact_apikey_qs` + `raise_for_status_redacted` helpers
cover the SYNC `requests` leak surface (bd-6641/q4b4/ygtq). This test
suite adds coverage for #963: the LOG-record leak surface — when any
code path (upstream FMP, un-wrapped requests, third-party libraries)
emits a log record containing `apikey=<real key>`, an installed
logging filter should scrub it before it reaches any handler.

Discovered live during PR #966 recording batch 3 — FMP's HTTPError
message on 402 embeds the raw URL (with apikey) into the exception,
which then flows into `logger.error(f"...{e}")` calls at
base_cached.py:97 and similar sites. The scrubbed helpers don't help
if the exception was constructed by upstream code we don't wrap.
"""

from __future__ import annotations

import logging

from openbb_fmp_cached.utils.security import (
    ApikeyScrubFilter,
    install_apikey_scrub_filter,
    redact_apikey_qs,
)

# ---------------------------------------------------------------------------
# redact_apikey_qs — pre-existing regex, retest for #963 corners
# ---------------------------------------------------------------------------


def test_redact_apikey_qs_basic() -> None:
    """?apikey=<value>&other=x → ?apikey=__redacted__&other=x."""
    got = redact_apikey_qs("https://a.co/x?apikey=SECRET&other=y")
    assert got == "https://a.co/x?apikey=__redacted__&other=y"


def test_redact_apikey_qs_case_insensitive() -> None:
    """?APIKEY=... and ?ApiKey=... both scrubbed."""
    assert "__redacted__" in redact_apikey_qs("https://a.co/x?APIKEY=SECRET")
    assert "__redacted__" in redact_apikey_qs("https://a.co/x?ApiKey=SECRET&z=1")


def test_redact_apikey_qs_only_first_param() -> None:
    """?apikey=<value> as the ONLY query param — must still scrub."""
    got = redact_apikey_qs("https://a.co/x?apikey=SECRET")
    assert got == "https://a.co/x?apikey=__redacted__"


def test_redact_apikey_qs_does_not_match_similar_names() -> None:
    """?myapikey=<value> and ?xapikey=<value> — must NOT match."""
    # (These have no ? or & directly before 'apikey=', so regex won't match.)
    got = redact_apikey_qs("https://a.co/x?myapikey=SAFE&z=1")
    assert "SAFE" in got, "must preserve non-apikey params"
    assert "__redacted__" not in got


def test_redact_apikey_qs_empty_string() -> None:
    """Empty string round-trips."""
    assert redact_apikey_qs("") == ""


# ---------------------------------------------------------------------------
# ApikeyScrubFilter — #963 core
# ---------------------------------------------------------------------------


def test_apikey_scrub_filter_scrubs_msg_arg() -> None:
    """Filter scrubs apikey= in the fully-formatted message."""
    f = ApikeyScrubFilter()
    rec = logging.LogRecord(
        name="x",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="Failed at https://a.co/x?apikey=SECRET&z=1",
        args=None,
        exc_info=None,
    )
    assert f.filter(rec) is True
    assert "SECRET" not in rec.getMessage()
    assert "__redacted__" in rec.getMessage()


def test_apikey_scrub_filter_handles_args_lazy_formatting() -> None:
    """Filter handles lazy `%s` formatting where key is in an arg, not msg."""
    f = ApikeyScrubFilter()
    rec = logging.LogRecord(
        name="x",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="Failed at %s",
        args=("https://a.co/x?apikey=SECRET",),
        exc_info=None,
    )
    assert f.filter(rec) is True
    assert "SECRET" not in rec.getMessage()


def test_apikey_scrub_filter_leaves_non_apikey_content_alone() -> None:
    """Non-apikey log messages pass through unchanged (no false positives)."""
    f = ApikeyScrubFilter()
    rec = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="normal log without any secret",
        args=None,
        exc_info=None,
    )
    orig = rec.getMessage()
    f.filter(rec)
    assert rec.getMessage() == orig


def test_apikey_scrub_filter_scrubs_exception_repr(caplog) -> None:
    """Filter scrubs when a leaky Exception is stringified into the message.

    Reproducer for the exact bug seen during PR #966 recording: a
    requests.HTTPError with apikey in the URL was logged as
    `logger.error(f"...{e}")`.
    """
    logger = logging.getLogger("openbb_fmp_cached.test_scrub_repr")
    logger.setLevel(logging.DEBUG)
    logger.addFilter(ApikeyScrubFilter())

    class FakeHTTPError(Exception):
        pass

    exc = FakeHTTPError(
        "402 Client Error: Payment Required for url: "
        "https://financialmodelingprep.com/stable/x?apikey=oTP74s9TxGsnRjac3xRBn3JQ"
    )
    with caplog.at_level(logging.ERROR, logger="openbb_fmp_cached.test_scrub_repr"):
        logger.error("wrapped: %s", exc)

    combined = " ".join(r.getMessage() for r in caplog.records)
    assert (
        "oTP74s9TxGsnRjac3xRBn3JQ" not in combined
    ), "the raw apikey MUST NOT survive the filter"
    assert "__redacted__" in combined


def test_install_apikey_scrub_filter_is_idempotent() -> None:
    """Calling install_apikey_scrub_filter twice attaches only one filter."""
    root = logging.getLogger("openbb_fmp_cached.test_idempotent_install")
    root.filters = [f for f in root.filters if not isinstance(f, ApikeyScrubFilter)]
    install_apikey_scrub_filter(root)
    install_apikey_scrub_filter(root)
    count = sum(1 for f in root.filters if isinstance(f, ApikeyScrubFilter))
    assert count == 1, f"expected 1 filter, got {count}"


def test_install_apikey_scrub_filter_targets_fmp_cached_by_default() -> None:
    """Default install targets the 'openbb_fmp_cached' logger tree."""
    # Fresh install
    tgt = logging.getLogger("openbb_fmp_cached")
    tgt.filters = [f for f in tgt.filters if not isinstance(f, ApikeyScrubFilter)]
    install_apikey_scrub_filter()  # default = openbb_fmp_cached
    assert any(isinstance(f, ApikeyScrubFilter) for f in tgt.filters)


def test_scrubbing_survives_percent_s_repr(caplog) -> None:
    """R7.11 discriminator: without the filter, exception repr leaks; with filter, redacted.

    Note: this test's PRE-filter side is asserted by the built-in
    `test_apikey_scrub_filter_scrubs_exception_repr` above via
    scrubbing verification. Here we verify from the other direction —
    a logger WITHOUT the filter DOES leak, and installing the filter
    fixes it. This is the reverse-verification per CLAUDE.md R7.11.

    Complication: importing `openbb_fmp_cached` at test collection time
    triggers the package-init auto-install, which wraps
    ``root.addHandler`` and installs an ``ApikeyScrubFilter`` on every
    existing root handler. To test the pre-filter LEAK side, we have to
    temporarily strip that filter from every handler for the duration
    of the leak-check, then restore.
    """
    from openbb_fmp_cached.utils.security import ApikeyScrubFilter  # noqa: PLC0415

    key = "OoTP74s9TxGsnRjac3xRBn3JQcP5qvYwQ"
    exc_msg = f"402 for url: https://x.co/?apikey={key}"

    # Snapshot + strip auto-installed filters so we can prove records LEAK
    # without them.
    root = logging.getLogger()
    stripped: list[tuple[logging.Handler, list[logging.Filter]]] = []
    for h in root.handlers:
        removed = [f for f in list(h.filters) if isinstance(f, ApikeyScrubFilter)]
        for f in removed:
            h.removeFilter(f)
        if removed:
            stripped.append((h, removed))

    try:
        # Also strip caplog's own handler (pytest injects one)
        for h in getattr(caplog, "handler", None) and [caplog.handler] or []:
            removed = [f for f in list(h.filters) if isinstance(f, ApikeyScrubFilter)]
            for f in removed:
                h.removeFilter(f)
            if removed:
                stripped.append((h, removed))

        # Without filter — leaks
        unfiltered = logging.getLogger(f"outside_tree_no_filter_{key[:6]}")
        unfiltered.setLevel(logging.DEBUG)
        unfiltered.filters = []
        with caplog.at_level(logging.ERROR, logger=unfiltered.name):
            unfiltered.error("leak-vector: %s", exc_msg)
        leaked = any(key in r.getMessage() for r in caplog.records)
        assert leaked, "test setup broken: unfiltered logger should have leaked the key"

        caplog.clear()

        # With filter — scrubbed
        filtered = logging.getLogger(f"outside_tree_with_filter_{key[:6]}")
        filtered.setLevel(logging.DEBUG)
        filtered.filters = []
        filtered.addFilter(ApikeyScrubFilter())
        with caplog.at_level(logging.ERROR, logger=filtered.name):
            filtered.error("leak-vector: %s", exc_msg)
        assert not any(
            key in r.getMessage() for r in caplog.records
        ), "installed filter FAILED to scrub the key"
    finally:
        # Restore stripped filters
        for h, filters in stripped:
            for f in filters:
                h.addFilter(f)
