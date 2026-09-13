# EOD Snapshot Refresh

The generic post-close runner lives in `openbb_techtrade.snapshot`, not the
legacy scan-specific `openbb_techtrade.snapshots` package.

TechTrade installs adapters for movers, scan, signals, plan, orders, simulate,
validate, tune, and audit through the `openbb_snapshot_dataset` entry-point
group. Run one adapter directly after its exchange close:

```powershell
.\.venv_portfolio\Scripts\python.exe -m openbb_techtrade.snapshot.refresh --dataset techtrade.movers
```

Retry only the failed keys from a partial run:

```powershell
.\.venv_portfolio\Scripts\python.exe -m openbb_techtrade.snapshot.refresh `
  --dataset techtrade.movers `
  --retry-job-run-id <job-run-id>
```

For Windows Task Scheduler, configure one daily action with:

- **Program:** the repository virtual environment's `python.exe`
- **Arguments:** `-m openbb_techtrade.snapshot.refresh --dataset <dataset>`
- **Start in:** the repository root
- **Trigger:** once after the XNYS close
- **Overlap:** do not start a second instance

The durable `snapshot_job` lease is the second line of defense: a fresh
overlapping run is refused and a run stale for more than two hours is reclaimed.
There is no market-hours schedule.

The OpenBB jobs extension registers `techtrade.daily_scan` at 18:00
`America/New_York` for movers and scan, then `techtrade.eod_snapshots` at 18:05
for the remaining fan-out. The latter's `datasets` parameter accepts any subset
of the nine registered datasets. Its default includes validation, tuning, and
audit only when their optional `openbb-backtest`/`tuneta` dependencies are
installed. Keeping the legacy job name preserves durable schedules without
running a second competing writer.

Every payload stores an explicit `exchange_calendar`. The shipped US-equity
adapters use `XNYS`; freshness and the `as_of` badge are calculated with the
stored calendar. Unknown calendar identifiers fail validation rather than
silently receiving an XNYS date.

Earnings and delisting events come from the configured public `fmp_cached`
provider. Until a provider-native halt feed is available, operators can supply
a comma-separated public symbol list in `PI_TECHTRADE_HALTED_SYMBOLS`; those
symbols are removed before validation and publication.

`validate`, `tune`, and `audit` payloads are rendered as
`in-sample · survivorship-uncorrected` unless their adapter supplies universe
membership captured for the exact same session and calendar.

SQLite paths must resolve outside the repository. Account-scoped datasets must
be registered with `pii_scoped=True` and supplied an explicit user-local
SQLite store; shared MySQL refuses them.
