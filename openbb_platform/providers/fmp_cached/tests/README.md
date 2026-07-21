# fmp_cached test suite

## Recorded HTTP fixtures (VCR cassettes)

The `fmp_cached` provider tests are meant to run **offline** in CI
without live FMP API keys. This is done via [pytest-recorder](https://pypi.org/project/pytest-recorder/)
(a `vcrpy` wrapper) — each `@pytest.mark.record_http` test records a
YAML cassette of its HTTP traffic on first run against live FMP, then
replays that cassette forever after.

Cassette layout:

```
tests/record/http/test_fmp_cached_fetchers/
├── test_fmp_cached_balance_sheet_fetcher_urllib3_v2.yaml
├── test_fmp_cached_equity_historical_fetcher_urllib3_v2.yaml
├── test_fmp_cached_equity_profile_fetcher_urllib3_v2.yaml
├── test_fmp_cached_equity_quote_fetcher_urllib3_v2.yaml
├── test_fmp_cached_etf_countries_fetcher_urllib3_v2.yaml
├── test_fmp_cached_etf_holdings_fetcher_urllib3_v2.yaml
├── test_fmp_cached_etf_info_fetcher_urllib3_v2.yaml
├── test_fmp_cached_etf_sectors_fetcher_urllib3_v2.yaml
├── test_fmp_cached_financial_ratios_fetcher_urllib3_v2.yaml
└── test_fmp_cached_income_statement_fetcher_urllib3_v2.yaml
```

Coverage: **10 of 75 registered fetchers** — the portfolio_intel
critical path. The other 65 are tracked in
[#955](https://github.com/prajoria/OpenBB/issues/955) for phased
draining. The coverage-gate test
`test_fetcher_dict_coverage.py::test_every_registered_endpoint_has_cassette_or_is_allowlisted`
regresses loudly if you add a new endpoint without either recording a
cassette or adding an allowlist entry that cites #955 (or a newer
follow-up issue).

## Running tests

**Default (offline replay)** — this is what CI runs:

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/fmp_cached/tests/ -m "not integration"
```

No FMP key needed. Cassettes replay the recorded HTTP traffic;
integration-marked tests that hit live DB are skipped.

## Recording cassettes for a new endpoint

Two steps: (1) add a `@pytest.mark.record_http` test, (2) run the
recording CLI.

### 1. Add the test function

In `tests/test_fmp_cached_fetchers.py`:

```python
@pytest.mark.record_http
def test_fmp_cached_<snake_case_endpoint>_fetcher(credentials=test_credentials):
    """Test FMP cached <endpoint> fetcher (#<your-issue>)."""
    from openbb_fmp_cached import fmp_cached_provider

    cached_fetcher_class = fmp_cached_provider.fetcher_dict["<CamelEndpoint>"]
    params = {"symbol": "AAPL"}  # or whatever the endpoint requires

    fetcher = cached_fetcher_class()
    result = fetcher.test(params, credentials)
    assert result is None
```

### 2. Record the cassette

```bash
# Ensure fmp_cached_api_key is in ~/.openbb_platform/user_settings.json
.venv_win\Scripts\python.exe scripts\pi_fmp_record.py --endpoint <snake_case_endpoint>
```

The wrapper:
- **Fails loud** if no FMP key is configured (otherwise cassettes get
  written from 401 responses and the "green" lies).
- **Clears matching L2 cache rows** so cache-hits don't short-circuit
  the HTTP call — a real bug discovered while recording
  `equity_profile` (populated cache rows meant pytest-recorder saw
  zero traffic and wrote no cassette, silently). If your new endpoint
  uses dedicated database persistence (`_get_cached_*` pattern in the
  model), add a cache-clear entry to
  `scripts/pi_fmp_record.py::_CACHE_CLEAR_ROWS`.
- **--overwrite** to force re-record if the cassette exists (default
  preserves the checked-in cassette).

Verify replay works:

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/providers/fmp_cached/tests/test_fmp_cached_fetchers.py::test_fmp_cached_<name>_fetcher
```

Should pass in <2 seconds without hitting live FMP.

### 3. Remove the allowlist entry (if any)

If the endpoint was in `test_fetcher_dict_coverage.py::_KNOWN_UNCOVERED`,
delete its entry. The `test_kicked_out_of_allowlist_when_cassette_lands`
test catches you if you forget.

## Refreshing a stale cassette

When FMP changes their response shape (adds/removes a field, changes
type), re-record:

```bash
.venv_win\Scripts\python.exe scripts\pi_fmp_record.py --endpoint <name> --overwrite
```

Then review the diff before committing — a legit API change should be
small; a huge diff usually means the API changed in a way that breaks
callers, not just the cassette.

## API-key scrubbing

`test_fmp_cached_fetchers.py::response_filter` scrubs
`apikey=<real>` → `apikey=MOCK_API_KEY` in the `Location` response
header, and pytest-recorder scrubs the query string on the request URI
by default (`apikey=MOCK_API_KEY` appears in cassettes' `uri:` field).

**Never disable this scrubbing.** Every checked-in cassette must be
audit-safe. Sanity check:

```bash
grep -rE 'apikey=[A-Za-z0-9]{20,}' tests/record/http/
# should return zero matches
```

## Fixtures directory redirect

The historical spec (#508) mentioned `tests/fixtures/fmp/` as the
fixture path. The repo convention is `tests/record/http/` per
pytest-recorder. A README stub at `tests/fixtures/fmp/README.md`
redirects anyone looking at the historical path.
