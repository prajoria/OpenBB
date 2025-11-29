"""Cached earnings_call_transcript model for FMP."""

from openbb_fmp.models.earnings_call_transcript import FMPEarningsCallTranscriptFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP earnings_call_transcript fetcher
FMPCachedEarningsCallTranscriptFetcher = create_cached_fetcher_class(
    FMPEarningsCallTranscriptFetcher,
    "earnings_call_transcript"
)
