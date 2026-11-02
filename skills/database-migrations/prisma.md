# Prisma (TypeScript/Node.js)

Install it in the project if it is not already a dependency, with `prisma` and `@prisma/client`
pinned to the **same stable version**: `npm install --save-dev prisma@<version>` and
`npm install @prisma/client@<version>`. Look the version up first (`npm view prisma versions`):
a `latest` tag can point at a pre-release, and the two packages' tags can disagree, so two bare
installs can mismatch. Run the pinned CLI through `npx prisma`; without a local install `npx`
fetches whatever `latest` is.

## Workflow

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

## Schema Example

```prisma
model Member {
  // Integer key by growth class: member is a bounded entity table, so Int is enough.
  // Do NOT reach for @default(cuid()) or @default(uuid()) here — a random string key on a
  // single-database entity table buys nothing and costs index locality. Use a UUID (v7) only
  // for distributed generation or an externally exposed identifier, as a separate column.
  memberId  Int      @id @default(autoincrement()) @map("member_id")
  email     String   @map("email")
  name      String?
  avatarUrl String?  @map("avatar_url")
  createdAt DateTime @default(now()) @map("created_at")
  updatedAt DateTime @updatedAt @map("updated_at")
  // a relation like `orders PurchaseOrder[]` needs a matching model — omitted here

  // Named constraint, per rdbms-naming. Prisma's bare `@unique` lets the engine pick the name.
  @@unique([email], map: "uq_member_email")
  @@map("member")
}
```

## Custom SQL Migration

For operations Prisma cannot express (concurrent indexes, data backfills):

```bash
# Create empty migration, then edit the SQL manually
npx prisma migrate dev --create-only --name add_member_last_login_index
```

```sql
-- migrations/20260815_add_member_last_login_index/migration.sql
-- Prisma cannot generate CONCURRENTLY, so we write it manually.
-- (Not an index on `email` — the model already declares `email @unique`, which
--  creates a unique index; a second one would be pure write cost.)
CREATE INDEX CONCURRENTLY idx_member_last_login
-- No IF NOT EXISTS here: a failed CONCURRENTLY build leaves an *invalid* index behind, and
-- IF NOT EXISTS would skip it and report success while the index stays unusable. Instead
-- pre-flight: SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;  -- then DROP and rebuild
  ON member (last_login_at);
```
