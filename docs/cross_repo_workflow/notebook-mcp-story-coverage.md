# Notebook stories, MCP coverage and Python-agent delivery

**Audit date:** 2026-10-03  
**Source baseline:** Portfolio `39f171603c9bc4a28778e668ba981cf0e4358b9a`,
including the preserved pre-existing working-copy change to the Portfolio
single-name deep dive. This is not a claim that the dirty notebook is committed
at that SHA.

## 1. Executive verdict

**The notebooks are not yet proven reproducible or manageable end-to-end through
MCP.** Many API primitives are already discoverable, but notebook-local state,
direct Python engines, workflow orchestration, artifacts and approvals require
additional contracts and tests.

The follow-on Python **Notebook MCP Companion** is specified to demonstrate
genuine MCP coverage: it may not bypass gaps with direct `obb` calls, provider
SDKs, SQL, generated Python, or execution of the original notebooks.

| Measurement | Result | Interpretation |
| --- | ---: | --- |
| Notebook files inventoried | 25/25 | Eight Portfolio, eight Portfolio YFinance, nine TechTrade |
| Distinct filename/story families | 17 | Eight paired Portfolio families plus nine TechTrade families |
| Cells labeled code | 243 | Source metadata count, not executed cells |
| Unparsed code-labeled cells | 1 | TechTrade morning-scan cell 7 contains narrative text |
| Unique literal `obb.*` call targets in parsed notebook source | 40 | Includes helper bodies; excludes calls hidden in imported engines/dynamic dispatch |
| Those 40 literal targets matching the richer audited MCP API catalog | 40/40 | Static route/name matches, not successful execution or default-launcher coverage |
| Notebook end-to-end runs performed in this audit | 0 | Deliberately not executed; runtime story parity is unmeasured |
| Planned notebook-agent implementation tasks | 24 | Follow the 44-task base MCP program; all blocked by its T44 release |

Do not interpret 40/40 as 100% notebook coverage. In particular:

- The current Portfolio deep dive delegates to `Analysis/stock_analysis.py`.
  Its seven-phase `run_full_analysis` pipeline does not appear as a literal
  `obb.*` call in that notebook.
- TechTrade T5 notebooks directly instantiate order sinks and SQLite paper
  engines. Those are not automatically MCP tools.
- Matching a tool name says nothing about credentials, schema compatibility,
  provider entitlement, cache behavior, artifacts or authorization.
- FMP Cached remains the earlier audit's **70/181 model keys routed**, with
  **111 routing gaps** and **58 non-persistent fallback registrations**.
  Notebook-specific work does not erase those prerequisites.

## 2. Deliverables and work-of-record

- [Machine-readable source inventory](notebook-mcp-story-inventory.csv):
  all 25 paths, source-only hashes, cell counts, literal SDK calls, matching tools,
  direct engine/state/artifact call sites and task owners.
- [Functional requirements and acceptance](../Specs/notebook-mcp-agent/requirements.md).
- [Engineering design](../designs/notebook-mcp-agent-design.md).
- [Notebook-agent implementation plan](../superpowers/plans/2026-10-03-notebook-mcp-agent.md).
- [Base MCP implementation plan](../superpowers/plans/2026-10-03-portfolio-mcp-capability-parity.md).
- [GitHub issue map and verified project tracking](project-issue-map.md).

