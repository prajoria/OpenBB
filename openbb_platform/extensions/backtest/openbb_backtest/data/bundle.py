"""fmp_cached data bundle: columnar store + point-in-time data layer (component 03).

Pure, dependency-light logic lives here so it can be unit-tested with synthetic
in-memory fixtures (no live MySQL, no parquet on disk):

- :func:`compute_adj_factor`  — corporate-action back-adjustment (design §3).
- :func:`availability_date`   — point-in-time fundamentals lagging (design §2).
- :func:`build_ohlcv` / :func:`build_fundamentals` — calendar-aligned ingestion
  transforms (design §1, §2).
- :func:`universe_at`         — survivorship-safe point-in-time constituents (§3).

The :class:`Bundle` reader implements the ``DataFeed`` protocol with a bounded
``history`` (no future bars) and an as-of fundamentals join, plus an atomic
parquet ``save``/``load``. :class:`BundleIngestor` drives the cache-first
ingest; :class:`FmpCachedReader` is the live ``openbb_fmp_cache`` MySQL source
(exercised behind the ``integration`` marker), while unit tests inject an
in-memory fake reader.

See ``docs/designs/backtest-design/03-data-bundle.md``.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from openbb_backtest.data.calendars import sessions_in_range

# Default reporting lags when an explicit filing date is unavailable (design §2).
_LAG_ANNUAL = timedelta(days=90)  # 10-K
_LAG_QUARTERLY = timedelta(days=45)  # 10-Q


@dataclass
class BundleMetadata:
    """Describes a persisted bundle (written to ``metadata.json``)."""

    name: str
    symbols: list[str]
    calendar: str
    start: str | None = None
    end: str | None = None
    ingested_at: str | None = None
    has_fundamentals: bool = False
    extra: dict = field(default_factory=dict)


def reporting_lag(period_type: str | None) -> timedelta:
    """Return the default availability lag for a filing ``period_type``.

    Annual filings (``10-K``) lag 90 days; everything else (``10-Q`` and
    unknown) lags 45 days. Used only when ``filing_date`` is missing.
    """
    pt = (period_type or "").upper()
    if "K" in pt:
        return _LAG_ANNUAL
    return _LAG_QUARTERLY


def availability_date(
    filing_date: date | None,
    period_end: date,
    period_type: str | None = None,
) -> date:
    """Return the point-in-time availability date for a fundamentals record.

    Prefers the explicit ``filing_date``; otherwise falls back to
    ``period_end + reporting_lag(period_type)`` (design §2). The result is the
    earliest date a backtest is allowed to *see* this record, preventing
    look-ahead from restated or late-filed fundamentals.
    """
    if filing_date is not None:
        return filing_date
    return period_end + reporting_lag(period_type)


def build_fundamentals(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert raw filings into the point-in-time long form (design §2).

    ``raw`` carries ``symbol``, ``period_end``, ``field``, ``value`` and the
    optional ``filing_date``/``period_type`` used to derive availability. The
    output is the ``symbol, available_date, field, value`` shape the
    :class:`Bundle` as-of join expects, so restated values (later
    ``available_date``) never leak backward.
    """
    cols = ["symbol", "available_date", "field", "value"]
    if raw is None or raw.empty:
        return pd.DataFrame({c: [] for c in cols})

    available = []
    for _, row in raw.iterrows():
        filing = row.get("filing_date")
        filing = (
            None if filing is None or pd.isna(filing) else pd.Timestamp(filing).date()
        )
        period_end = pd.Timestamp(row["period_end"]).date()
        available.append(availability_date(filing, period_end, row.get("period_type")))

    out = pd.DataFrame(
        {
            "symbol": raw["symbol"].to_numpy(),
            "available_date": pd.to_datetime(available),
            "field": raw["field"].to_numpy(),
            "value": pd.to_numeric(raw["value"], errors="coerce").to_numpy(),
        }
    )
    return out[cols]


