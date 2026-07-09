"""TEMPORARY E0 STUB — deleted in Phase E2 when the real
``pynecore.providers.Provider`` lands in this repo via the extracted
pynecore. Do NOT depend on this from anything outside
``security_dispatcher.py`` and its tests. Its role is to give E0.2 an
abstract ABC to program against so we can decouple the dispatcher from
``FMPOHLCVProvider`` WITHOUT waiting for E1 to land in pynecore first.

Shape rationale (E0-only deviation from plan §E0.2)
---------------------------------------------------
The E1 real ``pynecore.providers.Provider`` exposes
``fetch(symbol, timeframe, *, start, end) -> list[OHLCV]``. This E0
stub instead types the return as ``pd.DataFrame`` because:

  * The dispatcher operates in DataFrame-space (forward-fill alignment
    via ``pd.DataFrame.reindex(method='ffill')``, cache put/get of
    aligned frames, etc.). Changing to ``list[OHLCV]`` here would ripple
    through ``security_hook.py`` (which does ``iloc[bar_index]``
    lookups) and the ``SecondarySeriesCache`` — outside the scope of
    E0.2.
  * A separate E3 task will introduce the ``list[OHLCV] → pd.DataFrame``
    adapter at the extraction boundary, once pynecore's real Provider
    is in place.

The method NAMES (``stream``, ``fetch``), positional shape
(``symbol, timeframe``), and keyword-only ``start`` / ``end`` DO match
the eventual ``pynecore.providers.Provider`` signature — so the
extraction-time swap is a pure typing + return-value adaptation, not a
call-site rewrite.
"""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:  # pragma: no cover -- typing-only
    import pandas as pd
    from pynecore.types.ohlcv import OHLCV  # type: ignore[import-not-found]


class _DataProviderStub(metaclass=ABCMeta):
    """Abstract Provider stub matching pynecore.providers.Provider ``stream`` / ``fetch``.

    See module docstring for the rationale on the ``pd.DataFrame`` return
    from ``fetch`` (E0-only bridging concession).
    """

    @abstractmethod
    def stream(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Iterator["OHLCV"]:
        """Yield OHLCV bars for the given symbol/timeframe window.

        Present on the E0 stub for shape-parity with pynecore's real
        Provider; the E0 dispatcher does NOT invoke this method (it uses
        the DataFrame-returning ``fetch`` path). Implementations may
        raise ``NotImplementedError`` if streaming isn't needed for E0.
        """
        ...

    @abstractmethod
    def fetch(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> "pd.DataFrame":
        """Return an OHLCV DataFrame for the given symbol/timeframe window.

        The dispatcher forward-fills the returned frame onto the primary
        bar grid. Empty frames are legal (produce an empty aligned
        result). See module docstring for the DataFrame-vs-list[OHLCV]
        deviation from the E1 pynecore.providers.Provider contract.
        """
        ...


__all__ = ["_DataProviderStub"]
