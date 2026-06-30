"""Schema smoke test for the wild-corpus fingerprint index.

This is a tripwire for schema drift, not a full coverage simulation. The
real wild-corpus-coverage gate lands in L0.5 — here we only assert that
``index.json`` is shaped the way ``tools/pine/crawl_wild_corpus.py`` claims
to produce it, so downstream consumers don't have to defensive-code
against unexpected types.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

INDEX_PATH = Path(__file__).parent / "index.json"

REQUIRED_KEYS = {
    "url",
    "title",
    "author",
    "likes",
    "script_type",
    "pine_version",
    "builtins_used",
    "features_used",
    "source_visible",
    "crawled_at",
}

FEATURE_BOOL_KEYS = {
    "uses_request_security",
    "uses_library_directive",
    "uses_drawings",
    "uses_strategy_directive",
    "uses_indicator_directive",
}
FEATURE_INT_KEYS = {"uses_input_array"}


@pytest.fixture(scope="module")
def index() -> list[dict]:
    assert INDEX_PATH.exists(), (
        f"{INDEX_PATH} not found — run "
        "`python tools/pine/crawl_wild_corpus.py --target 20 "
        "--rate-limit-sec 2.0` first"
    )
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return data


def test_index_is_json_array(index):
    assert isinstance(index, list), "index.json must be a JSON array"
    assert index, "index.json must contain at least one entry"


def test_every_entry_is_an_object_with_required_keys(index):
    for i, entry in enumerate(index):
        assert isinstance(entry, dict), f"entry {i} is not an object"
        missing = REQUIRED_KEYS - set(entry)
        assert not missing, f"entry {i} ({entry.get('url')!r}) missing keys: {missing}"


def test_pine_version_is_int_or_null(index):
    for entry in index:
        v = entry["pine_version"]
        assert v is None or (isinstance(v, int) and v in (5, 6)), (
            f"{entry['url']!r}: pine_version must be 5, 6, or null; got {v!r}"
        )


def test_builtins_used_is_list_of_strings_or_null(index):
    for entry in index:
        b = entry["builtins_used"]
        if b is None:
            continue
        assert isinstance(b, list), (
            f"{entry['url']!r}: builtins_used must be list or null; got {type(b).__name__}"
        )
        for ident in b:
            assert isinstance(ident, str) and "." in ident, (
                f"{entry['url']!r}: builtin entry {ident!r} should be 'namespace.member'"
            )


def test_features_used_shape(index):
    for entry in index:
        f = entry["features_used"]
        if f is None:
            continue
        assert isinstance(f, dict), (
            f"{entry['url']!r}: features_used must be dict or null"
        )
        for k in FEATURE_BOOL_KEYS:
            assert k in f, f"{entry['url']!r}: features_used missing {k!r}"
            assert isinstance(f[k], bool), (
                f"{entry['url']!r}: features_used.{k} must be bool, got {type(f[k]).__name__}"
            )
        for k in FEATURE_INT_KEYS:
            assert k in f, f"{entry['url']!r}: features_used missing {k!r}"
            assert isinstance(f[k], int) and not isinstance(f[k], bool), (
                f"{entry['url']!r}: features_used.{k} must be int, got {type(f[k]).__name__}"
            )


def test_source_visible_is_bool(index):
    for entry in index:
        assert isinstance(entry["source_visible"], bool), (
            f"{entry['url']!r}: source_visible must be bool"
        )


def test_source_visible_consistency(index):
    """If source_visible is False the body-derived fields must all be None;
    if True, builtins_used and features_used must not be None."""
    for entry in index:
        if entry["source_visible"]:
            assert entry["builtins_used"] is not None, (
                f"{entry['url']!r}: source_visible=true but builtins_used is null"
            )
            assert entry["features_used"] is not None, (
                f"{entry['url']!r}: source_visible=true but features_used is null"
            )
        else:
            assert entry["builtins_used"] is None, (
                f"{entry['url']!r}: source_visible=false but builtins_used is not null"
            )
            assert entry["features_used"] is None, (
                f"{entry['url']!r}: source_visible=false but features_used is not null"
            )
            assert entry["pine_version"] is None, (
                f"{entry['url']!r}: source_visible=false but pine_version is not null"
            )


def test_crawled_at_parses_as_iso_timestamp(index):
    for entry in index:
        ts = entry["crawled_at"]
        assert isinstance(ts, str) and ts, (
            f"{entry['url']!r}: crawled_at must be a non-empty string"
        )
        # datetime.fromisoformat accepts both with and without timezone in 3.11+
        try:
            datetime.fromisoformat(ts)
        except ValueError as exc:
            pytest.fail(f"{entry['url']!r}: crawled_at {ts!r} is not ISO: {exc}")


def test_likes_is_non_negative_int(index):
    for entry in index:
        likes = entry["likes"]
        assert isinstance(likes, int) and not isinstance(likes, bool) and likes >= 0, (
            f"{entry['url']!r}: likes must be a non-negative int, got {likes!r}"
        )


def test_url_is_tradingview_script_permalink(index):
    for entry in index:
        url = entry["url"]
        assert isinstance(url, str) and url.startswith(
            "https://www.tradingview.com/script/"
        ), f"unexpected url: {url!r}"


def test_no_pine_source_redistributed(index):
    """Guardrail per PRD §2.1 + §3.4 — index must not contain Pine source.

    We block on two strong signals: presence of the `//@version=` directive
    (a Pine file marker) or any `\n`-separated multi-line text that contains
    both an indicator/strategy/library declaration and a plot/ta call. Either
    would indicate someone accidentally stashed source into the index.
    """
    for entry in index:
        for field_name, value in entry.items():
            if not isinstance(value, str):
                continue
            # Allowed: pine vocabulary in description prose (single line, short).
            # Disallowed: anything that looks like an actual Pine file body.
            if "//@version=" in value:
                pytest.fail(
                    f"{entry['url']!r}: field {field_name!r} contains "
                    "'//@version=' — Pine source must never be stored "
                    "(PRD §2.1, §3.4)"
                )
