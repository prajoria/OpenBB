---
name: setup-memory-mcp
description: Index a code repository into the codebase-memory-mcp knowledge graph so search_graph / trace_path / query_graph / get_code_snippet / get_architecture / search_code / detect_changes return real results for it. Use this whenever the user says "/setup-memory-mcp", "setup memory mcp", "index this repo", "index this codebase", "set up codebase memory", "load the codebase into the knowledge graph", "make this codebase searchable", "register this repo with codebase memory", "index it" (in a context that just established the codebase-memory MCP server), or asks to add the current checkout to the graph. Strongly prefer triggering this skill over running the raw MCP calls yourself — it handles the preflight, naming, beads tracking, mode selection, and post-index verification that one-off calls routinely skip. Do NOT trigger this skill for general questions about codebase-memory-mcp (what it is, how queries work, how to install the server) — those don't need indexing.
---

# Setup Memory MCP — index a repo for graph queries

This skill drives `index_repository` end-to-end for whichever repository the user is sitting in (or hands you as an argument). Once it completes, the `mcp__codebase-memory-mcp__*` tools — `search_graph`, `trace_path`, `query_graph`, `get_code_snippet`, `get_architecture`, `search_code`, `detect_changes` — start returning real, project-scoped results for that repo.

The MCP server must already be installed and reachable; this skill only handles the **indexing** step. If `mcp__codebase-memory-mcp__list_projects` is not in your available tools, the server isn't wired in — tell the user, don't try to install it yourself.

---

## What to do when invoked

Run these steps in order. The preflight matters — silent failures here cost the user 30–90 minutes of re-indexing later.

### 1. Identify the repo

- Default: the current working directory (`pwd`).
- If the user passed an absolute path as an argument, use that instead.

Verify it's a real repo before doing anything else:

```bash
git -C <repo_path> rev-parse --show-toplevel
```

If that fails, stop and tell the user the path isn't a git repository. Don't try to index it anyway.

### 2. Check whether it's already indexed

Call `list_projects()` (i.e. `mcp__codebase-memory-mcp__list_projects`) first. The MCP server normalizes the repo path into a project name by collapsing `:`, `/`, and `\` to `-` — for example `H:/masterswork/git/OpenBB` becomes `H-masterswork-git-OpenBB`. But construction is fiddly, so just **read the project name back from `list_projects()` output** rather than trying to predict it.

If a project for this repo already exists, ask the user before doing anything destructive:

> "Already indexed as `<name>` with N nodes / M edges. Re-index from scratch (~30–90 min) or skip?"

Optionally call `index_status(project=...)` first if it helps the user decide. Re-indexing **replaces** the graph (idempotent, not additive), and runs the full LSP + embedding pipeline again.

For an incremental "what changed since last index" view, recommend `detect_changes()` instead of a full re-index — much cheaper.

### 3. File a beads task (only if the repo uses beads)

If `<repo>/.beads/` exists, file and claim a tracked task before kicking off the index:

```bash
bd create --title "Index <repo-name> into codebase-memory-mcp" --type task --priority 2
bd update <id> --status in_progress
```

Capture the issue ID for later. If `.beads/` doesn't exist, **skip beads entirely** — don't pollute repos that don't use it.

### 4. Pick the mode

Three modes are available:

| Mode | What it builds | When to pick |
|---|---|---|
| `fast` | Files + imports + CALLS edges; no similarity/semantic edges | Only when the repo is enormous and the user is impatient — natural-language `search_graph(query=...)` won't work well without semantic edges |
| `moderate` | `fast` + `SIMILAR_TO` + `SEMANTICALLY_RELATED` edges (vector embeddings) | **Default.** Best balance for query-heavy use |
| `full` | `moderate` but **without** the usual exclude list (vendored deps, generated, tests) | Only when the user wants vendored / generated / third-party code searchable too |

Default to `moderate`. Briefly mention the mode in your reply so the user can interrupt before it starts if they wanted something different.

### 5. Run the index

```
index_repository(
  repo_path="<absolute_path>",
  mode="moderate"   # or whatever was selected
)
```

This is a single MCP call but it can take **30–90 minutes** on a large repo (~50K Python files, full LSP type resolution, semantic embeddings). The call blocks until done and returns a JSON summary. **Don't poll** with `index_status` in a loop — just wait.

If the call returns immediately with `nodes: 0`, raises an error, or surfaces a permission denial, surface the error to the user. Don't paper over it with "looks good!" — that wastes hours when they later notice nothing's there.

### 6. Verify and report

After success, pull a quick architecture snapshot to confirm the graph is actually useful, not just populated:

```
get_architecture(project="<project_name>")
```

Report a compact summary, leading with the result:

```
Indexed: <project_name>
  N nodes / M edges / X MB — mode: moderate

Hotspots: <top 3-5 functions by fan_in with their fan_in numbers>
Clusters: <Leiden community labels with member counts — these are the de-facto modules>
<L> HTTP routes detected · <F> Python files

