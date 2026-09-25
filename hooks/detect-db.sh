#!/bin/sh
# SessionStart: detect which RDBMS this repo already uses and say so once.
# Silent when nothing is found — no DB work in the project means no context needed.
#
# ponytail: fixed grep list over a handful of high-signal files, not a full
# dependency-graph parse. Add a pattern below when a real project is missed.

set -u

# Some harnesses pipe hook payload on stdin; drain it so we never block.
[ -t 0 ] || cat >/dev/null 2>&1 || true

# Explicit project paths stay scoped to that directory. Otherwise inspect the cwd and
# its ancestors through the Git root, so both root manifests and monorepo modules work.
if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
  cd "$CLAUDE_PROJECT_DIR" 2>/dev/null || exit 0
  ROOT=$(pwd -P)
else
  ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd -P)
  ROOT=$(cd "$ROOT" 2>/dev/null && pwd -P) || exit 0
  # A foreign GIT_WORK_TREE must not make us walk outside the cwd's repository.
  case "$(pwd -P)/" in "$ROOT/"*) ;; *) ROOT=$(pwd -P) ;; esac
fi

# Files worth reading. Missing ones are skipped silently.
FILES="docker-compose.yml docker-compose.yaml compose.yml compose.yaml
.env .env.example .env.sample
alembic.ini flyway.conf flyway.toml liquibase.properties
prisma/schema.prisma knexfile.js knexfile.ts ormconfig.json
package.json requirements.txt pyproject.toml Cargo.toml go.mod
pom.xml build.gradle build.gradle.kts"

HAYSTACK=$(
  while :; do
    for f in $FILES; do
      if [ -f "$f" ]; then
        cat "$f" 2>/dev/null
        printf '\n'
      fi
    done
    [ "$(pwd -P)" = "$ROOT" ] && break
    cd .. 2>/dev/null || break
  done
)
[ -n "$HAYSTACK" ] || exit 0

FOUND=""

# PostgreSQL: images, URL schemes, drivers, migration tools
if printf '%s' "$HAYSTACK" | grep -qiE \
  'postgres|postgis|pgvector|psycopg|asyncpg|pgbouncer|"pg"|lib/pq|pq\.|sqlx.*postgres|provider *= *"postgresql"|jdbc:postgresql'; then
  FOUND="PostgreSQL"
fi

# MariaDB — detect separately so MySQL-specific advice gets a compatibility check first
if printf '%s' "$HAYSTACK" | grep -qiE 'mariadb'; then
  if [ -n "$FOUND" ]; then FOUND="$FOUND and MariaDB (MySQL-compatible; verify divergence)"; else FOUND="MariaDB (MySQL-compatible; verify divergence)"; fi
fi
# MySQL
if printf '%s' "$HAYSTACK" | grep -qiE \
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
# 여러 엔진 또는 MariaDB에서는 이미 지정된 대상을 유지한다.
# 아직 대상이 불명확할 때만 질문해 잘못된 dialect의 SQL을 막는다.
case "$FOUND" in
  *" and "*|*MariaDB*) CLOSING="More than one engine (or a MySQL-compatible variant) is present. Use the target already specified by the user; otherwise ask which one the current task targets before writing dialect-specific SQL. Verify the target version and deployment form from configuration or runtime." ;;
  *)                   CLOSING="The engine is inferred from the repository, so take it as given and do not re-ask which database this project uses. Still confirm the *version* and deployment form (managed / Aurora / container) from configuration or runtime before emitting version-specific SQL; ask only for unresolved facts -- this detection does not reveal them." ;;
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
