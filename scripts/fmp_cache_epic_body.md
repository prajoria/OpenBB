## Purpose

Program-level tracking issue for FMP (Financial Modeling Prep) response
caching in OpenBB. All FMP-cache-related work (storage backend,
invalidation/TTL, fetch/API client, serialization, config, docs, tests,
tooling) attaches here as a sub-issue.

## Goals

- Provide a first-class caching layer for FMP provider responses so repeated
  requests are served from cache instead of re-hitting the FMP API.
- Reduce FMP API call volume (rate-limit / cost pressure) while keeping data
  freshness controllable via TTL / invalidation policy.
- Offer a consistent, testable cache surface (storage, serialization, config)
  that other OpenBB providers can reuse.

## Non-goals

- A general-purpose caching framework for every provider (we target FMP first;
  generalization is a later, separate effort).
- Bypassing FMP's terms of service on data retention — caching honors any
  contractual freshness/retention constraints.

## How this is organized

- This issue is the root. Every sub-topic (storage, invalidation, fetch, etc.)
  gets its own child issue linked here via GitHub's native sub-issue feature.
- Every child is added to the "FMP Cache" project so the Area / Priority /
  Type / dates fields are populated.
- PRs land against `develop` unless a program-branch is agreed on separately.

## Docs

- Design spec: TBD
- Contact: @prajoria
