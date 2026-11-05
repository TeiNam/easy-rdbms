---
name: database-migrations
description: Database migration best practices for schema changes, data migrations, rollbacks, and zero-downtime deployments. PostgreSQL-first mechanics with MySQL online-DDL notes, widening a primary key from int to bigint (ALGORITHM=COPY / ACCESS EXCLUSIVE table rewrite), and workflows for Prisma, Drizzle, Kysely, Django, and golang-migrate.
---

# Database Migration Patterns

Safe, reversible database schema changes for production systems.

## Contents

- When to Activate
- Core Principles
- Migration Safety Checklist
- How Much Latitude Each Step Has
- PostgreSQL Patterns
  - Adding a Column Safely
  - Adding an Index Without Downtime
  - Renaming a Column (Zero-Downtime)
  - Widening a Primary Key — Not an Ordinary Migration
  - Removing a Column Safely
  - Large Data Migrations
- Tool Workflows
- Zero-Downtime Migration Strategy
  - Timeline Example
- 엔진·확장 버전 변경
- Anti-Patterns
- Related

## When to Activate

- Creating or altering database tables
- Adding/removing columns or indexes
- Running data migrations (backfill, transform)
- Planning zero-downtime schema changes
- Widening a primary key or any column type on a large table
- Setting up migration tooling for a new project

## Core Principles

1. **Every change is a migration** — never alter production databases manually
2. **Migrations are forward-only in production** — rollbacks use new forward migrations
3. **Schema and data migrations are separate** — never mix DDL and DML in one migration
4. **Test migrations against production-sized data** — a migration that works on 100 rows may lock on 10M
5. **Migrations are immutable once deployed** — never edit a migration that has run in production

## Migration Safety Checklist

Before applying any migration:

- [ ] A rollback plan exists — a DOWN migration where the tool supports one (golang-migrate,
      Kysely), or a documented forward-fix procedure where it does not (Prisma is forward-only)
- [ ] No full table locks on large tables (use concurrent operations)
- [ ] New columns have defaults or are nullable (never add NOT NULL without default)
- [ ] Indexes created concurrently (not inline with CREATE TABLE for existing tables)
- [ ] Data backfill is a separate migration from schema change
- [ ] Tested against a copy of production data

## How Much Latitude Each Step Has

| Step | Latitude |
|---|---|
| Tool, file layout, migration names, batch size | **Yours** — follow the project's existing tool and conventions |
| Expand → backfill → contract order, the `NOT NULL` path, a PK cutover | **None** — run the statements in the order shown. Do not merge or reorder steps, and do not add options such as `CASCADE` or `IF NOT EXISTS` |
| Anything that deletes data (`DROP COLUMN`, `DROP TABLE`, a purge) | **None** — only after that step's verification passes, in its own migration |

## PostgreSQL Patterns

### Adding a Column Safely

Every `ADD COLUMN` takes a brief **ACCESS EXCLUSIVE lock** — what varies is whether the table is
*rewritten*. Behind long transactions or `pg_dump`, even the brief lock queues everything after it,
so set a `lock_timeout` and retry.

```sql
-- GOOD: nullable column — brief lock, no rewrite
ALTER TABLE member ADD COLUMN avatar_url TEXT;

-- GOOD: column with constant default (Postgres 11+ stores the default in the catalog, no rewrite)
ALTER TABLE member ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true;

-- FAILS on a non-empty table: NOT NULL with no default has nothing to fill existing rows with
ALTER TABLE member ADD COLUMN access_level TEXT NOT NULL;
-- ERROR: column "access_level" of relation "member" contains null values

-- GOOD: the NOT NULL-without-default path. Order matters: a `NOT VALID` CHECK still enforces on
-- NEW writes, so adding it before every writer populates the column breaks running inserts.
-- And a bare SET NOT NULL scans the whole table under ACCESS EXCLUSIVE — a pre-validated CHECK
-- lets PostgreSQL (12+) skip that scan.

-- 1. nullable add (migration)
ALTER TABLE member ADD COLUMN access_level TEXT;

-- 2. DEPLOY application code that always writes `access_level`  <- before any constraint exists

-- 3. backfill existing rows (separate migration, batched — see Large Data Migrations)
UPDATE member SET access_level = 'member' WHERE access_level IS NULL;

-- 4. now that no writer produces NULL and no row holds one:
ALTER TABLE member ADD CONSTRAINT chk_member_access_level_not_null
  CHECK (access_level IS NOT NULL) NOT VALID;                                 -- instant, no scan
ALTER TABLE member VALIDATE CONSTRAINT chk_member_access_level_not_null;      -- scans under a weak lock
ALTER TABLE member ALTER COLUMN access_level SET NOT NULL;                    -- no scan — the CHECK proves it
ALTER TABLE member DROP CONSTRAINT chk_member_access_level_not_null;          -- helper no longer needed
```

