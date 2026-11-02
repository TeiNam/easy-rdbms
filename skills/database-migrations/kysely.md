# Kysely (TypeScript/Node.js)

Install it in the project if it is not already a dependency — `npm install kysely` and
`npm install --save-dev kysely-ctl`. The `kysely-ctl` package installs a binary named `kysely`;
run the pinned version through `npx kysely`.

## Contents

- Workflow (kysely-ctl)
- Migration File
- Programmatic Migrator

## Workflow (kysely-ctl)

```bash
# kysely-ctl's subcommand form has changed across versions (space vs colon, e.g.
# `migrate latest` vs `migrate:latest`). Confirm with `npx kysely --help` for your version.

# Initialize config file (kysely.config.ts)
npx kysely init

# Create a new migration file
npx kysely migrate make add_member_avatar

# Apply all pending migrations
npx kysely migrate latest

# Rollback last migration
npx kysely migrate down

# Show migration status
npx kysely migrate list
```

## Migration File

```typescript
// migrations/2024_01_15_001_create_member_profile.ts
import { type Kysely, sql } from 'kysely'

// IMPORTANT: Always use Kysely<any>, not your typed DB interface.
// Migrations are frozen in time and must not depend on current schema types.
export async function up(db: Kysely<any>): Promise<void> {
  await db.schema
    .createTable('member_profile')
    // member_profile is a bounded entity table, so 'integer' -- 'bigint' is for event/log
    // tables whose rows grow as rate x time.
    .addColumn('member_profile_id', 'integer', (col) =>
      col.generatedAlwaysAsIdentity().primaryKey())
    .addColumn('email', 'text', (col) => col.notNull())
    .addColumn('avatar_url', 'text')
    .addColumn('created_at', 'timestamptz', (col) =>
      col.defaultTo(sql`now()`).notNull()
    )
    // Named, per rdbms-naming — .unique() on the column would let PostgreSQL pick the name
    .addUniqueConstraint('uq_member_profile_email', ['email'])
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

## Programmatic Migrator

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
