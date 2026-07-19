# portfolio_export

Strict record-and-replay tool for broker web sessions (e.g. Fidelity), built
on [Playwright](https://playwright.dev/python/). Recordings are **plain Python
functions** — no AI, no heuristics at replay time, no fuzzy matching. The
recorded flow runs the exact same clicks / fills / downloads every time.

## Design goals

- **Deterministic replay** — a recording is a Python function you can read,
  diff, and version. Replay executes it verbatim against a live browser.
- **Downloads stay OUT of the repo** — the tool refuses to run if the
  configured download or browser-profile directory resolves inside the git
  repo. Default download dir is `~/portfolio_exports/`.
- **Persistent login session** — uses Chromium `launch_persistent_context`
  with a user-data-dir kept outside the repo (default
  `~/.portfolio_export/chrome_profile/`), so cookies / device-trust /
  passkey enrollment persist across runs and MFA doesn't re-prompt every
  session.
- **No credentials on disk** — the tool never stores your password. Log in
  once manually during `record`; the browser profile keeps the session.
- **Strict path validation** — every path used (downloads, profile,
  recordings) is checked to be outside the detected git repo root before
  any browser is launched.

## Install

From `OpenBB/openbb_platform/tools/portfolio_export/`:

```powershell
# uses whichever python is on PATH — recommended: OpenBB/.venv_portfolio
pip install -e .
python -m playwright install chromium
```

## Configure paths (all outside the repo)

Copy `.env.example` to `.env` and edit, or set these env vars in your shell:

| Env var                          | Default                                    | Purpose                              |
| -------------------------------- | ------------------------------------------ | ------------------------------------ |
| `PORTFOLIO_EXPORT_DIR`           | `~/portfolio_exports`                      | Where recorded flows save downloads  |
| `PORTFOLIO_EXPORT_PROFILE_DIR`   | `~/.portfolio_export/chrome_profile`       | Persistent Chromium user-data-dir    |
| `PORTFOLIO_EXPORT_RECORDINGS_DIR`| `~/portfolio_export_recordings`            | Where `pe record` scaffolds new flows; `pe replay` looks here first, then falls back to the bundled `recordings/` examples |
| `PORTFOLIO_EXPORT_HEADLESS`      | `0`                                        | `1` to run replays headless          |

Paths may be absolute or `~`-prefixed. All are validated to be OUTSIDE the
repo before any browser starts — if you accidentally point them at the repo,
the tool exits with an error.

## Usage

```powershell
# 1. Record a flow interactively — opens Chromium + Playwright Inspector.
#    Log in to Fidelity, do the export, then close the browser.
#    Copy the generated Python code from the inspector into
#    recordings/<name>.py under a function `def run(page): ...`
pe record fidelity_export --url https://digital.fidelity.com/

# 2. Replay it. Uses the SAME persistent profile, so you're already logged in.
pe replay fidelity_export

# 3. List recordings
pe list

# 4. Show resolved paths and validation status
pe status
```

## Generate test data (offline, no broker session)

`pe-testdata` produces a Fidelity-shaped CSV with the same header layout
`pe replay` emits, but with all sensitive fields randomized within
realistic bounds. Use it to exercise the loader + downstream importers
without touching a real broker session.

```powershell
# Default: 10-row preset (AAPL/MSFT/GOOGL/AMZN/NVDA/SPY/VTI/TLT/SPAXX/BRK.B)
pe-testdata --seed 42

# Household export: two users, two accounts, rows round-robin
pe-testdata --user-ids alice,bob --accounts X78542853,Z12345678 --date 2026-07-18

# Custom holdings via CSV or JSON template
#   template needs Symbol / Description / Quantity / Last price columns
pe-testdata --template my_holdings.csv --seed 42
```

**Design invariants** — these hold by construction so tests can assert
equality (Fidelity's own CSVs hold them too, within display precision):

- `Current value = Quantity × Last price`
- `Cost basis total = Quantity × Average cost basis`
- `Total gain/loss $ = Current value − Cost basis total`
- `Today's gain/loss $ = Quantity × Last price change`
- `Percent of account` per account sums to 100

Fields kept from the template as-is: `Symbol`, `Description`, `Quantity`,
`Last price`. Everything else is derived or bounded-random. Money-market
symbols (SPAXX, etc.) get blank gain/loss cells per Fidelity convention.

## Writing a recording

Every recording is a module under `recordings/` that defines:

```python
# recordings/fidelity_export.py
from playwright.sync_api import Page

URL = "https://digital.fidelity.com/"

def run(page: Page, download_dir: str) -> list[str]:
    """
    Runs the recorded flow. Return a list of file paths that were downloaded
    (may be empty). `download_dir` is guaranteed to exist and be outside the repo.
    """
    page.goto(URL)
    # ... paste codegen-recorded steps here ...
    # For downloads:
    with page.expect_download() as dl_info:
        page.get_by_role("button", name="Download").click()
    dl = dl_info.value
    dest = f"{download_dir}/{dl.suggested_filename}"
    dl.save_as(dest)
    return [dest]
```

The runner:

1. Validates all paths are outside the repo.
2. Launches Chromium with the persistent profile, `accept_downloads=True`,
   and `downloads_path=<download_dir>`.
3. Opens a fresh page and calls `run(page, download_dir)`.
4. Prints returned download paths and exits cleanly.

## Recording workflow (recommended)

`pe record` launches Chromium in the persistent profile and calls
`page.pause()`, which opens the Playwright Inspector. In the inspector:

1. Click the red **Record** button.
2. Do your flow in the browser (log in if needed, navigate, click Export, etc.).
3. Copy the generated Python from the inspector.
4. Paste it into `recordings/<name>.py` inside `def run(page, download_dir):`.
5. Wrap the download click in `with page.expect_download() as dl: ...` and
   `dl.value.save_as(f"{download_dir}/...")`.

Then `pe replay <name>` runs it deterministically.

## Security notes

- Never commit `.env`, the browser profile, or downloaded files. `.gitignore`
  is configured accordingly.
- Automating your broker session may violate their Terms of Service. Use
  responsibly, only against your own accounts, and keep MFA / device-trust
  active — this tool does not attempt to defeat any anti-automation control.
- Chromium is launched non-headless by default so you can see what it does.
- The persistent user-data-dir contains your logged-in session cookies —
  treat it like a password. Keep it on an encrypted volume if possible.

## Layout

```
portfolio_export/
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── portfolio_export/         # package
│   ├── cli.py                # argparse entry point
│   ├── config.py             # env vars + path validation
│   ├── session.py            # persistent Chromium context
│   ├── record.py             # `pe record` implementation
│   └── replay.py             # `pe replay` implementation
└── recordings/               # your recordings live here (VCS-tracked code)
    └── example_fidelity_export.py
```
