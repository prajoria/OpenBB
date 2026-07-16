"""Manual smoke script for the flattened cache — NOT a pytest test.

This file was originally a hand-run script (`python test_flattened_cache.py`)
that print-verifies the cache's store/retrieve/stats flow. pytest happens
to collect it because of the `test_` filename prefix, but the function:

* is `async def` (not properly declared as `@pytest.mark.asyncio`)
* has zero `assert` statements — uses `print(...)` for pass/fail visibility
* depends on a real `DatabaseManager` (no MySQL mock)
* uses an out-of-date API (`store_cached_data_async` was renamed to
  `store_data_async`, `get_cached_data_async` to `get_stored_data_async`)

Rather than gold-plate this into a "real" test just to satisfy pytest,
we skip module collection here. If someone wants live cache round-trip
coverage, write it against `DatabaseManager.store_data_async` /
`get_stored_data_async` with proper fixtures and MySQL mocking.

Kept as a manual runner via `if __name__ == "__main__":` at the bottom
of the historical version — see git history for the previous contents.
"""

import pytest

pytest.skip(
    "Manual smoke script, not a pytest test. See module docstring.",
    allow_module_level=True,
)
