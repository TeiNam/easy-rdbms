---
name: database-migrations
description: Database migration best practices for schema changes, data migrations, rollbacks, and zero-downtime deployments. PostgreSQL-first mechanics with MySQL online-DDL notes, and workflows for Prisma, Drizzle, Kysely, Django, and golang-migrate.
---

# Database Migration Patterns

Safe, reversible database schema changes for production systems.

## When to Activate

- Creating or altering database tables
- Adding/removing columns or indexes
- Running data migrations (backfill, transform)
- Planning zero-downtime schema changes
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
- [ ] Rollback plan documented

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
ALTER TABLE member ADD COLUMN role TEXT NOT NULL;
-- ERROR: column "role" of relation "member" contains null values

-- GOOD: the NOT NULL-without-default path. Order matters: a `NOT VALID` CHECK still enforces on
-- NEW writes, so adding it before every writer populates the column breaks running inserts.
-- And a bare SET NOT NULL scans the whole table under ACCESS EXCLUSIVE — a pre-validated CHECK
-- lets PostgreSQL (12+) skip that scan.

-- 1. nullable add (migration)
ALTER TABLE member ADD COLUMN role TEXT;

-- 2. DEPLOY application code that always writes `role`  ← before any constraint exists

-- 3. backfill existing rows (separate migration, batched — see Large Data Migrations)
UPDATE member SET role = 'member' WHERE role IS NULL;

-- 4. now that no writer produces NULL and no row holds one:
ALTER TABLE member ADD CONSTRAINT chk_member_role_not_null
  CHECK (role IS NOT NULL) NOT VALID;                                 -- instant, no scan
ALTER TABLE member VALIDATE CONSTRAINT chk_member_role_not_null;      -- scans under a weak lock
ALTER TABLE member ALTER COLUMN role SET NOT NULL;                    -- no scan — the CHECK proves it
ALTER TABLE member DROP CONSTRAINT chk_member_role_not_null;          -- helper no longer needed
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

### Removing a Column Safely

```sql
-- Step 1: Remove all application references to the column
-- Step 2: Deploy application without the column reference
-- Step 3: Drop column in next migration
ALTER TABLE purchase_order DROP COLUMN legacy_status;

-- For Django: use SeparateDatabaseAndState to remove from model
-- without generating DROP COLUMN (then drop in next migration)
```

### Large Data Migrations

```sql
-- BAD: Updates all rows in one transaction (locks table)
UPDATE member SET normalized_email = LOWER(email);

-- GOOD: Batch update with progress
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
    WHERE id IN (
      SELECT id FROM member
      WHERE normalized_email IS NULL
      LIMIT batch_size
      FOR UPDATE SKIP LOCKED
    );
    GET DIAGNOSTICS rows_updated = ROW_COUNT;
    RAISE NOTICE 'Updated % rows', rows_updated;
    EXIT WHEN rows_updated = 0;
    COMMIT;
  END LOOP;
END $$;
```

## Prisma (TypeScript/Node.js)

### Workflow

```bash
# Create migration from schema changes
npx prisma migrate dev --name add_user_avatar

# Apply pending migrations in production
npx prisma migrate deploy

# Reset database (dev only)
npx prisma migrate reset

# Generate client after schema changes
npx prisma generate
```

### Schema Example

```prisma
model User {
  id        String   @id @default(cuid())
  email     String   @unique
  name      String?
  avatarUrl String?  @map("avatar_url")
  createdAt DateTime @default(now()) @map("created_at")
  updatedAt DateTime @updatedAt @map("updated_at")
  // a relation like `orders PurchaseOrder[]` needs a matching model — omitted here

  @@map("member")
}
```

### Custom SQL Migration

For operations Prisma cannot express (concurrent indexes, data backfills):

```bash
# Create empty migration, then edit the SQL manually
npx prisma migrate dev --create-only --name add_email_index
```

