"""Complementary market data services for fmp_cached."""

from .free_yield_service import get_latest_us10y_rate, get_us10y_series

__all__ = ["get_us10y_series", "get_latest_us10y_rate"]