### Adding an Index Without Downtime

(Assumes the index is already justified — the query, the plan, and the write cost come from
`rdbms-modeling/references/index-design.md`. This section is about *how* to build it safely.)

```sql
-- BAD: Blocks writes on large tables
CREATE INDEX idx_member_last_login ON member (last_login_at);

-- GOOD: Non-blocking, allows concurrent writes
CREATE INDEX CONCURRENTLY idx_member_last_login ON member (last_login_at);

-- Note: CONCURRENTLY cannot run inside a transaction block
-- Most migration tools need special handling for this
```

`CONCURRENTLY` is **PostgreSQL-only**, and even there a **partitioned parent** does not accept it —
build each child's index `CONCURRENTLY`, then create the parent index (metadata-only once all
children have one). On **MySQL** the equivalent is InnoDB online DDL:

```sql
ALTER TABLE member ADD INDEX idx_member_last_login (last_login_at), ALGORITHM=INPLACE, LOCK=NONE;
-- If the ALTER cannot run in-place MySQL errors instead of silently locking — that error is the signal
```

### Renaming a Column (Zero-Downtime)

Never rename directly in production. Use the expand-contract pattern:

```sql
-- Step 1: Add the new column (migration 001)
ALTER TABLE member ADD COLUMN display_name TEXT;

-- Step 2: DEPLOY dual writes — the app writes BOTH columns, still reads the old one.
--         This must precede the backfill: otherwise writes landing between the backfill
--         and the deploy leave display_name NULL.

-- Step 3: Backfill the rows that predate the dual-write deploy (migration 002, batched)
UPDATE member SET display_name = username WHERE display_name IS NULL;

-- Step 4: DEPLOY reads switched to the new column (still writing both)

-- Step 5: DEPLOY writes to the old column removed

-- Step 6: Drop the old column (migration 003)
ALTER TABLE member DROP COLUMN username;
```

### Widening a Primary Key — Not an Ordinary Migration

Changing a PK from `int` to `bigint` is a multi-week rollout on either engine, not one `ALTER`:
MySQL rebuilds the table and every secondary index under `ALGORITHM=COPY`, PostgreSQL rewrites it
under `ACCESS EXCLUSIVE`, and every referencing column has to move in lockstep. Stop, size the work,
and follow `widen-primary-key.md` step by step. Physical FKs are rebound per
`rdbms-modeling/references/foreign-keys.md`; the migration you actually want is the one avoided by
sizing the key at `CREATE TABLE` time (`rdbms-modeling/references/identifier-selection.md`).

### Removing a Column Safely

```sql
-- Step 1: Remove all application references to the column
-- Step 2: Deploy application without the column reference
-- Step 3: Drop column in next migration
ALTER TABLE purchase_order DROP COLUMN legacy_status;

-- For Django: SeparateDatabaseAndState (django.md) to remove from model
-- without generating DROP COLUMN (then drop in next migration)
```

### Large Data Migrations

```sql
-- BAD: Updates all rows in one transaction (locks table)
UPDATE member SET normalized_email = LOWER(email);

-- GOOD: Batch update with progress
-- Precondition: email is NOT NULL; deployed writers maintain normalized_email on new/changed rows.
-- CAUTION: a DO block cannot COMMIT between batches when the migration runner wraps it
-- in a transaction — then it is one giant transaction wearing a loop. Run it outside a
-- transaction (psql, or the runner's no-transaction mode), or batch from application code.
DO $$
DECLARE
  batch_size INT := 10000;
  rows_updated INT;
BEGIN
  LOOP
    UPDATE member
    SET normalized_email = LOWER(email)
    WHERE member_id IN (
      SELECT member_id FROM member
      WHERE normalized_email IS NULL
      LIMIT batch_size
      FOR UPDATE SKIP LOCKED
    );
    GET DIAGNOSTICS rows_updated = ROW_COUNT;
    RAISE NOTICE 'Updated % rows', rows_updated;
    IF rows_updated = 0 THEN
      -- SKIP LOCKED can return an empty batch while another writer owns unfinished rows.
      IF EXISTS (SELECT 1 FROM member WHERE normalized_email IS NULL) THEN
        RAISE EXCEPTION 'Backfill incomplete: unprocessed rows remain; retry after active writers finish';
      END IF;
      EXIT;
    END IF;
    COMMIT;
  END LOOP;
END $$;
```

## Tool Workflows

Open only the file for the migration tool the project already uses. Each starts with its install
step — run the project's pinned version, not a global or freshly downloaded one.