```sql
-- migrations/20240115_add_email_index/migration.sql
-- Prisma cannot generate CONCURRENTLY, so we write it manually
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_email ON member (email);
```

## Drizzle (TypeScript/Node.js)

### Workflow

```bash
# Generate migration from schema changes
npx drizzle-kit generate

# Apply migrations
npx drizzle-kit migrate

# Push schema directly (dev only, no migration file)
npx drizzle-kit push
```

### Schema Example

```typescript
import { pgTable, text, timestamp, uuid, boolean } from "drizzle-orm/pg-core";

export const member = pgTable("member", {
  id: uuid("id").primaryKey().defaultRandom(),
  email: text("email").notNull().unique(),
  name: text("name"),
  isActive: boolean("is_active").notNull().default(true),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});
```

## Kysely (TypeScript/Node.js)

### Workflow (kysely-ctl)

```bash
# kysely-ctl's subcommand form has changed across versions (space vs colon, e.g.
# `migrate latest` vs `migrate:latest`). Confirm with `kysely --help` for your version.

# Initialize config file (kysely.config.ts)
kysely init

# Create a new migration file
kysely migrate make add_member_avatar

# Apply all pending migrations
kysely migrate latest

# Rollback last migration
kysely migrate down

# Show migration status
kysely migrate list
```

### Migration File

```typescript
// migrations/2024_01_15_001_create_member_profile.ts
import { type Kysely, sql } from 'kysely'

// IMPORTANT: Always use Kysely<any>, not your typed DB interface.
// Migrations are frozen in time and must not depend on current schema types.
export async function up(db: Kysely<any>): Promise<void> {
  await db.schema
    .createTable('member_profile')
    .addColumn('id', 'bigint', (col) => col.generatedAlwaysAsIdentity().primaryKey())
    .addColumn('email', 'text', (col) => col.notNull().unique())
    .addColumn('avatar_url', 'text')
    .addColumn('created_at', 'timestamptz', (col) =>
      col.defaultTo(sql`now()`).notNull()
    )
    .execute()

  await db.schema
    .createIndex('idx_member_profile_avatar')
    .on('member_profile')
    .column('avatar_url')
    .execute()
}

export async function down(db: Kysely<any>): Promise<void> {
  await db.schema.dropTable('member_profile').execute()
}
```

### Programmatic Migrator

```typescript
import { Migrator, FileMigrationProvider } from 'kysely'
import { promises as fs } from 'fs'
import * as path from 'path'
// ESM only — CJS can use __dirname directly
import { fileURLToPath } from 'url'
const migrationFolder = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  './migrations',
)

// `db` is your Kysely<any> database instance
const migrator = new Migrator({
  db,
  provider: new FileMigrationProvider({
    fs,
    path,
    migrationFolder,
  }),
  // WARNING: Only enable in development. Disables timestamp-ordering
  // validation, which can cause schema drift between environments.
  // allowUnorderedMigrations: true,
})

const { error, results } = await migrator.migrateToLatest()

results?.forEach((it) => {
  if (it.status === 'Success') {
    console.log(`migration "${it.migrationName}" executed successfully`)
  } else if (it.status === 'Error') {
    console.error(`failed to execute migration "${it.migrationName}"`)
  }
})

if (error) {
  console.error('migration failed', error)
  process.exit(1)
}
```

## Django (Python)

### Workflow

```bash
# Generate migration from model changes
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Show migration status
python manage.py showmigrations

# Generate empty migration for custom SQL
python manage.py makemigrations --empty app_name -n description
```

### Data Migration

`atomic = False` is what makes the batching real — without it Django wraps the whole `RunPython`
in one transaction and the loop becomes a single giant transaction wearing a loop.

