# Design — FMP fixture-record harness for fmp_cached (#508)

- **Date:** 2026-07-21
- **Issue:** [#508 `[portfolio] [M0] Recorded-fixture harness for FMP (tests/fixtures/fmp/)`](https://github.com/prajoria/OpenBB/issues/508)
- **Parent epic:** #491 Portfolio Intelligence Engine
- **Branch:** `feat/pi-data/fmp-fixture-harness-gh-508`
- **Author:** Claude (openbb-dev-cycle v3, Phase 1)
- **Status:** Draft

---

## 1. Purpose

Give the `fmp_cached` provider a **reliable, discoverable, one-command fixture-record + replay flow** so that:

- Every model has (or can trivially acquire) a recorded HTTP fixture — E2/E3 unit tests run offline in CI without live FMP keys.
- A contributor adding a new fmp_cached model can bootstrap its fixture in one command (`.venv_win\Scripts\python.exe scripts\pi_fmp_record.py <EndpointName>`).
- Regenerating fixtures on API drift is a batch operation, not 4 hand-crafted VCR runs.

## 2. Scope-correction from the issue title

The issue title says "Create `tests/fixtures/fmp/` dir + fixture-record CLI. Documented in README." Live inspection (2026-07-21) shows:

| Layer | State |
|---|---|
| `pytest-recorder` (VCR) harness | ✅ Present — 4 `@pytest.mark.record_http` tests in `tests/test_fmp_cached_fetchers.py` |
| Recorded cassettes location | ✅ `tests/record/http/test_fmp_cached_fetchers/*.yaml` (per pytest-recorder's default layout) |
| Coverage | ⚠ **4 of ~70 endpoints** — `balance_sheet`, `equity_historical`, `equity_quote`, `income_statement` |
| README documenting the flow | ❌ None |
| Batch-record CLI | ❌ None — recording is per-test, requires manual `pytest --record-mode=once` |
| `tests/fixtures/fmp/` directory | ❌ Absent — fixtures live under `tests/record/http/` not `tests/fixtures/fmp/` |

So the real deliverable = **make the existing harness usable** + **extend coverage in a repeatable way**, not "invent a new harness."

## 3. In / out of scope

**In scope (this PR):**

- **3.1 — README + docstring**: `openbb_platform/providers/fmp_cached/tests/README.md` (new) explaining the pytest-recorder flow: `pytest -m record_http --record-mode=once` to add a cassette, `pytest -m record_http --record-mode=none` (default) to replay. Cover: which endpoints have cassettes, how to add one, how to refresh a stale one, how the API-key-scrubbing filter works.
- **3.2 — Batch-record CLI**: `scripts/pi_fmp_record.py` — one-command wrapper that either (a) records ALL missing fixtures or (b) records a named subset. Uses the same `pytest -m record_http` invocation under the hood so behavior is single-sourced. Refuses to run without `fmp_cached_api_key` set (fails loud, not silently to empty cassette).
- **3.3 — Extend coverage to the portfolio_intel critical path**: add `@pytest.mark.record_http` tests + cassettes for the endpoints portfolio_intel already consumes:
  - `EtfHoldings` (already exists via SSGA-issuer path but no FMP-tier cassette)
  - `EtfInfo`, `EtfSectors`, `EtfCountries` (used by `xray.rollup_by`)
  - `EquityProfile` (used by attribute_provider construction)
  - `FinancialRatios` (used by Analysis stock_analysis)
  - Take total from 4 → ~10 cassettes.
- **3.4 — CI gate**: expand the existing `test_fmp_cached_fetchers.py` matrix so that when a contributor adds a new endpoint to `fmp_cached_provider.fetcher_dict` but forgets a cassette, CI turns red (a coverage assertion — enumerates the fetcher_dict and asserts every entry either has a cassette OR is on an explicit exclusion list). This is the "loud missing" guardrail.
- **3.5 — Legacy `tests/fixtures/fmp/` compat**: create an empty `tests/fixtures/fmp/` directory with a README stub that redirects to `tests/record/http/test_fmp_cached_fetchers/` — the issue title spec-asserted this path; contributors who look there deserve a signpost, not a 404.

**Out of scope (follow-ups):**

- Extending coverage to all ~70 fmp_cached endpoints. That's per-endpoint work with real product prioritization — file 6-8 follow-up issues grouped by portfolio_intel consumer (analyst-track, macro-track, insider-track, etc.).
- Recording cassettes for the raw `openbb-fmp` provider (upstream — not our fork's job).
- Automated cassette staleness detection (SSGA URL changed, FMP added a new field, etc.). Manual refresh cadence is fine for M0.
- CI matrix expansion to run the record_http tests on GH Actions (currently only replay; recording is developer-machine only per the pytest-recorder convention).

## 4. Design decisions (with rationale)

### 4.1 Why extend pytest-recorder rather than roll our own

`pytest-recorder` (which the repo already uses via `openbb-devtools`) is the OpenBB convention across every provider that has cassettes. Building a parallel harness (raw `vcrpy` fixtures, JSON snapshots, etc.) fragments the mental model and forces every future OpenBB dev to learn two systems. The one-line marker `@pytest.mark.record_http` + the `pytest -m record_http --record-mode=once` invocation is the industry-standard OpenBB pattern.

### 4.2 Why a batch CLI at all (given `pytest --record-mode=once` exists)

Two reasons:

1. **Discoverability** — `pi_fmp_record.py --help` in one place beats "read the pytest-recorder README and figure out the marker + record-mode combination."
2. **Guardrails** — enforce that `fmp_cached_api_key` is set BEFORE the pytest run starts. Otherwise pytest merrily records an empty cassette from a 401 response and the "tests passed" green lies about what's in the fixture.

### 4.3 Why the CI coverage-gate

Without it, the "1 endpoint added but no cassette" state is invisible until the next agent tries to run tests offline and their local pytest run hits live FMP. Fail-fast in CI = fewer surprises.

### 4.4 Fixture path decision

**Keep cassettes at `tests/record/http/test_fmp_cached_fetchers/*.yaml`** (pytest-recorder default). The issue title said `tests/fixtures/fmp/` but the repo convention is different, and moving would break the 4 existing cassettes. Ship a `tests/fixtures/fmp/README.md` redirect stub for anyone who looks at the historical path.

### 4.5 API-key scrubbing

The existing `response_filter` in `test_fmp_cached_fetchers.py` already scrubs `apikey=<real>` → `apikey=MOCK_API_KEY` in the `Location` header. Also need to scrub:

- Query string on the request URL (currently not scrubbed — cassettes leak the api key)
- `Authorization` request header if FMP starts using it
- `apikey` in JSON response bodies (rare but possible on some FMP endpoints)

Add a broadened scrubber to the shared conftest fixture so every recorded cassette gets it uniformly.

## 5. File layout

```
openbb_platform/providers/fmp_cached/
├── openbb_fmp_cached/                          # (unchanged)
└── tests/
    ├── test_fmp_cached_fetchers.py             # +6 @record_http tests
    ├── test_fetcher_dict_coverage.py           # NEW — CI coverage-gate
    ├── conftest.py                             # +broadened api-key scrubber
    ├── README.md                               # NEW — record/replay flow docs
    └── record/http/test_fmp_cached_fetchers/
        ├── test_fmp_cached_balance_sheet_fetcher_urllib3_v2.yaml  # existing
        ├── test_fmp_cached_equity_historical_fetcher_urllib3_v2.yaml  # existing
        ├── test_fmp_cached_equity_quote_fetcher_urllib3_v2.yaml  # existing
        ├── test_fmp_cached_income_statement_fetcher_urllib3_v2.yaml  # existing
        ├── test_fmp_cached_etf_holdings_fetcher_urllib3_v2.yaml   # NEW
        ├── test_fmp_cached_etf_info_fetcher_urllib3_v2.yaml       # NEW
        ├── test_fmp_cached_etf_sectors_fetcher_urllib3_v2.yaml    # NEW
        ├── test_fmp_cached_etf_countries_fetcher_urllib3_v2.yaml  # NEW
        ├── test_fmp_cached_equity_profile_fetcher_urllib3_v2.yaml # NEW
        └── test_fmp_cached_financial_ratios_fetcher_urllib3_v2.yaml # NEW

scripts/
└── pi_fmp_record.py                            # NEW — batch record CLI

openbb_platform/providers/fmp_cached/tests/fixtures/fmp/
└── README.md                                   # NEW — redirect stub
```

## 6. Testing plan

1. **`test_fetcher_dict_coverage` (unit test — the guardrail)** — enumerates `fmp_cached_provider.fetcher_dict.keys()`, checks each has either a cassette OR is on `_KNOWN_UNCOVERED` list (an explicit tech-debt allowlist). Fails when a new endpoint lands without a cassette or an allowlist entry.
2. **6 new `@record_http` fetcher tests** — one per endpoint added in §3.3. Each records once against live FMP, then replays offline in CI.
3. **`test_pi_fmp_record_cli` (unit test)** — mocks the pytest subprocess call, asserts (a) refuses without `fmp_cached_api_key`, (b) invokes the right marker + mode, (c) `--endpoint` filters correctly.
4. **API-key scrubbing regression** — walk every checked-in cassette and assert no real key patterns leak (regex against known key shapes).

## 7. Acceptance criteria

- [ ] README explains record + replay in <5 min for a new contributor
- [ ] `pi_fmp_record.py` refuses on missing key + succeeds on 1 endpoint end-to-end
- [ ] `test_fetcher_dict_coverage` passes with the 6 new endpoints registered
- [ ] All 10 cassettes replay green offline (no live FMP call)
- [ ] Coverage-gate test correctly FAILS when I temporarily delete a cassette (R7.11 reverse-verify)
- [ ] No API key leakage in any cassette (regex sweep test)

## 8. Provenance

- Plan step: 1 of 1 (single-file harness + docs + CLI + coverage gate — no decomposition warranted)
- Parent epic: #491
- Sub-issue link: #508 already exists; add as sub-issue of #491 via `gh api sub_issues` in Phase 2 if not already
- Design spec: this file
