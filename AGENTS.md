# Working on this repo

Context for agents editing **this plugin**. It is not how the plugin ships — Claude Code and
Codex both deliver it through `skills/`, and neither loads this file from a plugin root.

## Layout

| Path | Loaded by | Notes |
|---|---|---|
| `skills/*/SKILL.md` | Claude Code + Codex | The delivery channel. Frontmatter is `name` + `description` only |
| `commands/*.md` | Claude Code | Slash commands |
| `commands/*.toml` | Codex | Same commands, Codex format — keep the two in sync |
| `agents/*.md` | Claude Code only | Thin wrappers over skills. Codex plugins cannot register named subagents |
| `hooks/hooks.json` | Claude Code + Codex | Same schema, same `${CLAUDE_PLUGIN_ROOT}` variable |
| `.claude-plugin/`, `.codex-plugin/`, `.agents/plugins/` | Respective harness | Manifests |

## Rules

- **`skills/` is the single source of truth.** Commands and agents must not restate skill
  content — they point at it. Duplicated guidance drifts.
- **Four skills are ported from `my_harness_for_claude_code`**: `rdbms-naming`,
  `mysql-guideline`, `postgres-guideline`, `database-migrations`. They carry deliberate local
  edits (dropped `mysql_` filename prefix, stripped `origin:`/`workloads:` frontmatter,
  cross-references repointed at plugin skills). Use `scripts/sync-from-harness.sh` to see
  upstream drift — never blind-copy over them.
- **`db-select`, `rdbms-modeling`, `rdbms-review` are plugin-authored.** No upstream to sync.
- **A skill's `description` is its only trigger.** If a skill should fire on a phrase, that
  phrase belongs in the description.
- **Reference filenames in a `SKILL.md` must resolve.** The harness originals shipped broken
  `mysql_`-prefixed references; do not reintroduce that.
- `hooks/detect-db.test.sh` must pass. Run `sh hooks/detect-db.test.sh`.
