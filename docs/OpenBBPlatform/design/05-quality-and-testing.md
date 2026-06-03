# 05 — Quality & Testing

[← design/](./README.md) · Prev: [04 Gotchas](./04-gotchas.md) · Up: [design/](./README.md)

> How to pass pre-commit, write provider tests with VCR cassettes, and run the test tiers.
> Last verified: 2026-06-02.

> **Upstream how-to (canonical):**
> `third_party/openbb-docs/content/odp/python/developer/how-to/tests.mdx` documents
> `Fetcher.test`, `pytest_recorder` cassettes, integration-test generators, and `tuna`
> import profiling. This page adds the fork's pre-commit gates and project-venv commands.

---

## Pre-commit gates

Install once, then every commit runs them:

```bash
pre-commit install
pre-commit run --all-files          # run everything manually
pre-commit run ruff                 # a single hook
```

| Hook | Enforces |
|---|---|
| **Black** | Formatting (line length 122). |
| **Ruff** | Lint rule sets `E/W/F/Q/S/UP/I/PLC/PLE/PLR/PLW/SIM/T20`; `PLC0415` (import-not-top-level) **globally ignored** to allow lazy provider imports. |
| **MyPy** | Static types. |
| **PyLint** | Extra lint. |
| **PyDocStyle** | Docstrings, **numpy convention**. |
| **CodeSpell** | Spelling. |
| **Detect-secrets** | No committed secrets. |
| **package guard** | Hard-fails if `core/openbb/package/*` (except `__init__.py`) is staged. |

→ Style rules summarized in [Conventions § style](./02-conventions.md#style-rules-enforced-by-gates)

**Common failures & fixes**

- `T20` print found → use a logger/warning.
- pydocstyle missing docstring → document the command/field (also feeds OpenAPI).
- package-guard fail → you staged generated files; `git restore --staged core/openbb/package/*`.

---

## Test tiers

| Tier | Marker | Needs keys? | Command |
|---|---|---|---|
| Unit | (default, `not integration`) | No | `pytest openbb_platform -m "not integration"` |
| Integration | `integration` | Yes | `pytest openbb_platform -m "integration"` |
| Provider fetchers | per-package | Recorded (VCR) | `pytest openbb_platform/providers/<name>/tests/` |

Use the project venv interpreter (`.venv_win\Scripts\python.exe -m pytest ...` on this fork).

---

## Provider fetcher tests (VCR cassettes)

Each provider ships a `test_<name>_fetchers.py` plus recorded cassettes under `tests/record/`.
The `Fetcher.test()` harness exercises the full TET pipeline and asserts the result validates.

**Pattern:**

```python
@pytest.fixture(scope="module")
def vcr_config():
    return {"filter_headers": [("User-Agent", None)],
            "filter_query_parameters": [("apikey", "MOCK")]}

@pytest.mark.record_http
def test_some_equity_historical_fetcher(credentials=test_credentials):
    params = {"symbol": "AAPL", "start_date": date(2023, 1, 1), "end_date": date(2023, 1, 5)}
    fetcher = SomeEquityHistoricalFetcher()
    result = fetcher.test(params, credentials)
    assert result is None   # test() asserts internally; returns None on success
```

- **Always filter the API key** out of cassettes (`filter_query_parameters` / `filter_headers`).
  Detect-secrets and review will reject leaked keys.
- Record once against the live API, then commit the sanitized `*.yaml`; CI replays offline.
- `Fetcher.test()` runs `transform_query → extract → transform_data` and validates the typed
  model — it's the fastest way to prove a new provider works end-to-end.

→ [Provider Framework § TET](../architecture/core/provider-framework.md#2-the-fetcher-tet-lifecycle) · [Recipes A](./03-recipes.md#recipe-a--add-a-provider-integration-for-an-existing-standard-model)

---

## Extension integration tests

Extensions carry `integration/` tests that hit both surfaces (Python + API) behind the
`integration` marker. They need real credentials and network, so they're excluded by default.

---

## Rebuild before you test structure

Structural changes (new provider/command/field) require an SDK rebuild **before** tests see
them:

```bash
python -c "import openbb; openbb.build()"
```

→ [Gotchas G2 stale build](./04-gotchas.md#g2--stale-generated-sdk-after-a-change)

---

## Analysis module tests (fork-local)

```bash
# Unit (no API), ~1s
.venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "not integration" -v
# Integration via fmp_cached (~19 min), reads creds from user_settings.json + .env
.venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "integration" -v
```

→ [ADR-10 fmp_cached](./01-decisions.md#adr-10-fork-local--fmp_cached-is-the-canonical-provider)

---

← Back to [design/ hub](./README.md) · See also [architecture/](../architecture/README.md) · [GLOSSARY](../GLOSSARY.md)