You can now: search_graph(project="<name>", query="..."), trace_path(...), get_code_snippet(...).
```

Pick out one or two unexpected things that show the indexer actually understood the code — for example: "found a backtest sub-cluster with 183 members including `VectorizedEngine` and `reconcile`", or "917 HTTP routes auto-detected". These prove it parsed semantics, not just counted files. Don't manufacture them — only include what's actually striking in the data.

### 7. (Optional) Cross-repo intelligence

If the user already has another related repo indexed **and** mentions cross-service flows (one repo's HTTP/async/channel/gRPC/GraphQL/tRPC calls hitting another repo's handlers), offer to wire up cross-repo edges:

```
index_repository(
  repo_path="<this_repo>",
  mode="cross-repo-intelligence",
  target_projects=["<other-project-name>", ...]   # or ["*"] for all
)
```

This does **not** re-index — it only scans this repo's route/channel definitions and matches them against handlers in the target projects, creating `CROSS_HTTP_CALLS` / `CROSS_ASYNC_CALLS` / `CROSS_CHANNEL` / `CROSS_GRPC_CALLS` / `CROSS_GRAPHQL_CALLS` / `CROSS_TRPC_CALLS` edges. Takes seconds, not hours.

**Skip this step if you suspect no actual runtime IPC exists between the repos.** Peer Python checkouts that share package names but don't make HTTP calls to each other will return 0 cross edges — that's correct, not a bug. Static Python imports don't count, only runtime IPC does. If you offer the cross-repo step and it returns 0 edges, explain that's expected when the repos are peer checkouts rather than communicating services.

### 8. Close the bead

If you filed one in step 3:

```bash
bd close <id> --reason "Indexed <repo>. Mode: moderate. Nodes: N, Edges: M. <one sentence on what the graph proved — e.g. 'backtest cluster (183 members) and 917 routes captured'>. All codebase-memory-mcp MCP tools now queryable; pass project='<name>'."
```

---

## Gotchas — read these before debugging anything

### 1. MCP permission classifier may silently hard-block the call

On some machines (especially fresh setups), the Claude Code auto-mode classifier hard-blocks `mcp__codebase-memory-mcp__index_repository` **without showing a permission prompt** to the user. If your first attempt comes back denied with no UI, the user has to manually add allow rules to `.claude/settings.local.json` (project-local) or `~/.claude/settings.json` (global).

The exact JSON entries to add to the `permissions.allow` array:

```json
"mcp__codebase-memory-mcp__list_projects",
"mcp__codebase-memory-mcp__index_repository",
"mcp__codebase-memory-mcp__index_status",
"mcp__codebase-memory-mcp__get_architecture",
"mcp__codebase-memory-mcp__search_graph",
"mcp__codebase-memory-mcp__search_code",
"mcp__codebase-memory-mcp__trace_path",
"mcp__codebase-memory-mcp__get_code_snippet",
"mcp__codebase-memory-mcp__query_graph",
"mcp__codebase-memory-mcp__get_graph_schema",
"mcp__codebase-memory-mcp__detect_changes",
"mcp__codebase-memory-mcp__manage_adr"
```

Tell the user exactly what to paste and where, then retry once they confirm. Don't try to edit `settings.local.json` yourself — that path is usually also classifier-blocked.

### 2. Project naming — always read back, never construct

The MCP server's name-normalization rule (`:` `/` `\` → `-`) is simple but easy to get wrong on Windows drive letters. **Always read the actual project name from the output of `list_projects()` or `index_repository()`** and use that string verbatim in subsequent `project=` parameters. Constructing it by hand will eventually bite you.

### 3. Excluded directories — usually correct, occasionally wrong

The indexer auto-skips `.git`, `.venv*`, `node_modules`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `third_party`, `docs`, `examples`, `build`, `assets`, and similar. The response's `excluded.count` is normally 250–350 for a typical Python monorepo.

If `excluded.count` is much higher than that and the user complains the graph is missing real code, the heuristic over-excluded — fall back to `mode="full"` to bring everything in.

### 4. Cross-repo intelligence ≠ shared imports

Cross-repo edges measure **runtime IPC** (one service calling another's HTTP route, publishing to its channel, etc.). They don't measure shared package names or static Python imports. Two checkouts that each have their own `openbb_platform/` will return 0 cross edges — that's not a bug, that's the metric working as designed. Don't propose cross-repo unless you're confident there's a real service boundary.

### 5. `list_projects` is the only safe probe

If you call `get_architecture(project="some-name-that-doesnt-exist")` or `search_graph(project="...")` with a wrong name, you get back an **empty result, not an error**. So a typo silently looks like "the index is broken". Always confirm the project name via `list_projects()` first.

### 6. Re-indexing is not incremental

Running `index_repository` on an already-indexed project replaces the entire graph and takes the full 30–90 minutes again. For "what changed since last index?", use `detect_changes()` instead — it diffs against the current graph and is orders of magnitude faster.

---

## What this skill does NOT do

- **Does not install codebase-memory-mcp itself.** If the `mcp__codebase-memory-mcp__*` tools aren't in your available toolset, the server isn't wired in. Tell the user to install/configure it and re-invoke.
- **Does not manage MCP server config** (`.mcp.json`, `~/.claude.json`, claude config files).
- **Does not run queries for the user.** Once indexed, *they* invoke `search_graph` / `trace_path` (or ask Claude to). This skill just makes the index exist.

---

## Argument handling

`$ARGUMENTS` is optional:

- **No argument:** index the current working directory.
- **Single absolute path:** index that path.
- **Anything else** (multiple words, mode flags, etc.): be liberal — interpret the first token that looks like a path as the repo, and warn the user if the rest seems like it was meant as a flag (this skill doesn't currently parse `--mode=fast` style switches; modes are chosen by the assistant per step 4).
