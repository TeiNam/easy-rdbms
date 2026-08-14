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

  out=$(CLAUDE_PROJECT_DIR="$tmp" sh "$SCRIPT" </dev/null 2>&1) || {
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

echo "---"
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ]