```python
from django.db import migrations, transaction

def backfill_display_names(apps, schema_editor):
    Member = apps.get_model("accounts", "Member")
    batch_size = 5000
    while True:
        with transaction.atomic():          # one committed transaction per batch
            batch = list(
                Member.objects.filter(display_name="").only("pk", "username")[:batch_size]
            )
            if not batch:
                break
            for member in batch:
                member.display_name = member.username
            Member.objects.bulk_update(batch, ["display_name"], batch_size=batch_size)

def reverse_backfill(apps, schema_editor):
    pass  # data migration — nothing to reverse

class Migration(migrations.Migration):
    atomic = False                          # required: lets each batch commit on its own
    dependencies = [("accounts", "0015_add_display_name")]

    operations = [
        migrations.RunPython(backfill_display_names, reverse_backfill),
    ]
```

### SeparateDatabaseAndState

Remove a column from the Django model without dropping it from the database immediately:

```python
class Migration(migrations.Migration):
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="user", name="legacy_field"),
            ],
            database_operations=[],  # Don't touch the DB yet
        ),
    ]
```

## golang-migrate (Go)

### Workflow

```bash
# Create migration pair
migrate create -ext sql -dir migrations -seq add_user_avatar

# Apply all pending migrations
migrate -path migrations -database "$DATABASE_URL" up

# Rollback last migration
migrate -path migrations -database "$DATABASE_URL" down 1

# Force version (fix dirty state)
migrate -path migrations -database "$DATABASE_URL" force VERSION
```

### Migration Files

golang-migrate sends the whole file to PostgreSQL as **one query**, which makes it an implicit
transaction — and `CREATE INDEX CONCURRENTLY` **cannot run inside a transaction block**. Keep the
concurrent index alone in its own migration file so nothing else shares that implicit transaction.

```sql
-- migrations/000003_add_member_avatar.up.sql   (transactional: DDL only)
ALTER TABLE member ADD COLUMN avatar_url TEXT;

-- migrations/000003_add_member_avatar.down.sql
ALTER TABLE member DROP COLUMN IF EXISTS avatar_url;
```

```sql
-- migrations/000004_index_member_avatar.up.sql   (must be alone in the file)
CREATE INDEX CONCURRENTLY idx_member_avatar ON member (avatar_url) WHERE avatar_url IS NOT NULL;

-- migrations/000004_index_member_avatar.down.sql
DROP INDEX CONCURRENTLY IF EXISTS idx_member_avatar;
```

## Zero-Downtime Migration Strategy

For critical production changes, follow the expand-contract pattern:

```
Phase 1: EXPAND
  - Add new column/table (nullable or with default)
  - Deploy: app writes to BOTH old and new
  - Backfill existing data

Phase 2: MIGRATE
  - Deploy: app reads from NEW, writes to BOTH
  - Verify data consistency

Phase 3: CONTRACT
  - Deploy: app only uses NEW
  - Drop old column/table in separate migration
```

### Timeline Example

```
Day 1: Migration adds new_status column (nullable)
Day 1: Deploy app v2 — writes to both status and new_status
Day 2: Run backfill migration for existing rows
Day 3: Deploy app v3 — reads from new_status only
Day 7: Migration drops old status column
```

## Anti-Patterns

| Anti-Pattern | Why It Fails | Better Approach |
|-------------|-------------|-----------------|
| Manual SQL in production | No audit trail, unrepeatable | Always use migration files |
| Editing deployed migrations | Causes drift between environments | Create new migration instead |
| NOT NULL without default | **Fails** on a non-empty table — nothing fills existing rows | Add nullable, backfill, then `SET NOT NULL` |
| Inline index on large table | Blocks writes on PostgreSQL; MySQL builds eligible secondary indexes online but silently falls back when it cannot | PostgreSQL `CREATE INDEX CONCURRENTLY`; MySQL state `ALGORITHM=INPLACE, LOCK=NONE` explicitly so an ineligible change errors instead of locking |
| Schema + data in one migration | Hard to rollback, long transactions | Separate migrations |
| Dropping column before removing code | Application errors on missing column | Remove code first, drop column next deploy |
