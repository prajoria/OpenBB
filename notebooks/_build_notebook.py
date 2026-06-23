"""Build the POC notebook for the "Developer Guide to Disciplined Trading" series.

Source of truth for `notebooks/01-foundations-techtrade-and-analysis.ipynb`.
Edit this file; regenerate the notebook with:

    .venv_win/Scripts/python.exe notebooks/_build_notebook.py

The notebook is built section-by-section using nbformat so the structure is
diffable in git, easy to edit in chunks, and reproducible. Cells are written
but NOT executed at build time — many cells need user state (API keys, manual
review of results) or run long enough that pre-execution would mislead the
reader.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


# ---------------------------------------------------------------------------
# Cell builders (one per major section). Each returns a list[NotebookNode].
# ---------------------------------------------------------------------------


def _md(text: str) -> dict:
    """Dedent and wrap a multi-line markdown string."""
    return new_markdown_cell(dedent(text).strip() + "\n")


def _code(text: str, *, tags: list[str] | None = None) -> dict:
    """Build a code cell with optional tags (e.g., ['hide-output'])."""
    cell = new_code_cell(dedent(text).strip())
    if tags:
        cell.metadata["tags"] = tags
    return cell


# ---------------------------------------------------------------------------
# Section 0 — cover + user story
# ---------------------------------------------------------------------------


def cover() -> list:
    return [
        _md(
            r"""
            # A Developer Guide to Disciplined Trading

            **Notebook 1 of a series — Foundations: techtrade + Analysis end-to-end POC**

            > *"I've been trading for a year on hunches and I'm tired of losing
            > to my own biases. I can read Python — can a deterministic engine
            > do better than my gut?"*

            ---

            ## What this notebook is

            A **single, self-contained proof-of-concept** that walks a
            programming-literate newbie trader through every working command
            in the OpenBB-techtrade fork as of **2026-06-22**. By the end,
            you will have:

            1. A working `.venv_win` environment with an editable techtrade install.
            2. A fundamental health-check on one ticker via the `Analysis` 7-phase pipeline.
            3. A technical setup for that ticker via `obb.techtrade.signals` / `plan` / `scan`.
            4. An Excel workbook ready to print (`obb.techtrade.export`).
            5. A statistical robustness verdict on the plan (`obb.techtrade.validate`).
            6. An honest understanding of what is **NOT** yet shipped (tuning, narrator, MCP).

            **Time budget:** 15 minutes if you only read; ~1 hour if you run
            every cell (one cell is a 5-10 minute backtest validation).

            ---

            ## Who this is for — the user story

            You are **Alex**, a software engineer who started day-trading during
            the 2024-25 bull run, made some money, gave most of it back, and now
            wants the discipline of a system rather than the gambler's high of a
            hunch. You:

            - Read Python well enough to debug a stack trace and refactor a function.
            - Know what a *moving average* and *RSI* are by name, but couldn't
              defend a specific period choice in court.
            - Want to **measure** whether a setup has an edge before you size
              into it, not after.
            - Have **never** trusted a "buy this stock" indicator and don't intend
              to start — but you'd trust a *gated* recommendation that came with
              a Probability of Backtest Overfitting number attached.

            This notebook hands you that pipeline. You don't get to skip the
            verification — every recommendation it produces is shown alongside
            its statistical caveats.

            ## What this notebook is NOT

            - **Not financial advice.** Every output the engine produces is
              research / paper-trading material. Real-money decisions are yours.
            - **Not a backtesting framework.** Backtesting is delegated to the
              separate `openbb-backtest` extension (which ships in-tree); this
              notebook calls it via `obb.techtrade.validate` but does not
              re-implement WFO / CPCV / PBO / DSR.
            - **Not a replacement for fundamentals.** The `Analysis` 7-phase
              pipeline covered in §3 is the fundamental complement to
              techtrade's purely-technical view. A complete decision uses both.
            """
        ),
    ]


# ---------------------------------------------------------------------------
# Section 1 — environment setup
# ---------------------------------------------------------------------------


def env_setup() -> list:
    return [
        _md(
            r"""
            ## 1. Environment Setup

            ### 1.1 Repository + virtual environment

            **Windows / PowerShell** (the canonical dev setup for this fork — see
            `CLAUDE.md`):

            ```powershell
            # 1. Clone the fork
            git clone https://github.com/prajoria/OpenBB.git OpenBBTechnical
            cd OpenBBTechnical
            git checkout trading_technicals

            # 2. Create the project venv (Python 3.10-3.13; this fork is dev'd on 3.12)
            py -3.12 -m venv .venv_win

            # 3. Activate
            .\.venv_win\Scripts\Activate.ps1

            # 4. Editable install of every extension
            cd openbb_platform
            python dev_install.py -e
            cd ..

            # 5. Install Jupyter (this notebook needs it; ipykernel is already pulled)
            python -m pip install jupyterlab

            # 6. Launch
            jupyter lab notebooks/01-foundations-techtrade-and-analysis.ipynb
            ```

            **macOS / Linux:** identical except `.venv_win` becomes `.venv` and
            the activation path is `source .venv/bin/activate`. The rest of the
            commands are identical; paths shown in this notebook use `.venv_win`
            because the primary dev environment is Windows.

            ### 1.2 Credentials — `fmp_cached` is the only provider

            This fork is hard-pinned to the `fmp_cached` provider (a caching
            wrapper around FinancialModelingPrep) — there is no `yfinance`
            fallback. Configure once in
            **`~/.openbb_platform/user_settings.json`**:

            ```json
            {
              "credentials": {
                "fmp_api_key": "YOUR_FMP_KEY",
                "fmp_cached_api_key": "YOUR_FMP_KEY"
              }
            }
            ```

            > Both keys point to the same FMP API key — `fmp_cached` reuses
            > `fmp`'s credential. You can get a free starter key at
            > <https://financialmodelingprep.com/>; the free tier covers
            > everything in this notebook.

            **Optional**: drop a `.env` at the repo root with `FMP_API_KEY=...`
            for scripts that load it via `python-dotenv`.

            > **Privacy:** `.env` and `user_settings.json` are both `.gitignore`d.
            > Never commit them — even if your fork is private. Quants who have
            > pushed an FMP key to a public repo have had it rotated by FMP
            > within hours.

            ### 1.3 What's installed where

            Run the cell below to verify your environment is wired correctly.
            All of these are **required**:
            """
        ),
        _code(
            r"""
            # Cell 1.3 — environment check (no API calls; safe to run repeatedly).
            import importlib.util
            import sys

            REQUIRED = [
                "openbb",                  # Top-level OpenBB
                "openbb_techtrade",        # This fork's technical-trading extension
                "openbb_backtest",         # Validation engine (#82 dep)
                "openbb_fmp_cached",       # The only provider this fork uses
                "openpyxl",                # Excel export engine
                "pandas_ta_classic",       # Vendored indicator library
            ]
            OPTIONAL = [
                ("tuneta",  "needed only for obb.techtrade.tune (#83); pip install 'openbb-techtrade[tuneta]'"),
                ("xlsxwriter", "richer Excel engine; pip install 'openbb-techtrade[xlsxwriter]'"),
            ]

            print(f"Python: {sys.version.split()[0]}  ({sys.executable})\n")
            print("Required packages:")
            missing = []
            for pkg in REQUIRED:
                ok = importlib.util.find_spec(pkg) is not None
                print(f"  {'OK ' if ok else 'XX '} {pkg}")
                if not ok:
                    missing.append(pkg)

            print("\nOptional extras (notebook works without them):")
            for pkg, hint in OPTIONAL:
                ok = importlib.util.find_spec(pkg) is not None
                print(f"  {'OK ' if ok else '-- '} {pkg:<14} {'' if ok else hint}")

            if missing:
                raise RuntimeError(
                    f"Missing required packages: {missing}. "
                    "Re-run `cd openbb_platform && python dev_install.py -e` from .venv_win."
                )
            print("\nEnvironment OK.")
            """
        ),
        _md(
            r"""
            **Expected output (yours may differ on optionals):**

            ```
            Python: 3.12.13  (H:\masterswork\git\OpenBBTechnical\.venv_win\Scripts\python.exe)

            Required packages:
              OK  openbb
              OK  openbb_techtrade
              OK  openbb_backtest
              OK  openbb_fmp_cached
              OK  openpyxl
              OK  pandas_ta_classic

            Optional extras (notebook works without them):
              --  tuneta         needed only for obb.techtrade.tune (#83); pip install 'openbb-techtrade[tuneta]'
              OK  xlsxwriter

            Environment OK.
            ```

            If any **required** package is missing, the rest of the notebook
            will not work — go back to §1.1 and re-run `dev_install.py -e`.
            """
        ),
        _code(
            r"""
            # Cell 1.4 — credentials probe (no API calls; just checks the file exists).
            import json
            from pathlib import Path

            settings_path = Path.home() / ".openbb_platform" / "user_settings.json"
            print(f"Looking for credentials at: {settings_path}")
            if not settings_path.exists():
                raise RuntimeError(
                    f"{settings_path} does not exist. Create it per §1.2 before continuing."
                )

            creds = json.loads(settings_path.read_text(encoding="utf-8")).get("credentials", {})
            has_fmp_cached = bool(creds.get("fmp_cached_api_key"))
            has_fmp = bool(creds.get("fmp_api_key"))

            print(f"fmp_cached_api_key configured: {has_fmp_cached}")
            print(f"fmp_api_key configured:        {has_fmp}")
            if not (has_fmp_cached or has_fmp):
                raise RuntimeError(
                    "Neither fmp_cached_api_key nor fmp_api_key is set in user_settings.json. "
                    "See §1.2 for the schema."
                )
            print("\nCredentials OK.")
            """
        ),
        _md(
            r"""
            ### 1.5 The `obb` object

            All techtrade commands hang off the top-level `obb` object. Importing
            it once at the top of the notebook makes every later cell a one-liner.
            The first import is slow (~5-10 seconds) — that's `openbb.build()`
            generating the typed Python surface from every installed extension's
            entry points. Later imports are instant.
            """
        ),
        _code(
            r"""
            # Cell 1.5 — load OpenBB. First call is slow; later cells are instant.
            from openbb import obb
            techtrade_cmds = sorted(
                c for c in dir(obb.techtrade)
                if not c.startswith("_") and callable(getattr(obb.techtrade, c, None))
            )
            print(f"obb loaded. {len(techtrade_cmds)} commands under obb.techtrade.*:")
            for cmd in techtrade_cmds:
                print(f"  obb.techtrade.{cmd}")
            """
        ),
        _md(
            r"""
            **Expected:** the printout should include `about`, `export`,
            `movers`, `orders`, `plan`, `scan`, `segments`, `signals`,
            `simulate`, `validate`. If `tune` is missing, that's correct —
            it's not yet shipped (see §6 Roadmap).
            """
        ),
    ]


# ---------------------------------------------------------------------------
# Section 2 — Alex's workflow (story + acceptance criteria)
# ---------------------------------------------------------------------------


def workflow() -> list:
    return [
        _md(
            r"""
            ## 2. Alex's Workflow — what we're going to actually do

            Alex's research process for one trading day looks like this:

            ```
            [Universe selection]
                  |
                  v
            [Fundamentals check]     <-- §3 Analysis 7-phase pipeline
                  |  (is the company healthy enough to even trade?)
                  v
            [Technical setup]        <-- §4 obb.techtrade.signals/plan/scan
                  |  (what's the signal, where do stops go?)
                  v
            [Excel export]           <-- §4.4 obb.techtrade.export
                  |  (printable plan for the trading day)
                  v
            [Robustness gate]        <-- §5 obb.techtrade.validate
                  |  (would this rule have survived out-of-sample?)
                  v
            [Decision]               <-- Alex's call (the machine never auto-trades)
            ```

            Alex uses **one ticker for the deep-dive** (Microsoft, `MSFT` — large
            cap, liquid, well-understood — picked because every public study
            covers it so Alex can sanity-check) and **one segment for the scan**
            (Information Technology, the GICS sector MSFT belongs to).

            > **NG4 — Non-goal #4 from the PRD:** the agent layer never makes
            > trading decisions. Every command in this notebook is a research
            > tool. Alex pulls the trigger, not the engine.
            """
        ),
    ]


# ---------------------------------------------------------------------------
# Section 3 — Analysis 7-phase pipeline (fundamentals)
# ---------------------------------------------------------------------------


def analysis_section() -> list:
    return [
        _md(
            r"""
            ## 3. Fundamentals — the `Analysis` 7-phase pipeline

            Before Alex looks at a chart, the company needs to clear basic
            financial-health bars. The `Analysis/stock_analysis.py` module ships
            a standalone, deterministic 7-phase pipeline that scores one ticker
            from company profile through final decision. It uses **only**
            `fmp_cached` (no live FMP calls if your cache is warm).

            **The 7 phases** (full glossary in `Analysis/docs/FINANCIAL_DOMAIN_GLOSSARY.md`):

            | Phase | What it scores | Why Alex cares |
            |---|---|---|
            | P1 | Company profile + market cap + sector | Is this even tradeable? Is it a microcap nobody can exit? |
            | P2 | Fundamentals (revenue, margins, debt) | Is the underlying business solvent? |
            | P3 | Technicals (price trend, volume) | Is price action sensible? |
            | P4 | Valuation (DCF margin of safety) | Is it priced as if everything will go right? |
            | P5 | Risk (volatility, beta, drawdowns) | What's my downside if I'm early? |
            | P6 | Peer relative | How does it stack vs sector peers? |
            | P7 | Composite decision (BUY/SELL/HOLD + score) | The summary line |
            """
        ),
        _code(
            r"""
            # Cell 3.1 — run the 7-phase analysis on MSFT.
            # Wall-clock: ~30-90 seconds on a warm fmp_cached cache; longer on first run.
            # The pipeline reads obb.user.credentials.fmp_cached_api_key automatically
            # because we configured user_settings.json in §1.2.
            import sys
            from pathlib import Path

            # Make the standalone Analysis module importable from the repo root.
            repo_root = Path.cwd().resolve()
            while not (repo_root / "Analysis").is_dir() and repo_root != repo_root.parent:
                repo_root = repo_root.parent
            if (repo_root / "Analysis").is_dir():
                sys.path.insert(0, str(repo_root / "Analysis"))
            else:
                raise RuntimeError(
                    "Could not find Analysis/ directory. Are you in the repo? "
                    f"Started from {Path.cwd()}"
                )

            from stock_analysis import AnalysisConfig, run_full_analysis

            cfg = AnalysisConfig(symbol="MSFT")
            results = run_full_analysis(cfg)
            print(f"Pipeline phases returned: {sorted(results.keys())}")
            """
        ),
        _md(
            r"""
            > **What you should see:** something like
            > `Pipeline phases returned: ['p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7']`.
            > Each key holds a typed dataclass — `results['p7']` carries the
            > final action label and composite score.
            >
            > **If you see a `RuntimeError: obb is unavailable`** — your
            > `user_settings.json` doesn't have a valid `fmp_cached_api_key`
            > (go back to §1.2).
            """
        ),
        _code(
            r"""
            # Cell 3.2 — inspect the Phase-7 decision.
            p7 = results["p7"]
            print(f"Symbol:          {cfg.symbol}")
            print(f"Action label:    {p7.action_label}")
            print(f"Composite score: {p7.composite_score:.2f} / 5.0")
            print(f"Top reasons:")
            # Field names vary across phases; use getattr defensively so this
            # cell never crashes even if the phase API evolves.
            for attr in ("top_reasons", "rationale", "drivers", "summary"):
                val = getattr(p7, attr, None)
                if val:
                    print(f"  ({attr}) {val}")
                    break
            """
        ),
        _md(
            r"""
            ### 3.3 What Alex should take from §3

            - **A composite ≥ 3.5/5 with no red P5 (risk) flags** is the rough
              floor for "worth a technical setup look." Below that, even a
              beautiful chart is fighting bad fundamentals.
            - **The Analysis pipeline does NOT issue trade orders.** It scores
              the *company*. The next section scores the *setup*.
            - You can run the pipeline phase-by-phase if you want to skip
              expensive ones — see the docstring at the top of
              `Analysis/stock_analysis.py` for the per-phase function imports.
            """
        ),
    ]


# ---------------------------------------------------------------------------
# Section 4 — techtrade signals -> plan -> scan -> export
# ---------------------------------------------------------------------------


def techtrade_section() -> list:
    return [
        _md(
            r"""
            ## 4. Technical Setup — the techtrade engine

            techtrade's job is to turn OHLCV bars into an actionable, **auditable**
            trade plan: levels, stops, sizing, and an Excel-ready summary. Every
            score it produces carries the full vote attribution so Alex can
            always answer "why long?"

            The engine has four working layers (PRD §12):

            1. **Indicators** — `pandas-ta-classic` vendored as a submodule,
               adapter at `engine/indicators.py` produces the per-symbol
               `IndicatorPanel` (trend / momentum / volatility / volume).
            2. **Confluence** — `engine/confluence.py` weights families into a
               composite `score ∈ [-1, +1]` with the locked Q4 weights
               (`trend 0.40 / momentum 0.25 / volatility 0.20 / volume 0.15`).
               Three presets ship: `trend_follow` (default), `mean_revert`,
               `breakout`.
            3. **Rules + Orders** — `engine/rules.py` + `engine/plan.py` turn the
               signal + an `EntryExitRule` into entry / stop / target / time-exit
               orders, sized by risk-per-trade (default 1% of notional).
            4. **Paper broker** — `execution.py` simulates fills at next-bar-open
               with slippage + commission. **No look-ahead** — bar-*t* signals
               only fill at *t+1*.

            ### 4.1 The lightest call — `signals`

            Get the confluence score for a single symbol with default weights:
            """
        ),
        _code(
            r"""
            # Cell 4.1 — single-symbol confluence signal for MSFT.
            # This call goes to fmp_cached for ~250 bars of daily OHLCV.
            result = obb.techtrade.signals(symbols=["MSFT"], preset="trend_follow")
            # `results` is a list[MoverSignal] — one per ranked signal.
            signals = result.results
            for s in signals:
                print(f"{s.symbol:6} score={s.score:+.3f}  direction={s.direction:<6}  votes={len(s.votes)}")
            """
        ),
        _md(
            r"""
            **What you should see:** one row with MSFT, a directional `score`
            in `[-1, +1]`, and a `direction` of `long` / `short` / `flat`.
            `votes` is a `list[IndicatorVote]` carrying the per-indicator
            contribution to the score — that's what makes the call auditable.

            ### 4.2 The actionable call — `plan`

            `plan` runs the same signal chain but assembles a complete
            `TradePlan` per symbol: levels, sizing, broker-ready orders, and an
            inline `Recommendation` (the human-facing call). It's the bridge
            from "what's the signal" to "what do I actually do."
            """
        ),
        _code(
            r"""
            # Cell 4.2 — full trade plan for MSFT at 1% risk per trade.
            result = obb.techtrade.plan(
                symbols=["MSFT"],
                preset="trend_follow",
                risk=0.01,
            )
            plans = result.results
            for plan in plans:
                rec = plan.recommendation
                print(f"--- {plan.symbol} ({plan.segment}) as of {plan.as_of} ---")
                print(f"  Signal score:  {plan.signal.score:+.3f}  ->  {rec.action}  ({rec.conviction} conviction)")
                print(f"  Entry:         ${rec.entry_price}")
                print(f"  Stop:          ${rec.stop_price}      ({rec.stop_distance_pct*100:.2f}% away)")
                print(f"  Target:        ${rec.target_price}      ({rec.target_distance_pct*100:.2f}% away)")
                print(f"  R:R:           {rec.risk_reward:.2f}")
                print(f"  Position:      {rec.position_size} shares")
                print(f"  ATR(14):       {rec.atr:.2f}")
                print(f"  Time stop:     {rec.time_stop_bars} bars")
                print(f"  Caveats:       {rec.caveats}")
                print(f"  Orders ({len(plan.orders)}):")
                for o in plan.orders:
                    print(f"    {o.intent:<12}  {o.side:<5}  qty={o.quantity}  type={o.order_type}")
            """
        ),
        _md(
            r"""
            **What this is teaching Alex:** every order has an `intent` tag
            (`entry` / `exit_stop` / `exit_target` / `exit_time` / `exit_signal`).
            A real broker integration knows which leg is which. The
            paper broker (§4.5) respects this tagging too.

            ### 4.3 The cross-sector view — `scan`

            `scan` runs `plan` across all 11 GICS sectors and ranks the
            top setups by conviction. This is the daily "what does the universe
            look like today" call.
            """
        ),
        _code(
            r"""
            # Cell 4.3 — segment scan across all 11 GICS sectors.
            # WALL-CLOCK: ~30s on a warm cache; up to a few minutes cold.
            result = obb.techtrade.scan(preset="trend_follow", risk=0.01)
            plans = result.results
            print(f"Scan returned {len(plans)} actionable plans.\n")
            # Top-5 by absolute score.
            top = sorted(plans, key=lambda p: -abs(p.signal.score))[:5]
            for p in top:
                rec = p.recommendation
                print(
                    f"  {p.symbol:6} {p.segment:<24} "
                    f"score={p.signal.score:+.3f}  "
                    f"{rec.action:<10}  R:R={rec.risk_reward:.1f}  "
                    f"conv={rec.conviction}"
                )
            """
        ),
        _md(
            r"""
            ### 4.4 Excel export — what Alex actually prints

            `export` writes a 6-sheet Excel workbook (Recommendations / Levels /
            Reasoning / Orders / Fills / Summary) with conditional formatting
            (color-coded actions, R:R color scale, conviction). Default path is
            `Analysis/exports/techtrade_<date>.xlsx`. Every workbook carries the
            "research/paper output — not investment advice" disclaimer on the
            Recommendations sheet.
            """
        ),
        _code(
            r"""
            # Cell 4.4 — export the scan to a multi-sheet Excel workbook.
            from pathlib import Path

            result = obb.techtrade.export(plans=plans)
            xlsx_path = Path(result.results)
            print(f"Wrote workbook: {xlsx_path}")
            print(f"  Size: {xlsx_path.stat().st_size / 1024:.1f} KB")

            # Peek at the sheet names so Alex knows what's in the file before opening it.
            import openpyxl
            wb = openpyxl.load_workbook(xlsx_path, read_only=True)
            print(f"  Sheets ({len(wb.sheetnames)}): {wb.sheetnames}")
            wb.close()
            """
        ),
        _md(
            r"""
            > Open the workbook in Excel / LibreOffice / Google Sheets to see
            > the conditional formatting. The `Recommendations` sheet carries
            > the per-row action/conviction; `Reasoning` holds the audit trail
            > (which indicator votes drove the call); `Summary` is the
            > end-of-scan summary.

            ### 4.5 Paper-broker simulation — `simulate`

            For one plan, you can paper-fill its orders against a forward OHLCV
            window. The fills include slippage + commission. **No look-ahead** —
            a bar-*t* signal only fills at *t+1*.

            (Skipping a live demo cell here because `simulate` requires a
            forward bar window the cache may not have; see
            `tests/integration/test_scan_integration.py` for a fixture-backed
            example.)
            """
        ),
    ]


# ---------------------------------------------------------------------------
# Section 5 — validate (#82, the robustness gate)
# ---------------------------------------------------------------------------


def validate_section() -> list:
    return [
        _md(
            r"""
            ## 5. The Robustness Gate — `obb.techtrade.validate` (issue #82)

            This is the **anti-hunch** gate. Even a beautifully-formatted plan
            from §4 might be fitting noise. `validate` delegates to the
            in-tree `openbb-backtest` extension to ask the blunt question:

            > **Would this rule have survived out-of-sample over the last 5 years?**

            It re-runs the techtrade confluence strategy over walk-forward
            (WFO) or combinatorial purged cross-validation (CPCV) folds,
            computes:

            - **PBO** — Probability of Backtest Overfitting (López de Prado).
              Low is good (< 0.2 = robust; ≥ 0.5 = overfit).
            - **DSR** — Deflated Sharpe Ratio (Bailey / López de Prado). High
              is good (> 0.95 = robust; < 0.5 = overfit).
            - **OOS Sharpe** — aggregated out-of-sample Sharpe ratio.

            ...then returns a single `verdict ∈ {robust, fragile, overfit}`
            with the precedence **overfit > robust > fragile**.

            > **What "fragile" actually means**: not enough evidence to call
            > the edge real, but no evidence it's fake either. Treat fragile
            > setups as "size smaller and watch behavior." `overfit` is a
            > hard no.

            ### 5.1 Validate the MSFT plan

            **Wall-clock warning:** 2-10 minutes on a warm cache. This cell
            calls real WFO folds; each fold re-runs the strategy over a
            multi-year OHLCV window. If you're just reading, skip it.
            """
        ),
        _code(
            r"""
            # Cell 5.1 — validate the first MSFT plan from §4.2.
            # Choose the MSFT plan from §4.2 (re-run plan if `plans` is empty).
            plan_to_validate = next((p for p in plans if p.symbol == "MSFT"), None)
            if plan_to_validate is None:
                # Fall back: re-build a single-symbol MSFT plan if scan didn't include it.
                plan_to_validate = obb.techtrade.plan(symbols=["MSFT"]).results[0]

            import asyncio
            from openbb_techtrade.validation.backtest_bridge import validate_plan

            # validate_plan is async because the WFO loop can take minutes;
            # asyncio.run drives it from a notebook synchronously.
            updated_plan, report = asyncio.run(
                validate_plan(plan_to_validate, method="wfo", horizon_years=5)
            )
            print(f"Verdict:               {report.verdict}")
            print(f"Method:                {report.method}")
            print(f"PBO (lower=better):    {report.pbo:.3f}")
            print(f"Deflated Sharpe:       {report.deflated_sharpe:.3f}")
            print(f"OOS Sharpe:            {report.oos_metrics.sharpe:.3f}")
            print(f"Min-backtest-length:   {report.min_backtest_length_years:.2f} years")
            print(f"Folds: {len(report.folds)}")
            print(f"\nVerdict thresholds in effect:")
            for k, v in report.thresholds.items():
                print(f"  {k:<14} {v}")
            """
        ),
        _md(
            r"""
            **How to read this output:**

            - **`verdict: robust`** — the strategy survived OOS testing. The
              gate would approve persisting tuned parameters for it (see §6).
            - **`verdict: fragile`** — couldn't reject "this is noise" with
              statistical confidence. Don't bet the farm.
            - **`verdict: overfit`** — actively bad. The rule looks great
              in-sample because it memorized the past; OOS performance is poor.
              Walk away.

            ### 5.2 What `validate` does NOT do

            - It does **not** tell you the strategy will work tomorrow.
              "Robust over 5 years" is a *necessary*, not *sufficient*,
              condition for shipping a rule.
            - It does **not** tune the rule. The tuner is `obb.techtrade.tune`
              (issue #83, roadmap — see §6).
            - It does **not** test on your live order book or your slippage
              profile. Forward-test on paper first (`simulate`) before scaling.
            """
        ),
    ]


# ---------------------------------------------------------------------------
# Section 6 — roadmap (#83, #84, #85, #86, #87)
# ---------------------------------------------------------------------------


def roadmap_section() -> list:
    return [
        _md(
            r"""
            ## 6. Roadmap — what's not yet shipped

            techtrade ships in phases (PRD §18). As of **2026-06-22**:

            | Phase | Status | Issue | Surface |
            |---|---|---|---|
            | P0 Foundations | ✅ Shipped | #65 | Extension skeleton, models, GICS map |
            | P1 Segment screener | ✅ Shipped | #69 | `obb.techtrade.segments`, `movers` |
            | P2 Indicator engine | ✅ Shipped | #72/#73 | `engine.indicators`, `pandas-ta-classic` adapter |
            | P3 Confluence engine | ✅ Shipped | #74/#75 | `obb.techtrade.signals`, 3 presets |
            | P4 Rules + orders + fills | ✅ Shipped | #77/#78 | `obb.techtrade.plan`, `orders`, `simulate` |
            | P5 Recommendation + Excel | ✅ Shipped | #80/#81 | `obb.techtrade.export`, 6-sheet workbook |
            | **P6 Validation bridge** | ✅ Shipped 2026-06-21 | **#82** | `obb.techtrade.validate` (covered in §5) |
            | **P7 Tuning** | 🚧 In progress | **#83** | `obb.techtrade.tune` — T1/7 shipped (bootstrap), T2-T7 in TDD pipeline |
            | P8 Agent / MCP | 📋 Planned | #84 / #85 | LLM narrator + MCP tool exposure |
            | P9 Streaming / intraday | 📋 Planned | #87 | O(1) streaming indicators, hourly/minute |
            | (Docs) | 🚧 In progress | **#86** | README + worked examples (this notebook is the seed) |

            ### 6.1 What "in progress" looks like for #83 (tuning)

            The **T1 bootstrap** has shipped on `worktree-83-tuneta-adapter`:
            the `[tuneta]` Poetry extra is declared and the `TuningReport`
            model is in `openbb_techtrade.models`. The remaining 6 tasks
            (T2-T7) are TDD-decomposed in
            `docs/superpowers/plans/2026-06-21-83-tuneta-adapter-tune-gated-validation.md`.

            **When `tune` ships**, the call will look like:

            ```python
            # NOT YET FUNCTIONAL — requires #83 T2-T7 to complete.
            from openbb import obb
            result = obb.techtrade.tune(segment="Information Technology")
            report = result.results
            print(report.verdict, report.persisted, report.candidate)
            ```

            The design lock (from the approved doc): only candidates whose
            verdict comes back **`robust`** persist. `fragile` / `overfit`
            candidates are returned for inspection but never reach the panel
            builder.

            ### 6.2 What this notebook will look like in v2

            When #83 T2-T7 land, §5 grows a §5.3 "Tune the rule, then
            re-validate" subsection. When #84 (narrator) lands, every cell's
            raw output is paired with an LLM-generated plain-English summary.
            When #85 (MCP) lands, every command in this notebook is also
            callable from an external LLM tool — making the notebook itself
            redundant for headless use, but still the best teaching surface
            for humans.
            """
        ),
    ]


# ---------------------------------------------------------------------------
# Section 7 — verification harness (this notebook IS a test)
# ---------------------------------------------------------------------------


def verification_section() -> list:
    return [
        _md(
            r"""
            ## 7. This Notebook as a Verification Harness

            One of the goals stated in the original brief: **this notebook is
            our way of testing and verifying everything works fine**. Running
            it end-to-end exercises every shipped surface:

            - §1 verifies install + credentials.
            - §3 exercises the standalone `Analysis` pipeline (no techtrade
              dependency).
            - §4 exercises `obb.techtrade.{signals, plan, scan, export}`.
            - §5 exercises `obb.techtrade.validate` against the in-tree
              `openbb-backtest`.
            - §6 documents what's deliberately untested (because it's not yet
              shipped).

            ### 7.1 What a green run looks like

            All cells below execute without `RuntimeError` or `ImportError`,
            and produce non-empty results:

            | Cell | Expected outcome |
            |---|---|
            | 1.3 environment | "Environment OK." prints; no missing required pkgs |
            | 1.4 credentials | "Credentials OK." prints |
            | 1.5 obb load | Lists `obb.techtrade.*` commands incl. `validate` |
            | 3.1 Analysis | `Pipeline phases returned: ['p1'..'p7']` |
            | 3.2 Phase-7 | Non-empty `action_label` and `composite_score` |
            | 4.1 signals | At least one signal returned with finite score |
            | 4.2 plan | One `TradePlan` with non-empty `orders` (or a flat plan with empty orders + clear note) |
            | 4.3 scan | `len(plans) >= 1` |
            | 4.4 export | A `.xlsx` file written with 6 sheets |
            | 5.1 validate | `verdict in {'robust','fragile','overfit'}` + finite PBO/DSR |

            ### 7.2 Failure modes and what they mean

            - **`ImportError: No module named 'openbb_techtrade'`** — your
              editable install didn't run from `.venv_win`. Re-do §1.1 step 4.
            - **`KeyError: 'fmp_cached_api_key'`** or `401 Unauthorized` — bad
              or missing FMP key in `user_settings.json`. §1.2.
            - **`429 Too Many Requests`** from FMP — you've burned through
              the free-tier daily limit. Wait an hour or upgrade your FMP
              plan.
            - **Cell 4.3 returns 0 plans** — every sector's top mover scored
              below the entry threshold today. That's a real "no trade" day;
              not a bug. Try with `preset="mean_revert"` to test on a flatter
              tape.
            - **Cell 5.1 hangs > 15 minutes** — the WFO fold loop is fetching
              cold OHLCV. Cancel, re-run §4 once to warm the cache, then
              retry §5.

            ### 7.3 When to evolve this into a multi-notebook series

            The original brief mentioned **"A Developer Guide to Disciplined
            Trading"** as the target. The natural decomposition once this POC
            stabilizes:

            | Future notebook | Focus | Triggers |
            |---|---|---|
            | `02-fundamentals-deep-dive.ipynb` | Each Analysis phase in detail | When P1-P7 questions exceed §3's depth |
            | `03-confluence-internals.ipynb` | Indicator votes, preset weights, regime detection | When users ask "why this score?" |
            | `04-tuning-and-validation.ipynb` | #83 `tune` + full WFO/CPCV walkthrough | When #83 T2-T7 ship |
            | `05-paper-to-live.ipynb` | `simulate` -> live broker integration | When PRD P9 (live broker) lands |
            | `06-agent-narrator-and-MCP.ipynb` | Hands-off LLM narrator + tool exposure | When #84 / #85 ship |

            For now, **this single notebook is enough** — it covers every
            shipped surface end-to-end. Iterate by editing
            `notebooks/_build_notebook.py` and regenerating.
            """
        ),
    ]


# ---------------------------------------------------------------------------
# Appendix
# ---------------------------------------------------------------------------


def appendix() -> list:
    return [
        _md(
            r"""
            ---

            ## Appendix A — File map

            Where each piece of code lives in the repo:

            | Path | What's there |
            |---|---|
            | `Analysis/stock_analysis.py` | 7-phase fundamentals pipeline (used in §3) |
            | `openbb_platform/extensions/techtrade/` | The techtrade extension |
            | `openbb_platform/extensions/techtrade/openbb_techtrade/engine/` | Indicators, confluence, rules, plan, scan |
            | `openbb_platform/extensions/techtrade/openbb_techtrade/reporting/` | Excel export |
            | `openbb_platform/extensions/techtrade/openbb_techtrade/validation/` | #82 backtest bridge + validate router |
            | `openbb_platform/extensions/techtrade/openbb_techtrade/tuning/` | #83 tuneta adapter (T1 bootstrap shipped; T2-T7 pending) |
            | `openbb_platform/extensions/backtest/` | In-tree `openbb-backtest` (WFO/CPCV/PBO/DSR engine) |
            | `docs/Specs/TechnicalTrading-Engine-PRD.md` | The product spec everything traces back to |
            | `docs/designs/quant_trading/` | One design doc per issue (#82, #83, #86) |
            | `docs/superpowers/plans/` | TDD plans for in-flight features |
            | `notebooks/01-foundations-techtrade-and-analysis.ipynb` | This notebook |
            | `notebooks/_build_notebook.py` | The Python builder for this notebook (edit + regenerate) |

            ## Appendix B — Regenerating this notebook

            ```bash
            .venv_win/Scripts/python.exe notebooks/_build_notebook.py
            ```

            The builder is idempotent — it overwrites the `.ipynb` with the
            current content of `_build_notebook.py`. Outputs are not stored
            (cells are blank in git), so a diff of the notebook = a diff of
            the builder's cell-list output, not random execution noise.

            ## Appendix C — Issue tracker

            This fork uses **GitHub Issues** for human-facing tracking (the
            #65/#74/#82/#83 numbers above) and **Beads (`bd`)** for
            session-local sub-tasks (the `OpenBBTechnical-03x`-style IDs in
            internal commits). Run `bd ready` from the repo root to see
            what's available to work on; `bd prime` for the full command
            reference.

            ---

            *End of notebook 1. Series: "A Developer Guide to Disciplined
            Trading". Maintained on the `trading_technicals` branch of
            `prajoria/OpenBB`.*
            """
        ),
    ]


# ---------------------------------------------------------------------------
# Assemble + write
# ---------------------------------------------------------------------------


def build() -> None:
    nb = new_notebook()
    nb.cells = (
        cover()
        + env_setup()
        + workflow()
        + analysis_section()
        + techtrade_section()
        + validate_section()
        + roadmap_section()
        + verification_section()
        + appendix()
    )
    # Pin a kernel so Jupyter opens cleanly without prompting.
    nb.metadata["kernelspec"] = {
        "name": "python3",
        "display_name": "Python 3 (.venv_win)",
        "language": "python",
    }
    nb.metadata["language_info"] = {
        "name": "python",
        "version": "3.12",
        "file_extension": ".py",
        "mimetype": "text/x-python",
        "codemirror_mode": {"name": "ipython", "version": 3},
        "pygments_lexer": "ipython3",
    }

    out = Path(__file__).resolve().parent / "01-foundations-techtrade-and-analysis.ipynb"
    nbformat.write(nb, out)
    print(f"wrote {out} ({len(nb.cells)} cells)")


if __name__ == "__main__":
    build()
