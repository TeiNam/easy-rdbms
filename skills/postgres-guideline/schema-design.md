# Schema Design

## Primary Key Policy
- Use `GENERATED ALWAYS AS IDENTITY` (not SERIAL)
- UUID allowed for distributed or external-facing IDs

PostgreSQL stores rows in a **heap** — a PK creates a unique B-tree index but does not keep the
table ordered by it (`CLUSTER` reorders once and is not maintained). So a UUID PK costs far less
here than on InnoDB, but **not nothing**: index locality still applies to the PK's own B-tree, so
write-heavy tables should still prefer an ordered key.

**Integer width is a decision you cannot cheaply revisit, so size it from what makes the row count
grow.** `ALTER TABLE … ALTER COLUMN id TYPE bigint` **rewrites the entire table** while holding
`ACCESS EXCLUSIVE` — no reads, no writes — and rebuilds every index on the column. Any referencing
column has to change in lockstep, and under a logical-FK policy those are plain columns needing their
own migrations. The workaround is a multi-week expand-contract project with an application change in
the middle (`database-migrations` has the procedure).

- An **entity** table — one row per real thing — is bounded by the real world. `member` cannot exceed
  the human population, and `int` reaches 2.1 billion, so `int` is a defensible choice here. Record
  what bounds it.
- An **event/log** table is bounded by nothing: rows = insert rate × elapsed time. PostgreSQL
  `integer` is **signed**, so at 10,000 inserts/s it is exhausted in about **2.5 days** — MySQL's
  `int unsigned` buys ~5 days from the same 4 bytes, and PostgreSQL has no `UNSIGNED`. Because a
  sequence never reuses values, deleting old rows or dropping old partitions reclaims storage but
  **not** ID range. IoT telemetry, audit trails, message history, access logs, metering, outbox —
  `bigint` from the start.

| Situation | Use |
|---|---|
| Event/log/IoT table | **`bigint GENERATED ALWAYS AS IDENTITY`** — no exceptions |
| Single-system entity table | `int` when the entity count is bounded by something real (record what); otherwise `bigint` |
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
-- `user` is reserved in PostgreSQL — the table is named `member` per rdbms-naming.
-- public_id is the externally visible UID; omit it when nothing outside sees the row.
CREATE TABLE app.member (
  member_id  int GENERATED ALWAYS AS IDENTITY,  -- entity table: bounded by real user count
  public_id  uuid NOT NULL,          -- UUIDv7 from the app (uuidv7() on PG 18+)
  email      text NOT NULL,          -- text, not varchar(n); length rules belong in CHECK
  is_active  boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),  -- set by the application, not a trigger
  CONSTRAINT pk_member PRIMARY KEY (member_id),
  CONSTRAINT uq_member_public_id UNIQUE (public_id),
  CONSTRAINT uq_member_email UNIQUE (email)
);
```

## Foreign Key Policy — Allowed by Default, Created When Conditions Are Met

Physical `FOREIGN KEY` constraints **are permitted on PostgreSQL**. This differs from the MySQL
guideline, which prohibits them — PostgreSQL has no clustering-index penalty, supports FKs on
partitioned tables, and can validate a large table without holding a long exclusive lock.

**"Allowed by default" is not "always create."** Create the constraint when all six conditions hold.
A failing condition means fix it first, or fall back to a logical FK with the compensating controls
below and state why.

| # | Condition | If it fails |
|---|---|---|
| 1 | Parent column is a **PK or UNIQUE** | Fix the parent model — a non-unique target is a modeling error |
| 2 | Referencing column is **indexed** (PostgreSQL never auto-creates this) | Create the index in the same migration, or every parent delete/key update sequentially scans the child |
| 3 | No **redundant** index introduced | Reuse an index that already leads with the column |
| 4 | If `CASCADE`: the child's **lifecycle genuinely depends** on the parent (order → purchase_order_item) | Use `RESTRICT` and delete explicitly. Never cascade across an aggregate boundary or from a high-fan-out parent |
| 5 | **`NOT DEFERRABLE`** unless a circular reference must resolve in one transaction | Keep it non-deferrable. Deferred constraints are PostgreSQL-only — mark the schema non-portable if used |
| 6 | Large existing table: **`NOT VALID`** first, then `VALIDATE CONSTRAINT` | Do the two-step; a single-step add holds a strong lock for the whole validation scan |

```sql
-- Condition 2 first, in the same migration
CREATE INDEX idx_purchase_order_customer_id ON app.purchase_order (customer_id);

ALTER TABLE app.purchase_order
  ADD CONSTRAINT fk_purchase_order_customer
  FOREIGN KEY (customer_id) REFERENCES app.customer (customer_id)
  ON DELETE RESTRICT;
```

```sql
-- Condition 6: two-step add on a large existing table
ALTER TABLE app.purchase_order
  ADD CONSTRAINT fk_purchase_order_customer
  FOREIGN KEY (customer_id) REFERENCES app.customer (customer_id)
  ON DELETE RESTRICT
  NOT VALID;

