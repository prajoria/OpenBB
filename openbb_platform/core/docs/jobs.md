# OpenBB Jobs Service

The jobs service provides durable SQLite-backed scheduling, retries, leases,
cancellation, recovery, and authenticated API control. Job handlers are loaded
through the `openbb_job_extension` entry-point group.

## Commands

```powershell
python -m openbb_core.app.jobs.worker list
python -m openbb_core.app.jobs.worker worker --poll-seconds 5
python -m openbb_core.app.jobs.worker worker --once
python -m openbb_core.app.jobs.worker trigger techtrade.daily_scan --wait
```

Set `OPENBB_JOBS_DATABASE` to an absolute SQLite path shared by the API and
worker. Back up that file while the worker and API are stopped. SQLite WAL mode
is enabled; copy the database, `-wal`, and `-shm` files together if an offline
stop is not possible.

Schedules are persisted with each job definition. The worker reconciles due
runs, renews leases, retries failures using the registered backoff, and recovers
expired leases after interruption. Only one installed worker should own a
given database.

## Windows

The `OpenBBPortfolio` service starts the jobs worker before the API and UX.
See `deploy/windows/README.md`. Legacy Task Scheduler wrappers now enqueue the
same durable jobs and wait for completion:

- `run_fetch_position_history.ps1` → `portfolio.position_history`
- `run_refresh_etf_holdings_cache.ps1` → `portfolio.etf_holdings`

Remove old scheduled tasks after the Windows Service is installed to avoid
duplicate runs.

## Linux systemd

```ini
[Unit]
Description=OpenBB Jobs Worker
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/openbb/current/app
EnvironmentFile=/etc/openbb/jobs.env
ExecStart=/opt/openbb/current/python/bin/python -m openbb_core.app.jobs.worker worker
Restart=on-failure
User=openbb

[Install]
WantedBy=multi-user.target
```

Use filesystem permissions so only the service account and administrators can
read provider credentials or mutate the jobs database. Inspect the read-only
`/api/v1/jobs/health` endpoint for queue depth, worker heartbeat age, and last
successful runs.