| Tool | File | Covers |
|---|---|---|
| Prisma | `prisma.md` | `migrate dev` / `deploy`, named constraints in `schema.prisma`, hand-written `CONCURRENTLY` migrations |
| Drizzle | `drizzle.md` | `generate` / `migrate` / `push`, named unique indexes |
| Kysely | `kysely.md` | `kysely-ctl` commands, `Kysely<any>` migrations, the programmatic `Migrator` |
| Django | `django.md` | `makemigrations` / `migrate`, batched `RunPython` with `atomic = False`, `SeparateDatabaseAndState` |
| golang-migrate | `golang-migrate.md` | `up` / `down` / `force`, one `CONCURRENTLY` statement per file |

## Zero-Downtime Migration Strategy

For critical production changes, follow the expand-contract pattern. The order is the safety
mechanism, so copy this checklist into your response and tick each step only when it holds:

```
Expand-contract progress:
- [ ] 1. EXPAND   — add the new column/table (nullable, or with a constant default)
- [ ] 2. Deploy   — the app writes BOTH old and new, still reads old
- [ ] 3. Backfill — existing rows, in bounded batches, as its own migration
- [ ] 4. Verify   — no row has the new value missing while the old one is set, and a sample
                    satisfies the backfill rule (new = old for a rename, new = f(old) for a
                    transform such as LOWER(email)). Mismatch → back to step 3; rows written
                    since step 2 without the new value → back to step 2
- [ ] 5. MIGRATE  — deploy reads from NEW, still writing both
- [ ] 6. Deploy   — the app writes NEW only
- [ ] 7. Verify   — no deployed reader or writer references the old column: grep the deployed
                    revision, and count only statements run since the step-6 deploy (the
                    pg_stat_statements `calls` delta over a window, performance_schema
                    `LAST_SEEN`) — both keep pre-deploy history. A new call → back to 6
- [ ] 8. CONTRACT — drop the old column/table in a separate migration
```

### Timeline Example

```
Day 1: Migration adds new_status column (nullable)
Day 1: Deploy app v2 - writes BOTH status and new_status, still reads status
Day 2: Run backfill migration for existing rows (batched)
Day 3: Deploy app v3 - reads new_status, still writes both
Day 5: Deploy app v4 - stops writing status          <- REQUIRED before the drop
Day 6: Verify no writer references status (grep the deployed revision; in
       pg_stat_statements / performance_schema count only calls made since Day 5)
Day 7: Migration drops old status column
```

## 엔진·확장 버전 변경

- PostgreSQL major 전환은 `postgres-guideline/version-and-upgrade.md`의 사전 검사·복원·전환
  경로를 따른다. 18 전용 VIRTUAL/uuidv7/파티션 FK DDL은 기존 16/17에 적용하지 않는다.
- 확장 패키지 설치와 `CREATE/ALTER EXTENSION`은 다른 단계다. 바이너리·SQL 버전·preload
  목록·재기동·업데이트 경로는 `postgres-guideline/extensions.md`로 확인한다.
  downgrade나 `DROP EXTENSION ... CASCADE`를 자동 rollback으로 생성하지 않는다.
- pgvector 모델 변경은 재임베딩과 품질 검증, PostGIS는 좌표계·라이브러리 변경에 따른 결과
  검증, FDW는 원격 DDL과 mapping 호환성을 포함한다.
- MySQL 8.4나 9.7로 전환할 때는 `mysql-guideline/operations.md`의 LTS 점검(인증·제거된 옵션·
  비표준 FK·change buffer 기본값)을 실행하고, LTS는 한 단계씩 올린다(8.0→8.4→9.7).
  `ALGORITHM=INSTANT`는 지원 작업에만 쓰며, 명시해서 실패하면 COPY/잠금 영향과 온라인 이관 도구를
  별도로 검토한다.

## Anti-Patterns

| Anti-Pattern | Why It Fails | Better Approach |
|-------------|-------------|-----------------|
| Manual SQL in production | No audit trail, unrepeatable | Always use migration files |
| Editing deployed migrations | Causes drift between environments | Create new migration instead |
| NOT NULL without default | **Fails** on a non-empty table — nothing fills existing rows | Add nullable, backfill, then `SET NOT NULL` |
| Inline index on large table | Blocks writes on PostgreSQL; MySQL builds eligible secondary indexes online but silently falls back when it cannot | PostgreSQL `CREATE INDEX CONCURRENTLY`; MySQL state `ALGORITHM=INPLACE, LOCK=NONE` explicitly so an ineligible change errors instead of locking |
| Schema + data in one migration | Hard to rollback, long transactions | Separate migrations |
| Dropping column before removing code | Application errors on missing column | Remove code first, drop column next deploy |

## Related

- `rdbms-modeling` — Designs the target schema in the first place;
  `rdbms-modeling/references/index-design.md` justifies an index before this skill builds it safely.
- `mysql-guideline` / `postgres-guideline` / `sqlite-guideline` — Engine-specific DDL semantics: which
  `ALTER` is in-place, which locks it takes, and the type rules the new column has to satisfy.
- `rdbms-review` — Review the resulting schema, not just the migration mechanics.
