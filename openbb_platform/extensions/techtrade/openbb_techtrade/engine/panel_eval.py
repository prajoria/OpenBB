"""Panel-evaluation harness (bd-7ct.10, bd-0st).

Computes the **Information Coefficient (IC)** — the Spearman rank
correlation between a vote series and forward returns — so every
future family PR (bd-luy/40v/z43/alj) can prove *empirically* that a
new indicator adds predictive value before it ships.

**Why IC and not linear correlation?** Rank correlation is invariant
to monotonic transforms. A vote of `+0.7` and a vote of `+0.9` both
rank "very bullish"; Pearson's r would care about the specific
magnitude difference, Spearman only cares about the ordering. Vote
mappers are already clipped/thresholded (see ``confluence.py``), so
the linear-magnitude information is mostly noise — rank is the honest
signal.

**Why this matters (design spec §10 C4 / R1):** Breiman's ensemble
variance reduction is about decorrelated **errors relative to the
target**, not decorrelated **features**. Two indicators can be
mutually uncorrelated yet both carry ~0 predictive information
(IC ≈ 0); averaging them under the simple mean fold just adds noise
and dilutes the strong votes. The R1 acceptance gate — "no vote
ships without demonstrated *incremental* forward IC" — converts the
confluence expansion from "more indicators because theory says
decorrelation helps" into "more indicators *that are proven to help*."

**References:**

- Richard C. Grinold, *"The Fundamental Law of Active Management"*
  (Journal of Portfolio Management, 1989) — IR = IC · √breadth. IC
  is the per-signal skill; breadth is the count of **independent**
  bets. Everything in techtrade derives from one OHLCV series, so
  effective breadth ≪ nominal vote count.
- David Bailey & Marcos López de Prado, *"Pseudo-Mathematics and
  Financial Charlatanism: The Effects of Backtest Overfitting on
  Out-of-Sample Performance"* (Notices of the AMS, 2014) — why
  degrees-of-freedom expansion without an OOS gate produces
  false-positive backtests. IC on a held-out basket is the cheapest
  guard against this failure mode.

Full context: docs/superpowers/plans/2026-07-08-bd-7ct-confluence-foundation.md
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

#: Default forward-return horizon in trading bars (1 business week).
#: Semantic constant — changing this shifts every IC in the baseline
#: report (bd-7ct.11), which is what family PRs diff against.
DEFAULT_FORWARD_BARS: int = 5


@dataclass(frozen=True, slots=True)
class ICResult:
    """Result of a single :func:`compute_information_coefficient` call.

    Attributes
    ----------
    coefficient : float
        Spearman rank correlation of votes vs forward returns, in
        ``[-1, +1]``. ``NaN`` when correlation is undefined (zero
        variance on either side, or fewer than 2 valid pairs).
    p_value : float
        Two-tailed p-value from the Spearman test. ``NaN`` when
        coefficient is ``NaN``. Family PRs treat ``p < 0.05`` as
        "statistically significant on this symbol" — the pooled
        cross-symbol significance is a separate downstream check.
    n_samples : int
        Number of (vote, forward-return) pairs that fed the
        correlation, AFTER shift + NaN-dropping + index alignment.
    n_dropped_nan : int
        Count of pairs dropped because either the vote or the
        forward-shifted return was ``NaN``. Includes warm-up NaNs
        from short indicators (RSI-14 has 13, Ichimoku ~78) and the
        trailing ``forward_bars`` bars that lack a forward return.
    backend : Literal["scipy", "fallback"]
        Which correlation implementation produced ``coefficient`` /
        ``p_value``. ``"scipy"`` uses :func:`scipy.stats.spearmanr`
        (exact t-distribution p-value); ``"fallback"`` uses rank-
        Pearson with a normal-approximation p-value when SciPy is
        unavailable. iter-1 silent-hunter F1 fix: baseline reports
        (bd-7ct.11) generated on a slim install must be diff-able
        against family-PR reports on a full install — surfacing the
        backend lets downstream analysis tell them apart instead of
        silently comparing apples to oranges.
    """

    coefficient: float
    p_value: float
    n_samples: int
    n_dropped_nan: int
    backend: str = "scipy"


def compute_information_coefficient(
    votes: pd.Series,
    returns: pd.Series,
    *,
    forward_bars: int = DEFAULT_FORWARD_BARS,
) -> ICResult:
    """Spearman rank IC between ``votes[t]`` and ``returns[t..t+forward_bars]``.

    Parameters
    ----------
    votes : pd.Series
        Per-bar directional vote series. Should be indexed on the same
        DatetimeIndex as ``returns``; the two are aligned on the
        intersection. Warm-up ``NaN`` values are tolerated (dropped).
    returns : pd.Series
        Per-bar return series (typically ``close.pct_change()``).
    forward_bars : int, keyword-only, default ``DEFAULT_FORWARD_BARS`` (5)
        Number of bars forward the return is shifted. Must be strictly
        positive — zero would correlate a vote with its own bar's
        return (no forecast), negative would introduce look-ahead bias.

    Returns
    -------
    ICResult
        Populated dataclass. On any degenerate input (zero variance,
        no aligned pairs, fewer than 2 valid samples), ``coefficient``
        and ``p_value`` are ``NaN`` but ``n_samples`` / ``n_dropped_nan``
        remain accurate so callers can diagnose why.

    Raises
    ------
    ValueError
        If ``forward_bars`` is not strictly positive. This is defensive:
        the mistake is easy to make (negative sign, or "correlate with
        today's return") and always a bug, so fail loud at the seam.

    Notes
    -----
    Uses ``scipy.stats.spearmanr``. If SciPy is unavailable in the
    environment (edge case for slim installs), falls back to a manual
    rank-based Pearson computation on the aligned series — the result
    is numerically identical for tie-free data.
    """
    if forward_bars <= 0:
        raise ValueError(
            f"forward_bars must be strictly positive; got {forward_bars}. "
            f"Zero would correlate a vote with its own bar's return "
            f"(no forecast); negative would introduce look-ahead bias."
        )

    # Align on the intersection of indices. `.reindex()` preserves the
    # union with NaN fills; we want the intersection so misaligned
    # timestamps count as "no data", not "zero vote".
    common_index = votes.index.intersection(returns.index)
    votes_aligned = votes.reindex(common_index)
    returns_aligned = returns.reindex(common_index)

    # Shift returns so `returns_shifted[t] = return_{t+forward_bars}`.
    # `.shift(-N)` puts future value at current index, per pandas.
    returns_shifted = returns_aligned.shift(-forward_bars)

    # Build the (vote, forward-return) DataFrame + drop any row with NaN
    # on either side. That set is the domain of the correlation.
    pair_frame = pd.DataFrame({"vote": votes_aligned, "ret": returns_shifted})
    n_before = len(pair_frame)
    clean_frame = pair_frame.dropna()
    n_samples = len(clean_frame)
    n_dropped = n_before - n_samples

    # Degenerate cases: too few samples, or zero variance on either side.
    if n_samples < 2:
        return ICResult(
            coefficient=float("nan"),
            p_value=float("nan"),
            n_samples=n_samples,
            n_dropped_nan=n_dropped,
        )
    if clean_frame["vote"].nunique() < 2 or clean_frame["ret"].nunique() < 2:
        # Zero variance on either side → correlation undefined.
        return ICResult(
            coefficient=float("nan"),
            p_value=float("nan"),
            n_samples=n_samples,
            n_dropped_nan=n_dropped,
        )

    try:
        from scipy.stats import spearmanr
    except ImportError:
        # iter-1 silent-hunter F1: log a WARNING when the SciPy fallback
        # fires so baseline reports generated on a slim install do not
        # silently disagree with family-PR reports on a full install.
        # The rank-Pearson math with normal-approx p-value is numerically
        # close to SciPy's exact t-distribution p-value for moderate n
        # (>30) but not byte-identical — the `backend` field on the
        # returned ICResult surfaces which path ran so downstream analysis
        # can filter/segregate.
        _logger.warning(
            "compute_information_coefficient: SciPy unavailable — using "
            "rank-Pearson fallback with normal-approximation p-value "
            "(numerically close to spearmanr but not byte-identical; "
            "ICResult.backend='fallback' will identify these rows)."
        )
        # Fallback: rank both series and take Pearson correlation on
        # the ranks — numerically identical to Spearman for tie-free
        # data. p-value estimated via t-distribution transform of r.
        rho = float(clean_frame["vote"].rank().corr(clean_frame["ret"].rank()))
        # Fisher-transform-derived approximate p-value for Pearson r
        # under H0: rho = 0, using t = r * sqrt((n-2)/(1-r^2)).
        if abs(rho) >= 1.0:
            p_value = 0.0
        else:
            t_stat = rho * np.sqrt((n_samples - 2) / (1 - rho * rho))
            # Approximate as normal for moderate n; adequate for the
            # "is it statistically significant?" tick.
            from math import erfc, sqrt
            p_value = float(erfc(abs(t_stat) / sqrt(2)))
        return ICResult(
            coefficient=rho,
            p_value=p_value,
            n_samples=n_samples,
            n_dropped_nan=n_dropped,
            backend="fallback",
        )

    # SciPy is available — use it.
    result = spearmanr(clean_frame["vote"].values, clean_frame["ret"].values)
    return ICResult(
        coefficient=float(result.statistic),
        p_value=float(result.pvalue),
        n_samples=n_samples,
        n_dropped_nan=n_dropped,
        backend="scipy",
    )


# ============================================================================
# Shadow-mode logger (bd-7ct.12, bd-9yg)
#
# "Shadow mode" = compute both the classic and extended panels, ACT on the
# extended, LOG the divergence. Feature-toggle canary deployment for the
# confluence panel expansion — once family PRs (bd-luy/40v/z43/alj) land,
# shadow logs give us empirical divergence data before the flag defaults on.
#
# See design spec §D2 + §D8 and https://en.wikipedia.org/wiki/Feature_toggle
# ============================================================================


_logger = __import__("logging").getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ShadowDiff:
    """One row of shadow-mode divergence between classic and extended
    signals for a (symbol, as_of) pair.

    Attributes
    ----------
    symbol : str
        The symbol these two signals came from.
    as_of : str
        ISO-format date the signals were computed for.
    score_delta : float
        ``extended.score - classic.score``. Zero today (stubs pass-
        through); non-zero once family PRs diverge extended.
    vote_count_classic : int
        Number of votes in the classic signal.
    vote_count_extended : int
        Number of votes in the extended signal. Family PRs will
        widen this beyond ``vote_count_classic``.
    added_vote_names : list[str]
        Vote names present in extended but absent in classic. Empty
        today; family PRs add entries like ``aroon_osc``, ``mfi``.
    removed_vote_names : list[str]
        Vote names present in classic but absent in extended. Usually
        empty (expansion is additive) but retained for the rare
        case a family PR replaces a vote.
    per_family_score_delta : dict[str, float]
        ``family -> extended_family_mean - classic_family_mean``.
        Diagnoses which family drives a score divergence. Zero today.
    """

    symbol: str
    as_of: str
    score_delta: float
    vote_count_classic: int
    vote_count_extended: int
    added_vote_names: list[str]
    removed_vote_names: list[str]
    per_family_score_delta: dict[str, float]


def shadow_diff(classic_signal, extended_signal) -> ShadowDiff:
    """Compute the divergence between a classic and extended MoverSignal.

    Both inputs are expected to be built from the same underlying panel
    (same symbol, same as_of); the diff extracts the observable score
    and per-family votes that a downstream analyst would care about.

    Parameters
    ----------
    classic_signal : MoverSignal
        Signal produced with ``panel_config=PANEL_CLASSIC``.
    extended_signal : MoverSignal
        Signal produced with ``panel_config=PANEL_EXTENDED`` on the
        same panel + weights.

    Returns
    -------
    ShadowDiff
        Populated dataclass. Symbol / as_of come from the classic
        signal.

    Raises
    ------
    ValueError
        If ``classic_signal.symbol != extended_signal.symbol`` or the
        as_of dates disagree. iter-1 silent-hunter F2 fix: the previous
        docstring described the failure mode ("would happily persist
        mismatched rows and that's a bug we'd rather catch loudly")
        but the code didn't enforce it. Now it does — a call with
        mismatched (symbol, as_of) is a programming error at the
        caller layer and must fail loud at the seam, not silently
        canonicalise to the classic signal's identity.
    """
    if classic_signal.symbol != extended_signal.symbol:
        raise ValueError(
            f"shadow_diff: symbol mismatch — classic={classic_signal.symbol!r} "
            f"vs extended={extended_signal.symbol!r}. Shadow-mode requires "
            f"BOTH signals to come from the same underlying panel."
        )
    if classic_signal.as_of != extended_signal.as_of:
        raise ValueError(
            f"shadow_diff: as_of mismatch — classic={classic_signal.as_of} "
            f"vs extended={extended_signal.as_of}. Diffing signals from "
            f"different sessions produces meaningless divergence rows."
        )

    classic_names = {v.name for v in classic_signal.votes}
    extended_names = {v.name for v in extended_signal.votes}
    added = sorted(extended_names - classic_names)
    removed = sorted(classic_names - extended_names)

    # Per-family means for divergence attribution.
    def _family_mean(sig, family: str) -> float:
        votes = [v.vote for v in sig.votes if v.family == family]
        return sum(votes) / len(votes) if votes else 0.0

    families = ("trend", "momentum", "volatility", "volume")
    per_family_delta = {
        f: _family_mean(extended_signal, f) - _family_mean(classic_signal, f)
        for f in families
    }

    return ShadowDiff(
        symbol=classic_signal.symbol,
        as_of=classic_signal.as_of.isoformat(),
        score_delta=float(extended_signal.score - classic_signal.score),
        vote_count_classic=len(classic_signal.votes),
        vote_count_extended=len(extended_signal.votes),
        added_vote_names=added,
        removed_vote_names=removed,
        per_family_score_delta=per_family_delta,
    )


def write_shadow_log(diffs: list[ShadowDiff], *, out_dir) -> None:
    """Persist shadow diffs to a per-day parquet file.

    File layout: ``<out_dir>/panel_shadow_YYYY-MM-DD.parquet`` (today's
    UTC date). Two writes on the same day append rows to the same file;
    two writes on different days go to different files.

    R7.3 loud-empty on write failure: if the target directory cannot be
    created or the parquet write raises, log a WARNING and return
    silently. A shadow-mode telemetry failure MUST NOT crash a trading
    pipeline — that's the opposite of the "canary before default-on"
    discipline this whole subsystem exists to enable.

    Parameters
    ----------
    diffs : list[ShadowDiff]
        Empty list is a no-op (no file written, no warning).
    out_dir : Path | str
        Directory to write into. Created if missing (unless creation
        fails, in which case we WARN + return).
    """
    if not diffs:
        return

    import datetime as _dt
    import pandas as _pd
    from pathlib import Path as _Path

    out_dir = _Path(out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, NotADirectoryError) as e:
        _logger.warning(
            "shadow log write skipped: cannot create out_dir=%s: %s",
            out_dir, e,
        )
        return

    # Flatten diffs into rows. per_family_score_delta expands into 4
    # columns (score_delta_trend, ..._momentum, ..._volatility, ..._volume)
    # for schema-stable columnar storage.
    rows = []
    for d in diffs:
        row = {
            "symbol": d.symbol,
            "as_of": d.as_of,
            "score_delta": d.score_delta,
            "vote_count_classic": d.vote_count_classic,
            "vote_count_extended": d.vote_count_extended,
            "added_vote_names": ",".join(d.added_vote_names),
            "removed_vote_names": ",".join(d.removed_vote_names),
        }
        for family, delta in d.per_family_score_delta.items():
            row[f"score_delta_{family}"] = delta
        rows.append(row)

    today = _dt.date.today().isoformat()
    path = out_dir / f"panel_shadow_{today}.parquet"

    try:
        new_df = _pd.DataFrame(rows)
        if path.exists():
            existing_df = _pd.read_parquet(path)
            new_df = _pd.concat([existing_df, new_df], ignore_index=True)
        new_df.to_parquet(path, engine="pyarrow", compression="snappy")
    except Exception as e:  # noqa: BLE001 - never crash the pipeline on telemetry
        _logger.warning(
            "shadow log write to %s failed: %s (%s)",
            path, e, type(e).__name__,
        )
