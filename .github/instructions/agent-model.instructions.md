---
description: Required execution model for all repository agents and subagents
applyTo: '**'
---

# Agent Model Policy

- Use `gpt-5.6-sol` for every agent and subagent launched to work on this
  repository.
- Specify `gpt-5.6-sol` explicitly whenever an agent-dispatch interface accepts
  a model. Do not rely on a session default or use model aliases, cheaper tiers,
  fallback models, or provider-specific alternatives.
- If `gpt-5.6-sol` is unavailable, stop and report the blocker rather than
  dispatching another model.
- This policy governs execution agents. It does not restrict models that the
  repository deploys, trains, evaluates, documents, or exposes as product
  functionality.
