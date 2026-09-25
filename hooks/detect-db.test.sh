#!/bin/sh
# Smallest thing that fails if detect-db.sh breaks.
# Run: sh hooks/detect-db.test.sh

set -eu

SCRIPT=$(cd "$(dirname "$0")" && pwd)/detect-db.sh
PASS=0
FAIL=0

# check <name> <expected-substring-or-EMPTY> <file>:<content> ...
check() {
  name=$1
  expect=$2
  shift 2

  tmp=$(mktemp -d)
  for spec in "$@"; do
    f=${spec%%:*}
    body=${spec#*:}
    mkdir -p "$tmp/$(dirname "$f")"
    printf '%s\n' "$body" >"$tmp/$f"
  done

  out=$(
    if [ "${MODE:-explicit}" = "git-subdir" ]; then
      git -C "$tmp" init -q || exit 1
      mkdir -p "$tmp/src/nested"
      cd "$tmp/src/nested" || exit 1
      unset CLAUDE_PROJECT_DIR
    elif [ "${MODE:-explicit}" = "cwd" ]; then
      cd "$tmp" || exit 1
      unset CLAUDE_PROJECT_DIR
    else
      CLAUDE_PROJECT_DIR="$tmp"
      export CLAUDE_PROJECT_DIR
    fi
    sh "$SCRIPT" </dev/null 2>&1
  ) || {
    echo "FAIL $name — script exited non-zero"
    FAIL=$((FAIL + 1))
    rm -rf "$tmp"
    return 0
  }
  rm -rf "$tmp"

  if [ "$expect" = "EMPTY" ]; then
    if [ -z "$out" ]; then
      PASS=$((PASS + 1))
    else
      echo "FAIL $name — expected no output, got: $out"
      FAIL=$((FAIL + 1))
    fi
  elif printf '%s' "$out" | grep -q "$expect"; then
    PASS=$((PASS + 1))
  else
    echo "FAIL $name — expected '$expect' in: $out"
    FAIL=$((FAIL + 1))
  fi
}

check "no db files at all" EMPTY \
  "README.md:just a readme"

check "non-db project with package.json" EMPTY \
  "package.json:{\"dependencies\":{\"react\":\"19.0.0\"}}"

check "postgres via docker-compose" "PostgreSQL" \
  "docker-compose.yml:services:
  db:
    image: postgres:16"

check "mysql via docker-compose" "MySQL" \
  "docker-compose.yml:services:
  db:
    image: mysql:8.4"

check "postgres via DATABASE_URL" "PostgreSQL" \
  ".env.example:DATABASE_URL=postgresql://app@localhost:5432/app"

check "mysql via python driver" "MySQL" \
  "requirements.txt:aiomysql==0.2.0"

check "postgres via prisma provider" "PostgreSQL" \
  "prisma/schema.prisma:datasource db {
  provider = \"postgresql\"
}"

check "both engines present" "PostgreSQL and MySQL" \
  "docker-compose.yml:services:
  pg:
    image: postgres:16
  my:
    image: mysql:8.4"

check "aurora endpoint noted" "Aurora/RDS" \
  ".env:DATABASE_URL=postgresql://app@mydb.cluster-abc.us-east-1.rds.amazonaws.com:5432/app"

check "supabase noted" "managed database platform" \
  ".env:DATABASE_URL=postgresql://x@db.abcdef.supabase.co:5432/postgres"

check "mariadb detected separately" "MariaDB" \
  "docker-compose.yml:services:
  db:
    image: mariadb:11"

check "sqlite via python driver" "SQLite" \
  "requirements.txt:aiosqlite==0.20.0"

check "sqlite via node driver" "SQLite" \
  "package.json:{\"dependencies\":{\"better-sqlite3\":\"11.0.0\"}}"

check "names the mysql guideline skill" "engine rules in mysql-guideline" \
  "requirements.txt:aiomysql==0.2.0"

check "single engine still requires confirming the version" "confirm the \*version\*" \
  "requirements.txt:aiomysql==0.2.0"

check "names the postgres guideline skill" "engine rules in postgres-guideline" \
  ".env.example:DATABASE_URL=postgresql://app@localhost:5432/app"

check "names the sqlite guideline skill" "engine rules in sqlite-guideline" \
  "requirements.txt:aiosqlite==0.20.0"

check "mariadb routes to the mysql guideline" "engine rules in mysql-guideline" \
  "docker-compose.yml:services:
  db:
    image: mariadb:11"

check "multiple engines name every guideline" "postgres-guideline, mysql-guideline, sqlite-guideline" \
  "package.json:{\"dependencies\":{\"pg\":\"8\",\"mysql2\":\"3\",\"better-sqlite3\":\"11\"}}"

check "routes to database-migrations for existing data" "database-migrations" \
  "requirements.txt:aiomysql==0.2.0"

check "single engine suppresses the question" "do not re-ask which database" \
  "docker-compose.yml:services:
  db:
    image: postgres:16"

check "two engines demand confirmation" "ask which one" \
  "docker-compose.yml:services:
  pg:
    image: postgres:16
  my:
    image: mysql:8.4"

check "mariadb demands confirmation" "ask which one" \
  "docker-compose.yml:services:
  db:
    image: mariadb:11"

check "postgis image routes to postgres" "engine rules in postgres-guideline" \
  "compose.yaml:services:
  db:
    image: postgis/postgis:18-3.6"

check "pgvector image routes to postgres" "engine rules in postgres-guideline" \
  "compose.yaml:services:
  db:
    image: pgvector/pgvector:pg18-bookworm"

check "mariadb does not hide mysql" "MariaDB (MySQL-compatible; verify divergence) and MySQL" \
  "compose.yaml:services:
  legacy:
    image: mariadb:11
  db:
    image: mysql:8.4"

check "multiple engines preserve the user's target" "Use the target already specified by the user" \
  "package.json:{\"dependencies\":{\"pg\":\"8\",\"mysql2\":\"3\"}}"

check "postgres jdbc in maven" "engine rules in postgres-guideline" \
  "pom.xml:<dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId></dependency>"

check "mysql jdbc in gradle kotlin" "engine rules in mysql-guideline" \
  "build.gradle.kts:runtimeOnly(\"com.mysql:mysql-connector-j:9.7.0\")"

MODE=git-subdir
check "codex from nested git directory without CLAUDE_PROJECT_DIR" "PostgreSQL" \
  "package.json:{\"dependencies\":{\"pg\":\"8\"}}"

check "codex finds a component manifest between cwd and git root" "MySQL" \
  "src/package.json:{\"dependencies\":{\"mysql2\":\"3\"}}"

MODE=cwd
check "non-git cwd without CLAUDE_PROJECT_DIR" "SQLite" \
  "requirements.txt:aiosqlite==0.20.0"
unset MODE

echo "---"
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ]
