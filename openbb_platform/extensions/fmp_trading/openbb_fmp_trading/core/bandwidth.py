"""BandwidthMeter — monthly persistent FMP bandwidth accounting (PRD §8.7 / P6).

State file layout (JSON): {"month": "YYYY-MM", "used_bytes": int}.
Atomic writes via write-to-temp + os.replace so a crash never yields a
corrupt state file. Corrupt state files start fresh at 0 bytes (rather
than blocking startup) — a conservative choice that costs one month of
bandwidth accounting in the worst case, vs. a hard failure that blocks
the trading day.

Thresholds (PRD NFR-14):
    normal        <= 80% of budget
    conservation  >= 80% and < 95% — IntradaySession switches to short-quote
                                     endpoints + longer polling
    halted        >= 95%           — IntradaySession stops new fetches and
                                     closes open positions
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from openbb_fmp_trading.models import BandwidthState

Mode = Literal["normal", "conservation", "halted"]

CONSERVATION_THRESHOLD: float = 0.80
HALTED_THRESHOLD: float = 0.95


@dataclass
class BandwidthMeter:
    """Persist-and-account FMP bandwidth usage across a calendar month.

    Usage:
        m = BandwidthMeter(state_path=Path("~/.../bandwidth.json"),
                           budget_bytes=50 * 1024**3, today=date.today())
        state = m.charge(payload_size_bytes)
        if state.mode == "halted":
            ...  # IntradaySession flattens open positions
    """

    state_path: Path
    budget_bytes: int
    today: date
    state: BandwidthState = field(init=False)
    _session_used: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.state_path = Path(self.state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_or_init()

    # ------------------------------------------------------------------
    # State construction
    # ------------------------------------------------------------------

    def _load_or_init(self) -> None:
        """Load `state_path` if it exists AND its month matches today's month.

        Corrupt / missing / stale-month state -> start at 0 bytes for this month.
        """
        month_key = self.today.strftime("%Y-%m")
        used = 0
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                if data.get("month") == month_key:
                    used = int(data.get("used_bytes", 0))
            except (json.JSONDecodeError, ValueError, TypeError):
                # Corrupt file: start fresh. In P2, IntradaySession logs this
                # via SessionJournal so operators know why the counter reset.
                used = 0
        self.state = self._build_state(used)

    def _build_state(self, used: int) -> BandwidthState:
        """Compute a BandwidthState snapshot from a byte total."""
        pct = used / self.budget_bytes if self.budget_bytes else 0.0
        mode: Mode = "normal"
        if pct >= HALTED_THRESHOLD:
            mode = "halted"
        elif pct >= CONSERVATION_THRESHOLD:
            mode = "conservation"
        return BandwidthState(
            month_used_bytes=used,
            month_budget_bytes=self.budget_bytes,
            month_used_pct=pct,
            mode=mode,
            session_used_bytes=self._session_used,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def charge(self, num_bytes: int) -> BandwidthState:
        """Record a fetch of ``num_bytes`` and return the updated state."""
        self._session_used += num_bytes
        new_used = self.state.month_used_bytes + num_bytes
        self.state = self._build_state(new_used)
        self._persist()
        return self.state

    def rollover_if_needed(self, today: date) -> None:
        """Reset counters when the calendar month rolls over.

        Called by IntradaySession at session boot each day. Safe to call
        every day — a same-month call is a no-op.
        """
        current_month = self.today.strftime("%Y-%m")
        new_month = today.strftime("%Y-%m")
        if new_month != current_month:
            self.today = today
            self._session_used = 0
            self.state = self._build_state(0)
            self._persist()

    # ------------------------------------------------------------------
    # Persistence (atomic)
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        """Write state atomically: tmp file in same dir + os.replace.

        Same-dir tmp is required because os.replace is atomic only within
        a single filesystem. Any crash mid-write leaves the previous good
        state intact — the tmp file is cleaned up on the next successful
        write or explicitly by the except branch below.
        """
        payload = json.dumps({
            "month": self.today.strftime("%Y-%m"),
            "used_bytes": self.state.month_used_bytes,
        })
        fd, tmp = tempfile.mkstemp(
            prefix="bw-", suffix=".json", dir=str(self.state_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, self.state_path)
        except Exception:
            # Clean up the tmp file on any failure so it doesn't accumulate.
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass  # best-effort — surface the original exception
            raise