ALTER TABLE app.purchase_order VALIDATE CONSTRAINT fk_purchase_order_customer;
```

`RESTRICT` blocks immediately and can never be deferred. `NO ACTION` is checked after the statement's
action and *can* be deferred — but **only when the constraint is `DEFERRABLE` and actually deferred**.
Under this guideline's `NOT DEFERRABLE` default the two give the same result for ordinary deletes;
they are not defined as identical, and documented edge cases differ (notably some `ON UPDATE`
paths), so do not treat them as interchangeable in a design that leans on the timing. On MySQL InnoDB they are always identical, so a schema relying on
the difference is not portable.

### Costs That Remain

Permitting FKs does not make them free. Each of these is a reason to choose a logical FK for a
*specific* relationship:

- **Extra write I/O** — every child write does a parent lookup the statement never shows, hard to
  attribute in `pg_stat_statements`
- **Parent-row lock contention** — validation takes a `FOR KEY SHARE` lock. Child writes are
  mutually compatible, but a parent-key update or delete conflicts with all of them — on a hot
  parent row the two sides stall each other
- **Cascade scope** — `ON DELETE CASCADE` on a high-fan-out parent turns one statement into a long
  transaction, with lock and bloat consequences
- **Restore and bulk-load ordering** — `pg_restore` and backfills must order operations or run with
  constraints disabled, so the guarantee is absent during the operations most likely to corrupt data

### When Using a Logical FK Instead

A relationship left as a logical FK — a failed condition, a very hot parent, or extreme write volume
— carries all four compensating controls:

1. The reference documented in a `COMMENT` (`logical FK: schema.parent_table.parent_column`)
2. An index on the referencing column
3. Application-level validation, with the **integrity owner named**
4. A scheduled orphan check

```sql
-- Orphan detection — schedule one per logical FK
SELECT c.chat_history_id
FROM log.chat_history c
LEFT JOIN app.member u ON u.member_id = c.member_id
WHERE u.member_id IS NULL
LIMIT 100;
```

A constraint left `NOT VALID` never checked the existing rows. Until `VALIDATE CONSTRAINT` succeeds,
treat the reference as a logical FK and keep running the orphan query.

If several writers exist (batch jobs, admin tooling, external integrations), the integrity owner must
be a layer they all pass through — not one application's validation code.

```sql
CREATE TABLE log.chat_history (
  chat_history_id bigint GENERATED ALWAYS AS IDENTITY,  -- event table: rows = rate x time, unbounded
  member_id int NOT NULL,            -- logical FK: app.member.member_id
  conversation_id char(18) NOT NULL, -- logical FK: app.conversation_session.conversation_id
  user_message text NOT NULL,
  bot_response text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_chat_history PRIMARY KEY (chat_history_id)
);

-- Control 1: document both references
COMMENT ON COLUMN log.chat_history.member_id IS
  'logical FK: app.member.member_id; integrity owner: chat-service ChatWriter';
COMMENT ON COLUMN log.chat_history.conversation_id IS
  'logical FK: app.conversation_session.conversation_id; integrity owner: chat-service ChatWriter';

-- Control 2: index every referencing column (PostgreSQL never auto-creates these)
CREATE INDEX idx_chat_history_member_id ON log.chat_history (member_id);
CREATE INDEX idx_chat_history_conversation_id ON log.chat_history (conversation_id);

-- Control 4: one scheduled orphan query per reference
-- SELECT c.chat_history_id FROM log.chat_history c
-- LEFT JOIN app.member m ON m.member_id = c.member_id WHERE m.member_id IS NULL LIMIT 100;
-- SELECT c.chat_history_id FROM log.chat_history c
-- LEFT JOIN app.conversation_session s ON s.conversation_id = c.conversation_id
-- WHERE s.conversation_id IS NULL LIMIT 100;
```

### Application-Level Referential Integrity

```python
async def create_chat_history(pool, member_id: int, conversation_id: str,
                              message: str, response: str) -> int:
    """The parent locks and the insert must share ONE transaction — otherwise the locks are
    released before the insert and the checks bought nothing. Validate EVERY logical
    reference: conversation_id needs the same treatment as member_id."""
    async with pool.connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT member_id FROM app.member"
                    " WHERE member_id = %(member_id)s AND is_active = true FOR UPDATE",
                    {"member_id": member_id},
                )
                if await cur.fetchone() is None:
                    raise ValueError("member does not exist")

                await cur.execute(
                    "SELECT conversation_id FROM app.conversation_session"
                    " WHERE conversation_id = %(cid)s FOR UPDATE",
                    {"cid": conversation_id},
                )
                if await cur.fetchone() is None:
                    raise ValueError("conversation session does not exist")

                await cur.execute(
                    "INSERT INTO log.chat_history"
                    " (member_id, conversation_id, user_message, bot_response)"
                    " VALUES (%(member_id)s, %(cid)s, %(msg)s, %(resp)s)"
                    " RETURNING chat_history_id",
                    {"member_id": member_id, "cid": conversation_id,
                     "msg": message, "resp": response},
                )
                row = await cur.fetchone()
                return row["chat_history_id"]
