# Schema Design

## Primary Key Policy
- Use `GENERATED ALWAYS AS IDENTITY` (not SERIAL)
- UUID allowed for distributed or external-facing IDs

PostgreSQL stores rows in a **heap** — a PK creates a unique B-tree index but does not keep the
table ordered by it (`CLUSTER` reorders once and is not maintained). So a UUID PK costs far less
here than on InnoDB, but **not nothing**: index locality still applies to the PK's own B-tree, so
write-heavy tables should still prefer an ordered key.

| Situation | Use |
|---|---|
| Single-system table | `bigint GENERATED ALWAYS AS IDENTITY` |
| Distributed generation | native `uuid` with **UUIDv7** |
| Write-heavy | `IDENTITY`, or UUIDv7 — not UUIDv4 |
| Externally visible ID | UUID PK, or an integer PK plus a separate public UID |

**`uuidv7()` is built in from PostgreSQL 18.** This guideline's baseline is 16.7+, so on 16 and 17
generate v7 in the application or use a vetted extension. `gen_random_uuid()` returns **v4** — do
not reach for it when ordering is what you wanted.

Never use a raw timestamp as the sole PK (concurrent collisions, clock regression), and never
treat a UUID as an authentication or authorization token. Full criteria in
`rdbms-modeling/references/identifier-selection.md`.

```sql
CREATE TABLE app.user (
  user_id int GENERATED ALWAYS AS IDENTITY,
  email varchar(255) NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),  -- updated by application, not triggers
  CONSTRAINT user_pk_user_id PRIMARY KEY (user_id)
);

-- External-facing ID with UUID
CREATE TABLE app.user (
  user_id int GENERATED ALWAYS AS IDENTITY,
  public_id uuid NOT NULL DEFAULT gen_random_uuid(),
  email varchar(255) NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT user_pk_user_id PRIMARY KEY (user_id),
  CONSTRAINT uidx_user_public_id UNIQUE (public_id)
);
```

## Foreign Key Policy — No Physical FK Constraints

**Do not create `FOREIGN KEY` constraints in the physical model.** Referential integrity is
managed at the application layer with the relationship documented via `COMMENT`.

Why, on PostgreSQL specifically:

| Cost | What actually happens |
|---|---|
| **Extra I/O on every write** | Each child `INSERT`/`UPDATE` does a parent lookup the query never asked for; the cost is invisible in the statement and hard to attribute in `pg_stat_statements` |
| **Parent-row lock contention** | FK validation takes a `FOR KEY SHARE` lock on the parent row. It does not block ordinary parent reads, but it **does** conflict with parent-key updates and deletes — a hot parent row serializes unrelated child writes |
| **Cascades have unbounded scope** | `ON DELETE CASCADE` turns one statement into an arbitrarily large transaction: long-running locks, replication lag, and bloat from the mass delete |
| **No auto-index on the referencing side** | PostgreSQL indexes the *referenced* column (it must be unique) but **not** the referencing one. An unindexed child column makes every parent delete a sequential scan of the child — a common production surprise |
| **Partitioning and attach complexity** | FKs referencing a partitioned table are supported only from PG 12+, and `ATTACH PARTITION` must validate constraints, which takes stronger locks and lengthens the maintenance window |
| **Restore and bulk-load ordering** | `pg_restore` and backfills must order operations to satisfy constraints, or run with them disabled — meaning the guarantee is absent during the operations most likely to corrupt data |

The trade-off must be paid for, not ignored: **without a physical FK, orphan rows are possible.**
Every logical FK requires all four:

1. The reference documented in a `COMMENT` (`logical FK: schema.parent_table.parent_column`)
2. An index on the referencing column — needed for joins and parent-side lookups regardless
3. Application-level validation on the write path, with the **integrity owner named**
4. A scheduled orphan check, so violations surface instead of accumulating silently

```sql
-- Orphan detection — schedule one per logical FK
SELECT c.chat_history_id
FROM log.chat_history c
LEFT JOIN app.user u ON u.user_id = c.user_id
WHERE u.user_id IS NULL
LIMIT 100;
```