def compute_adj_factor(
    sessions: pd.DatetimeIndex,
    closes: np.ndarray,
    splits: pd.DataFrame,
    dividends: pd.DataFrame,
) -> np.ndarray:
    """Compute a cumulative back-adjustment factor aligned to ``sessions``.

    The factor is applied *backward* from the most recent session so the latest
    price equals the unadjusted close (``factor[-1] == 1.0``) — design §3.

    Parameters
    ----------
    sessions
        Trading sessions, ascending, aligned 1:1 with ``closes``.
    closes
        Raw (unadjusted) closing prices.
    splits
        Columns ``ex_date`` and ``ratio`` (e.g. ``2.0`` for a 2-for-1 split).
        Sessions strictly before ``ex_date`` are scaled by ``1 / ratio``.
    dividends
        Columns ``ex_date`` and ``amount`` (cash per share). Sessions strictly
        before ``ex_date`` are scaled by ``1 - amount / prior_close`` where
        ``prior_close`` is the close on the last session before ``ex_date``.

    Returns
    -------
    numpy.ndarray
        Multiplicative factor; ``closes * factor`` yields the adjusted series.
    """
    sessions = pd.DatetimeIndex(sessions)
    closes = np.asarray(closes, dtype=float)
    factor = np.ones(len(sessions), dtype=float)

    # Splits are multiplicative: pre-split sessions scale down by 1 / ratio.
    for ex_date, raw_ratio in zip(splits["ex_date"], splits["ratio"]):
        ratio = float(raw_ratio)
        if ratio == 0.0:
            continue
        factor[sessions < pd.Timestamp(ex_date)] /= ratio

    # Cash dividends: pre-ex sessions scale by (1 - amount / prior_close).
    for ex_date, raw_amount in zip(dividends["ex_date"], dividends["amount"]):
        prior = sessions < pd.Timestamp(ex_date)
        if not prior.any():
            continue
        prior_close = closes[prior][-1]
        if prior_close <= 0:
            continue
        factor[prior] *= 1.0 - float(raw_amount) / prior_close

    return factor


def universe_at(constituents: pd.DataFrame, when: pd.Timestamp) -> list[str]:
    """Return the point-in-time constituent set active at ``when`` (design §3).

    ``constituents`` carries ``symbol``, ``from_date`` and ``thru_date`` (the
    last column ``NaT`` for still-active members). A symbol is a member iff
    ``from_date <= when`` and (``thru_date`` is null or ``thru_date >= when``).

    This mitigates survivorship bias: names that were removed or delisted after
    ``when`` are retained, and names that joined later are excluded — so a
    backtest universe reflects what was actually investable on that date.
    """
    when = pd.Timestamp(when)
    frm = pd.to_datetime(constituents["from_date"])
    thru = pd.to_datetime(constituents["thru_date"])
    active = (frm <= when) & (thru.isna() | (thru >= when))
    return constituents.loc[active, "symbol"].tolist()


_OHLCV_COLUMNS = [
    "symbol",
    "session",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adj_factor",
]


def build_ohlcv(
    raw: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    splits: pd.DataFrame,
    dividends: pd.DataFrame,
) -> pd.DataFrame:
    """Align one symbol's raw OHLCV to ``sessions`` and attach ``adj_factor``.

    Implements the per-symbol ingestion transform (design §1, §3):

    - Reindexes raw rows onto the full calendar ``sessions``. Genuine gaps stay
      ``NaN`` for price/volume — they are **never** forward-filled (design §1).
    - Computes the cumulative corporate-action ``adj_factor`` from ``splits`` and
      ``dividends`` on every session, back-adjusted so the latest factor is 1.0.

    The ``raw`` frame must carry a single ``symbol`` and a ``date`` column.
    """
    symbol = raw["symbol"].iloc[0] if len(raw) else None
    sessions = pd.DatetimeIndex(sessions)

    indexed = raw.set_index(pd.DatetimeIndex(raw["date"])).sort_index()
    aligned = indexed.reindex(sessions)

    out = pd.DataFrame(
        {
            "symbol": symbol,
            "session": sessions,
            "open": aligned["open"].to_numpy(),
            "high": aligned["high"].to_numpy(),
            "low": aligned["low"].to_numpy(),
            "close": aligned["close"].to_numpy(),
            "volume": aligned["volume"].to_numpy(),
        }
    )

    # adj_factor needs a price on every session; forward/back-fill close for the
    # factor math only (never written back to the price columns).
    factor_close = aligned["close"].ffill().bfill().to_numpy()
    out["adj_factor"] = compute_adj_factor(sessions, factor_close, splits, dividends)
    return out[_OHLCV_COLUMNS]


