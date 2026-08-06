---
name: openbb-workspace-ux-test
description: Deploy the OpenBB Portfolio-Intelligence Workspace backends from `.venv_portfolio` and drive the browser UX to validate shipped `pi_*`/`tt_*` widgets. Captures the runtime deployment topology (copilot proxy :4141, portfolio_intel widget backend :6130, portfolio backend :6902), the exact detached launch commands, health-check probes, the Local Workspace Viewer routes (`/viewer`), self-signed-cert acceptance, and browser-driven screenshot validation. Also documents the hard-won gotchas that keep getting re-derived — the Windows venv-redirector `ExecutablePath` trap (do NOT diagnose the interpreter by OS process image), openbb-api `--app` colon-split, no-auto-reload, CORS locked to pro.openbb.co, and the build-artifact re-dirty trap. Use whenever the user says "redeploy", "run/test the UX", "restart the backend(s)", "the widget isn't showing", or after landing a widget fix that must be validated live in the Workspace.
---

# OpenBB Workspace UX Test & Redeploy

The repeatable procedure for **(re)deploying the Portfolio-Intelligence Workspace
backends and validating widgets in the browser UX**. This is the runtime sibling
of `openbb-dev-cycle` / `portfolio-validation` (which cover the *code* workflow):
this skill covers **deploy + drive-the-UX**, the part that was being re-derived
every session.

**Golden rule:** always launch from `.venv_portfolio` (never system Python — its
site-packages cannot even `import openbb_portfolio_intel`). But see the
**venv-redirector trap** below before you conclude a running process is "the
wrong interpreter."

---

## 1. Deployment topology (3 backends — memorize this table)

| Port | Process | Serves | Protocol | Launch from |
|------|---------|--------|----------|-------------|
| **4141** | copilot proxy (`copilot_proxy` / agents relay) | Copilot chat backend (`/agents.json`, `/query`) that :6902 fronts | HTTP | pre-existing; **leave running**, don't restart casually |
| **6130** | `openbb_portfolio_intel.widget_backend.main:app` (uvicorn) | **"Portfolio Intelligence - Terminal"** + "…- Overview" + "Techtrade Trading Desk" apps — ALL `pi_*`/`tt_*` widgets. Also `/viewer`, `/widgets.json`, `/apps.json` | **HTTP** (loopback) | `.venv_portfolio` |
| **6902** | `openbb-api` → `openbb_platform/extensions/portfolio/launch.py` | "Portfolio Overview" app + Copilot (`/agents.json`+`/query`, routes to :4141) + Local Workspace Viewer `/viewer` | **HTTPS** (self-signed) | `.venv_portfolio` |

> **Port caveat:** code comments and `local_viewer.py` docstrings say the widget
> backend is **6120**; the **live deployment uses 6130**. The `/viewer` is
> same-origin so it self-adjusts to whatever port you launch on. A
> pro.openbb.co custom-backend registration is pinned to a specific port —
> confirm which port the running instance uses (`Get-NetTCPConnection`) before
> assuming. When in doubt, keep the port that is already running so the saved
> Workspace registration still resolves.

**The widget backend on :6130 is the one to redeploy after a `pi_*`/`tt_*`
widget fix.** The :6902 backend is only needed for the Overview app + Copilot +
its own viewer.

---

## 2. The venv-redirector trap (READ THIS before diagnosing "wrong interpreter")

On Windows, `.venv_portfolio\Scripts\python.exe` is a **stdlib-venv redirector**.
When it runs `-m uvicorn`, the child process that actually binds the socket
re-execs the base interpreter, so:

```
Win32_Process.ExecutablePath  ==  C:\...\Python312\python.exe   <- the OS image, ALWAYS base python
sys.prefix                    ==  H:\...\.venv_portfolio         <- the REAL environment
```

**Do NOT conclude a listener is "system Python / wrong interpreter" from
`ExecutablePath`.** That is a red herring and has cost real debugging time.
Verify correctly:

```powershell
# pyvenv.cfg proves isolation:
Get-Content .venv_portfolio\pyvenv.cfg   # include-system-site-packages = false

# Decisive proof: system python CANNOT import the extension, the venv CAN.
& "C:\Users\daaji\AppData\Local\Programs\Python\Python312\python.exe" -c "import openbb_portfolio_intel" 2>&1  # -> ModuleNotFoundError
.venv_portfolio\Scripts\python.exe -c "import sys,openbb_portfolio_intel as p; print(sys.prefix, p.__file__)"   # -> venv prefix + on-disk editable source
```

If the served endpoint returns your fix (see section 4) **and** system python
can't import the module, the listener is genuinely the venv regardless of what
`ExecutablePath` shows. The parent PID will be `.venv_portfolio\Scripts\python.exe`
— check the parent, not the OS image, to confirm provenance.

---

## 3. Redeploy procedure

### 3a. Find and stop the stale backend processes (by PID only)

