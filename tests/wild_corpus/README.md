# Wild Corpus — fingerprint index

## What this is

The **L4 user-intent baseline** described in
[PRD §3.4](../../temp/openbb-pine-extension-prd.md) for the
`openbb-extension-pine` project: a fingerprint index of the top ~1000
TradingView community Pine scripts (ranked by boost / popularity), used by
the `wild-corpus-coverage` CI job (L0.5) to compute *"fraction of scripts
that would run unedited against the current implemented set."*

The fingerprint per script captures **what** the script uses — its declared
`//@version=`, the set of built-in identifiers it references, and a handful
of grammar-feature flags — so the coverage gate can intersect that set
against our `implemented` / `stub` / `unsupported` matrix without ever
needing to look at the script source.

## What this is NOT

This index **does not contain Pine source code**.

Per [PRD §2.1](../../temp/openbb-pine-extension-prd.md) ("TradingView
API/data feeds — their terms of service. ❌ No scraping of TV chart data
at runtime."), TradingView's API and feeds are off-limits, and we do not
redistribute community script source. The crawler only stores metadata
derived from publicly-visible script pages — enough to answer *"does this
script use only builtins / features we've implemented?"* and nothing more.

When TradingView's public page exposes no Pine syntax (the common case,
since full source is gated behind login), the script is recorded with
`source_visible: false` and contributes to the *unknown* cohort in the
coverage metric, **not** to the *would-not-run* cohort. L0.5 reports both
cohorts separately so we never silently inflate or deflate the score.

## Schema

`index.json` is a JSON array, one object per script, pretty-printed with
`indent=2` and `sort_keys=True` so PR diffs remain reviewable. Each entry
has the following fields (all required; values may be `null`):

| Field            | Type                      | Meaning |
|------------------|---------------------------|---------|
| `url`            | string                    | TradingView permalink to the script (`https://www.tradingview.com/script/{id}-{slug}/`) |
| `title`          | string                    | Human-readable script name from the listing card |
| `author`         | string                    | Author handle (the `{handle}` in `/u/{handle}/`); public on the script page |
| `likes`          | integer                   | Boost count at crawl time; `0` if the card didn't expose one |
| `script_type`    | `"indicator"`/`"strategy"`/`null` | From the card type badge |
| `pine_version`   | `5` / `6` / `null`        | Parsed from a visible `//@version=` directive; `null` when not visible |
| `builtins_used`  | list of strings or `null` | Sorted unique `namespace.member` identifiers found in the visible body (e.g. `"ta.sma"`, `"input.int"`). `null` when `source_visible` is `false` |
| `features_used`  | object or `null`          | Grammar-feature flags (see below). `null` when `source_visible` is `false` |
| `source_visible` | boolean                   | `true` if the page yielded code-like markers we could regex against; `false` if only description prose was visible |
| `crawled_at`     | string (UTC ISO 8601)     | When this entry was fingerprinted |

`features_used` (when present) is an object with these keys:

| Key                        | Type    | Meaning |
|----------------------------|---------|---------|
| `uses_request_security`    | boolean | `request.security(...)` appears (the most-used "advanced" Pine builtin) |
| `uses_library_directive`   | boolean | `library(...)` appears |
| `uses_drawings`            | boolean | Any of `line.new` / `label.new` / `box.new` / `table.new` appears |
| `uses_strategy_directive`  | boolean | `strategy(...)` appears |
| `uses_indicator_directive` | boolean | `indicator(...)` appears |
| `uses_input_array`         | integer | Count of `input.*(...)` calls (rough proxy for input cardinality) |

These regex-based flags are deliberately conservative: they're a text scan,
not an AST query, so a positive match means "this identifier appears in the
visible body" rather than "this feature is invoked at top level." For the
coverage metric, that's sufficient — we want to *over*-count usage when in
doubt so the gate is harder, not easier, to pass.

## Refresh cadence

Re-crawl **every quarter**, and additionally **on any major Pine version
release**. The crawler is idempotent: `tools/pine/refresh_wild_corpus.py`
always passes `--resume`, so unchanged URLs are not refetched (the HTTP
cache in `tools/pine/_cache/` further short-circuits repeated work
inside a single run).

```sh
python tools/pine/refresh_wild_corpus.py            # default 1000 target
python tools/pine/refresh_wild_corpus.py --target 1500   # expand corpus
```

If a script's fingerprint changes between refreshes (author edited it, new
TV-version directive, etc.), the new fingerprint replaces the old one — use
`git diff` on `index.json` after each refresh to spot drift.

## Note on completeness

The crawler targets 1000 entries. TradingView's public script page omits
the full Pine source by default (it's behind a JS auth flow that we
deliberately do not bypass — see *What this is NOT* above), so for most
entries `source_visible` will be `false`. Those scripts are still useful
in the metric — they contribute to the *unknown* cohort, which L0.5
reports separately from the *would-not-run* cohort.

If TradingView's anti-scraping defenses tighten (captchas, IP blocks),
the crawler will gracefully degrade: it caches each fetch, retries
on 429 / 5xx with exponential backoff, and respects a configurable
inter-request floor (`--rate-limit-sec`, default 1.5 s). The corpus stays
meaningful at any N ≥ 100 as long as the metric trend is monotonic with
implementation progress.

## Privacy posture

Author handles **are** recorded because they are public on the script page
and on the listing card itself — every TradingView script credits its
author by handle in its URL slug, on the page header, and in the
`og:description` meta. Recording them is a faithful copy of public,
already-published metadata.

If an author requests removal of their entries from this index:

1. Add their script URL(s), one per line, to `tests/wild_corpus/.removal_requests`.
2. Re-run the crawler (`tools/pine/refresh_wild_corpus.py`) — the index
   builder will skip URLs found in `.removal_requests`. *(Note: this skip
   behavior is a planned follow-up; right now the file is documented as
   the intake mechanism and any present entries can be scrubbed by hand
   from `index.json` and the URL added to `.removal_requests` to prevent
   re-introduction by future crawls.)*
3. Open a PR with the diff for the parent epic's review.

## Smoke test

`test_index_schema.py` is a pytest smoke test that loads `index.json` and
asserts the schema invariants above (JSON array, required keys present,
`pine_version` is `int` or `null`, `builtins_used` is list-of-str or
`null`, `crawled_at` parses as ISO timestamp). Run with:

```sh
python -m pytest tests/wild_corpus/test_index_schema.py -v
```

The smoke test is intentionally cheap — it's a tripwire for schema drift,
not a full coverage simulation. The full coverage gate is L0.5 work.