GitHub [Project #4](https://github.com/users/prajoria/projects/4/views/2) is the
work-of-record. Both programs target `prajoria/OpenBB` and the `portfolio`
integration branch. Creating issues does not close MCP gaps or deliver a
running agent.

## 3. Source-reading method and limits

Only notebook cell types and source were inspected. No saved outputs,
attachments, private account data or execution results were copied into the
report or fixtures. Source hashes cover ordered code/Markdown source, excluding
execution counts, outputs and metadata.

The call inventory statically traverses Python ASTs, including function bodies.
It therefore identifies **potential source call sites**, not observed execution
paths. Literal `obb` paths are matched to the earlier
[API inventory](../../openbb_platform/extensions/mcp_server/tests/fixtures/capability_audit/mcp-api-inventory.csv). Dynamic calls, imported engine internals,
provider selection and runtime data schemas require the planned contract tests.

The one parse exception is recorded rather than silently discarded:
[TechTrade morning scan](../../notebooks/techtrade/02-morning-scan.ipynb), cell 7,
contains a "Reading the output" narrative despite its code cell type. It was
not edited. N01 (#2211) classifies it as `narrative-in-code` in the inventory's
reviewed defect registry, so it stays visible without failing the drift check.
All other code-labeled cells parsed; this is not a runtime validity test.

### Reproducing the source inventory

`scripts/notebook_story_inventory.py` regenerates these source facts without
executing or importing any notebook. It uses the same fingerprint as this audit
(compact JSON of ordered `(cell_type, source)` pairs), so its hashes match the
[story inventory](./notebook-mcp-story-inventory.csv) for all 25 notebooks:

```powershell
.venv_portfolio\Scripts\python.exe scripts\notebook_story_inventory.py `
    --root notebooks `
    --check docs\cross_repo_workflow\notebook-mcp-story-inventory.csv
```

The command reports 25 stories, 17 families, 243 code cells' symbols by
one-based cell position, and the classified morning-scan diagnostic. It exits
1 if any notebook's source hash changed, a notebook was added or removed
without review, or a new unclassified parse failure appears. Diagnostics name
the cell position and error kind, never the cell text. Reviewing a change means
updating the story inventory row (and, for a defect, the registry) in the same
pull request.

### Stage readiness (N04, #2214)

The 25 manifests under `notebook_guide/stories/` map every notebook cell to a
stage, and every stage capability to the reviewed catalog. Each capability is
either a real Platform tool pinned by input-schema hash or a planned bridge
with its owning issue. `notebook_guide.readiness.check_readiness` evaluates a
story without any network, provider, job, browser or paper call.

Gross denominators at this baseline, counting every stage:

| Measure | Count |
| --- | ---: |
| Stories / ready stories | 25 / 11 |
| Stages | 287 |
| Setup and narrative stages (no capability needed) | 121 |
| Stages doing financial work | 166 |
| Of those, runnable on existing MCP tools | 129 |
| Stages waiting on a planned bridge | 37 |
| Missing, forbidden or browser-unavailable stages | 0 |

Planned capability needs by owning task (a stage can need more than one):

| Owner | Bridge | Needs |
| --- | --- | ---: |
| #2219 (N09) | Sandboxed Portfolio and TechTrade paper actions | 23 |
| #2220 (N10) | Provider variants and recording | 14 |

N04 reviewed the two bindings the generator could not decide. The morning-scan
cell 7 narrative needs no capability. The Portfolio chapter 1 preview of the
operator's local positions database is an optional stage bound only to the
Portfolio adapter's sanitized `portfolio_portfolio_snapshots` read, under a
new `private_read` access class that public profiles never grant.

N05a (#2313) moved 12 x-ray stages in the Portfolio chapters 3 and 8, in
both provider variants, onto four `story_*` tools: N-PORT look-through,
look-through sector view, concentration, and capped construction targets.
They use the same engine as the notebooks' `_nport_lookthrough` helper. The
free-tier chapters' hand-maintained issuer-to-sector map has no server tool,
so those two stages still need N05.

N05b (#2314) added `story_single_name_analysis`, which runs the repository's
seven-phase `Analysis` pipeline and returns every phase, gate diagnostics and
provenance. It binds the portfolio chapter 2 walk-through (including the
regime overlay and the bad-symbol check) and the chapter 8 spot check. The
TechTrade chapter 1 and Portfolio chapter 7 stages that also do other local
work bind it too, but still need N05 for the rest.

N05c (#2315) added `story_brinson_attribution`, `story_whatif_diff` and
`story_candidate_trades` for the Portfolio chapter 5 what-if and attribution
walk-through in both provider variants. Unlike the notebook, the what-if diff
never substitutes a $100 price for a missing quote. Review also reclassified
two chapter 4 stages that only illustrate a smart-money signal's shape as
narrative, which is why the financial-stage count fell by two.

N05d (#2316) added six `story_*` tools for the TechTrade chapters 1-6:
market weather, the local 13F institutional summary, actionable-plan review,
round-trip P&L, forward-bar replay with discipline statistics, and the
indicator-config review. Their math is `openbb_techtrade.engine.story_analytics`.
Review reclassified eight more stages that run nothing (dependency probes,
static decision tables and a code template) and two that only format a
Platform tool's report. The workbook finder now waits on the artifacts bridge
(N07) instead of N05. TechTrade chapter 3 is the first story whose every stage
is runnable on MCP tools.

N05e (#2321) closed out N05 and N06. Review of the last 39 `story:analytics`
needs found no further analytics adapter to build: they were environment
probes and illustrations (no capability), basket definitions and loads (run
state), recording and free-tier sector maps (N10), paper-engine fills (N09),
an exported CSV (N07) and timing loops that only orchestrate tools their
stages already bind. Cross-chapter run state now binds to the delivered N06
tools `story_run_get` and `story_run_checkpoint` instead of waiting on a
planned bridge. Nothing waits on N05 or N06.

N07 (#2217) added seven `story_artifact_*` tools. Five write into a run
the principal owns: a table (CSV or canonical JSON), a chart spec with its
data, an escaped HTML report that cites the run's other artifacts by ID and
hash, a typed workbook, and the TechTrade six-sheet export. `story_artifact_list`
and `story_artifact_read` find and read them back; workbooks come back as
bounded sheet previews. IDs are server-issued, names are labels, files are
created atomically without overwrite or link escape, spreadsheet cells cannot
hold formulas, and every read re-checks the stored SHA-256. Each of the 18
artifact stages has a reviewed binding:

- Eight chapter preambles and panel-only cells need no tool: they create the
  notebook's state directory or import its rendering toolkit.
- Portfolio chapter 6's preamble loads chapter 5's basket from run state.
- The two end-to-end capstones bind the report tool. The Portfolio one still
  needs N08 for the routine it times.
- TechTrade chapters 1 and 2 write the morning workbook into the run. This
  replaces `techtrade_export`, which writes under `Analysis/exports` and is an
  operator-only filesystem write.
- The chapter 6 audit lists and reads an earlier run's workbook.
- Chapters 7 and 9 read back the paper sink's CSV and workbook. Writing them
  is N09.

Portfolio chapters 3 and 4 and TechTrade chapters 2 and 6 joined TechTrade
chapter 3 as fully runnable.

N08 (#2218) added four `story_job_*` tools over the existing durable jobs
service: submit, list, get and cancel, all inside a run the principal owns.
They only enqueue; the existing worker runs five allowlisted kinds
registered through `openbb_job_extension`:

- `story.single_name`: the seven-phase `Analysis` pipeline.
- `story.backtest`: a `BacktestConfig` through `openbb_backtest`.
- `story.validate`: TechTrade validation of a plan.
- `story.tune`: TechTrade segment tuning, never persisted.
- `story.replay`: the forward-bar replay.

A caller-chosen operation ID makes submission idempotent: retrying after a
lost response returns the same job, and reusing the ID for anything else is a
`409`. The worker runs only submissions the routes recorded, writes the full
result as a run artifact, and fails a lost run once instead of repeating it.
Cancel reports `cancelled`, `too_late` (a claimed job is never interrupted) or
`already_finished`. A missing engine or worker definition is a `503` that
names it. Each of the 12 job stages has a reviewed binding:

- Backtests, validation and the two timed routines submit a job and read it
  back. The soft-dependency demo is the submission's `503`.
- Building a `BacktestConfig` prepares the next stage's payload; the free
  track's version also loads the basket from run state.
- TechTrade chapter 5's knob table and tuned-config check read
  `story_indicator_config`, which now lists the tunable knobs.

Six more stories became fully runnable: TechTrade chapters 1, 4 and 5, and
Portfolio chapters 6 and 8 and free-track chapter 6. The remaining stages wait
on N09 and N10. These figures are stage outcomes, not an API-count parity
claim.

N09a (#2331) added the paper gate that N09 builds on: six `story_paper_*`
tools over TechTrade's `SqlitePaperEngine` in isolated, principal-scoped
sandboxes. Preparing an action records it with an `ApprovalRequest` that binds
principal, sandbox, run, action, argument hash, manifest version, expiry and a
one-use nonce. No MCP tool approves. A person approves with
`python -m openbb_mcp_server.story_adapters.paper_approve <request_id>`, which
reads the stored arguments, needs a terminal and prints an HMAC keyed by the
operator's `OPENBB_STORY_APPROVAL_KEY`. Only portfolio-ops can apply, once, with
that approval; changed arguments, another sandbox, a changed manifest or an
expired approval are refused, and a re-delivered apply returns the first result.
Stage bindings follow in N09d (#2334), so the readiness figures above are
unchanged.

N09b (#2332) added the TechTrade batch tools. `story_paper_order_batch`
builds an `OrderBatch` from typed tickets, gates and provenance and returns
the engine's content SHA, any failed gates and the operator's "type this at
Fidelity" checklist. `story_paper_batch_artifacts` writes the batch through
`PaperOrderSink` and publishes the paired Fidelity CSV and six-sheet review
workbook as run artifacts, idempotently by batch SHA. Neither submits or
needs approval: a batch with failed gates is written so a reviewer sees them,
and only N09a's approved apply can submit, which refuses a failed verdict.

N09c (#2333) added the Portfolio engine. A sandbox created with
`engine: "portfolio"` holds a Portfolio Intelligence paper account, its lots
and its ledger in durable SQLite stores that implement the existing
`AccountStore`, `PositionStore` and `LedgerStore` protocols. The account,
fill, ledger, isolation and race suites now run against both the in-memory
and SQLite stores. The sandbox may open with chapter 5's seed lots, which
enter the ledger as a deposit and a trade, so it opens at its starting cash.
Its one action, `submit_order`, runs `submit_order` behind the N09a approval
gate. The approved arguments include the quote, so the person approves the
price the order fills against. At apply time the quote must not be stamped in
the future, be over 30 minutes old, or predate the book's last entry.
A business rejection is an applied result with its reason and the alert the
Portfolio alerts pipeline raises. The low-buying-power alert is that kind of
rejection, and it changes nothing. Every order lands on the sandbox blotter.
The sandbox state replays the ledger and reports whether it reconciles with
the live book. No tool was added.

The existing change to
[Portfolio single-name deep dive](../../notebooks/portfolio/02-single-name-deep-dive.ipynb)
was preserved byte-for-byte. Its current working-copy pipeline is authoritative
for this follow-on plan; older notebook descriptions are not assumed equivalent.

## 4. Portfolio story and state progression

The [story bible](../../notebooks/portfolio/STORY_BIBLE.md) describes an
analytical learning sequence, not independent API examples:

1. **Orientation:** establish provider and tool vocabulary.
2. **Single name:** answer the investment questions and stage a decision.
3. **Basket pivot:** discover hidden concentration with ETF/N-PORT lookthrough,
   HHI/effective number of holdings, risk and drawdown.
4. **Events/smart money:** connect calendars and ownership signals to a thesis.
5. **What-if/attribution/paper:** test changes that may worsen concentration,
   attribute outcomes and build a paper blotter.
6. **Backtest/validation:** challenge an attractive base result with sweeps,
   validation and overfitting checks.
7. **Offline replay:** reconstruct prior evidence and the end-to-end story.
8. **Analyst basket:** optional narrative extension, mandatory acceptance case.

Required handoffs include:

- NB02 staged entries -> NB05 proposed paper orders.
- NB03 lookthrough -> a revised NB02 single-name decision.
- NB04 event/ownership rationale -> NB05 scenario rationale.
- NB05 scenario -> recomputed NB03 concentration/risk.
- NB06 validation warnings -> a revised NB02 investigation.
- NB07 -> prior run artifacts with consistent provider/as-of lineage.

Feedback is a **new plan revision/run**, not an unbounded cycle in a single
stage DAG. A model must not skip validation because it narrates a plausible
trade thesis.

## 5. Complete 25-notebook scope matrix

All rows are **source scoped; runtime parity unverified**. "Existing primitives"
means names matched the richer audited API catalog, not all required stages.
N17-N20 and N23-N24 qualify every row in addition to the bridge owners shown.

### Portfolio

| Notebook | Story outcomes / existing primitives | Additional coverage and owners |
| --- | --- | --- |
| [01 - Providers](../../notebooks/portfolio/01-getting-started-and-providers.ipynb) | Provider orientation; quotes, history, profile, fundamentals, peers, estimates, ownership and N-PORT primitives | Provider registry/snapshot introspection, narrative artifacts and explicit cache policy: N01/N02/N04/N06/N10 |
| [02 - Single-name deep dive](../../notebooks/portfolio/02-single-name-deep-dive.ipynb) | Working copy calls `run_full_analysis`, `AnalysisConfig`, feature flags and regime variants; seven-phase decision/evidence | Bridge the actual `Analysis` pipeline, not the older `/stock/*` lookalike; typed state/rendering and FMP-only contract: N05/N06/N07/N10 |
| [03 - Basket x-ray](../../notebooks/portfolio/03-basket-xray-and-risk.ipynb) | History/profile/risk primitives; effective positions, N-PORT and sector rollup | Lookthrough aggregation, concentration/risk calculations, scenario handoffs and charts: N05/N06/N07/N10 |
| [04 - Events and smart money](../../notebooks/portfolio/04-events-and-smart-money.ipynb) | Timeline, smart-money rollup and company-news primitives | Joined narrative/evidence, state and provider availability: N05/N06/N07/N10 |
| [05 - What-if, attribution and paper](../../notebooks/portfolio/05-whatif-attribution-and-paper.ipynb) | Quote primitive; direct Brinson reference, in-memory accounts/positions and order submission | Scenario recalculation, attribution parity, paper approvals and artifacts: N05/N06/N07/N09 |
| [06 - Backtest and validation](../../notebooks/portfolio/06-backtest-and-validation.ipynb) | Run, sweep, validate, factor evaluation, bundle ingest and tearsheet primitives | Typed configuration, durable jobs, validation evidence and state: N05/N06/N07/N08 |
| [07 - Offline and end-to-end](../../notebooks/portfolio/07-offline-recording-and-end-to-end.ipynb) | Backtest primitive; N-PORT helper and prior-state replay | Replace subprocess/CLI discovery and pickle loading with approved catalog/run/artifact tools: N06/N07/N08/N10/N21 |
| [08 - Analyst basket](../../notebooks/portfolio/08-analyst-recommendations-basket.ipynb) | Backtest/profile primitives; direct effective-position/N-PORT/sector helpers | Recommendation basket construction, provenance, scenario persistence and artifacts: N05/N06/N07/N08/N10 |

### Portfolio YFinance

| Notebook | Source-verified differences / existing primitives | Additional coverage and owners |
| --- | --- | --- |
| [01 - Free-provider orientation](../../notebooks/portfolio_yfinance/01-getting-started-and-providers.ipynb) | Free-provider vocabulary, recorded quote fetcher, history/options/fundamental/insider/N-PORT primitives | Explicit fixture/recorded source and unavailable free fields: N01/N02/N04/N06/N10 |
| [02 - Free single-name analysis](../../notebooks/portfolio_yfinance/02-single-name-deep-dive.ipynb) | Direct filings/income/balance/cash/quote/insider/institutions primitives and recorded quote fetcher; not the same `Analysis` pipeline | Distinct free-data analytical story, artifacts and state: N05/N06/N07/N10 |
| [03 - Free basket x-ray](../../notebooks/portfolio_yfinance/03-basket-xray-and-risk.ipynb) | History primitive; effective positions and N-PORT helpers | Same outcome classes, different available data/aggregation scaffold: N05/N06/N07/N10 |
| [04 - Free events/smart money](../../notebooks/portfolio_yfinance/04-events-and-smart-money.ipynb) | Dividends, Form 13F and insider primitives; direct `yfinance` import | Explicit free-provider event/ownership composition, not a claim of equal paid data: N05/N06/N07/N10 |
| [05 - Free what-if/paper](../../notebooks/portfolio_yfinance/05-whatif-attribution-and-paper.ipynb) | Brinson and in-memory paper calls; free-track x-ray/smart-money state | Typed free-track handoffs and approved paper artifacts: N05/N06/N07/N09 |
| [06 - Free backtest/validation](../../notebooks/portfolio_yfinance/06-backtest-and-validation.ipynb) | Same six backtest primitives over alternate inputs | Provider-specific fixtures/configuration, durable jobs and artifact parity: N05/N06/N07/N08 |
| [07 - Free offline replay](../../notebooks/portfolio_yfinance/07-offline-recording-and-end-to-end.ipynb) | Backtest/quote primitives, prior free-track artifacts and subprocess discovery | Safe recorded data registry, typed replay and resumable runs: N06/N07/N08/N10/N21 |
| [08 - Free analyst basket](../../notebooks/portfolio_yfinance/08-analyst-recommendations-basket.ipynb) | Backtest primitive; effective-position/N-PORT helper calls | Distinct recommendation availability/selection evidence and basket outputs: N05/N06/N07/N08/N10 |

The paired files differ in more than a provider string: data availability,
snapshot paths, API calls, state names, presentation and the current single-name
implementation differ. Parity is **within each variant against its own reviewed
expectations**, not equality of FMP and YFinance live results.

### TechTrade

| Notebook | Existing primitives / direct source operations | Additional coverage and owners |
| --- | --- | --- |
| [01 - Foundations](../../notebooks/techtrade/01-foundations-techtrade-and-analysis.ipynb) | Scan/signals/plan/export plus history/profile; direct SEC helper and `validate_plan` | Discovery/readiness, analysis validation and provider policy. Exclude credential/settings bootstrap from agent execution: N04/N05/N06/N10 |
| [02 - Morning scan](../../notebooks/techtrade/02-morning-scan.ipynb) | About, segments, movers, scan and export primitives | Ranked tables/workbooks, live versus snapshot universe provenance, and cell 7 classification: N01/N05/N06/N07/N10 |
| [03 - Single-position deep dive](../../notebooks/techtrade/03-single-position-deep-dive.ipynb) | Signals, plan, orders, simulate and price-history primitives | Explain votes/risk/scenario outputs and preserve evidence: N05/N06/N07/N10 |
| [04 - Validation gate](../../notebooks/techtrade/04-validation-gate.ipynb) | Plan/validate primitives plus `validate_a_plan.main` and `validate_plan` | Typed validation result, fold metrics, threshold/verdict and job control: N05/N06/N08 |
| [05 - Per-sector tuning](../../notebooks/techtrade/05-tuning-per-sector.ipynb) | Tune primitive; tuned-default lookup, cache clear, persisted JSON | Versioned configuration registry, controlled tuning jobs, reload/rollback evidence: N05/N06/N07/N08 |
| [06 - Audit/replay](../../notebooks/techtrade/06-audit-and-replay.ipynb) | Price-history primitive; direct workbook read/inspection | Authorized audit artifact reading and deterministic replay rather than arbitrary filesystem access: N06/N07/N08 |
| [07 - T5 order batch/XLSX](../../notebooks/techtrade/07-t5-order-batch-and-xlsx-workbook.ipynb) | `OrderTicket`, `OrderBatch`, `PlanContext`, `VerdictGate`, `PaperOrderSink.write_batch`; no literal SDK call | Batch identity/verdict semantics, CSV/XLSX artifact creation and safe manual-placement boundary: N05/N06/N07/N09 |
| [08 - T5 paper engine](../../notebooks/techtrade/08-t5-paper-trading-engine-walkthrough.ipynb) | `SqlitePaperEngine`, submit/cancel/record-fill/read state and reopen; no literal SDK call | Explicit sandbox approvals, durable idempotent fills, precision and recovery: N06/N07/N09/N21 |
| [09 - T5 plan to fills](../../notebooks/techtrade/09-t5-end-to-end-plan-to-fills.ipynb) | Batch/verdict -> sink/workbook -> SQLite paper engine/fills; no literal SDK call | Full validated artifact/action chain with approval and replay lineage: N05/N06/N07/N09/N21 |

## 6. Important direct-engine boundaries

### 6.1 Current single-name pipeline versus existing widget calculations

[Analysis stock pipeline](../../Analysis/stock_analysis.py) defines:

- `phase1_company_profile`
- `phase2_fundamentals`
- `phase3_technicals`
- `phase4_valuation`
- `phase5_risk`
- `phase6_peer_relative`
- `phase7_decision`
- `run_full_analysis`

The current notebook calls the wrapper in cells 7, 32 and 40, including feature
flags, regime-aware variants and error/diagnostic demonstrations. The pipeline
declares `fmp_cached` as its sole provider.

The separately packaged
[Portfolio stock computations](../../openbb_platform/extensions/portfolio/openbb_portfolio/stock_analysis.py)
and [widget router](../../openbb_platform/extensions/portfolio/openbb_portfolio/portfolio_router.py)
expose related seven-phase calculations. They are not proven equivalent to the
current pipeline. Base MCP custom-API work can be reused only where actual
contracts and numerical results agree. N05 explicitly owns this distinction and
uses [existing pipeline tests](../../Analysis/tests/test_stock_analysis.py) as
regression prior art.

### 6.2 Lookthrough and presentation helpers

[N-PORT lookthrough helper](../../notebooks/portfolio/_nport_lookthrough.py)
provides `effective_positions`, `nport_holdings` and `sector_rollup`. The CSV
records exact call cells, including Portfolio basket cells 10/12 and analyst
basket cells 11/13/22. These helpers and notebook-local calculations are not
automatically exported by an OpenAPI-to-MCP converter.

[Notebook rendering helper](../../notebooks/portfolio/_nb_render.py) supplies
tables/panels/phase rendering. The agent needs equivalent structured evidence
and artifacts, not arbitrary execution of display helper code.

### 6.3 Separate paper implementations

- Portfolio notebooks use `brinson_reference`, in-memory accounts/positions and
  `submit_order` to illustrate attribution and paper workflows.
- TechTrade T5 notebooks use order batches/sinks and `SqlitePaperEngine`
  submission, fill recording, cancellation and reopen behavior.

One generic "paper tool exists" checkbox cannot prove both stories. N09 requires
separate engine contracts and financial conservation/idempotency assertions.
Mention of paper in a notebook is not evidence every cell mutates state; the
actual submit/fill/cancel call sites define the mutation boundary.

## 7. Operations to replace or exclude

| Notebook mechanism | Agent/MCP treatment |
| --- | --- |
| Provider/module introspection | Metadata-only reviewed capability catalog; no dynamic import tool |
| Direct SDK or analysis-engine calls | Existing typed MCP tool or reviewed server adapter around the same engine |
| Pickle state loading/saving | Typed JSON state and authorized artifact IDs; never deserialize notebook pickle through MCP |
| Local subprocess/CLI discovery in replay chapters | Explicit server catalog/provenance resources; no arbitrary command execution |
| TechTrade settings/credential bootstrap | Operator configuration outside the model loop; never a secret-setting tool |
| Notebook-local workbook paths | Authorized run-scoped artifact create/read operations |
| Paper submission/fill/cancel | Explicit sandbox, human approval, server authorization and idempotency |
| Tuning persistence/cache-clear | Controlled job/configuration operation, separate from read-only research |
| Browser/dashboard publication | Optional Workspace MCP session with its own permission and explicit availability |

No raw SQL text/`read_sql`/`to_sql` was found in the notebook source inspection.
That does not imply imported engines never use databases: the T5 paper engine
explicitly persists to SQLite. Static notebook inspection cannot certify all
transitive side effects.

## 8. Proposed Python agent and demonstrations

The product uses the existing agents extension, official MCP client SDK and
one explicitly configured local vLLM OpenAI-compatible model endpoint. It does
not inherit the existing agent configuration's cloud/Copilot/Ollama fallback
search. The served Nemotron model ID, vLLM parser/template and context limits
must be qualified rather than guessed. Workspace already occupies port 8000.

The CLI and Workspace adapter share one engine:

```text
inspect story -> verify capabilities -> build stage plan -> request approvals
  -> invoke MCP -> collect typed evidence/artifacts -> explain -> checkpoint
```

All financial computation and data access remain behind MCP. The model chooses,
plans and explains; it does not calculate portfolio metrics from invented or
unverified values. MCP errors remain visible.

Showcases cover the full Portfolio progression, free-provider counterpart,
analyst-basket extension, TechTrade research/validation/tuning, and the T5
plan-to-workbook-to-approved-paper-fills chain. The whole 25-file corpus remains
the acceptance denominator.

## 9. Acceptance and scheduling

The base program has 44 tasks. This follow-on has 24 tasks, with these gates:

1. MCP T44 accepted before any N-task implementation.
2. All source manifests and independently reviewed fixtures defined.
3. Notebook-specific bridges callable over actual MCP with authorization.
4. Python model/client/tool-loop/CLI deliverables complete.
5. All 25 deterministic fixture stories pass twice with zero provider network.
6. Numerical, chart, workbook, JSON and evidence outputs match independent
   expectations.
7. Local Nemotron qualifies at least 48/50 runs and every showcase journey.
8. All denial/injection/approval/idempotency/resume cases pass.
9. Shared Workspace integration and Portfolio drift CI pass.
10. Release evidence and rollback guidance are linked in Project #4.

The notebook-agent plan estimates **61-88 engineer-days** beyond the base MCP
plan's **81-119**. These are planning estimates, not elapsed-time promises or
authority to start the implementation.

## 10. What has and has not been verified

Verified during this planning work:

- Complete 25-file source inventory, 17 families and source fingerprints.
- All 40 literal SDK targets matched to the previously audited richer catalog.
- Direct-engine/artifact/state call sites and the one code-cell parse exception.
- Preserved working-copy notebook hash.
- Requirements/design/task traceability and explicit post-MCP sequencing.
- Actual GitHub creation/read-back results recorded separately in the issue map.

Not performed:

- Notebook execution, provider data calls, personal-data access, paper mutations.
- Agent implementation or local model/server setup.
- Numerical notebook parity, Nemotron tool-call reliability or runtime story
  completion.
- Commits, pushes, releases or capability-gap closure.
