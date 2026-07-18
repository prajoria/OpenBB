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