class Bundle:
    """In-memory columnar reader implementing the ``DataFeed`` protocol.

    Holds long-form OHLCV (and optional point-in-time fundamentals) plus a
    trading calendar. The on-disk parquet store is loaded into the same frames,
    so this single reader backs both the synthetic-fixture tests and live
    bundles. Crucially, :meth:`history` enforces a hard upper bound at ``end``
    so **no future bar is ever returned** (design §1).
    """

    def __init__(
        self,
        ohlcv: pd.DataFrame,
        fundamentals: pd.DataFrame | None = None,
        calendar: str = "XNYS",
    ) -> None:
        self._ohlcv = ohlcv.sort_values(["symbol", "session"]).reset_index(drop=True)
        self._fundamentals = (
            fundamentals.sort_values(["symbol", "field", "available_date"]).reset_index(
                drop=True
            )
            if fundamentals is not None
            else None
        )
        self._calendar = calendar

    @classmethod
    def from_frames(
        cls,
        ohlcv: pd.DataFrame,
        fundamentals: pd.DataFrame | None = None,
        calendar: str = "XNYS",
    ) -> Bundle:
        """Construct a :class:`Bundle` directly from in-memory frames."""
        return cls(ohlcv=ohlcv, fundamentals=fundamentals, calendar=calendar)

    def history(
        self, symbols: list[str], end: pd.Timestamp, lookback: int
    ) -> pd.DataFrame:
        """Return up to ``lookback`` bars per symbol ending at ``end`` inclusive.

        Bars strictly after ``end`` are never returned — the look-ahead guard.
        """
        end = pd.Timestamp(end)
        frame = self._ohlcv
        mask = frame["symbol"].isin(symbols) & (frame["session"] <= end)
        visible = frame.loc[mask]
        # Keep only the trailing ``lookback`` sessions per symbol.
        trimmed = (
            visible.sort_values("session")
            .groupby("symbol", group_keys=False)
            .tail(lookback)
        )
        return trimmed.reset_index(drop=True)

    def sessions(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
        """Return trading sessions in ``[start, end]`` from the bundle calendar."""
        return sessions_in_range(start, end, self._calendar)

    def as_of(self, symbol: str, field: str, when: pd.Timestamp) -> float | None:
        """Return the latest ``field`` value available for ``symbol`` at ``when``.

        Implements the point-in-time as-of join (design §2): only records whose
        ``available_date <= when`` are visible, so restated values carrying a
        later ``available_date`` never leak backward. Returns ``None`` when no
        record is yet available.
        """
        if self._fundamentals is None:
            return None
        when = pd.Timestamp(when)
        f = self._fundamentals
        mask = (
            (f["symbol"] == symbol)
            & (f["field"] == field)
            & (f["available_date"] <= when)
        )
        visible = f.loc[mask]
        if visible.empty:
            return None
        latest = visible.sort_values("available_date").iloc[-1]
        return float(latest["value"])

    def save(self, root: str | Path, name: str = "default") -> BundleMetadata:
        """Persist the bundle to ``root/name`` atomically and return its metadata.

        Writes parquet partitions to a sibling temp directory then renames it
        into place, so a concurrent reader never observes a partial bundle and a
        re-ingest under the same ``name`` fully replaces the prior contents
        (design §1, atomic refresh).

        ``name`` is treated as an in-root subpath: absolute paths and ``..``
        segments raise ``PathTraversalError`` (defends the ``shutil.rmtree``
        below from being pointed outside ``root`` — see bd-cwer / bd-9cdg).
        """
        # pylint: disable=import-outside-toplevel
        from openbb_core.app.paths import PathTraversalError, safe_join

        root_path = Path(root)
        root_path.mkdir(parents=True, exist_ok=True)
        dest = safe_join(root_path, name)
        # Extra guard: reject ``name`` values that collapse back to root
        # itself (e.g. ``'a/..'``, ``'foo/../.'``). safe_join accepts them
        # (root is trivially relative to itself), but the ``.tmp`` sibling
        # below would then land in root's parent — outside the sandbox —
        # restoring the same arbitrary-write/delete primitive this branch
        # closes. See regression test test_bundle_save_rejects_names_
        # collapsing_to_root.
        if dest == root_path.resolve():
            raise PathTraversalError(
                f"Bundle name {name!r} collapses to the root directory; "
                f"a bundle name must refer to a strict subpath of root"
            )
        # ``.tmp`` sibling must also stay inside root; build it from the
        # resolved dest's parent to avoid a second traversal-injection point.
        tmp = dest.parent / f".{dest.name}.tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)

        self._ohlcv.to_parquet(tmp / "ohlcv.parquet", index=False)
        if self._fundamentals is not None:
            self._fundamentals.to_parquet(tmp / "fundamentals.parquet", index=False)

        symbols = sorted(self._ohlcv["symbol"].unique().tolist())
        sessions = self._ohlcv["session"]
        meta = BundleMetadata(
            name=name,
            symbols=symbols,
            calendar=self._calendar,
            start=str(pd.Timestamp(sessions.min()).date()) if len(sessions) else None,
            end=str(pd.Timestamp(sessions.max()).date()) if len(sessions) else None,
            ingested_at=pd.Timestamp.utcnow().isoformat(),
            has_fundamentals=self._fundamentals is not None,
        )
        (tmp / "metadata.json").write_text(json.dumps(asdict(meta), indent=2))

        # Atomic swap: remove any existing bundle, then rename temp into place.
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
        return meta

    @classmethod
    def load(cls, root: str | Path, name: str = "default") -> Bundle:
        """Load a persisted bundle written by :meth:`save`.

        ``name`` must resolve inside ``root`` (see :meth:`save`); traversal
        attempts raise ``PathTraversalError``. ``name`` values that collapse
        back to ``root`` itself are also rejected (see :meth:`save`).
        """
        # pylint: disable=import-outside-toplevel
        from openbb_core.app.paths import PathTraversalError, safe_join

        root_path = Path(root)
        path = safe_join(root_path, name)
        if path == root_path.resolve():
            raise PathTraversalError(
                f"Bundle name {name!r} collapses to the root directory; "
                f"a bundle name must refer to a strict subpath of root"
            )
        meta = json.loads((path / "metadata.json").read_text())
        ohlcv = pd.read_parquet(path / "ohlcv.parquet")
        fundamentals = None
        if meta.get("has_fundamentals"):
            fundamentals = pd.read_parquet(path / "fundamentals.parquet")
        return cls(
            ohlcv=ohlcv,
            fundamentals=fundamentals,
            calendar=meta.get("calendar", "XNYS"),
        )


class BundleIngestor:
    """Materializes the fmp_cached MySQL cache into a columnar bundle.

    The ingestor is deliberately split from its data source: it depends on a
    ``reader`` object exposing ``equity_historical(symbols, start, end)``,
    ``splits(symbols)`` and ``dividends(symbols)``. The live implementation reads
    the existing ``openbb_fmp_cache`` tables (no new download path); unit tests
    inject an in-memory fake. This keeps the calendar-alignment and
    corporate-action logic (design §1, §3) testable without a database.
    """

    def __init__(self, reader, calendar: str = "XNYS") -> None:
        self._reader = reader
        self._calendar = calendar

    def ingest(
        self,
        symbols: list[str],
        start: date,
        end: date,
        name: str = "default",
        root: str | Path = ".openbb_backtest/bundles",
    ) -> BundleMetadata:
        """Read the cache, align to the calendar, adjust, and persist a bundle.

        Returns the :class:`BundleMetadata` written alongside the parquet store.
        """
        sessions = sessions_in_range(start, end, self._calendar)

        raw = self._reader.equity_historical(symbols, start, end)
        all_splits = self._reader.splits(symbols)
        all_divs = self._reader.dividends(symbols)

        per_symbol = []
        for sym in symbols:
            sym_raw = raw[raw["symbol"] == sym]
            if sym_raw.empty:
                continue
            sym_splits = _select(all_splits, sym, ["ex_date", "ratio"])
            sym_divs = _select(all_divs, sym, ["ex_date", "amount"])
            per_symbol.append(build_ohlcv(sym_raw, sessions, sym_splits, sym_divs))

        ohlcv = (
            pd.concat(per_symbol, ignore_index=True)
            if per_symbol
            else pd.DataFrame(columns=_OHLCV_COLUMNS)
        )

        # Point-in-time fundamentals are optional: only readers that expose a
        # ``fundamentals(symbols, start, end)`` method contribute them (design §2).
        fundamentals = None
        if hasattr(self._reader, "fundamentals"):
            raw_fund = self._reader.fundamentals(symbols, start, end)
            built = build_fundamentals(raw_fund)
            if not built.empty:
                fundamentals = built

        return Bundle(
            ohlcv=ohlcv, fundamentals=fundamentals, calendar=self._calendar
        ).save(root, name=name)


def _select(frame: pd.DataFrame, symbol: str, columns: list[str]) -> pd.DataFrame:
    """Return ``columns`` of ``frame`` for ``symbol`` (empty frame if absent)."""
    if frame is None or frame.empty or "symbol" not in frame:
        return pd.DataFrame({c: [] for c in columns})
    sub = frame[frame["symbol"] == symbol]
    return sub[columns].reset_index(drop=True)


def _coerce_json(value) -> dict:
    """Parse a possibly-stringified ``data_json`` cell into a dict (``{}`` on fail)."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def rows_to_ohlcv(rows: list[dict]) -> pd.DataFrame:
    """Map ``equity_historical`` DictCursor rows to a typed OHLCV frame."""
    cols = ["symbol", "date", "open", "high", "low", "close", "volume"]
    if not rows:
        return pd.DataFrame({c: [] for c in cols})
    frame = pd.DataFrame(rows)[cols].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    for c in ("open", "high", "low", "close", "volume"):
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    return frame.reset_index(drop=True)


def rows_to_splits(rows: list[dict]) -> pd.DataFrame:
    """Map ``calendar_splits`` rows to ``symbol, ex_date, ratio``.

    The split ratio is ``numerator / denominator``, read from the ``data_json``
    payload (the generic calendar tables keep FMP-specific fields there).
    """
    out: dict[str, list] = {"symbol": [], "ex_date": [], "ratio": []}
    for row in rows:
        payload = _coerce_json(row.get("data_json"))
        numerator = payload.get("numerator", row.get("numerator"))
        denominator = payload.get("denominator", row.get("denominator"))
        if not numerator or not denominator:
            continue
        out["symbol"].append(row.get("symbol"))
        out["ex_date"].append(pd.Timestamp(row.get("date")))
        out["ratio"].append(float(numerator) / float(denominator))
    return pd.DataFrame(out)


def rows_to_dividends(rows: list[dict]) -> pd.DataFrame:
    """Map ``calendar_dividend`` rows to ``symbol, ex_date, amount``."""
    out: dict[str, list] = {"symbol": [], "ex_date": [], "amount": []}
    for row in rows:
        payload = _coerce_json(row.get("data_json"))
        amount = payload.get("amount", row.get("amount"))
        if amount is None:
            continue
        out["symbol"].append(row.get("symbol"))
        out["ex_date"].append(pd.Timestamp(row.get("date")))
        out["amount"].append(float(amount))
    return pd.DataFrame(out)


# Non-value columns in fundamentals tables that must never become a "field".
_FUNDAMENTALS_META = {
    "id",
    "symbol",
    "date",
    "period",
    "period_type",
    "filing_date",
    "currency",
    "reported_currency",
    "cik",
    "calendar_year",
    "link",
    "final_link",
    "accepted_date",
    "data_json",
    "additional_fields",
    "cached_at",
    "updated_at",
    "is_valid",
}


def rows_to_fundamentals(rows: list[dict]) -> pd.DataFrame:
    """Unpivot wide fundamentals rows to long PIT-input form.

    Returns ``symbol, period_end, filing_date, period_type, field, value`` with
    one row per numeric statement field. Non-numeric and metadata columns are
    dropped. The result feeds :func:`build_fundamentals` (design §2).
    """
    cols = ["symbol", "period_end", "filing_date", "period_type", "field", "value"]
    out: dict[str, list] = {c: [] for c in cols}
    for row in rows:
        period_end = row.get("date")
        filing_date = row.get("filing_date")
        period_type = row.get("period") or row.get("period_type")
        for key, value in row.items():
            if key in _FUNDAMENTALS_META or value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            out["symbol"].append(row.get("symbol"))
            out["period_end"].append(pd.Timestamp(period_end))
            out["filing_date"].append(
                pd.Timestamp(filing_date) if filing_date else pd.NaT
            )
            out["period_type"].append(period_type)
            out["field"].append(key)
            out["value"].append(numeric)
    return pd.DataFrame(out)


class FmpCachedReader:
    """Reads the existing ``openbb_fmp_cache`` MySQL tables for the ingestor.

    Honours the cache-first rule (design §1): it only *reads* the tables the
    fmp_cached provider already populates — no new download path. The SQL
    executor is injected so unit tests drive the row-mapping with synthetic
    DictCursor rows; in production it defaults to the provider's
    ``execute_query``. Live-DB behaviour is covered behind the ``integration``
    marker.
    """

    def __init__(self, execute=None) -> None:
        if execute is None:
            from openbb_fmp_cached.utils.database import execute_query

            execute = execute_query
        self._execute = execute

    def equity_historical(
        self, symbols: list[str], start: date, end: date
    ) -> pd.DataFrame:
        placeholders = ", ".join(["%s"] * len(symbols))
        # placeholders are literal "%s" markers; all values are parameterized.
        query = (
            "SELECT symbol, date, open, high, low, close, volume "  # noqa: S608
            f"FROM equity_historical WHERE symbol IN ({placeholders}) "
            "AND date BETWEEN %s AND %s AND interval_type = '1d' "
            "ORDER BY symbol, date"
        )
        rows = self._execute(query, tuple(symbols) + (str(start), str(end)))
        return rows_to_ohlcv(list(rows or []))

    def splits(self, symbols: list[str]) -> pd.DataFrame:
        placeholders = ", ".join(["%s"] * len(symbols))
        query = (
            "SELECT symbol, date, data_json FROM calendar_splits "  # noqa: S608
            f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date"
        )
        rows = self._execute(query, tuple(symbols))
        return rows_to_splits(list(rows or []))

    def dividends(self, symbols: list[str]) -> pd.DataFrame:
        placeholders = ", ".join(["%s"] * len(symbols))
        # The dividend amount lives in data_json (no top-level ``amount`` column).
        query = (
            "SELECT symbol, date, data_json FROM calendar_dividend "  # noqa: S608
            f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date"
        )
        rows = self._execute(query, tuple(symbols))
        return rows_to_dividends(list(rows or []))

    def fundamentals(self, symbols: list[str], start: date, end: date) -> pd.DataFrame:
        """Read statement tables and return long PIT-input fundamentals.

        Pulls the income statement, balance sheet and cash-flow tables the
        fmp_cached provider already populates, unpivots their numeric columns,
        and tags each record with its period/filing dates for the as-of join.
        """
        placeholders = ", ".join(["%s"] * len(symbols))
        frames = []
        for table in ("income_statement", "balance_sheet", "cash_flow"):
            query = (
                f"SELECT * FROM {table} "  # noqa: S608
                f"WHERE symbol IN ({placeholders}) AND date BETWEEN %s AND %s "
                "ORDER BY symbol, date"
            )
            rows = self._execute(query, tuple(symbols) + (str(start), str(end)))
            frames.append(rows_to_fundamentals(list(rows or [])))
        non_empty = [f for f in frames if not f.empty]
        if not non_empty:
            return rows_to_fundamentals([])
        return pd.concat(non_empty, ignore_index=True)
