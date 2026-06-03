# Codex shared configuration

These files (`config.toml`, `hooks.json`) enable Codex integration with the
**Beads (`bd`)** issue tracker that this fork has adopted. They are committed as
shared, opt-in-for-all settings so every contributor gets the same Codex context
behavior.

## Prerequisite: `bd` on PATH

The hooks in `hooks.json` shell out to `bd codex-hook ...` on session
start/compact/prompt. **`bd` (beads) must be installed and on your PATH**, or
those hooks will error. Install/setup instructions live in the root `CLAUDE.md`
("Beads Issue Tracker"); run `bd prime` once `bd` is available.

If you do not use Codex or Beads, you can safely ignore this directory — it only
affects Codex sessions.
