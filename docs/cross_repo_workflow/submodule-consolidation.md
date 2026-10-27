# Submodule consolidation

## Goal

`OpenBB/third_party` is the canonical, revision-pinned view of adjacent
repositories used to understand, develop, or validate the Portfolio fork. It
does not turn those repositories into one release unit. Each submodule retains
its own history, licensing, dependency manager, and upstream workflow.

## Complete submodule inventory

| Path | Pinned revision | Role | Classification |
| --- | --- | --- | --- |
| `copilot-api` | `d852550084153aba87901a5e364d0418db4ac5d8` | Optional OpenAI-compatible local proxy | Runtime-adjacent product |
| `openbb_platform/extensions/techtrade/external/pandas-ta-classic` | `cfda99036ba64a4983e5871d42d1865743b7c6a9` | Technical-analysis implementation | Direct source dependency |
| `third_party/adk-python` | `62bcdd343c5ea12583f98fa479c265f3b108a50e` | Forked Google ADK | Direct source dependency |
| `third_party/agents-for-openbb` | `aa1073d2b098ae6cf597dabf0635822aa808dd81` | Workspace agent examples | Reference and contract tests |
| `third_party/awesome-quant` | `69616148bd64e27e698bf3bba00393a5f9d7c554` | Quantitative ecosystem reference | Research/reference |
| `third_party/backends-for-openbb` | `a6293707576e16edda8305adda95b07b6a4b968b` | Workspace backend examples | Reference and contract tests |
| `third_party/openbb-docs` | `78c73a902ac95e8452c6dc6c051fbce585780fd4` | Upstream OpenBB documentation | Documentation source |
| `third_party/openbb-rag-financial-research-agent` | `a69cbce56cc80c26a6d3c8a84067636429a2348a` | Specialized Workspace RAG agent | Integration/reference |
| `third_party/openbb-workspace-bench` | `b11572b59b7a5722e4c4ec60676d7613c1b05ac5` | Workspace agent benchmark | Validation tooling |
| `third_party/openfigi-api` | `f847dce9492a6bac685f9fdf1d9450e57280a9c4` | OpenFIGI API implementation/reference | Data integration/reference |
| `third_party/workspace` | `be00e95019a55d57af146919ee46b7e1a4859226` | Workspace product source | Runtime-adjacent product/source |

The direct source dependencies are intentionally outside the flat
`third_party` layout when their owning package expects a nested source path.
Moving `pandas-ta-classic` would break TechTrade's source layout. Moving
`copilot-api` would break existing launch scripts and documentation. The
single-place goal is therefore a single **superproject manifest**, not a rule
that every gitlink must be physically below one directory.

## Consolidation result for the requested roots

| Standalone repository | Canonical submodule | Audit result |
| --- | --- | --- |
| `agents-for-openbb` | `third_party/agents-for-openbb` | Existing; SHA matched |
| `backends-for-openbb` | `third_party/backends-for-openbb` | Existing; SHA matched |
| `openbb-rag-financial-research-agent` | `third_party/openbb-rag-financial-research-agent` | Added; SHA matched |
| `openbb-workspace-bench` | `third_party/openbb-workspace-bench` | Existing; SHA matched |
| `workspace` | `third_party/workspace` | Existing; SHA matched |

No standalone repository from `OpenBBAll` remains unrepresented.

## Why the RAG agent belongs in `third_party`

The RAG agent qualifies because it:

- is an independent Git repository with its own remote and release lifecycle;
- implements the same Workspace agent protocol used by the example agents and
  Portfolio copilot;
- provides a concrete compatibility target for older `openbb-ai` 1.x clients;
- is useful for end-to-end agent, widget-data, citation, and model-provider
  testing;
- was already co-located in the aggregation workspace, indicating active
  cross-repository use.

It remains an integration/reference submodule, not a dependency installed by
the default OpenBB environment.

## What should not be added automatically

### Worktrees and generated directories

Never add `.worktrees/`, `worktrees/`, virtual environments, caches,
notebook state, build directories, or `node_modules` as submodules.

### Package-index dependencies

Do not create submodules for every dependency in `pyproject.toml` or
`package.json`. Packages such as `openbb-ai`, FastAPI, FastMCP, React, and
SQLAlchemy should remain versioned package-manager dependencies unless the fork
must patch unreleased source.

### Hosted services

Hosted Workspace, model endpoints, databases, Redis, cloud storage, and vendor
APIs are runtime services, not source submodules.

### Ambiguous `workspace-mcp`

Workspace Bench's Harbor path expects a standalone `workspace-mcp` repository,
but that repository is not one of the audited repositories under the requested
roots and its canonical remote is not declared in the benchmark manifest.
Do not guess a remote and add it. Resolve ownership and remote URL first.

## Initialization profiles

Avoid initializing every submodule by default.

### Platform-only development

```powershell
git submodule update --init --recursive -- `
  third_party/adk-python `
  openbb_platform/extensions/techtrade/external/pandas-ta-classic
```

Initialize only the direct dependency needed by the selected extension.

### Workspace integration development

```powershell
git submodule update --init --recursive -- `
  third_party/workspace `
  third_party/backends-for-openbb `
  third_party/agents-for-openbb `
  third_party/openbb-rag-financial-research-agent
```

### Benchmark work

```powershell
git submodule update --init --recursive -- `
  third_party/openbb-workspace-bench `
  third_party/workspace `
  third_party/backends-for-openbb
```

The Workspace source does not satisfy the benchmark Harbor exporter's
standalone sidecar layout without additional work.

### Documentation/research

```powershell
git submodule update --init --recursive -- `
  third_party/openbb-docs `
  third_party/awesome-quant `
  third_party/openfigi-api
```

## Pin update policy

Every submodule update should be an explicit compatibility change:

1. update and test the child repository on its own branch;
2. push the child commit first;
3. update the superproject gitlink to that exact commit;
4. run the relevant cross-repository contract tests;
5. commit the gitlink update with the compatibility evidence.

Example:

```powershell
Push-Location third_party\agents-for-openbb
git fetch origin
git switch main
git pull --ff-only
$child = git rev-parse HEAD
Pop-Location

git add third_party/agents-for-openbb
git diff --cached --submodule=log
Write-Output "Pinned agents-for-openbb at $child"
```

The `branch = main` setting enables intentional
`git submodule update --remote`; it does not make normal clones float with
`main`.

## Drift audit

When standalone clones are retained for upstream work, compare them with the
superproject pins:

```powershell
$pairs = @(
    @("agents-for-openbb", "third_party/agents-for-openbb"),
    @("backends-for-openbb", "third_party/backends-for-openbb"),
    @("openbb-rag-financial-research-agent", "third_party/openbb-rag-financial-research-agent"),
    @("openbb-workspace-bench", "third_party/openbb-workspace-bench"),
    @("workspace", "third_party/workspace")
)

foreach ($pair in $pairs) {
    $standalone = git -C "..\..\OpenBBAll\$($pair[0])" rev-parse HEAD
    $pinned = (git ls-tree HEAD -- $pair[1]).Split()[2]
    [pscustomobject]@{
        Repository = $pair[0]
        Standalone = $standalone
        Pinned = $pinned
        Match = $standalone -eq $pinned
    }
}
```

Run this as an informational audit. A mismatch is not automatically wrong:
the standalone clone may contain work that has not passed integration tests.

## Ownership rule

Make source changes in one canonical child checkout, commit and push them
there, then update the Portfolio gitlink. Do not independently edit both the
standalone clone and the initialized submodule. Git identifies equivalence by
commit SHA; copying files between clones loses history and makes review harder.