```

## Soft Delete Pattern

Tables requiring logical deletion standardize on the `is_active` column.

```sql
is_active boolean NOT NULL DEFAULT true
```

- Physical DELETE prohibited (recoverable logical deletion). **This is not an audit trail** — it
  records only the current flag, not who deleted it, when, or why. An audit requirement needs a
  history mechanism (`rdbms-modeling/references/history-entities.md`)
- Always include `WHERE is_active = true` in queries
- Use Partial Index to index only active records → reduces index size

```sql
-- Partial index: index only active member (excludes deleted member)
CREATE INDEX idx_member_active_email ON app.member (email) WHERE is_active = true;
```

> WARNING: a standalone B-tree index on `is_active` is *usually* poor value — but low cardinality
> alone does not decide it. If the queried value is rare (0.5% inactive, and you query those), the
> index is selective for that value. Judge by skew and the plan; the partial index above serves the
> common case either way.

## Row Level Security (RLS)

**RLS only enforces anything if the runtime role is subject to it.** Superusers and roles with
`BYPASSRLS` bypass policies unconditionally, and the **table owner** bypasses them unless
`FORCE ROW LEVEL SECURITY` is set. Run the application as a non-owner
`NOSUPERUSER NOBYPASSRLS` role, or the policies below are decoration.

```sql
-- The runtime role must not own the table and must not bypass RLS
CREATE ROLE app_runtime LOGIN NOSUPERUSER NOBYPASSRLS;

ALTER TABLE app.purchase_order ENABLE ROW LEVEL SECURITY;
-- Needed only if the owner itself must obey the policies
ALTER TABLE app.purchase_order FORCE ROW LEVEL SECURITY;

-- Wrap the session lookup in SELECT so it evaluates once per query, not once per row.
-- current_setting() is engine-native; on a platform like Supabase substitute its own
-- auth.uid() — and make sure the types match the key you compare against.
CREATE POLICY member_orders ON app.purchase_order
  USING (
    member_id = (SELECT current_setting('app.current_member_id', true))::int
  );

-- Always index RLS policy columns
-- Always index the column an RLS policy filters on
CREATE INDEX idx_purchase_order_member_id ON app.purchase_order (member_id);

REVOKE ALL ON SCHEMA public FROM public;
```

## JSONB Usage

```sql
CREATE TABLE app.member_setting (
  member_id int NOT NULL,      -- logical FK: app.member.member_id (type matches parent)
  setting_data jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_member_setting PRIMARY KEY (member_id)
);
COMMENT ON COLUMN app.member_setting.member_id IS
  'logical FK -> app.member.member_id; owner: account-service; orphan check: nightly job q-142';

-- Query
SELECT setting_data->>'theme' AS theme FROM app.member_setting WHERE member_id = 1;

-- Partial update
UPDATE app.member_setting
SET setting_data = setting_data || '{"theme": "dark"}'::jsonb, updated_at = now()
WHERE member_id = 1;

-- Key existence check
-- Filtering ON a JSON key means that key is a queried field — per the JSON policy it belongs in a
-- real column (or a generated column + index). This example shows the operator, not a design to copy.
SELECT member_id, setting_data FROM app.member_setting WHERE setting_data ? 'theme';
```

## Table Creation Checklist
- [ ] PK uses `GENERATED ALWAYS AS IDENTITY` (not SERIAL)
- [ ] FK: physical constraint only where all six conditions hold (PK/UNIQUE target, referencing
      column indexed, no redundant index, `CASCADE` justified by lifecycle dependency,
      `NOT DEFERRABLE`, `NOT VALID`+`VALIDATE` on large tables)
- [ ] Any relationship left as a logical FK carries all four compensating controls (`COMMENT`,
      index, named integrity owner, scheduled orphan check)
- [ ] No constraint left `NOT VALID` without a validation step — it never checked existing rows
- [ ] `timestamptz` for instants and audit times (plain `timestamp` only for genuine wall-clock
      values with no instant meaning — e.g. a recurring local opening time)
- [ ] `boolean` type used (never 'Y'/'N' strings)
- [ ] `created_at` included (required for all tables)
- [ ] `updated_at` included (except append-only log tables) — updated by application, not triggers
- [ ] Soft Delete tables use `is_active boolean DEFAULT true` + Partial Index
- [ ] No procedures/triggers/rules carrying **business logic** (the operational-utility and
      audit-trigger exceptions are in `rdbms-modeling/references/db-internal-routines.md`; `RULE`
      stays fully prohibited)
- [ ] Schema separated by purpose (`app`, `log`, `ref`)
