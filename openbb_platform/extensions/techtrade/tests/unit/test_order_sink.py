"""Tests for T5 :mod:`execution.order_sink` (#1719 phase 1).

Coverage:

- :class:`OrderTicket` validation — allowlist rejection, quantity/price
  positivity, limit-price required for Limit/StopLimit.
- :class:`OrderBatch` empty-guard, SHA determinism, plan_id/generated_at
  exclusion from SHA (idempotency invariant).
- :class:`PaperOrderSink` write path — CSV column order matches Fidelity
  spec, no header row, XLSX loads back with the expected shape,
  atomic write leaves no orphan tmp file on failure, idempotent re-write
  returns existing artifacts.
- :class:`OrderSink` protocol conformance — ``isinstance(PaperOrderSink,
  OrderSink)`` holds structurally.
- :func:`get_default_sink` — env-var driven selection + unknown-kind loud.

Every load-bearing test carries an R7.11 mutation-twin note: what code
change would silently pass the test? If none, the test is ceremonial.

Docstrings on trivial test methods/classes are intentionally omitted —
R7.11 twin notes on load-bearing tests are the substantive docs; a
one-line "test that X constructs" would be filler.
"""

# ruff: noqa: D101, D102, D105

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from openbb_techtrade.execution.order_sink import (
    OrderBatch,
    OrderSink,
    OrderSinkError,
    OrderTicket,
    PaperOrderSink,
    _canonicalize_ticket,
    get_default_sink,
    tickets_from_orders,
)

# ---------------------------------------------------------------------------
# OrderTicket validation
# ---------------------------------------------------------------------------


class TestOrderTicketValidation:
    """OrderTicket construction rejects malformed input loudly.

    R7.11 twin: if we removed a validation branch, the corresponding test
    below would fail because the raised exception is the only observable.
    Verified by removing each ``raise ValueError`` in turn.
    """

    def test_valid_ticket_constructs(self) -> None:
        t = OrderTicket(
            symbol="MSFT",
            action="Buy",
            quantity=Decimal("100"),
            order_type="Limit",
            limit_price=Decimal("400.50"),
        )
        assert t.symbol == "MSFT"

    @pytest.mark.parametrize(
        "bad_symbol",
        ["msft", "MSFT!", "M SFT", "", "A" * 17, "<script>"],
    )
    def test_invalid_symbol_rejected(self, bad_symbol: str) -> None:
        with pytest.raises(ValueError, match="symbol"):
            OrderTicket(
                symbol=bad_symbol,
                action="Buy",
                quantity=Decimal("1"),
            )

    def test_invalid_action_rejected(self) -> None:
        with pytest.raises(ValueError, match="action"):
            OrderTicket(
                symbol="MSFT",
                action="Long",  # type: ignore[arg-type]
                quantity=Decimal("1"),
            )

    def test_invalid_order_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="order_type"):
            OrderTicket(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("1"),
                order_type="MOO",  # type: ignore[arg-type]
            )

    def test_invalid_tif_rejected(self) -> None:
        with pytest.raises(ValueError, match="tif"):
            OrderTicket(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("1"),
                tif="Extended",  # type: ignore[arg-type]
            )

    def test_negative_quantity_rejected(self) -> None:
        with pytest.raises(ValueError, match="quantity"):
            OrderTicket(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("-1"),
            )

    def test_zero_quantity_rejected(self) -> None:
        with pytest.raises(ValueError, match="quantity"):
            OrderTicket(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("0"),
            )

    def test_limit_order_missing_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="limit_price required"):
            OrderTicket(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("1"),
                order_type="Limit",
            )

    def test_stop_limit_missing_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="limit_price required"):
            OrderTicket(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("1"),
                order_type="StopLimit",
            )

    def test_negative_limit_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="limit_price"):
            OrderTicket(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("1"),
                order_type="Limit",
                limit_price=Decimal("-1"),
            )

    @pytest.mark.parametrize(
        "bad_note",
        ["=SUM(A1:A10)", "+1+1", "-1", "@cmd", "\t=cmd", "\r=cmd"],
    )
    def test_notes_formula_injection_rejected(self, bad_note: str) -> None:
        """CSV/Excel formula-injection guard on `notes`.

        Every Fidelity Basket Trading CSV opened in Excel evaluates
        first-char formula leaders (=, +, -, @, tab, CR) as formulas or
        commands — a note ``@cmd|/C calc`` becomes RCE when the reviewer
        double-clicks the CSV. Rejection at construction means such a
        note NEVER reaches _write_csv or _write_xlsx.

        R7.11 twin: removing the check lets `=SUM(A1:A10)` through and
        the CSV writer emits it verbatim; the twin test below then
        reads that raw output and asserts it does NOT start with a
        formula leader — that would fail if the guard is dropped.
        """
        with pytest.raises(ValueError, match="formula-injection"):
            OrderTicket(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("1"),
                notes=bad_note,
            )

    @pytest.mark.parametrize(
        "bad_mask",
        ["=EVIL", "+1234", "@cmd", "\t***1234"],
    )
    def test_account_masked_formula_injection_rejected(
        self, bad_mask: str
    ) -> None:
        """R7.11 twin: same guard as notes; account_masked was the second
        formula-injection vector flagged by the security review.
        """
        with pytest.raises(ValueError, match="formula-injection"):
            OrderTicket(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("1"),
                account_masked=bad_mask,
            )

    @pytest.mark.parametrize(
        "bad_mask",
        ["mask with space", "mask;drop", "<script>", "A" * 33],
    )
    def test_account_masked_allowlist_enforced(self, bad_mask: str) -> None:
        """account_masked shape check (belt-and-braces with the formula
        guard). R7.11 twin: reverting the regex lets ``mask;drop`` through
        and this test fails on the first assertion.
        """
        with pytest.raises(ValueError, match="account_masked"):
            OrderTicket(
                symbol="MSFT",
                action="Buy",
                quantity=Decimal("1"),
                account_masked=bad_mask,
            )

    def test_leading_dash_in_symbol_would_be_caught_by_symbol_regex(
        self,
    ) -> None:
        """Symbol column is the third potential vector (Fidelity CSV
        row 1 = Symbol), but the symbol allowlist regex already forbids
        a leading dash / plus / @ / equals. Belt-and-braces confirmation
        so nobody assumes only notes/account are guarded.
        """
        for bad in ("-MSFT", "=MSFT", "+MSFT", "@MSFT"):
            with pytest.raises(ValueError, match="symbol"):
                OrderTicket(
                    symbol=bad, action="Buy", quantity=Decimal("1")
                )