```powershell
cd H:\masterswork\git\OpenBB-Portfolio-Validation
# Which PIDs own the ports?
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 4141,6120,6130,6900,6902 } |
  Select-Object LocalPort,OwningProcess | Sort-Object LocalPort | Format-Table -AutoSize

# Stop ONLY the widget/portfolio backends (leave 4141 copilot proxy running).
# Name-based kill is prohibited by repo policy — always Stop-Process -Id <PID>.
Stop-Process -Id <PID_6130>,<PID_6902> -Force
Start-Sleep -Seconds 3
```

Kill every duplicate on a port (there are often two — a parent + a stuck
prior-bind). Re-check the port table is empty for 6130/6902 before relaunching.

### 3b. Relaunch DETACHED from `.venv_portfolio`

Backends must survive session shutdown -> launch with `mode=async, detach=true`.

**Widget backend (:6130 — the Terminal/Overview/Techtrade apps):**
```powershell
cd H:\masterswork\git\OpenBB-Portfolio-Validation
$env:PI_WIDGET_BACKEND_AUTH_MODE = "loopback-dev"
.venv_portfolio\Scripts\python.exe -m uvicorn openbb_portfolio_intel.widget_backend.main:app `
  --host 127.0.0.1 --port 6130 --log-level info
```

**Portfolio backend (:6902 — Overview + Copilot + viewer, HTTPS):**
```powershell
cd H:\masterswork\git\OpenBB-Portfolio-Validation
.venv_portfolio\Scripts\openbb-api.exe --app openbb_platform/extensions/portfolio/launch.py `
  --ssl_certfile portfolio_app/cert.pem --ssl_keyfile portfolio_app/key.pem `
  --host 127.0.0.1 --port 6902
# Or the canonical launcher (installs deps first run; -SkipInstall to skip):
#   .\scripts\run_portfolio_backend.ps1 -SkipInstall
#   .\scripts\run_portfolio_backend.ps1 -NoSsl -Port 6900   # plain-HTTP dev path
```

> **openbb-api `--app` colon-split gotcha:** `openbb_platform_api` splits `--app`
> on `:`, which corrupts a Windows absolute path (drive-letter colon). ALWAYS
> pass a **repo-root-relative** path (`openbb_platform/extensions/portfolio/launch.py`)
> AND run from the repo root.
>
> **No auto-reload:** openbb-api and this uvicorn invocation do NOT hot-reload.
> Any edit to `launch.py` / widget endpoints requires a restart (repeat 3a-3b).

---

## 4. Health + fix-is-live verification

```powershell
# Backends up?
(Invoke-WebRequest "http://127.0.0.1:6130/widgets.json" -UseBasicParsing -TimeoutSec 10).StatusCode   # 200
(Invoke-WebRequest "https://127.0.0.1:6902/widgets.json" -UseBasicParsing -TimeoutSec 15 -SkipCertificateCheck).StatusCode  # 200
(Invoke-WebRequest "https://127.0.0.1:6902/agents.json"  -UseBasicParsing -TimeoutSec 15 -SkipCertificateCheck).StatusCode  # 200 = copilot wired

# Viewer + app manifest:
(Invoke-WebRequest "http://127.0.0.1:6130/viewer"    -UseBasicParsing -TimeoutSec 10).StatusCode       # 200
(Invoke-WebRequest "http://127.0.0.1:6130/apps.json" -UseBasicParsing -TimeoutSec 10).Content | ConvertFrom-Json | % name
#  -> Portfolio Intelligence - Overview / Portfolio Intelligence - Terminal / Techtrade Trading Desk

# CONFIRM YOUR FIX IS SERVED — hit the specific widget endpoint and check the shape/keys.
# Example: the #1935 company-filings shape fix ({filing_date, report_type, report_url, filing_url}):
(Invoke-WebRequest "http://127.0.0.1:6130/pi/equity/company-filings?symbol=AAPL" -UseBasicParsing -TimeoutSec 60).Content
```

"Green health" is not "fix is live." Always hit the **specific endpoint you
changed** and assert on the returned keys/values — that is the proof the running
process imports your on-disk edit.

---

## 5. Run the UX in the browser

Two ways to view the apps:

1. **Local Workspace Viewer (no pro.openbb.co needed):** open
   `http://127.0.0.1:6130/viewer` — self-contained, same-origin, renders the
   Overview / Terminal / Techtrade apps directly from :6130. Best for fast
   local widget validation.
2. **pro.openbb.co Workspace (the "real" UX):** the app is a *custom backend*
   registered in Workspace pointing at the localhost port. Requires the
   self-signed cert to be accepted once (see below) and CORS allows
   `https://pro.openbb.co` (the widget backend locks CORS to it on purpose).

**Self-signed cert acceptance (one-time per browser):** open
`https://127.0.0.1:6902/` in Chrome, click through "Your connection is not
private" -> Proceed. Without this, pro.openbb.co / Workspace can't fetch from
localhost and widgets show fetch/CORS errors.

