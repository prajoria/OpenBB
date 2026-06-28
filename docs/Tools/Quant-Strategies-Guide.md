# Comprehensive Quant Strategies & Algorithms Guide

A single-document survey of the quant algorithms, strategies, and techniques found
across the **~453 repositories** cloned under `quant_repos/` (via
`tools/quant_scraper`, sourced from the *awesome-quant* list). This is a
**research-only catalog** — no cloned repo was modified, and nothing here is a
license to vendor restricted code. It is meant to be read end-to-end to understand
the landscape, then used as a sourcing index when designing OpenBB quant features.

> **How this guide was built:** all 453 repos were cataloged by 8 parallel research
> agents into per-batch digests (`.tmp_batches/digest_00..07.md`). This guide
> consolidates those digests into one navigable, category-organized reference.

> **License caution:** A few notable libraries are **source-available but NOT
> open-source** (e.g. `attack68/rateslib`, `hudson-and-thames/mlfinlab` full code,
> `goldmansachs/gs-quant` pricing via GS Marquee). These are study-only references —
> do **not** copy their code into OpenBB. Always re-implement from public papers or
> use permissively-licensed equivalents.

---

## Table of Contents

1. [How to use this guide](#1-how-to-use-this-guide)
2. [Category taxonomy](#2-category-taxonomy)
3. [Backtesting engines](#3-backtesting-engines)
4. [Portfolio optimization & allocation](#4-portfolio-optimization--allocation)
5. [Technical indicators](#5-technical-indicators)
6. [Options & derivatives pricing](#6-options--derivatives-pricing)
7. [Volatility modeling](#7-volatility-modeling)
8. [Time-series & forecasting](#8-time-series--forecasting)
9. [Machine learning & reinforcement learning](#9-machine-learning--reinforcement-learning)
10. [Factor & alpha research](#10-factor--alpha-research)
11. [Risk management](#11-risk-management)
12. [Performance analytics & reporting](#12-performance-analytics--reporting)
13. [Fixed income & structured finance](#13-fixed-income--structured-finance)
14. [Market microstructure & execution](#14-market-microstructure--execution)
15. [Trading bots & execution frameworks](#15-trading-bots--execution-frameworks)
16. [Market data providers](#16-market-data-providers)
17. [Agent / MCP patterns](#17-agent--mcp-patterns)
18. [Cross-cutting "best of breed" shortlist](#18-cross-cutting-best-of-breed-shortlist)
19. [License / reuse notes](#19-license--reuse-notes)

---

## 1. How to use this guide

- **Browsing by need:** jump to the category section. Each lists the concrete
  algorithms/techniques and the standout repos that implement them.
- **"Reusability" rating** reflects fit for the OpenBB Platform (Python-first,
  permissive license, production quality) — from *Foundational* (already a core dep)
  down to *Skip* (obsolete/wrong-language/proprietary).
- **Language matters:** OpenBB Platform is Python. R/Julia/Rust/C++/Go/Scala/Java/
  TS repos are mostly **reference** (algorithm source to port), not direct deps.
- The companion proposal — `docs/Specs/Quant-Analysis-Module-Proposal.md` — turns
  this landscape into a concrete OpenBB extension design.

---

## 2. Category taxonomy

The repos cluster into these recurring categories (a repo may span several):

| Category | What it covers |
|---|---|
| Backtesting | Event-driven & vectorized strategy simulation, optimization, walk-forward |
| Portfolio Optimization | Mean-variance, risk-parity, HRP, CVaR, Black-Litterman, OLPS |
| Technical Indicators | TA libraries (batch + streaming), candlestick patterns |
| Options/Derivatives Pricing | BS/binomial/MC/Fourier pricing, Greeks, IV, exotics |
| Volatility Modeling | GARCH family, range estimators, SABR, rough vol, surfaces |
| Time-Series/Forecasting | ARIMA, Prophet, deep probabilistic forecasting, smoothing |
| ML / RL | Financial ML pipelines, deep learning, RL trading agents |
| Factor/Alpha Research | Factor models, 101 alphas, IC/quantile evaluation, anti-overfit |
| Risk Management | VaR/CVaR/ES, drawdown, Kelly, stress testing, backtesting tails |
| Performance Analytics | Tear sheets, Sharpe/Sortino, attribution, reporting |
| Fixed Income | Curve bootstrapping, IRS/bonds, day-counts, CDS, ABS waterfalls |
| Market Microstructure | LOB, order-flow, Lee-Ready, OBI/CVD, custom bars |
| Trading Execution/Bots | Live/paper engines, broker connectivity, backtest→live parity |
| Market Data | Provider wrappers (equities, crypto, macro, filings, FX) |
| Agent / MCP | LLM/agent factor research, MCP tool servers, signal fusion |

---

## 3. Backtesting engines

The single most-represented category. Three architectural families dominate.

### 3a. Event-driven engines
Bar-by-bar `Market → Signal → Order → Fill` loops with realistic accounting.

- **`quantopian/zipline`** + **`stefan-jansen/zipline-reloaded`** — reference
  event-driven engine; **Pipeline API** for cross-sectional factor compute,
  slippage/commission models, data bundles. *Heavyweight but canonical.*
- **`backtrader/backtrader`** — canonical Python engine; huge indicator library,
  analyzers (Sharpe/drawdown/SQN), broker sim, multi-timeframe, optimization.
- **`QuantConnect/Lean`** (C#) — full Alpha/Portfolio/Risk/Execution framework
  modules; reference architecture for a strategy framework.
- **`mhallsmoore/qstrader`** — clean modular alpha→risk→portfolio-construction→
  execution pipeline with rebalancing schedules. *High reuse for architecture.*
- **`pmorissette/bt`** — elegant tree-structured composable Algo/AlgoStack blocks
  (weighting/rebalancing/selection) built on `ffn`. *High reuse.*
- **`quarkfin/qf-lib`**, **`ts-kontakt/antback`**, **`raphaub-hub/SEXTANT`**,
  **`bsdz/yabte`** — lookahead-bias-safe transparent loops + reporting.
- **`robcarver17/pysystemtrade`** — gold-standard **systematic futures**:
  EWMAC trend + carry forecasts, forecast scaling/capping/combination, volatility
  targeting & position sizing, handcrafting/bootstrap/shrinkage portfolio weights.
- **`fasiondog/hikyuu`** (C++/Py) — modular env/condition/signal/MM/sizing/slippage
  components; strong modular architecture reference.

### 3b. Vectorized / mass-parameter engines
Numba/Pandas-accelerated for sweeping thousands of strategy combos.

- **`polakowo/vectorbt`** — best-in-class vectorized backtesting; Numba portfolio
  sim, huge hyperparameter grid sweeps, Plotly dashboards. *High reuse.*
- **`edtechre/pybroker`** — Numba backtester with **walk-forward analysis** +
  **bootstrap-randomized metrics** (robust Sharpe/CIs); ML-focused. *High reuse.*
- **`abbass2/pyqstrat`** — fast (Cython/C++) with strong **PNL-attribution**
  (contract groups, futures+options, delta hedge), custom fills, multi-CPU optim.
- **`quantrocket-llc/moonshot`** — `prices_to_signals`/`signals_to_target_weights`
  convention-driven vectorized Pandas backtester.
- **`jrmeier/fast-trade`** — JSON-config-driven crypto backtests + parquet archive.

### 3c. Microstructure-realistic backtesting
The most rigorous fill/latency modeling — corrects naive mid-fill bias.

- **`nkaz001/hftbacktest`** (Py/Rust) — **most realistic**: feed + order latency
  modeling, **order-queue-position** fills, full L2/L3 order-book reconstruction,
  tick-by-tick, Numba JIT; GLFT grid + OBI alpha; live bot. *Very high value.*
- **`FlashAlpha-lab/flashalpha-fill-simulator`** — post-and-wait queue modeling,
  stale-quote guards, deterministic tiebreaking, edge-captured metric for options
  spreads. *Excellent realistic-fill primitive.*
- **`nautechsystems/nautilus_trader`** (Rust/Py) — production event engine with
  deterministic **backtest↔live parity**, nanosecond clock, latency modeling.
- **`jensnesten/rust_bt`**, **`MathisWellmann/lfest-rs`** (Rust) — bid-ask/slippage/
  margin sim, leveraged perpetual-futures simulator.

### 3d. Backtest→live bridges & deploy
- **`StrateQueue/StrateQueue`** — bridges backtrader/zipline/vectorbt/backtesting.py
  to live brokers with no code change.
- **`Lumiwealth/lumibot`** — same code backtest/paper/live; **rigorous corporate-
  action (split/dividend) handling** with no-fake-data policy. *High reuse.*
- **`coding-kitties/investing-algorithm-framework`**, **`timkpaine/aat`** — unified
  backtest+deploy pipelines.

**Anti-overfitting / validation toolkits (critical, cross-cutting):**
- **`bcosm/backtester-mcp`** — **Probability of Backtest Overfitting (PBO)**,
  **Deflated Sharpe Ratio**, bootstrap CIs, walk-forward; MCP-native. *High value.*
- **`Miasyster/QuantGPT`**, **`arteemg/AutoHypothesis`**, **`NeuZhou/finclaw`** —
  strict train/dev/holdback/walk-forward harnesses, Monte-Carlo robustness, GA
  strategy evolution with anti-overfit gating.

---

## 4. Portfolio optimization & allocation

Extremely deep coverage — convex, hierarchical, risk-parity, heuristic, online, ML.

### 4a. Convex / mean-risk optimizers (Python, directly usable)
- **`dcajasn/Riskfolio-Lib`** — **26 convex risk measures** (CVaR, EVaR, Relativistic
  VaR, Tail Gini, MAD, GMD, Sortino/Omega, drawdown), HRP/HERC, risk-parity,
  Black-Litterman, factor models, NCO, efficient frontier. *Very high reuse.*
- **`robertmartin8/PyPortfolioOpt`** — mean-variance (efficient frontier, max
  Sharpe, min vol), Black-Litterman, HRP, CVaR/CDaR, Ledoit-Wolf shrinkage, L2
  reg, discrete allocation. *Premier, high-value integration.*
- **`skfolio/skfolio`** — **sklearn-API** portfolio optimization: Mean-Risk, Risk
  Budgeting, Max Diversification, Distributionally Robust CVaR, HRP/HERC, Nested
  Clusters, Schur complementary, stacking; rich covariance estimators (Gerber,
  denoising, Ledoit-Wolf, OAS, graphical lasso); CV + hyperparameter tuning.
  *Modern, cross-validation-native — strong fit.*
- **`fortitudo-tech/fortitudo.tech`** — **Sequential Entropy Pooling**, CVaR
  optimization, Fully Flexible Resampling — rare, production-grade methods.

### 4b. Risk parity
- **`dppalomar/riskparity.py`** — Spinu convex + cyclical coordinate + SCA for
  nonconvex. *Directly importable.* (R twin: `riskParityPortfolio`.)
- **`pmorissette/ffn`** — ERC/risk-parity + mean-variance weight calc primitives.

### 4c. Hierarchical / clustering / robust covariance
- **`emoen/Machine-Learning-for-Asset-Managers`** — de Prado **Marcenko-Pastur
  denoising/detoning**, optimal KDE bandwidth, **Optimal Number of Clusters (ONC)**.
- HRP/HERC appear across Riskfolio-Lib, PyPortfolioOpt, skfolio, mlfinlab.

### 4d. Online Portfolio Selection (OLPS)
- **`Marigold/universal-portfolios`** — **most complete OLPS suite in OSS**:
  Universal Portfolios (Cover), CRP/BCRP/DCRP, EG, ONS; follow-the-loser (Anticor,
  PAMR, OLMAR, RMR, CWMR, WMAMR, RPRT); pattern-matching (BNN, CORN); Kelly.
  *Ideal core for an OLPS module.*

### 4e. Heuristic / ML / specialized
- **`enricoschumann/NMOF`** (R) — Differential Evolution, GA, Particle Swarm,
  Simulated Annealing, Threshold Accepting for nonconvex problems.
- **`jankrepl/deepdow`** (PyTorch) — **end-to-end differentiable allocation**
  (forecasting + convex optimization layers in one forward pass).
- **`tradytics/eiten`** — **eigen portfolios** (PCA), min-variance, max-Sharpe, GA.
- **`dppalomar/sparseIndexTracking`** — sparse **index replication** (ETE/HETE/HDR).
- **`cjroth/rebalance`** — largest-remainder **whole-share rebalancing**.
- **`deltaray-io/kelly-criterion`** — multi-security Kelly leverage `f=μ/σ²`.
- **`lequant40/portfolio_allocation_js`** (JS) — broad allocation algorithm catalog.
- **R references:** `braverock/PortfolioAnalytics` (CVXR LP/QP/SOCP/SDP/MIP, robust
  covariance, regime switching, multi-layer), `dppalomar/pob`.

---

## 5. Technical indicators

Two paradigms: **batch** (vectorized over a full series) and **streaming/
incremental** (O(1) per-tick updates for live feeds).

### 5a. Batch libraries (Python)
- **`mrjbq7/ta-lib` / `TA-Lib/ta-lib-python`** — Cython bindings to TA-Lib C; 150+
  indicators + candlestick patterns. *Foundational, common dep.*
- **`bukosabino/ta`** — 43 pure-Pandas indicators (volume/volatility/trend/momentum),
  sklearn-friendly. *Clean, directly usable.*
- **`peerchemist/finta`** — 80+ Pandas indicators incl. adaptive MAs (KAMA/HMA/
  ZLEMA/FRAMA), channels. *Dependency-light, portable.*
- **`mementum/bta-lib`**, **`femtotrader/pandas_talib`** — pure-Python composable.
- **`cirla/tulipy`** — Cython bindings to Tulip Indicators C (fast TA-Lib alt).

### 5b. Streaming / incremental indicators
O(1) stateful updates with append/update-last/remove + chaining.

- **`nardew/talipp`** — incremental TA, indicator chaining, large set (Williams %R,
  Ichimoku). *Strong streaming engine.*
- **`mr-easy/streaming_indicators`** — stateful SMA/EMA/WMA/SMMA/RMA/RSI; O(1).
- **`MathisWellmann/sliding_features-rs`** (Rust) — composable zero-cost View tree.
- **`femtotrader/OnlineTechnicalIndicators.jl`** (Julia) — incremental TA.

### 5c. Indicator tuning
- **`jmrichardson/tuneta`** — optimizes TA params via **distance correlation** to a
  target return; Optuna + KMeans cluster selection to avoid "lucky" params; prunes
  correlated features for ML. *High value for feature engineering.*

### 5d. Reference catalogs (other languages)
`cinar/indicator` (Go, 80+), `cinar/indicatorts` (TS), `TulipCharts/tulipindicators`
(C, 100+), `ta4j/ta4j` (Java, 200+ + rule DSL), `dysonance/Indicators.jl`
(adaptive MAMA/MESA), `joshuaulrich/TTR` (R).

---

## 6. Options & derivatives pricing

Spans closed-form, lattice, Monte-Carlo, Fourier/transform, and exotics.

### 6a. Closed-form & Greeks/IV (Python, usable)
- **`vollib/py_vollib`** — Black/BS/BSM pricing, **LetsBeRational** fast/accurate
  implied vol (Jäckel), analytic + numeric Greeks. *High value.*
- **`dbrojas/optlib`** + **`dedwards25/Python_Option_Pricing`** — GBS, Asian, Kirk
  spread, **Bjerksund-Stensland (2002) American**, IV, Greiks; option-chain fetch.
- **`bbcho/finoptions-dev`** — Generalized Black-Scholes (analytic Greeks + IV),
  finite-difference Greeks for exotics, vectorized multi-input.
- **`quantsbin/Quantsbin`** — multi-asset (Equity/FX/Commodity/Futures) BSM/binomial/
  MC (American via LSM), Greeks, IV, payoff/strategy builder, cost-of-carry variants.
- **`opendoor-labs/pyfin`** — BS + binomial + MC, Greeks per model, discrete
  dividends, American via Longstaff-Schwartz.
- **`mcdallas/wallstreet`** — real-time Greeks + IV, scrapes Treasury for `r`.

### 6b. Multi-leg strategy analytics
- **`rgaveiga/optionlab`** — P/L profile, profitable ranges, per-leg Greeks,
  **probability of profit** (distribution / Monte Carlo). *Great for strategy module.*
- **`taylorizing/options.studies`** (R) — covered call, calendar, PMCC, straddle.
- **`deltaray-io/strategy-library`** — ready-made options strategy definitions.

### 6c. Full pricing libraries (broad)
- **`domokane/FinancePy`** (Numba) — equity/FX/rates/credit derivatives, bonds,
  curves, Monte Carlo. *Very high value, pure-Python.*
- **`lballabio/QuantLib`** (C++) + Python access via **`enthought/pyql`** /
  **`auto-differentiation/QuantLib-Risks-Py`** (XAD **AAD** for fast Greeks). The
  gold-standard pricing/fixed-income engine.
- **`yhilpisch/dx`** — global Monte-Carlo valuation of complex derivative portfolios,
  correlated risk factors, PV/vega surfaces. *High value.*
- **`google/tf-quant-finance`** (archived) — vectorized auto-diff PDE/MC, Ito
  framework, copula samplers.

### 6d. Fourier / transform / advanced
- **`jkirkby3/fypy`** — Python **PROJ** (frame projection), Lewis, Gil-Pelaez,
  Carr-Madan, Hilbert; Lévy/SV/SVJ/SABR **calibration** to market data. *High value.*
- **`yhilpisch/dawp`** — Carr-Madan/Lewis FFT, Heston, Bates/Merton jump-diffusion
  calibration to vol surfaces. *Strong reference.*
- **`LechGrzelak/*`** (course/book) — Heston, affine jump-diffusion, COS, MC Greeks,
  Bates. *Gold-standard pricing references.*
- **`Julian-Beatty/Pyderivatives`** — option-implied **risk-neutral density (RND)**,
  pricing-kernel & physical-density surfaces, risk-aversion surfaces. *Rare/valuable.*
- **`differential-machine-learning/notebooks`** — Differential ML twin networks
  (AAD pathwise) for pricing/Greeks; differential PCA/regression.
- Lattice: **`federicomariamassari/willowtree`** (Curran willow tree),
  **`federicomariamassari/financial-engineering`** (Merton jump-diffusion MC).

### 6e. AAD for risk (sensitivities)
- **`auto-differentiation/xad` / `xad-py`** — forward/adjoint AD via operator
  overloading; JIT record-replay for Monte Carlo. Powers fast full-graph Greeks.

---

## 7. Volatility modeling

### 7a. GARCH family (econometric)
- **`bashtage/arch`** — **best-in-class Python**: ARCH/GARCH/EGARCH/HARCH/FIGARCH/
  APARCH, normal/t/skew-t/GED distributions; unit-root (ADF/DFGLS/PP/KPSS/Zivot-
  Andrews), cointegration (Engle-Granger, Phillips-Ouliaris), IID/block bootstrap,
  multiple-comparison (SPA/Reality Check/StepM/MCS). *Foundational.*
- **`RJT1990/pyflux`** — Bayesian Beta-t-EGARCH, EGARCH-in-mean, Long-Memory, GAS.
- R references: **`alexiosg/rugarch`** (univariate, definitive + VaR/ES backtests),
  **`alexiosg/rmgarch`** (multivariate DCC/aDCC, GO-GARCH-ICA, GARCH-Copula),
  **`AlbertoAlmuinha/garchmodels`** (tidymodels API).

### 7b. Range-based realized volatility estimators
- **`jasonstrimpel/volatility-trading`** — Garman-Klass, Hodges-Tompkins,
  Parkinson, Rogers-Satchell, **Yang-Zhang**, plus skew/kurt/correlation + vol cones.
  *Directly usable.* (Also in `ArturSepp/QuantInvestStrats` OHLC estimators.)
- **`davidastephens/pandas-finance`** — rolling realized vol.

### 7c. Stochastic-vol smiles & surfaces
- **`ynouri/pysabr`** — **SABR** Hagan-2002 lognormal & normal, smile calibration,
  ATM fitting (swaptions/caps). *High value for rates vol.*
- **`ryanmccrickerd/rough_bergomi`** — **rough Bergomi** (Bayer-Friz-Gatheral),
  hybrid scheme, variance-reduction MC. **`jgatheral/RoughVolatilityWorkshop`** —
  rough Heston, fBM/Hurst<0.5. **`ryanmccrickerd/frh-fx`** — fast-reversion Heston FX.
- **`ysaporito/modelos_vol_derivativos`** — Dupire local vol + Heston/SABR surface
  calibration. **`MarcosCarreira/DermanPapers`** — local vol / implied trees.
- **`wol-fi/direct_vola`** — fast closed-form (inverse-Gaussian) IV approximation.

### 7d. Synthetic data with realistic vol
- **`welcra/fsynth`** — Heston + Merton jumps + regime-switching correlations, vol
  clustering/fat tails, linked synthetic fundamentals. *High value for ML/stress.*
- **`brotto/crng`** — RNG fitted to a real series' statistical fingerprint (fat
  tails, vol clustering) for Monte Carlo stress testing.

---

## 8. Time-series & forecasting

### 8a. Classical
- **`alkaline-ml/pmdarima`** — R-style **auto.arima** (stepwise SARIMA search),
  ADF/KPSS/PP/OCSB/CH tests, Box-Cox/Fourier transforms, TS cross-validation.
- **`statsmodels/statsmodels`** — ARIMA/SARIMAX/VAR/state-space, Kalman, Johansen
  cointegration, HAC/Newey-West. *Core dep.*
- **`facebook/prophet`** — additive changepoint trend + Fourier seasonality +
  holidays; robust to gaps/outliers. *Drop-in for any series.*

### 8b. Scalable & deep probabilistic
- **`awslabs/gluon-ts`** — DeepAR, DeepState, MQ-CNN/RNN, TFT, N-BEATS, WaveNet,
  DeepVAR; distributional/quantile output; **Chronos** zero-shot. *Production-grade.*
- **`functime-org/functime`** (Polars) — global panel forecasting + tsfresh/Catch22
  features + FLAML auto-tuning + expanding/sliding CV. *Fast, scalable.*
- **`pymc-devs/pymc`** — Bayesian MCMC (NUTS/HMC), VI; probabilistic forecasting.

### 8c. Feature engineering & smoothing
- **`blue-yonder/tsfresh`** — automatic extraction of 100s of TS features + FRESH
  hypothesis-test feature selection (FDR control). *Excellent for ML.*
- **`cerlymarco/tsmoothie`** — vectorized smoothing (exp/conv/spectral/spline/
  Gaussian/LOWESS/Kalman) with sigma/confidence/prediction intervals for anomalies.
- **`matrix-profile-foundation/matrixprofile`** — Matrix Profile motif/discord
  discovery, FLUSS segmentation, anomaly detection. *Novel pattern mining.*

### 8d. Trend / cycle / bubble detection
- **`rafa-rod/pytrendseries`** — trend detection, duration, drawdown/drawup.
- **`maread99/market_analy`** — trend definition & movement analysis.
- **`Boulder-Investment-Technologies/lppls`** — **LPPLS** log-periodic power-law
  singularity bubble/crash detection (CMA-ES, Numba). *Niche, self-contained.*
- **`LenkaV/CIF`** — OECD **Bry-Boschan** turning-point detection + composite
  leading indicators. *Unique macro-cycle analytics.*
- **`AccursedGalaxy/wasserstein-btc`** — Wasserstein-geodesic distributional return
  forecasting; CRPS/Diebold-Mariano scoring, stationary bootstrap, VaR/ES tail tests.

---

## 9. Machine learning & reinforcement learning

### 9a. Financial ML platforms / methods
- **`microsoft/qlib`** — **end-to-end AI quant platform**: alpha factor mining,
  supervised models (LightGBM/transformers), market-dynamics/concept-drift, **RL for
  order execution**, portfolio optimization, full backtest; RD-Agent LLM factor
  mining. *Very high value.*
- **`boyboi86/AFML`** + **`hudson-and-thames/mlfinlab`** (full code now gated) —
  **López de Prado**: info-driven bars (dollar/volume/imbalance), triple-barrier &
  meta-labeling, fractional differentiation, **purged/embargoed K-fold CV**, sample
  uniqueness/sequential bootstrap, MDI/MDA/SFI feature importance, bet sizing, HRP.
  *Gold-standard labeling/validation — re-implement (mlfinlab is restricted).*
- **`asavinov/intelligent-trading-bot`** — **offline/online feature-parity**
  pipeline, declarative derived-feature & label generators. *Strong design pattern.*
- **`ScottfreeLLC/AlphaPy`** — blended/stacked ensembles, feature engineering,
  MarketFlow market-ML + portfolios.

### 9b. Deep learning & RL trading agents
- **`AI4Finance-LLC/FinRL-Library`** — DRL for trading: A2C/DDPG/PPO/SAC/TD3,
  Gym market envs, train-test-trade pipeline, transaction-cost/turbulence rewards.
- **`huseinzol05/Stock-Prediction-Models`** — 30+ DL forecasters + 23 RL agents
  (evolution-strategy, DQN/dueling, actor-critic, policy gradient) + GAN sims.
- **`RichardS0268/Autoencoder-Asset-Pricing-Models`** — **conditional autoencoders**
  / IPCA (Gu-Kelly-Xiu) with characteristic-conditioned betas.
- **`yupoet/aurumq-rl`** — Alpha101 + GTJA191 factors + Stable-Baselines3 RL.

### 9c. ML cookbooks / references (educational)
`stefan-jansen/machine-learning-for-trading` (150+ notebooks), `packtpublishing/
hands-on-machine-learning-for-algorithmic-trading`, `mfrdixon/ML_Finance_Codes`,
`cerlymarco/MEDIUM_NoteBook` (conformal prediction, Granger, SHAP drift),
`yhilpisch/aiif`, `edgararuiz/tidypredict` (model→SQL).

---

## 10. Factor & alpha research

### 10a. Factor evaluation toolkits
- **`quantopian/alphalens`** + **`stefan-jansen/alphalens-reloaded`** — **IC
  analysis**, quantile returns, turnover, grouped/sector analysis, factor tear
  sheets. *Canonical — drop-in for alpha research.*
- **`VernonOY/alpha-skills`**, **`Miasyster/QuantGPT`** — IC/ICIR/quintile-spread,
  alpha-decay monitoring, anti-overfit + walk-forward, packaged as agent skills.

### 10b. Formulaic alpha libraries
- **`ram-ki/101_formulaic_alphas`** — WorldQuant **101 Formulaic Alphas** with
  rank/ts_rank/correlation/delay/decay_linear operators. *Directly valuable.*
- **`yupoet/aurumq-rl`** — Alpha101 (105) + GTJA191 (191) factor libraries.

### 10c. Factor models & covariance
- **`Heerozh/spectre`** — **GPU-accelerated** factor engine (alphalens/pyfolio-
  compatible), cross-sectional rank/zscore, up to 77× zipline. *High value.*
- **`dppalomar/covFactorModel`**, **`dppalomar/sparseEigen`** (sparse PCA),
  **`braverock/FactorAnalytics`** (fundamental/TS/statistical factor models, FMMC),
  **`husainm97/quant-lab-alpha`** (FF5 rolling regression, Ledoit-Wolf, block
  bootstrap), **`JustinMShea/ExpectedReturns`** (Ilmanen factor premia).

### 10d. Empirical asset pricing & pairs/stat-arb
- **`tidy-finance/r-tidyfinance`** — portfolio sorts/breakpoints/long-short.
- **`euclidjda/value-investing-studies`** — value vs inflation/rates/growth.
- **`artyyouth/r-quant`**, **`financialnoob/misc`** — cointegration screening, ADF,
  regression hedge ratios, copulas, state-space, partial-AR pairs trading.
- **`cesabici-bit/omni-oracle`** — multiple-testing-corrected lagged Granger-
  causality discovery across 500+ series.

---

## 11. Risk management

- **VaR / CVaR / ES:** `omichauhan-lgtm/quantitative-finance-tools` (MVO + VaR/CVaR),
  `QuantOracledev/quantoracle` (parametric VaR + CVaR, Kelly), `Mattbusel/fin-stream`
  (rolling historical-sim VaR, max drawdown), Riskfolio-Lib (26 measures).
- **Tail backtesting:** `AccursedGalaxy/wasserstein-btc` and R `rugarch` —
  **Kupiec, Christoffersen, Acerbi-Szekely** VaR/ES tests, Diebold-Mariano.
- **Kelly sizing:** `deltaray-io/kelly-criterion` (`f=μ/σ²`),
  `cryptomotifs/cipher-starter` (fractional Kelly + ATR stops + circuit breakers),
  `YichengYang-Ethan/oracle3` (Wang-transform calibrated pricing + Kelly + arb).
- **Stress testing / scenarios:** `husainm97/quant-lab-alpha` (leverage/margin
  mechanics), `brotto/crng` & `welcra/fsynth` (synthetic-data stress), `MarcusRainbow/
  QuantMath` (scenario bump reuse).
- **R canon:** `braverock/PerformanceAnalytics` (modified Cornish-Fisher VaR/CVaR).

---

## 12. Performance analytics & reporting

- **`quantopian/empyrical` / `stefan-jansen/empyrical-reloaded`** — Sharpe, Sortino,
  Calmar, Omega, max drawdown, alpha/beta, tail ratio, VaR, downside risk, FF
  loadings. *Clean, directly usable.*
- **`quantopian/pyfolio` / `stefan-jansen/pyfolio-reloaded`** — tear sheets, rolling
  Sharpe/beta, drawdown periods, Bayesian (PyMC) performance, round-trip stats.
- **`ranaroussi/quantstats`** — stats + plots + HTML tear sheets + Monte Carlo
  bust/goal probabilities. **`Jebel-Quant/jquantstats`** — Polars-native successor,
  execution-lag analysis. **`pmorissette/ffn`** — perf functions under `bt`.
- **`ArturSepp/QuantInvestStrats`** — production-grade factsheets, attribution,
  regime-conditional analytics, EWM factor/covariance, block bootstrap. *Very high.*
- **`ssantoshp/Empyrial`** — QuantStats + PyPortfolioOpt all-in-one wrapper.
- **`ymyke/pypme`** — **Public Market Equivalent** (Kaplan-Schoar) + XIRR for PE.
- **Visualization:** `matplotlib/mplfinance` (candles/Renko/P&F), `highfestiva/
  finplot` & `man-group/dtale` (fast/interactive EDA), `devexperts/dxcharts-lite` &
  `devexperts`-style TS charting for desktop.

---

## 13. Fixed income & structured finance

- **Curve construction:** `lballabio/QuantLib` (bootstrapping, day-counts, calendars),
  `Mattbusel/fin-primitives` (Nelson-Siegel + cubic spline + duration/convexity +
  curve-shape classification), `attack68/book_irds3` (IRS curve build/risk).
  *License-restricted study-only:* `attack68/rateslib` (multi-curve AD risk).
- **Pricing libraries:** `domokane/FinancePy`, `OpenGamma/Strata` (Java; institutional
  rates: swaps/FRAs/caps/swaptions/CDS, PV01), `amaggiulli/qlnet` (C# QuantLib + MBS
  PSA prepayment), `pazzo83/QuantLib.jl`.
- **Credit:** `blenezet/credule` (CDS survival/hazard-curve bootstrapping, Brent).
- **Structured finance:** `yellowbean/AbsBox` — **ABS/MBS waterfall** cashflow engine
  (Hastructure backend), scenario/assumption analysis. *High value for securitization.*
- **Valuation/DCF:** `akashaero/Intrinsic-Value-Calculator` (DCF + **reverse-DCF**
  implied-assumption solver), `defeat-beta/defeatbeta-api` (automated 10-yr DCF).
- **Day-count / calendars:** `wilsonfreitas/python-bizdays`, `gerrymanoim/
  exchange_calendars` (50+), `rsheftel/pandas_market_calendars` (50+). *Usable.*
- **Amortization:** `murraystokely/mortgagemath` (Decimal-exact, 30/360 & Act/360).
- **TVM/ratios:** `ebradyjobory/finance.js`, `felixfan/FinCal` (R).

---

## 14. Market microstructure & execution

- **`nkaz001/hftbacktest`** — L2/L3 order-book reconstruction, queue-position fills
  (see §3c). *Most realistic microstructure backtester.*
- **`whoareunot/btc-orderbook-research`** — **Order Book Imbalance (OBI)** signal
  decay/autocorrelation, OBI→forward-return Spearman, **Cumulative Volume Delta
  (CVD)** lead/lag, spread dynamics. *Strong feature reference.*
- **`Mattbusel/fin-stream`** — **Lee-Ready (1991)** trade classification + order-
  imbalance accumulator. *Useful microstructure primitive.*
- **Custom bars:** `MathisWellmann/trade_aggregation-rs` (volume/tick/Renko/VWAP/
  Shannon-entropy bars), `focus1691/orderflow` (footprint candles), `femtotrader/
  OnlineResamplers.jl` (streaming tick→OHLC).
- **LOB simulators:** `DrAshBooth/PyLOB` (price-time priority), `PIYUSH-KUMAR1809/
  order-matching-engine` (C++, ~160M/s).
- **Tick data:** `tardis-dev/tardis-python`, `crypto-lake/lake-api` (L2 + parallel S3).

---

## 15. Trading bots & execution frameworks

Mostly architecture references (broker connectivity, strategy DSLs, backtest→live).

- **Crypto bots:** `freqtrade/freqtrade` (backtest + hyperopt + FreqAI ML),
  `jesse-ai/jesse` (genetic optim, accurate fees), `Drakkar-Software/OctoBot`
  (grid/DCA + TA evaluators), `Blankly-Finance/Blankly`, `gbeced/basana` (async).
- **Multi-asset platforms:** `nautechsystems/nautilus_trader` (Rust, prod parity),
  `StockSharp/StockSharp` (.NET, 70+ connectors), `vnpy/vnpy` & `yutiansut/quantaxis`
  (China-focus full platforms), `ranaroussi/qtpylib` (IBKR).
- **Signal fusion / consensus:** `nazmiefearmutcu/TRADING-BOT` (15-indicator weighted
  consensus × 12 timeframes), `naimkatiman/tradeclaw`, `squidKid-deluxe/QTradeX-AI-
  Agents` (~40 indicator-confluence recipes), `alex-jb/orallexa-ai-trading-agent`
  (8-source fusion + adaptive per-source weighting).
- **Optimizers in bots:** `squidKid-deluxe/QTradeX-Algo-Trading-SDK` (QPSO quantum
  PSO + LSGA genetic).

---

## 16. Market data providers

Mostly provider wrappers — relevant as **OpenBB provider patterns** or new-market
coverage; few contain novel algorithms.

- **Aggregators / unified:** `cuemacro/findatapy` (Bloomberg/FRED/Quandl/Yahoo +
  **FX-cross auto-derivation**), `theOGognf/finagg` (SEC+FRED+BEA feature store),
  `eslazarev/pricehub` (multi-exchange unified OHLC), `ccxt/ccxt` (100+ crypto).
- **Fundamentals / filings (SEC/XBRL):** `dgunning/edgartools` (XBRL-standardized
  statements, 13F, insider), `john-friedman/datamule-python` (bulk EDGAR),
  `jaablon/filingfirehose-python` (8-K event detection, 13D/G activist tags),
  `JerBouma/FinanceDatabase` (300k+ symbol categorization).
- **Macro / statistical:** `dr-leo/pandaSDMX` (SDMX: World Bank/ECB/Eurostat/OECD),
  `TomasKoutek/pystlouisfed` (typed FRED), `econdb/inquisitor`.
- **Regional:** `jindaxiang/akshare` & `zvtvz/zvt` (China), `jugaad-py/jugaad-data`
  (India NSE/RBI), `ajtgjmdjp/edinet-mcp` (Japan XBRL, multi-GAAP normalization),
  `wilsonfreitas/python-bcb` & `ropensci/rb3` (Brazil).
- **Storage backends:** `man-group/ArcticDB` (versioned time-travel DataFrame DB,
  billions of rows), `pola-rs/polars` (lazy columnar engine).
- **Calendars/OHLCV:** `maread99/market_prices` (calendar-aware multi-interval bars).

*(Many thin/obsolete Yahoo/YQL/Google wrappers — listed in digests, skip for reuse.)*

---

## 17. Agent / MCP patterns

A notable emerging cluster — finance capabilities exposed as **MCP tool servers** or
multi-agent systems (directly relevant to OpenBB's agent direction).

- **Quant calculators as MCP:** `QuantOracledev/quantoracle` (63 deterministic
  calculators: Greeks, IV, VaR/CVaR, Kelly), `vdalhambra/financekit-mcp`,
  `bcosm/backtester-mcp` (PBO/Deflated-Sharpe validation tools).
- **Factor research as agents:** `Miasyster/QuantGPT` (15 MCP tools, anti-overfit),
  `VernonOY/alpha-skills`, `augiemazza/varrd` (governed statistical-edge engine).
- **Multi-agent analysis floors:** `demandai/ai-quant-agents` (12-agent analyst/
  bull/bear/risk consensus), `dragon1086/prism-insight`, `alex-jb/orallexa` (LLM
  Bull/Bear/Judge debate + prediction-market votes).
- **Pattern/cohort intelligence:** `grahammccain/chart-library-mcp` (chart-pattern
  embeddings → forward-return distributions, win rates).

---

## 18. Cross-cutting "best of breed" shortlist

If building OpenBB quant capabilities, these are the highest-leverage, Python-first,
permissively-licensed sources to study or depend on:

| Capability | Top picks |
|---|---|
| Volatility (GARCH/econometrics) | `bashtage/arch` |
| Range vol estimators | `jasonstrimpel/volatility-trading` |
| Options Greeks/IV | `vollib/py_vollib`, `domokane/FinancePy` |
| Options strategy P/L + PoP | `rgaveiga/optionlab` |
| Fourier pricing + calibration | `jkirkby3/fypy` |
| Portfolio optimization | `dcajasn/Riskfolio-Lib`, `robertmartin8/PyPortfolioOpt`, `skfolio/skfolio` |
| Entropy pooling / CVaR | `fortitudo-tech/fortitudo.tech` |
| Online portfolio selection | `Marigold/universal-portfolios` |
| Factor evaluation | `stefan-jansen/alphalens-reloaded` |
| Formulaic alphas | `ram-ki/101_formulaic_alphas` |
| Performance metrics | `stefan-jansen/empyrical-reloaded` |
| Tear sheets / reporting | `ranaroussi/quantstats`, `ArturSepp/QuantInvestStrats` |
| Forecasting (deep/probabilistic) | `awslabs/gluon-ts`, `facebook/prophet`, `functime` |
| TS feature engineering | `blue-yonder/tsfresh`, `jmrichardson/tuneta` |
| Financial ML methods | `boyboi86/AFML` (re-implement mlfinlab), `microsoft/qlib` |
| Vectorized backtest | `polakowo/vectorbt`, `edtechre/pybroker` |
| Microstructure backtest | `nkaz001/hftbacktest` |
| Anti-overfit validation | `bcosm/backtester-mcp` (PBO/Deflated Sharpe) |
| Technical indicators (batch) | `mrjbq7/ta-lib`, `bukosabino/ta` |
| Technical indicators (streaming) | `nardew/talipp` |
| Fixed income curves | `domokane/FinancePy`, `lballabio/QuantLib` |
| Structured finance waterfalls | `yellowbean/AbsBox` |
| Calendars | `gerrymanoim/exchange_calendars` |
| Synthetic data | `welcra/fsynth` |

---

## 19. License / reuse notes

- **Permissive (study + reuse, subject to attribution):** most listed Python libs
  (MIT/BSD/Apache) — verify each repo's LICENSE before vendoring.
- **Source-available / restricted (study ONLY, do not copy):**
  - `attack68/rateslib` — commercial use requires paid licence.
  - `hudson-and-thames/mlfinlab` — full code gated/commercial; re-implement AFML
    methods from López de Prado's published book instead (`boyboi86/AFML` is a
    permissive companion).
  - `goldmansachs/gs-quant` — pricing depends on GS Marquee (client-only API).
- **Wrong-language for direct dep (port/reference only):** all R, Julia, Rust, C++,
  C#, Go, Scala, Java, TS repos. Use them as algorithm sources to re-implement in
  Python or to expose via bindings.
- **Obsolete / skip:** legacy Yahoo/YQL/Google-Finance scrapers, defunct broker
  wrappers (TD Ameritrade), deprecated frameworks (catalyst, pyalgotrade).

> **Golden rule:** treat this corpus as a *design reference and sourcing index*.
> When implementing in OpenBB, prefer a small set of well-maintained permissive
> dependencies (or clean re-implementations from public papers) over wholesale
> vendoring, and always honor upstream licenses.
