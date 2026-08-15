# Working on this repo

Context for agents editing **this plugin**. It is not how the plugin ships — Claude Code and
Codex both deliver it through `skills/`, and neither loads this file from a plugin root.

## Layout

| Path | Loaded by | Notes |
|---|---|---|
| `skills/*/SKILL.md` | Claude Code + Codex | The delivery channel. Frontmatter is `name` + `description` only |
| `commands/*.md` | Claude Code only | Slash commands that point at skills |
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
- **`db-select`, `rdbms-modeling`, `rdbms-review`, `sqlite-guideline` are plugin-authored.** No upstream to sync.
- **A skill's `description` is its only trigger.** If a skill should fire on a phrase, that
  phrase belongs in the description. Codex rejects descriptions over 1,024 characters.
- **Codex plugins do not register custom slash commands.** Invoke a skill explicitly as
  `$easy-rdbms:<skill-name>`; do not add `commands/*.toml`.
- **Reference filenames in a `SKILL.md` must resolve.** The harness originals shipped broken
  `mysql_`-prefixed references; do not reintroduce that.
- `hooks/detect-db.test.sh` must pass. Run `sh hooks/detect-db.test.sh`.
- **README is bilingual, and the Korean section is not a translation** — it is written in its own
  voice, so do not diff the prose. But a *factual* correction has to land in **both** sections; it
  has twice landed in only one. `python3 scripts/check-readme-bilingual.py` fails on the four
  numbers that actually went stale: an exhaustion day count, a review total that disagreed with the
  round sequence it sits next to, a reference-file count that disagreed with
  `skills/rdbms-modeling/references/`, and the hook-test count. Run it after touching either section
  — and also after adding or removing a reference file or hook test, since the claims and repository
  contents have to agree.
