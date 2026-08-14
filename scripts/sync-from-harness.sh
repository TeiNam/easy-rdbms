#!/bin/sh
# Show (or apply) upstream changes from the harness that this plugin's skills were ported from.
#
# Diff-only by default. The plugin's copies carry deliberate edits — the `mysql_` filename
# prefix was dropped, cross-skill references were repointed at plugin skills, and
# harness-only frontmatter (origin, workloads) was stripped. A blind copy would undo those,
# so review the diff and port changes by hand.
#
#   sh scripts/sync-from-harness.sh              # diff against the default harness path
#   HARNESS=/path/to/harness sh scripts/...      # diff against a specific checkout
#   sh scripts/sync-from-harness.sh --apply      # overwrite plugin copies (then re-check)
#
# ponytail: diff + manual port, not a merge engine. Four skills drift slowly; a real
# three-way merge here would be more code than the reviews it saves.

set -eu

HARNESS=${HARNESS:-"$(cd "$(dirname "$0")/../.." && pwd)/my_harness_for_claude_code"}
PLUGIN=$(cd "$(dirname "$0")/.." && pwd)
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

if [ ! -d "$HARNESS/skills" ]; then
  echo "harness not found at: $HARNESS" >&2
  echo "set HARNESS=/path/to/my_harness_for_claude_code" >&2
  exit 1
fi

echo "harness: $HARNESS"
echo "plugin:  $PLUGIN"
echo

# Ported skills. rdbms-modeling, rdbms-review, and db-select are plugin-authored — not listed.
SKILLS="rdbms-naming mysql-guideline postgres-guideline database-migrations"

DRIFT=0
for s in $SKILLS; do
  src="$HARNESS/skills/$s"
  dst="$PLUGIN/skills/$s"

  if [ ! -d "$src" ]; then
    echo "== $s: gone from harness (renamed or removed upstream)"
    DRIFT=$((DRIFT + 1))
    continue
  fi

  # Compare content only; filenames and frontmatter differ on purpose.
  if diff -rq "$src" "$dst" >/dev/null 2>&1; then
    echo "== $s: identical"
    continue
  fi

  echo "== $s: differs"
  diff -ru "$src" "$dst" 2>&1 | head -60 || true
  echo
  DRIFT=$((DRIFT + 1))

  if [ "$APPLY" -eq 1 ]; then
    cp -R "$src/." "$dst/"
    echo "   applied — now re-check by hand:"
    echo "   - drop any mysql_ filename prefix"
    echo "   - strip 'origin:' and 'workloads:' frontmatter"
    echo "   - repoint references to db-select / rdbms-modeling / rdbms-review"
    echo "   - confirm SKILL.md reference filenames still resolve"
    echo
  fi
done

echo "---"
if [ "$DRIFT" -eq 0 ]; then
  echo "no drift"
else
  echo "$DRIFT skill(s) differ"
  [ "$APPLY" -eq 0 ] && echo "run with --apply to overwrite, then re-apply the plugin edits listed in this script"
fi
