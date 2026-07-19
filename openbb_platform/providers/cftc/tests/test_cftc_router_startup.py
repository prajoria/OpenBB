"""Regression tests for cftc_router startup lifespan hardening. #874."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import pytest


class TestBuildChoicesUpstreamFailure:
    """``build_choices`` must degrade gracefully rather than crash the API on
    upstream fetch failure. Silent-crash previously killed uvicorn startup
    whenever publicreporting.cftc.gov returned 503 or non-JSON."""

    def test_build_choices_swallows_upstream_exception_and_logs(self, caplog):
        """A raising fetch_data leaves COT_CHOICES empty and logs an error."""
        # Import here so the patch below binds against the imported module
        from openbb_cftc.models import cot_search as _cot_search
        from openbb_cftc import cftc_router as _router

        # Save + restore module-level state (avoid leaking across tests).
        prev = _router.COT_CHOICES

        async def _err(*a, **kw):
            raise Exception("simulated CFTC upstream 503")

        try:
            with caplog.at_level(logging.ERROR, logger="openbb_cftc.cftc_router"):
                with patch.object(
                    _cot_search.CftcCotSearchFetcher, "fetch_data", side_effect=_err
                ):
                    asyncio.run(_router.build_choices())

            # 1. API did NOT crash (function returned normally)
            # 2. State degraded to empty list
            assert _router.COT_CHOICES == []
            # 3. Failure was logged
            error_records = [
                r for r in caplog.records if r.levelno == logging.ERROR
            ]
            assert error_records, "expected at least one ERROR log record"
            combined = "\n".join(r.getMessage() for r in error_records)
            assert "cftc.build_choices" in combined
            assert "simulated CFTC upstream 503" in combined
        finally:
            _router.COT_CHOICES = prev

    def test_build_choices_populates_on_success(self):
        """Happy path: successful fetch populates COT_CHOICES."""
        from openbb_cftc import cftc_router as _router
        from openbb_cftc.models import cot_search as _cot_search

        prev = _router.COT_CHOICES

        class _Row:
            name = " Corn "
            code = " 002602 "
            subcategory = " Agricultural "

        async def _ok(*a, **kw):
            return [_Row()]

        try:
            with patch.object(
                _cot_search.CftcCotSearchFetcher, "fetch_data", side_effect=_ok
            ):
                asyncio.run(_router.build_choices())

            assert len(_router.COT_CHOICES) == 1
            entry = _router.COT_CHOICES[0]
            assert entry["label"] == "Corn"
            assert entry["value"] == "002602"
        finally:
            _router.COT_CHOICES = prev


class TestBuildChoicesNullFields:
    """Regression #902: build_choices must handle null fields per record
    without crashing the entire API startup. The pydantic model declares
    ``subcategory: str | None`` etc.; a naive ``d.subcategory.strip()``
    on a real-world record with subcategory=None raised
    ``AttributeError: 'NoneType' object has no attribute 'strip'`` and
    killed uvicorn."""

    def test_null_subcategory_does_not_crash(self):
        """A record with subcategory=None is emitted with empty description."""
        from openbb_cftc import cftc_router as _router
        from openbb_cftc.models import cot_search as _cot_search

        prev = _router.COT_CHOICES

        class _Row:
            name = "Bitcoin"
            code = "133741"
            subcategory = None  # <-- this used to crash startup (#902)

        async def _ok(*a, **kw):
            return [_Row()]

        try:
            with patch.object(
                _cot_search.CftcCotSearchFetcher, "fetch_data", side_effect=_ok
            ):
                asyncio.run(_router.build_choices())

            assert len(_router.COT_CHOICES) == 1
            entry = _router.COT_CHOICES[0]
            assert entry["label"] == "Bitcoin"
            assert entry["value"] == "133741"
            # Description contains only the code (subcategory blank).
            assert entry["extraInfo"]["description"] == "  | 133741"
        finally:
            _router.COT_CHOICES = prev

    def test_null_name_or_code_skips_record(self):
        """A record with null name OR code is skipped (unusable as a choice)
        rather than crashing or producing an empty-string label/value."""
        from openbb_cftc import cftc_router as _router
        from openbb_cftc.models import cot_search as _cot_search

        prev = _router.COT_CHOICES

        class _Good:
            name = "Corn"
            code = "002602"
            subcategory = "Agricultural"

        class _MissingName:
            name = None
            code = "999999"
            subcategory = "Bogus"

        class _MissingCode:
            name = "Gold"
            code = None
            subcategory = "Precious"

        async def _ok(*a, **kw):
            return [_Good(), _MissingName(), _MissingCode()]

        try:
            with patch.object(
                _cot_search.CftcCotSearchFetcher, "fetch_data", side_effect=_ok
            ):
                asyncio.run(_router.build_choices())

            # Only the well-formed row survives.
            assert len(_router.COT_CHOICES) == 1
            assert _router.COT_CHOICES[0]["value"] == "002602"
        finally:
            _router.COT_CHOICES = prev

    def test_parse_path_exception_degrades_and_logs(self, caplog):
        """A record-parsing exception (not from fetch) also degrades to
        empty + logs — so any future field-shape regression can't kill
        the whole REST API. Mirrors the fetch-path degrade pattern from
        #874."""
        from openbb_cftc import cftc_router as _router
        from openbb_cftc.models import cot_search as _cot_search

        prev = _router.COT_CHOICES

        class _Bomb:
            @property
            def name(self):
                raise RuntimeError("simulated field-access explosion")

            code = "X"
            subcategory = "Y"

        async def _ok(*a, **kw):
            return [_Bomb()]

        try:
            with caplog.at_level(logging.ERROR, logger="openbb_cftc.cftc_router"):
                with patch.object(
                    _cot_search.CftcCotSearchFetcher, "fetch_data", side_effect=_ok
                ):
                    asyncio.run(_router.build_choices())

            # API did NOT crash; COT_CHOICES degraded.
            assert _router.COT_CHOICES == []
            error_records = [
                r for r in caplog.records if r.levelno == logging.ERROR
            ]
            assert error_records, "expected at least one ERROR log record"
            combined = "\n".join(r.getMessage() for r in error_records)
            assert "cftc.build_choices" in combined
            assert "record parsing failed" in combined
        finally:
            _router.COT_CHOICES = prev