If several writers exist (batch jobs, admin tooling, external integrations), the integrity owner
must be a layer they all pass through — not one application's validation code. If no such layer
can exist, state that in the design rather than quietly relying on a constraint this policy
forbids.

```sql
CREATE TABLE app.chat_history (
  chat_history_id bigint GENERATED ALWAYS AS IDENTITY,
  user_id int NOT NULL,              -- logical FK: app.user.user_id
  conversation_id char(18) NOT NULL, -- logical FK: app.conversation_session
  user_message text NOT NULL,
  bot_response text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT chat_history_pk PRIMARY KEY (chat_history_id)
);

COMMENT ON COLUMN app.chat_history.user_id IS 'logical FK: app.user.user_id';
```

### Application-Level Referential Integrity

```python
async def create_chat_history(user_id: int, conversation_id: str, message: str, response: str):
    user = await db.execute_query(
        "SELECT user_id FROM app.user WHERE user_id = %(user_id)s AND is_active = true",
        {"user_id": user_id}
    )
    if not user:
        raise ValueError("User does not exist")

    result = await db.execute_command(
        """INSERT INTO log.chat_history (user_id, conversation_id, user_message, bot_response)
           VALUES (%(user_id)s, %(cid)s, %(msg)s, %(resp)s)
           RETURNING chat_history_id""",
        {"user_id": user_id, "cid": conversation_id, "msg": message, "resp": response}
    )
    return result
```

## Soft Delete Pattern

Tables requiring logical deletion standardize on the `is_active` column.

```sql
`is_active` boolean NOT NULL DEFAULT true
```

- Physical DELETE prohibited (ensures audit trail and recovery capability)
- Always include `WHERE is_active = true` in queries
- Use Partial Index to index only active records → reduces index size

```sql
-- Partial index: index only active users (excludes deleted users)
CREATE INDEX idx_user_active_email ON app.user (email) WHERE is_active = true;
```

> WARNING: Standalone B-tree index on `is_active` is ineffective due to low cardinality.
> Use PostgreSQL's Partial Index or composite indexes.

## Row Level Security (RLS)

```sql
ALTER TABLE app.orders ENABLE ROW LEVEL SECURITY;

-- Optimized RLS policy (wrap auth call in SELECT to avoid per-row evaluation)
-- Note: auth.uid() is project-specific — replace with platform-appropriate function (Supabase, etc.)
CREATE POLICY user_orders ON app.orders
  USING (
    (SELECT auth.uid()) = user_id
    AND (SELECT is_active FROM app.user WHERE user_id = (SELECT auth.uid()))
  );

-- Always index RLS policy columns
CREATE INDEX idx_orders_user_id ON app.orders (user_id);

REVOKE ALL ON SCHEMA public FROM public;
```

## JSONB Usage

```sql
CREATE TABLE app.user_setting (
  user_id int NOT NULL,
  setting_data jsonb NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT user_setting_pk PRIMARY KEY (user_id)
);

-- Query
SELECT setting_data->>'theme' AS theme FROM app.user_setting WHERE user_id = 1;

-- Partial update
UPDATE app.user_setting
SET setting_data = setting_data || '{"theme": "dark"}'::jsonb, updated_at = now()
WHERE user_id = 1;

-- Key existence check
SELECT * FROM app.user_setting WHERE setting_data ? 'theme';
```

## Table Creation Checklist
- [ ] PK uses `GENERATED ALWAYS AS IDENTITY` (not SERIAL)
- [ ] No physical FK constraints (logical only, documented with COMMENT)
- [ ] `timestamptz` used (never `timestamp`)
- [ ] `boolean` type used (never 'Y'/'N' strings)
- [ ] `created_at` included (required for all tables)
- [ ] `updated_at` included (except append-only log tables) — updated by application, not triggers
- [ ] Soft Delete tables use `is_active boolean DEFAULT true` + Partial Index
- [ ] No procedures/triggers/rules
- [ ] Schema separated by purpose (`app`, `log`, `ref`)
