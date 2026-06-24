"""Runnable end-to-end techtrade examples (issue #86).

Each script defines a ``main(...)`` function that accepts injectable offline
fakes (used by ``tests/unit/test_examples_smoke.py`` to prove the example
stays in sync with the README) AND a ``if __name__ == "__main__": main()``
guard that runs the live ``fmp_cached``-backed path when invoked directly.
"""
