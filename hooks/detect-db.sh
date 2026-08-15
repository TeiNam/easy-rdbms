#!/bin/sh
# SessionStart: detect which RDBMS this repo already uses and say so once.
# Silent when nothing is found — no DB work in the project means no context needed.
#
# ponytail: fixed grep list over a handful of high-signal files, not a full
# dependency-graph parse. Add a pattern below when a real project is missed.

set -u

# Some harnesses pipe hook payload on stdin; drain it so we never block.
[ -t 0 ] || cat >/dev/null 2>&1 || true

ROOT=${CLAUDE_PROJECT_DIR:-.}
cd "$ROOT" 2>/dev/null || exit 0

# Files worth reading. Missing ones are skipped silently.
FILES="docker-compose.yml docker-compose.yaml compose.yml compose.yaml
.env .env.example .env.sample
alembic.ini flyway.conf flyway.toml liquibase.properties
prisma/schema.prisma knexfile.js knexfile.ts ormconfig.json
package.json requirements.txt pyproject.toml Cargo.toml go.mod"

EXISTING=""
for f in $FILES; do
  [ -f "$f" ] && EXISTING="$EXISTING $f"
done
[ -n "$EXISTING" ] || exit 0

# shellcheck disable=SC2086
HAYSTACK=$(cat $EXISTING 2>/dev/null) || exit 0

FOUND=""

# PostgreSQL: images, URL schemes, drivers, migration tools
if printf '%s' "$HAYSTACK" | grep -qiE \
  'postgres|postgresql|psycopg|asyncpg|pgbouncer|"pg"|lib/pq|pq\.|sqlx.*postgres|provider *= *"postgresql"|jdbc:postgresql'; then
  FOUND="PostgreSQL"
fi

# MariaDB — detect separately so MySQL-specific advice gets a compatibility check first
if printf '%s' "$HAYSTACK" | grep -qiE 'mariadb'; then
  if [ -n "$FOUND" ]; then FOUND="$FOUND and MariaDB (MySQL-compatible; verify divergence)"; else FOUND="MariaDB (MySQL-compatible; verify divergence)"; fi
# MySQL
elif printf '%s' "$HAYSTACK" | grep -qiE \
  'mysql|aiomysql|pymysql|mysqlclient|mysql2|go-sql-driver|sqlx.*mysql|provider *= *"mysql"|jdbc:mysql'; then
  if [ -n "$FOUND" ]; then FOUND="$FOUND and MySQL"; else FOUND="MySQL"; fi
fi

# SQLite
if printf '%s' "$HAYSTACK" | grep -qiE \
  'sqlite|better-sqlite3|rusqlite|aiosqlite|sql\.js|modernc\.org/sqlite'; then
  if [ -n "$FOUND" ]; then FOUND="$FOUND and SQLite"; else FOUND="SQLite"; fi
fi

[ -n "$FOUND" ] || exit 0

# Aurora / managed hints refine the deployment-form advice
EXTRA=""
if printf '%s' "$HAYSTACK" | grep -qiE 'aurora|rds\.amazonaws\.com'; then
  EXTRA=" Aurora/RDS endpoints are referenced."
elif printf '%s' "$HAYSTACK" | grep -qiE 'supabase|neon\.tech|planetscale'; then
  EXTRA=" A managed database platform is referenced."
fi

# One engine → the dialect is settled, so suppress the confirmation question.
# Several engines (or MariaDB, which diverges from MySQL) → the agent MUST confirm which
# one the current task targets; guessing the dialect produces DDL that does not run.
case "$FOUND" in
  *" and "*|*MariaDB*) CLOSING="More than one engine (or a MySQL-compatible variant) is present — ask which one the current task targets before writing any dialect-specific SQL." ;;
  *)                   CLOSING="The dialect is settled; do not re-ask which database this project uses." ;;
esac

# Name the guideline skill(s) outright. The engine is already known here, so making the
# agent infer "the matching guideline skill" wastes the detection we just did.
GUIDES=""
case "$FOUND" in *PostgreSQL*) GUIDES="postgres-guideline" ;; esac
case "$FOUND" in *MySQL*|*MariaDB*) GUIDES="${GUIDES:+$GUIDES, }mysql-guideline" ;; esac
case "$FOUND" in *SQLite*) GUIDES="${GUIDES:+$GUIDES, }sqlite-guideline" ;; esac

cat <<CTX
This project already uses $FOUND.$EXTRA
For any table, index, migration, or query work here, use the easy-rdbms skills:
engine rules in $GUIDES; naming and data types in rdbms-naming; new table
design in rdbms-modeling; schema/query review in rdbms-review; changing a
schema that already holds data in database-migrations. $CLOSING
CTX
