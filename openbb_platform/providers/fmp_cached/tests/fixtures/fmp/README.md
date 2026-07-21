# fmp_cached fixtures — moved

The FMP recorded fixtures are **not here**. They live under:

```
tests/record/http/test_fmp_cached_fetchers/*.yaml
```

...following the pytest-recorder convention used throughout OpenBB.

See `openbb_platform/providers/fmp_cached/tests/README.md` for the
recording flow, coverage-gate, and refresh cadence.

The original #508 spec named `tests/fixtures/fmp/` as the directory —
this stub exists so anyone looking at that path lands somewhere useful
instead of a 404.
