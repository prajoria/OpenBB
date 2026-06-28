"""Static GICS segment map and placeholder segment resolver (PRD §10, §9.2).

The first pipeline stage maps **GICS sectors -> universes** (PRD §9.2 / §10). This
module holds the canonical mapping of the 11 GICS sectors to their benchmark
sector-SPDR ETFs and turns that mapping into :class:`SegmentConfig` rows.

The resolver here is a *placeholder*: it emits one :class:`SegmentConfig` per
sector with the benchmark ETF filled in, but does not yet expand each segment
into a live constituent universe (that arrives with the universe resolver,
issue #69).
"""

from __future__ import annotations

from openbb_techtrade.models import SegmentConfig

# The 11 GICS sectors -> benchmark sector-SPDR ETF (PRD §10, lines 604-605).
# Insertion order is the canonical segment order used throughout the engine.
GICS_SECTOR_ETFS: dict[str, str] = {
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Energy": "XLE",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}


def list_segments(
    universe_source: str = "etf_holdings",
    rank_metric: str = "pct_change",
    top_n: int = 10,
) -> list[SegmentConfig]:
    """Build one :class:`SegmentConfig` per GICS sector (PRD §9.2, §10).

    This is the placeholder resolver: each returned config carries the sector's
    benchmark ETF from :data:`GICS_SECTOR_ETFS`, but the live universe is not yet
    expanded (that is the universe resolver, issue #69).

    Parameters
    ----------
    universe_source : str, optional
        How each segment universe is resolved. One of ``"etf_holdings"``,
        ``"constituent_list"``, or ``"screener"``. Defaults to ``"etf_holdings"``.
    rank_metric : str, optional
        Metric used to rank movers within a segment. One of ``"pct_change"``,
        ``"volume"``, ``"gap"``, or ``"rel_volume"``. Defaults to ``"pct_change"``.
    top_n : int, optional
        Number of top movers to keep per segment. Defaults to ``10``.

    Returns
    -------
    list[SegmentConfig]
        One config per GICS sector, in canonical :data:`GICS_SECTOR_ETFS` order,
        each with ``benchmark_etf`` set from the map and the given knobs applied.
    """
    return [
        SegmentConfig(
            segment=segment,
            universe_source=universe_source,
            benchmark_etf=etf,
            rank_metric=rank_metric,
            top_n=top_n,
        )
        for segment, etf in GICS_SECTOR_ETFS.items()
    ]
