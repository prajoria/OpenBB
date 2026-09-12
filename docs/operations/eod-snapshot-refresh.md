# EOD Snapshot Refresh

The generic post-close runner lives in `openbb_techtrade.snapshot`, not the
legacy scan-specific `openbb_techtrade.snapshots` package.

Install a dataset adapter through the `openbb_snapshot_dataset` entry-point
group, then run it after the XNYS close:

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

SQLite paths must resolve outside the repository. Account-scoped datasets must
be registered with `pii_scoped=True` and supplied an explicit user-local
SQLite store; shared MySQL refuses them.
