# golang-migrate (Go)

The `migrate` CLI is a separate binary from the Go library, built with the drivers you name.
Install it with `go install -tags 'postgres mysql' github.com/golang-migrate/migrate/v4/cmd/migrate@latest`
(keep only the tags you need) or `brew install golang-migrate` on macOS, then confirm with
`migrate -version`.

## Workflow

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

## Migration Files

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