**Driving + screenshotting the UX** — use the available browser automation:
- `open_browser_page` tool to open/share a page (the summary often notes "2
  pages open but not shared" — you must open/share to drive them).
- `chrome-devtools` MCP or the `chrome-devtools-cli` skill for scripted
  navigation, DOM inspection, network inspection, and screenshots.
- `playwright` (via the a11y / harness skills) for end-to-end click-throughs.

**Validation checklist per widget:**
- [ ] Widget renders (no "Backend not available" / fetch error / empty state).
- [ ] Table columns are STABLE (no shape-drift — a `table` widget with no
      explicit `columns` in `widgets.json` auto-infers from returned keys, so
      stub and live MUST return identical keys).
- [ ] Chart/line/candle widgets actually plot (not a blank canvas).
- [ ] The narrative matches the notebook story for that ticker (per-ticker
      widgets should tell the SAME story as the Analysis notebook).
- [ ] Screenshot captured as evidence; log any defect as a GitHub issue on
      `prajoria/OpenBB` added to Project #4 BEFORE fixing (per repo protocol).

---

## 6. Failure modes & fixes (the recurring ones)

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ExecutablePath` shows `Python312.exe` on a venv-launched process | Windows venv redirector (section 2) | Not a bug. Check parent PID + `sys.prefix`; confirm system python can't import the module. |
| Port still bound after kill / "address already in use" | Duplicate process on the port, or kill didn't take | Re-list `Get-NetTCPConnection`, `Stop-Process -Id` every PID on that port, wait 3s, retry. |
| Widget shows "Copilot backend not available (GET /agents.json failed)" | :4141 proxy down, or :6902 not fronting it | Confirm :4141 listening; restart :6902; `curl -k https://127.0.0.1:6902/agents.json` -> 200. |
| Workspace can't fetch localhost / CORS error | Self-signed cert not accepted, or CORS not pro.openbb.co | Accept cert at `https://127.0.0.1:6902/`; widget backend CORS is intentionally locked to `https://pro.openbb.co`. |
| openbb-api boot fails / weird path error | `--app` colon-split on a Windows absolute path | Pass repo-relative `--app`, run from repo root. |
| Edit to endpoint not reflected | openbb-api/uvicorn don't auto-reload | Restart the backend (3a-3b). |
| Endpoint returns stub data not live | fmp_cached cold cache / tier miss -> stub fallback | Expected when live tier empties; the point of shape-drift fixes is stub==live keys so it's deterministic either way. |
| Git shows `reference.json` / `package/__init__.py` dirty | ANY openbb import re-dirties build artifacts | `git checkout -- openbb_platform/core/openbb/assets/reference.json openbb_platform/core/openbb/package/__init__.py` before any commit/branch switch. |
| portfolio_intel unit tests hang | dir has UNMARKED live tests that hit network | ALWAYS run `-m "not integration"`. |

---

## 7. Quick reference (copy-paste redeploy)

```powershell
cd H:\masterswork\git\OpenBB-Portfolio-Validation
# 1. Find PIDs on the backend ports
Get-NetTCPConnection -State Listen | ? { $_.LocalPort -in 6130,6902 } | Select LocalPort,OwningProcess
# 2. Stop them (fill in PIDs; leave 4141 alone)
Stop-Process -Id <PID_6130>,<PID_6902> -Force; Start-Sleep 3
# 3. Relaunch widget backend (detached async)
$env:PI_WIDGET_BACKEND_AUTH_MODE="loopback-dev"
.venv_portfolio\Scripts\python.exe -m uvicorn openbb_portfolio_intel.widget_backend.main:app --host 127.0.0.1 --port 6130 --log-level info
# 4. Relaunch portfolio backend (detached async)
.venv_portfolio\Scripts\openbb-api.exe --app openbb_platform/extensions/portfolio/launch.py --ssl_certfile portfolio_app/cert.pem --ssl_keyfile portfolio_app/key.pem --host 127.0.0.1 --port 6902
# 5. Health + fix-live check
(iwr http://127.0.0.1:6130/widgets.json -UseBasicParsing).StatusCode
(iwr https://127.0.0.1:6902/widgets.json -UseBasicParsing -SkipCertificateCheck).StatusCode
(iwr "http://127.0.0.1:6130/pi/equity/<your-endpoint>?symbol=AAPL" -UseBasicParsing).Content
# 6. Open the UX
#    http://127.0.0.1:6130/viewer   (local viewer) or pro.openbb.co (accept cert at https://127.0.0.1:6902/ first)
```

---

## Related skills

- `openbb-dev-cycle` — full gated feature-dev workflow (feat/pi-* branch + GH issue tree).
- `portfolio-validation` — lightweight fix/validate workflow on `portfolio_validations`.
- `chrome-devtools` / `chrome-devtools-cli` / `a11y-debugging` — browser automation + screenshots for the UX pass.
