# T5 Paper-Trading Engine — End-to-End Test Guide

Test guide covering the shipped phases of T5 (#1719):

- **P1** — `OrderSink` Protocol + `PaperOrderSink` (paired CSV + XLSX writer). Merged: PR #1749.
- **P2** — Full 6-sheet XLSX workbook + embedded charts. Merged: PR #1752.
- **P3.a** — Event-sourced paper-trading engine (accounts, orders, fills, positions, FIFO realized P&L). Merged: PR #1755.

**Not yet shipped** (out of scope for this guide): P3.b unrealized P&L, P3.c reconciliation, P4 widget rewrite, P5 Activity CSV parser.

---

## 1. What is T5?

**T5 is the "execute" step of the techtrade pipeline.** After the plan is
generated (T1-T3) and validated (T4), T5 turns the plan into brokerage
orders and books the resulting cash / position changes.

Fidelity has no API, so T5 doesn't route orders to a broker. Instead:

1. The techtrade widget generates a **batch of order tickets** and writes
   them to disk as a paired CSV + XLSX file (P1 / P2).
2. The operator reviews the XLSX workbook and files each order **manually**
   at Fidelity's regular order-entry UI.
3. Fidelity's fill confirmation is recorded back into T5's **paper-trading
   engine** (P3.a) so cash, positions, and realized P&L stay accurate.

The paper-trading engine is a *discipline-enforced ledger*: it will not
let the operator record an impossible fill (unknown order, overfill, sell
that exceeds long position, buy that would drive cash negative, etc.).
Every impossible state raises a loud `PaperEngineError` — no silent
coercion, no partial success.

---

## 2. Environment setup

### Prerequisites

- Python 3.12 (matches the repo's `.venv_portfolio`)
- Windows or Linux (tested on both; SQLite paths differ per OS)
- Access to the `prajoria/OpenBB` fork, `portfolio` branch or later
- No API keys required — T5 is entirely local

### Install

```bash
git clone https://github.com/prajoria/OpenBB.git
cd OpenBB
git checkout portfolio

# Fresh venv
python -m venv .venv_portfolio
.venv_portfolio/Scripts/python.exe -m pip install --upgrade pip

# Install the T5-dependent extensions editable.
.venv_portfolio/Scripts/python.exe -m pip install \
    -e openbb_platform/core \
    -e openbb_platform/extensions/backtest \
    -e openbb_platform/extensions/portfolio_intel \
    -e openbb_platform/extensions/techtrade

# Test deps
.venv_portfolio/Scripts/python.exe -m pip install pytest pytest-asyncio openpyxl

# Smoke test — should print no errors.
.venv_portfolio/Scripts/python.exe -c "
from openbb_techtrade.execution.order_sink import PaperOrderSink, OrderBatch, OrderTicket
from openbb_techtrade.execution.paper_engine import SqlitePaperEngine, OrderStatus
print('T5 modules import cleanly')
"
```

### Run the entire T5 unit test suite

Expected result: 121/121 pass, no skips.

```bash
.venv_portfolio/Scripts/python.exe -m pytest \
    openbb_platform/extensions/techtrade/tests/unit/test_order_sink.py \
    openbb_platform/extensions/techtrade/tests/unit/test_order_sink_p2.py \
    openbb_platform/extensions/techtrade/tests/unit/test_paper_engine.py \
    -v
```

If this doesn't produce 121 pass, do not proceed to E2E testing —
something is wrong with the environment.

---

## 3. Architecture at a glance

Three modules cover everything shipped so far:

```
openbb_platform/extensions/techtrade/openbb_techtrade/execution/
├── order_sink.py       — OrderTicket, OrderBatch, PaperOrderSink,
│                          CSV writer, XLSX minimal writer, factory
├── _xlsx_sheets.py     — 6-sheet XLSX writer + embedded charts (P2)
└── paper_engine.py     — PaperEngine Protocol + SqlitePaperEngine
                           + all order/fill/position bookkeeping (P3.a)
```

Nothing else in the codebase is a required dep for T5 tests. The paper
engine and order sink are independent — the paper engine's `submit_batch()`
is duck-typed on `OrderBatch` so tests can pass any object with `.tickets`
and `.sha256()`.

### Data flow

```
OrderTicket ── (many) ──> OrderBatch
                              │
              ┌───────────────┼───────────────┐
              ▼                               ▼
       PaperOrderSink                  SqlitePaperEngine
       ├── write CSV (Fidelity spec)    ├── submit_batch → PENDING orders
       └── write XLSX (6 sheets)        ├── record_fill → PENDING/PARTIAL/FILLED
                                        ├── cancel_order → CANCELLED
                                        ├── get_positions
                                        └── get_account
```

The XLSX is the **human-review artifact** the operator reads before
filing orders. The paper engine is the **shadow ledger** the operator
updates *after* filing orders. Same batch feeds both.

---

## 4. Manual QA walkthrough (no programming required)

This section is for a reviewer who can run Python scripts we provide but
doesn't write new ones. Follow each step and mark PASS/FAIL.

### Prep — get a real workbook + database on disk

Run this script (save as `demo.py` alongside the repo root):

```python
"""T5 demo — writes a 3-symbol batch to disk + runs the paper engine."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from openbb_techtrade.execution.order_sink import (
    OrderBatch, OrderTicket, PaperOrderSink, PlanContext, VerdictGate,
)
from openbb_techtrade.execution.paper_engine import SqlitePaperEngine

OUT = Path("./t5_demo")
OUT.mkdir(exist_ok=True)

# 1. Build a rich 3-symbol batch that exercises every P2 sheet.
batch = OrderBatch(
    tickets=(
        OrderTicket(symbol="MSFT", action="Buy", quantity=Decimal("50"),
                    order_type="Limit", limit_price=Decimal("400.00"),
                    account_masked="***1234"),
        OrderTicket(symbol="AAPL", action="Buy", quantity=Decimal("100"),
                    order_type="Limit", limit_price=Decimal("180.00"),
                    account_masked="***1234"),
        OrderTicket(symbol="NVDA", action="Sell", quantity=Decimal("25"),
                    order_type="Limit", limit_price=Decimal("130.00"),
                    account_masked="***1234", notes="Take profit on rally"),
    ),
    plan_id="qa-demo-2026",
    verdict_gate_pass=True,
    pricing={"MSFT": Decimal("398.00"), "AAPL": Decimal("179.50"),
             "NVDA": Decimal("128.00")},
    pre_execution_positions={"MSFT": Decimal("0.05"), "AAPL": Decimal("0.03"),
                              "NVDA": Decimal("0.12")},
    plan_context=PlanContext(
        verdict_gates=(
            VerdictGate(name="max_single_position",
                        threshold="0.10", actual="0.08", passed=True),
            VerdictGate(name="max_sector_exposure",
                        threshold="0.30", actual="0.35", passed=False,
                        notes="Tech cluster exceeds — reviewer sign-off required"),
        ),
        generator_version="qa-demo-1.0",
        git_sha="abc123def456",
    ),
)

# 2. Write CSV + XLSX to disk.
sink = PaperOrderSink(OUT)
art = sink.write_batch(batch)
print(f"CSV:  {art.csv_path}")
print(f"XLSX: {art.xlsx_path}")

# 3. Open the paper engine, submit the batch, record one fill.
eng = SqlitePaperEngine(OUT / "paper.db", starting_cash=Decimal("100000"))
order_ids = eng.submit_batch(batch, plan_id="qa-demo-2026")
print(f"\nSubmitted {len(order_ids)} PENDING orders")

eng.record_fill(order_ids[0], price=Decimal("398.50"),
                filled_qty=Decimal("50"), at=datetime.now(timezone.utc),
                commission=Decimal("1"))
print(f"Recorded fill: MSFT 50@398.50")

acct = eng.get_account()
print(f"Cash: {acct.cash}")
print(f"Realized P&L: {acct.realized_pl}")
print("\nPositions:")
for p in eng.get_positions():
    print(f"  {p.symbol}: {p.quantity} @ {p.avg_cost}")

eng.close()
print("\nOK — demo complete.")
```

Run:

```bash
.venv_portfolio/Scripts/python.exe demo.py
```

### Manual review checklist

Open `t5_demo/2026-08-03-<sha8>.xlsx` in Excel or LibreOffice and check:

#### Sheet 1 — Orders

- [ ] Header row is bold + centered + light-gray fill
- [ ] Three data rows: MSFT, AAPL, NVDA in that order
- [ ] MSFT row and AAPL row have a **green** background
- [ ] NVDA row has a **red** background (Sell action)
- [ ] Header row is frozen — scrolling keeps it visible
- [ ] Column widths are readable (no truncated Symbol/Action)
- [ ] "Notes" column shows "Take profit on rally" for NVDA row

#### Sheet 2 — Batch Summary

- [ ] Shows batch SHA (short) matching the filename's 8-char tail
- [ ] Shows the full 64-char SHA
- [ ] "Plan ID" = `qa-demo-2026`
- [ ] "Verdict gate" = `PASS` (green context — not red)
- [ ] "Total tickets" = 3
- [ ] "Buy tickets" = 2, "Sell tickets" = 1
- [ ] "Gross notional (limit-priced only)" shows $ formatted, not raw number

#### Sheet 3 — Plan Context

- [ ] Two rows:
  - `max_single_position` / `0.10` / `0.08` / `PASS`
  - `max_sector_exposure` / `0.30` / `0.35` / `FAIL` — **red background**
- [ ] "Notes" column on the FAIL row reads "Tech cluster exceeds..."

#### Sheet 4 — Deviation Analysis

- [ ] Three data rows: MSFT, AAPL, NVDA
- [ ] "Deviation %" column values match `(limit - last_close) / last_close × 100`:
  - MSFT: `(400 - 398) / 398 × 100` ≈ **0.503%**
  - AAPL: `(180 - 179.5) / 179.5 × 100` ≈ **0.279%**
  - NVDA: `(130 - 128) / 128 × 100` ≈ **1.563%**
- [ ] None of the rows have the amber highlight (all deviations < 5%)
- [ ] A **horizontal bar chart** is embedded to the right of the data
- [ ] The bar chart's category axis lists MSFT, AAPL, NVDA

#### Sheet 5 — Concentration

- [ ] Table shows AAPL, MSFT, NVDA rows (alphabetized), each with pre / delta / post columns
- [ ] AAPL row has post-exec weight > 10% (0.03 pre + this batch's delta) — should have **red background** if final weight exceeds 10%. Otherwise no red.
- [ ] Two **pie charts** side-by-side, labeled "Pre-execution" and "Post-execution"
- [ ] Same category order in both pies (eye tracks the delta)

#### Sheet 6 — Audit

- [ ] "Batch SHA (full)" matches Batch Summary sheet's full SHA
- [ ] "Plan ID" = `qa-demo-2026`
- [ ] "Verdict gate" = `PASS`
- [ ] "Generator version" = `qa-demo-1.0`
- [ ] "Git SHA" = `abc123def456`
- [ ] "Generated at (UTC)" is a timestamp with today's date
- [ ] "Written at (UTC)" is also today (should be within seconds of Generated at)

### CSV inspection

Open `t5_demo/2026-08-03-<sha8>.csv` in a text editor (NOT Excel, which
mangles it):

- [ ] **No header row** — the file starts with `MSFT,Buy,50,Limit,400,Day,***1234`
- [ ] Exactly 3 data rows
- [ ] 7 columns per row: Symbol, Action, Quantity, Order Type, Limit Price, TIF, Account
- [ ] No leading `=`, `+`, `-`, `@`, TAB, or CR in any field (formula-injection guard)

### PaperEngine console output check

The demo script's `print` output should show:

- [ ] "Submitted 3 PENDING orders" line
- [ ] "Recorded fill: MSFT 50@398.50" line
- [ ] Cash = 100000 - (50 × 398.50) - 1 = **80074.00** (not 80074.0, not $80074)
- [ ] Realized P&L = 0 (no closing lot yet)
- [ ] Positions shows only MSFT (50 @ 398.50). AAPL + NVDA are still PENDING, no position yet

---

## 5. Automated QA scenarios (Python scripts)

This section is for a QA team that writes Python test scripts. Each
scenario below is a full black-box test — invoke the public API, assert
on the observable outcome, no mocking of the internals.

### Setup boilerplate

```python
"""Common fixtures for T5 QA scenarios."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile

from openbb_techtrade.execution.order_sink import (
    OrderBatch, OrderTicket, PaperOrderSink, PlanContext, VerdictGate,
)
from openbb_techtrade.execution.paper_engine import (
    OrderStatus, PaperEngineError, SqlitePaperEngine,
)


def new_engine(starting_cash="100000"):
    """Fresh engine in a temp dir; caller must close()."""
    tmp = Path(tempfile.mkdtemp())
    return SqlitePaperEngine(tmp / "paper.db",
                              starting_cash=Decimal(starting_cash))


def simple_batch(*tickets):
    return OrderBatch(tickets=tickets)


def buy(symbol, qty="10", limit=None):
    return OrderTicket(
        symbol=symbol, action="Buy", quantity=Decimal(qty),
        order_type="Limit" if limit else "Market",
        limit_price=Decimal(limit) if limit else None,
    )


def sell(symbol, qty="10", limit=None):
    return OrderTicket(
        symbol=symbol, action="Sell", quantity=Decimal(qty),
        order_type="Limit" if limit else "Market",
        limit_price=Decimal(limit) if limit else None,
    )


def now():
    return datetime.now(timezone.utc)
```

### Scenario A — Happy-path full batch lifecycle

**Purpose:** Verify a batch can be submitted, fully filled, and results
in the expected cash + position state.

```python
def test_scenario_a_happy_path():
    eng = new_engine(starting_cash="100000")
    try:
        [oid] = eng.submit_batch(simple_batch(buy("MSFT", "50", "400")))
        eng.record_fill(oid, price=Decimal("400"),
                        filled_qty=Decimal("50"), at=now())

        # Order should be FILLED.
        [order] = eng.get_orders()
        assert order.status == OrderStatus.FILLED

        # Cash decreased by 50 * 400 = 20000.
        assert eng.get_account().cash == Decimal("80000")

        # One position: 50 MSFT @ 400.
        [pos] = eng.get_positions()
        assert pos.symbol == "MSFT"
        assert pos.quantity == Decimal("50")
        assert pos.avg_cost == Decimal("400")
    finally:
        eng.close()
```

**Expected PASS.** Also try:

- Change `starting_cash="1000"` → expect `PaperEngineError` on `record_fill` because 50 × 400 = 20000 > 1000. **Expected: error raised.**
- Add `commission=Decimal("5")` to `record_fill` → cash should be 79995.

### Scenario B — Partial fills

```python
def test_scenario_b_partial_fills():
    eng = new_engine()
    try:
        [oid] = eng.submit_batch(simple_batch(buy("MSFT", "100")))
        eng.record_fill(oid, price=Decimal("400"),
                        filled_qty=Decimal("60"), at=now())
        assert eng.get_orders()[0].status == OrderStatus.PARTIAL
        eng.record_fill(oid, price=Decimal("401"),
                        filled_qty=Decimal("40"), at=now())
        assert eng.get_orders()[0].status == OrderStatus.FILLED

        # Two fills logged.
        assert len(eng.get_fills()) == 2

        # Weighted avg cost = (60*400 + 40*401)/100 = 400.40.
        [pos] = eng.get_positions()
        assert pos.avg_cost == Decimal("400.4")
    finally:
        eng.close()
```

### Scenario C — FIFO realized P&L

**Purpose:** Verify the FIFO tax lot walker produces correct realized P&L
on a partial close after multiple opening lots.

```python
def test_scenario_c_fifo_realized_pl():
    eng = new_engine()
    try:
        # Two opening lots at different prices.
        [b1] = eng.submit_batch(simple_batch(buy("MSFT", "10")))
        eng.record_fill(b1, price=Decimal("400"),
                        filled_qty=Decimal("10"), at=now())
        [b2] = eng.submit_batch(simple_batch(buy("MSFT", "10")))
        eng.record_fill(b2, price=Decimal("420"),
                        filled_qty=Decimal("10"), at=now())

        # Sell 15 @ 430.
        [s1] = eng.submit_batch(simple_batch(sell("MSFT", "15")))
        eng.record_fill(s1, price=Decimal("430"),
                        filled_qty=Decimal("15"), at=now())

        # FIFO: close all 10 @ 400 first (realized 10 * 30 = 300),
        # then close 5 @ 420 (realized 5 * 10 = 50). Total = 350.
        assert eng.get_account().realized_pl == Decimal("350")
    finally:
        eng.close()
```

**If this returns 250 instead of 350**, the FIFO walker is broken (LIFO
order). Report as a critical bug.

### Scenario D — Loud rejection matrix

Each of these should raise `PaperEngineError`. **Any that silently
succeed is a critical bug.**

```python
def test_scenario_d_loud_rejections():
    # D1. Unknown order_id.
    eng = new_engine()
    try:
        try:
            eng.record_fill("ord_nope", price=Decimal("100"),
                            filled_qty=Decimal("1"), at=now())
            assert False, "D1 should have raised"
        except PaperEngineError as e:
            assert "unknown order_id" in str(e)
    finally:
        eng.close()

    # D2. Overfill.
    eng = new_engine()
    try:
        [oid] = eng.submit_batch(simple_batch(buy("MSFT", "10")))
        try:
            eng.record_fill(oid, price=Decimal("400"),
                            filled_qty=Decimal("11"), at=now())
            assert False, "D2 should have raised"
        except PaperEngineError as e:
            assert "overfill" in str(e)
    finally:
        eng.close()

    # D3. Buy that exceeds cash.
    eng = new_engine(starting_cash="1000")
    try:
        [oid] = eng.submit_batch(simple_batch(buy("MSFT", "10")))
        try:
            eng.record_fill(oid, price=Decimal("400"),
                            filled_qty=Decimal("10"), at=now())
            assert False, "D3 should have raised"
        except PaperEngineError as e:
            assert "cash negative" in str(e)
    finally:
        eng.close()

    # D4. Sell that exceeds long position (no accidental short).
    eng = new_engine()
    try:
        [b1] = eng.submit_batch(simple_batch(buy("MSFT", "10")))
        eng.record_fill(b1, price=Decimal("400"),
                        filled_qty=Decimal("10"), at=now())
        [s1] = eng.submit_batch(simple_batch(sell("MSFT", "15")))
        try:
            eng.record_fill(s1, price=Decimal("410"),
                            filled_qty=Decimal("15"), at=now())
            assert False, "D4 should have raised"
        except PaperEngineError as e:
            assert "exceeds long position" in str(e)
    finally:
        eng.close()

    # D5. Fill on cancelled order.
    eng = new_engine()
    try:
        [oid] = eng.submit_batch(simple_batch(buy("MSFT", "10")))
        eng.cancel_order(oid)
        try:
            eng.record_fill(oid, price=Decimal("400"),
                            filled_qty=Decimal("10"), at=now())
            assert False, "D5 should have raised"
        except PaperEngineError as e:
            assert "CANCELLED" in str(e)
    finally:
        eng.close()
```

### Scenario E — Idempotency across engine reopens

**Purpose:** The engine's SQLite DB should survive process restart with
zero data loss.

```python
def test_scenario_e_idempotent_reopen():
    tmp = Path(tempfile.mkdtemp())
    db_path = tmp / "paper.db"

    # Session 1 — establish state, then close.
    eng1 = SqlitePaperEngine(db_path, starting_cash=Decimal("100000"))
    [oid] = eng1.submit_batch(simple_batch(buy("MSFT", "10")))
    eng1.record_fill(oid, price=Decimal("400"),
                     filled_qty=Decimal("10"), at=now())
    cash_before = eng1.get_account().cash
    eng1.close()

    # Session 2 — re-open. Starting cash arg should be IGNORED.
    eng2 = SqlitePaperEngine(db_path, starting_cash=Decimal("999999"))
    acct = eng2.get_account()
    assert acct.cash == cash_before, "cash must survive restart"
    assert acct.starting_cash == Decimal("100000"), (
        "starting_cash arg must NOT overwrite the seeded value"
    )
    assert len(eng2.get_positions()) == 1
    assert len(eng2.get_fills()) == 1
    eng2.close()
```

### Scenario F — XLSX shape + chart embedding

**Purpose:** Verify the P2 XLSX writer produces all 6 sheets and embeds
the expected charts.

```python
def test_scenario_f_xlsx_shape():
    from openpyxl import load_workbook
    tmp = Path(tempfile.mkdtemp())
    sink = PaperOrderSink(tmp)
    batch = OrderBatch(
        tickets=(buy("MSFT", "10", "400"),),
        pricing={"MSFT": Decimal("395")},
        pre_execution_positions={"MSFT": Decimal("0.03")},
        plan_context=PlanContext(
            verdict_gates=(
                VerdictGate(name="max_pos", threshold="0.10",
                            actual="0.08", passed=True),
            ),
        ),
    )
    art = sink.write_batch(batch)
    wb = load_workbook(art.xlsx_path)

    # All 6 sheets in tab order.
    assert wb.sheetnames == [
        "Orders", "Batch Summary", "Plan Context",
        "Deviation Analysis", "Concentration", "Audit",
    ]

    # Deviation sheet has 1 bar chart.
    assert len(wb["Deviation Analysis"]._charts) == 1

    # Concentration sheet has 2 pie charts.
    assert len(wb["Concentration"]._charts) == 2
```

### Scenario G — Formula-injection security guard

**Purpose:** Verify the CSV/Excel formula-injection guard blocks
malicious inputs at construction time.

```python
def test_scenario_g_formula_injection_blocked():
    dangerous = ["=cmd", "@evil", "+1", "-1", "\t=cmd", "\r=cmd"]

    # OrderTicket.notes
    for bad in dangerous:
        try:
            OrderTicket(symbol="MSFT", action="Buy",
                        quantity=Decimal("1"), notes=bad)
            assert False, f"OrderTicket.notes accepted {bad!r} — critical bug"
        except ValueError as e:
            assert "formula-injection" in str(e)

    # OrderTicket.account_masked
    for bad in dangerous:
        try:
            OrderTicket(symbol="MSFT", action="Buy",
                        quantity=Decimal("1"), account_masked=bad)
            assert False, f"OrderTicket.account_masked accepted {bad!r}"
        except ValueError as e:
            assert "formula-injection" in str(e) or "account_masked" in str(e)

    # VerdictGate.name and .notes
    for bad in dangerous:
        try:
            VerdictGate(name=bad, threshold="ok", actual="ok", passed=True)
            assert False, f"VerdictGate.name accepted {bad!r}"
        except ValueError:
            pass

    # PlanContext.generator_version and .git_sha
    for bad in dangerous:
        try:
            PlanContext(generator_version=bad, git_sha="ok")
            assert False, f"PlanContext.generator_version accepted {bad!r}"
        except ValueError:
            pass
```

---

## 6. Known limitations (not bugs)

These behaviors are **intentional design choices** documented in the
module docstrings. Please don't file them as bugs.

1. **No auto-fill.** The engine will not simulate a fill against a
   market price. Every fill must be explicitly recorded by the operator
   (or by a future P5 Activity-CSV parser).
2. **No unrealized P&L.** `PaperPosition.avg_cost` is the cost basis, not
   the mark-to-market. Unrealized P&L needs a live price feed and lands
   in P3.b.
3. **FIFO only.** No LIFO, HIFO, or SpecificID lot selection. The paper
   engine's job is to log the fill sequence, not compute the operator's
   tax return.
4. **Single account.** `SqlitePaperEngine` is single-account per DB file.
   Multi-account is a rewrite (probably lands in P4 alongside the widget).
5. **No wash-sale tracking.** Same rationale as FIFO — tax compliance is
   above this layer.
6. **CSV format is NOT for import.** Fidelity does not accept a CSV
   upload. The CSV is data-portability only; the operator files each
   order manually at Fidelity's regular order-entry UI. The XLSX is the
   authoritative human-review artifact.
7. **Fidelity Positions download schema drift.** The `ingest.py` reader
   still parses an older Fidelity header set; alignment tracked by
   `#1753`. Not blocking T5.

---

## 7. Bug report template

When filing a T5 bug, use this template so we can triage quickly.

```
### Environment
- OS + Python version: 
- Branch + commit SHA: 
- venv + installed extension versions: 

### Scenario (which section of this guide)
- 

### Steps to reproduce
1. 
2. 
3. 

### Expected behavior
- 

### Actual behavior
- 

### Full traceback (if any)
```
[paste traceback here]
```

### Repro is deterministic? (Y/N)

### Additional context
- Do you have a copy of the failing XLSX / CSV / SQLite DB?  
- Any recent changes to the venv?
- Screenshots (redact any real PII):
```

**Do NOT include** in a bug report:

- Real brokerage account numbers (masked is fine: `***1234`)
- Real portfolio positions with dollar amounts
- Any personal usernames, emails, or file paths under
  `C:\Users\<name>\` (use `~` instead)

---

## 8. What's shipped vs. not shipped (for QA scoping)

**Shipped and in scope for this guide:**

- [x] OrderTicket / OrderBatch data model with validation
- [x] PaperOrderSink CSV + XLSX write
- [x] 6-sheet XLSX with embedded bar chart + pie charts
- [x] Formula-injection guard on every string field
- [x] SqlitePaperEngine with submit_batch, record_fill, cancel_order
- [x] FIFO realized P&L computation
- [x] Weighted-average avg_cost on adds
- [x] Cash + position side effects
- [x] Loud rejection on impossible states
- [x] Idempotent DB reopen

**Not yet shipped (do not test):**

- [ ] Unrealized P&L (needs live prices — **P3.b**)
- [ ] Fidelity positions snapshot reconciliation (**P3.c**)
- [ ] `tt_execute_bridge` widget with write-batch button (**P4**)
- [ ] Activity CSV bulk-import of fills (**P5**)
- [ ] Multi-account support
- [ ] Wash-sale tracking, LIFO / HIFO / SpecificID lot selection

---

## 9. Contact

- **Issue tracker:** `prajoria/OpenBB` — parent tracking issue is
  [#1719](https://github.com/prajoria/OpenBB/issues/1719)
- **Merged PRs:** #1749 (P1), #1752 (P2), #1755 (P3.a)
- **Design docs:** `docs/superpowers/specs/2026-08-*.md`
- **Related:** `#1744` (MySQL positions store), `#1715` (ChainedFetcher),
  `#1753` (ingest.py header alignment follow-up)

**Report all issues on the GitHub tracker.** Comments on merged PRs are
seen but not tracked. Do NOT open cross-fork PRs — every PR must target
`portfolio` in `prajoria/OpenBB` (see repo's `CLAUDE.md`).