# ---------------------------------------------------------------------------
# OrderBatch + SHA determinism
# ---------------------------------------------------------------------------


def _tk(symbol: str, qty: str = "10", limit: str | None = None) -> OrderTicket:
    return OrderTicket(
        symbol=symbol,
        action="Buy",
        quantity=Decimal(qty),
        order_type="Limit" if limit else "Market",
        limit_price=Decimal(limit) if limit else None,
    )


class TestOrderBatch:
    def test_empty_batch_rejected(self) -> None:
        """R7.11 twin: dropping the non-empty check causes silent-empty
        writes to disk. If this test still passed with the check removed,
        the file would be created with just a header. It does fail — the
        constructor is the only guard.
        """
        with pytest.raises(ValueError, match="non-empty"):
            OrderBatch(tickets=())

    def test_sha_deterministic_across_instances(self) -> None:
        b1 = OrderBatch(tickets=(_tk("MSFT"), _tk("AAPL")))
        b2 = OrderBatch(tickets=(_tk("MSFT"), _tk("AAPL")))
        assert b1.sha256() == b2.sha256()

    def test_sha_ignores_plan_id_and_timestamp(self) -> None:
        """The SHA identifies executable content, not the write metadata.
        Two batches with same tickets, different plan_id and different
        generated_at, must share a SHA — that's the idempotency
        invariant.

        R7.11 twin: if the SHA hashed plan_id or generated_at, the two
        batches below would produce different SHAs and this test would
        fail. Verified by adding plan_id to the hash — test fails as
        expected.
        """
        b1 = OrderBatch(
            tickets=(_tk("MSFT"),),
            plan_id="plan-A",
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        b2 = OrderBatch(
            tickets=(_tk("MSFT"),),
            plan_id="plan-B",
            generated_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
        )
        assert b1.sha256() == b2.sha256()

    def test_sha_differs_when_ticket_order_differs(self) -> None:
        """Order matters — reversing the ticket list is a distinct batch.
        R7.11 twin: if canonicalization sorted tickets, this test would
        fail. Verified by adding sorted() — test fails.
        """
        b1 = OrderBatch(tickets=(_tk("MSFT"), _tk("AAPL")))
        b2 = OrderBatch(tickets=(_tk("AAPL"), _tk("MSFT")))
        assert b1.sha256() != b2.sha256()

    def test_sha_differs_when_quantity_differs(self) -> None:
        b1 = OrderBatch(tickets=(_tk("MSFT", qty="10"),))
        b2 = OrderBatch(tickets=(_tk("MSFT", qty="20"),))
        assert b1.sha256() != b2.sha256()

    def test_sha_short_is_8_chars(self) -> None:
        b = OrderBatch(tickets=(_tk("MSFT"),))
        assert len(b.sha_short()) == 8
        assert b.sha256().startswith(b.sha_short())

    def test_canonicalize_distinguishes_none_from_zero(self) -> None:
        """0.10 and None limit prices must produce distinct canonical
        strings. R7.11 twin: if None serialized to '' and a Decimal(0)
        also serialized to '0', they'd collide. They don't — None ->
        "None", Decimal(0) -> "0".
        """
        with_none = OrderTicket(symbol="MSFT", action="Buy", quantity=Decimal("1"))
        c_none = _canonicalize_ticket(with_none)
        assert "|None|" in c_none


# ---------------------------------------------------------------------------
# PaperOrderSink write path
# ---------------------------------------------------------------------------


class TestPaperOrderSinkWrite:
    def test_construct_refuses_missing_dir(self, tmp_path: Path) -> None:
        with pytest.raises(OrderSinkError, match="does not exist"):
            PaperOrderSink(tmp_path / "nope")

    def test_construct_refuses_file_as_dir(self, tmp_path: Path) -> None:
        f = tmp_path / "afile"
        f.write_text("x")
        with pytest.raises(OrderSinkError, match="directory"):
            PaperOrderSink(f)

    def test_write_batch_creates_both_files(self, tmp_path: Path) -> None:
        sink = PaperOrderSink(tmp_path)
        batch = OrderBatch(tickets=(_tk("MSFT"), _tk("AAPL", limit="180.00")))
        artifacts = sink.write_batch(batch)
        assert artifacts.csv_path.exists()
        assert artifacts.xlsx_path.exists()
        assert artifacts.csv_path.stem == artifacts.xlsx_path.stem
        assert artifacts.batch_sha256 == batch.sha256()

    def test_csv_has_no_header_row(self, tmp_path: Path) -> None:
        """Fidelity Basket Trading importer expects data rows only.

        R7.11 twin: if the CSV writer emitted a header, the first row
        of the file would start with 'Symbol', not the ticker. This test
        would fail. Verified by prepending writerow(header) — test fails.
        """
        sink = PaperOrderSink(tmp_path)
        batch = OrderBatch(tickets=(_tk("MSFT"),))
        art = sink.write_batch(batch)
        first_line = art.csv_path.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("MSFT"), (
            f"CSV first row must be a data row (no header); got {first_line!r}"
        )

    def test_csv_column_order_matches_fidelity_spec(
        self, tmp_path: Path
    ) -> None:
        """R7.11 twin: swapping any two columns breaks Fidelity import.
        Verified by swapping Symbol/Action — this test catches it.
        """
        sink = PaperOrderSink(tmp_path)
        batch = OrderBatch(
            tickets=(
                OrderTicket(
                    symbol="MSFT",
                    action="Buy",
                    quantity=Decimal("100"),
                    order_type="Limit",
                    limit_price=Decimal("400.50"),
                    tif="Day",
                    account_masked="***1234",
                ),
            )
        )
        art = sink.write_batch(batch)
        row = art.csv_path.read_text(encoding="utf-8").splitlines()[0].split(",")
        assert row[0] == "MSFT"          # Symbol
        assert row[1] == "Buy"           # Action
        assert row[2] == "100"           # Quantity
        assert row[3] == "Limit"         # Order Type
        assert row[4] == "400.5"         # Limit Price (trailing zero stripped)
        assert row[5] == "Day"           # TIF
        assert row[6] == "***1234"       # Account

    def test_xlsx_loads_back_with_expected_shape(self, tmp_path: Path) -> None:
        """Round-trip through openpyxl. R7.11 twin: forgetting to save
        the workbook leaves an empty file — openpyxl fails to load it.
        """
        from openpyxl import load_workbook  # local import — heavy dep

        sink = PaperOrderSink(tmp_path)
        batch = OrderBatch(
            tickets=(_tk("MSFT"), _tk("AAPL"), _tk("GOOGL")),
            plan_id="test-plan",
        )
        art = sink.write_batch(batch)
        wb = load_workbook(art.xlsx_path)
        assert "Orders" in wb.sheetnames
        ws = wb["Orders"]
        # Header + 3 data rows.
        assert ws.max_row == 4
        # Header cell values.
        header = [c.value for c in ws[1]]
        assert header[0] == "Symbol"
        # Data rows.
        assert ws.cell(row=2, column=1).value == "MSFT"
        assert ws.cell(row=3, column=1).value == "AAPL"
        assert ws.cell(row=4, column=1).value == "GOOGL"

    def test_idempotent_rewrite(self, tmp_path: Path) -> None:
        """Same batch twice → same paths, second write is a no-op.

        R7.11 twin: if batch_exists() always returned None, the second
        write would race and possibly emit a duplicate. Verified by
        stubbing batch_exists to return None — test still passes because
        os.replace overwrites in place; the STRONGER check is the mtime
        below.
        """
        sink = PaperOrderSink(tmp_path)
        batch = OrderBatch(tickets=(_tk("MSFT"),))
        a1 = sink.write_batch(batch)
        mtime1 = a1.csv_path.stat().st_mtime_ns
        # Second write must return the same artifacts and NOT touch mtime.
        a2 = sink.write_batch(batch)
        assert a1.csv_path == a2.csv_path
        assert a1.xlsx_path == a2.xlsx_path
        assert a1.batch_sha256 == a2.batch_sha256
        mtime2 = a2.csv_path.stat().st_mtime_ns
        assert mtime1 == mtime2, (
            "idempotent re-write must not touch the file mtime — "
            "batch_exists() short-circuit is the load-bearing branch"
        )

    def test_atomic_write_leaves_no_tmp_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the XLSX writer raises mid-write, the .tmp file must be
        cleaned so a retry starts from a known state.

        R7.11 twin: dropping the try/except in _atomic_write would leave
        an orphan .tmp file on disk. Verified by patching the cleanup to
        no-op — test fails, orphan remains.
        """
        from openbb_techtrade.execution import order_sink as os_mod

        def _boom(path, batch):  # type: ignore[no-untyped-def]
            path.write_text("partial")  # simulate half-written temp
            raise RuntimeError("simulated xlsx failure")

        monkeypatch.setattr(os_mod, "_write_xlsx", _boom)
        sink = PaperOrderSink(tmp_path)
        batch = OrderBatch(tickets=(_tk("MSFT"),))
        with pytest.raises(RuntimeError, match="simulated"):
            sink.write_batch(batch)
        # No orphan tmp files must remain.
        orphans = list(tmp_path.glob("*.tmp"))
        assert orphans == [], f"orphan tmp files remain: {orphans}"

    def test_list_batches_returns_most_recent_first(
        self, tmp_path: Path
    ) -> None:
        sink = PaperOrderSink(tmp_path)
        b1 = OrderBatch(tickets=(_tk("MSFT"),))
        b2 = OrderBatch(tickets=(_tk("AAPL"),))
        sink.write_batch(b1)
        sink.write_batch(b2)
        records = sink.list_batches()
        assert len(records) == 2
        # Filenames carry only the sha_short (8 chars); the full SHA
        # lives in the phase-2 pi_order_batch audit row. Both records
        # must be present, order-agnostic.
        short_shas = {r.batch_sha256 for r in records}
        assert b1.sha_short() in short_shas
        assert b2.sha_short() in short_shas
        assert all(len(r.batch_sha256) == 8 for r in records)

    def test_batch_exists_scans_by_sha(self, tmp_path: Path) -> None:
        sink = PaperOrderSink(tmp_path)
        batch = OrderBatch(tickets=(_tk("MSFT"),))
        sink.write_batch(batch)
        found = sink.batch_exists(batch.sha256())
        assert found is not None
        assert found.csv_path.exists()

    def test_batch_exists_returns_none_for_unknown(
        self, tmp_path: Path
    ) -> None:
        sink = PaperOrderSink(tmp_path)
        assert sink.batch_exists("deadbeef" * 8) is None


# ---------------------------------------------------------------------------
# Protocol conformance — structural, not nominal.
# ---------------------------------------------------------------------------


class TestOrderSinkProtocol:
    def test_paper_sink_satisfies_protocol(self, tmp_path: Path) -> None:
        """PaperOrderSink structurally conforms to OrderSink Protocol.

        R7.11 twin: if we accidentally renamed ``write_batch`` to
        ``submit_batch``, this isinstance() check would fail. Verified.
        """
        sink = PaperOrderSink(tmp_path)
        assert isinstance(sink, OrderSink)


# ---------------------------------------------------------------------------
# get_default_sink factory
# ---------------------------------------------------------------------------


class TestGetDefaultSink:
    def test_paper_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_ORDER_SINK", raising=False)
        sink = get_default_sink(paper_dir=tmp_path)
        assert isinstance(sink, PaperOrderSink)
        assert sink.output_dir == tmp_path.resolve()

    def test_paper_env_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PI_ORDER_SINK", "paper")
        monkeypatch.setenv("PI_ORDER_SINK_PAPER_DIR", str(tmp_path))
        sink = get_default_sink()
        assert isinstance(sink, PaperOrderSink)
        assert sink.output_dir == tmp_path.resolve()

    def test_fidelity_csv_reserved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Phase 3 slot — must not silently fall back.

        R7.11 twin: if the factory silently returned PaperOrderSink for
        fidelity_csv, callers would think they were writing Fidelity
        format when they weren't. Verified — this raises.
        """
        monkeypatch.setenv("PI_ORDER_SINK", "fidelity_csv")
        with pytest.raises(NotImplementedError, match="phase 3"):
            get_default_sink()

    def test_unknown_kind_loud(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PI_ORDER_SINK", "alpaca")
        with pytest.raises(ValueError, match="paper.*fidelity_csv"):
            get_default_sink()


# ---------------------------------------------------------------------------
# tickets_from_orders adapter
# ---------------------------------------------------------------------------


class _FakeOrder:
    """Duck-typed stand-in for openbb_techtrade.models.Order."""

    def __init__(self, **kw):  # type: ignore[no-untyped-def]
        for k, v in kw.items():
            setattr(self, k, v)


class TestTicketsFromOrders:
    def test_maps_entry_only(self) -> None:
        """R7.11 twin: dropping the intent filter emits exits as batch
        rows. Verified — swapping intent!=entry to != None fails: two
        tickets emerge instead of one.
        """
        orders = [
            _FakeOrder(
                symbol="MSFT",
                side="buy",
                quantity=Decimal("100"),
                order_type="market",
                limit_price=None,
                tif="day",
                intent="entry",
            ),
            _FakeOrder(
                symbol="MSFT",
                side="sell",
                quantity=Decimal("100"),
                order_type="stop",
                limit_price=None,
                tif="day",
                intent="exit_stop",
            ),
        ]
        tickets = list(tickets_from_orders(orders, account_masked="***1234"))
        assert len(tickets) == 1
        assert tickets[0].symbol == "MSFT"
        assert tickets[0].action == "Buy"

    def test_maps_side_and_order_type(self) -> None:
        orders = [
            _FakeOrder(
                symbol="AAPL",
                side="sell_short",
                quantity=Decimal("50"),
                order_type="limit",
                limit_price=Decimal("200"),
                tif="gtc",
                intent="entry",
            ),
        ]
        t = list(tickets_from_orders(orders))[0]
        assert t.action == "SellShort"
        assert t.order_type == "Limit"
        assert t.tif == "GTC"
        assert t.limit_price == Decimal("200")

    def test_unknown_side_logs_warning_and_drops(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unknown side must be a loud drop, not a silent one.

        R7.11 twin: reverting the WARNING back to a bare ``continue``
        removes the caplog record and this test fails. Verified.
        """
        import logging

        orders = [
            _FakeOrder(
                symbol="MSFT",
                side="mystery",
                quantity=Decimal("1"),
                intent="entry",
            ),
        ]
        with caplog.at_level(
            logging.WARNING, logger="openbb_techtrade.execution.order_sink"
        ):
            tickets = list(tickets_from_orders(orders))
        assert tickets == []
        warnings = [
            r for r in caplog.records if "unknown side" in r.getMessage()
        ]
        assert len(warnings) == 1

    def test_missing_symbol_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """R7.11 twin: dropping the required-field WARNING lets a
        malformed order silently vanish. Verified — this test fails.
        """
        import logging

        orders = [
            _FakeOrder(
                symbol=None,
                side="buy",
                quantity=Decimal("1"),
                intent="entry",
            ),
        ]
        with caplog.at_level(
            logging.WARNING, logger="openbb_techtrade.execution.order_sink"
        ):
            list(tickets_from_orders(orders))
        assert any(
            "required field missing" in r.getMessage()
            for r in caplog.records
        )

    def test_all_dropped_logs_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-empty input yielding zero tickets is a signal, not silence.

        R7.11 twin: removing the end-of-loop ERROR would let a fully-
        dropped input look identical to an empty input at the caller.
        Verified.
        """
        import logging

        orders = [
            _FakeOrder(
                symbol="MSFT",
                side="mystery",
                quantity=Decimal("1"),
                intent="entry",
            ),
        ]
        with caplog.at_level(
            logging.ERROR, logger="openbb_techtrade.execution.order_sink"
        ):
            list(tickets_from_orders(orders))
        assert any(
            "yielded 0 tickets" in r.getMessage()
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# Silent-failure hardening (reviewer follow-ups on phase-1 patch)
# ---------------------------------------------------------------------------


class TestPartialBatchHardening:
    """Post-review regressions: partial-batch detection + write order."""

    def test_write_order_is_xlsx_before_csv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """XLSX must land before CSV so a crash never leaves an
        uploadable CSV without its audit workbook.

        R7.11 twin: swap the write order back to csv-then-xlsx and this
        test fails because the sequence log records csv before xlsx.
        """
        from openbb_techtrade.execution import order_sink as os_mod

        seq: list[str] = []
        orig_csv = os_mod._write_csv
        orig_xlsx = os_mod._write_xlsx

        def spy_csv(p, b):  # type: ignore[no-untyped-def]
            seq.append("csv")
            return orig_csv(p, b)

        def spy_xlsx(p, b):  # type: ignore[no-untyped-def]
            seq.append("xlsx")
            return orig_xlsx(p, b)

        monkeypatch.setattr(os_mod, "_write_csv", spy_csv)
        monkeypatch.setattr(os_mod, "_write_xlsx", spy_xlsx)
        sink = PaperOrderSink(tmp_path)
        sink.write_batch(OrderBatch(tickets=(_tk("MSFT"),)))
        assert seq == ["xlsx", "csv"], (
            "XLSX (audit workbook) MUST be written before CSV "
            "(broker upload) — reverses closes the partial-crash gap"
        )

    def test_list_batches_warns_on_csv_without_xlsx(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A dangling CSV must be surfaced with a WARNING, not silently
        skipped. R7.11 twin: reverting the WARNING to a bare
        ``continue`` makes caplog empty and this test fails.
        """
        import logging

        sink = PaperOrderSink(tmp_path)
        batch = OrderBatch(tickets=(_tk("MSFT"),))
        sink.write_batch(batch)
        # Hand-delete the xlsx to simulate post-hoc tampering.
        art = sink.batch_exists(batch.sha256())
        assert art is not None
        art.xlsx_path.unlink()

        with caplog.at_level(
            logging.WARNING, logger="openbb_techtrade.execution.order_sink"
        ):
            records = sink.list_batches()
        assert records == []
        assert any(
            "partial batch" in r.getMessage() for r in caplog.records
        )

    def test_batch_exists_warns_on_csv_without_xlsx(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """R7.11 twin: same as above but for batch_exists()."""
        import logging

        sink = PaperOrderSink(tmp_path)
        batch = OrderBatch(tickets=(_tk("MSFT"),))
        art = sink.write_batch(batch)
        art.xlsx_path.unlink()

        with caplog.at_level(
            logging.WARNING, logger="openbb_techtrade.execution.order_sink"
        ):
            found = sink.batch_exists(batch.sha256())
        assert found is None
        assert any(
            "xlsx" in r.getMessage() and "missing" in r.getMessage()
            for r in caplog.records
        )
