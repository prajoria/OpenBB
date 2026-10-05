# MCP capability decisions and accountability

The machine-readable source of truth is
`openbb_mcp_server/assets/capability_policy.json`. Capability status is derived
from source registration, route/provider inventory, reviewed policy and protocol
evidence—not from commit subjects.

| Work family | Owner issues | Current state | Review triggers |
| --- | --- | --- | --- |
| FMP routing waves | #2162, #2171 | Implemented routing; persistence backlog is explicit | Provider/model/command or persistence changes |
| Portfolio custom API | #2172, #2173 | Implemented reviewed adapter | Route, privacy or profile changes |
| Intelligence widgets and snapshots | #2174 | Implemented reviewed adapter | Widget, account-scope or snapshot changes |
| Jobs and cache operations | #2178, #2180 | Implemented guarded operator surface | Job kind, cache mutation or authorization changes |
| Execution controls | #2175, #2239 | Approved exclusion | Execution mode, approval or broker gateway changes |
| Agents specialist MCP | #2183, #2184 | Implemented two-tool stdio surface | Registration, documentation or protocol changes |
| Daytrade specialist MCP | #386, #2182 | Implemented six-tool stdio surface | Handler, declaration or transport changes |

Every family records rationale, repository-relative source evidence and review
triggers in the policy asset. Every restricted/unimplemented policy rule maps to
one of these families.

## Drift handling

Traceability is built dynamically from discovered operations, provider/model
rows and specialist declarations. A new route or specialist identity that is
not in the reviewed policy is emitted under `unowned`; it is never dropped
because a historical denominator remained fixed.

Provider rows are classified from current command/provider registration state.
An unrouted model maps to the FMP routing family and remains `unimplemented` in
gross coverage. Implemented product code wrapped by a missing/broken adapter is
`adapter_gap`; an actually absent callable product/handler is `absent_product`.

## Exclusion requirements

An approved exclusion requires:

1. owner issue with title/context;
2. reason and privilege class;
3. repository-relative source evidence;
4. explicit review triggers;
5. policy rule or specialist/provider decision ID.

Execution actions and unhardened caller-URL fetches are approved exclusions.
Their presence in source or Git history does not make them MCP-admitted.

## FMP Cached persistence contract

The registered denominator is 181 models:

- 123 use dedicated implementations and may persist according to their own
  table and freshness contracts.
- 58 are credential-translation-only fallback implementations and are
  explicitly non-persistent in `persistence_descriptors.json`.
- A model-specific TTL is separate from persistence classification. For
  example, `AftermarketQuote` has dedicated storage but considers rows stale
  after 60 seconds.

Fallback conversion priorities do not count as implemented coverage:

1. **High consumer demand:** news, movers, screening, government/insider
   activity, targets, revenue segmentation, yields, and common historical
   reference series.
2. **Entitlement blocked:** endpoints recorded in `plan_limited.py`; conversion
   waits for a lawful recording and runtime entitlement.
3. **Backlog:** remaining fallback registrations without demonstrated consumer
   demand.

Each conversion requires its own approved issue, dedicated storage contract,
atomic-write evidence, TTL/freshness semantics, and entitlement tests.
