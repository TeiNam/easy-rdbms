# Foreign Keys — Engine-Split Policy

The *meaning* of a foreign key is the same on both engines. The implementation and operational
behaviour are not, and the difference is large enough that the policy splits by engine.

| | MySQL / InnoDB | PostgreSQL |
|---|---|---|
| **Physical `FOREIGN KEY`** | **Not created** | **Allowed by default — created when the conditions below are met** |
| Referential integrity owner | Application | The database, once the constraint is valid |
| Referencing-column index | **Mandatory, by hand** | **Created unless an existing index already leads with the column** |

## Engine Differences That Drive the Split

| Aspect | MySQL / InnoDB | PostgreSQL |
|---|---|---|
| **Child (referencing) index** | Auto-created by the FK if no index leads with that column | **Never auto-created** |
| **Parent (referenced) target** | Historically permitted a non-unique index; deprecated | **PK or UNIQUE only** |
| **Check timing** | Immediate | Immediate, or deferrable to end of transaction |
| **Adding an FK to a large table** | Validates immediately — needs a window | `NOT VALID`, then `VALIDATE CONSTRAINT` as a separate step |
| **`NO ACTION` vs `RESTRICT`** | Effectively identical; both check immediately | `NO ACTION` can defer to end of transaction; `RESTRICT` blocks immediately |
| **Partitioned tables** | InnoDB **cannot** have an FK on a partitioned table, either direction | Supported (referencing a partitioned table from PG 12+); `ATTACH PARTITION` validates, taking stronger locks |

The operational rows (write I/O, parent-row locks, online-DDL tooling) justify the MySQL policy on
their own; the partitioning row seals it — log and history tables are the usual partitioning
candidates, and on InnoDB an FK today is a blocked partition tomorrow.

## MySQL / InnoDB — Logical FK Only

**Do not create `FOREIGN KEY` constraints.** Referential integrity is owned by the application and
the relationship is documented in a `COMMENT`.

Why, beyond partitioning: an FK adds a parent-index lookup to every child write that the statement
never shows and slow-query analysis cannot attribute; FK checks take shared locks on the parent row —
child writes do not block each other, but any update or delete of a hot parent's key (a tenant, a
category, a config row) blocks, and is blocked by, **every** in-flight child write, surfacing as
hard-to-diagnose stalls; `ON DELETE CASCADE` gives one statement unbounded transaction scope; and
`pt-online-schema-change` / `gh-ost` need special handling for FKs, turning routine maintenance into
a downtime negotiation.

### The Index Consequence — Do Not Miss This

InnoDB auto-creates a child index **when the FK is created** (if none leads with that column).
**Dropping the FK does not drop that index** — it remains, but under an auto-generated name that
reads like leftovers, and the next "unused index cleanup" is likely to remove it.

So on MySQL the referencing-column index is **deliberate and manual**: under this policy no FK ever
creates one for you, and on an inherited schema, after dropping an FK, run `SHOW INDEX` and keep or
rename the auto-created index explicitly. An unindexed child column means a full scan of the child
table on every parent-side lookup and join.

```sql
-- Mandatory unless an existing composite index already LEADS with customer_id
CREATE INDEX idx_orders_customer_id ON orders (customer_id);
```

Do not create a redundant one. If `idx_orders_customer_created (customer_id, created_at)` exists, it
already serves the lookup — a separate `(customer_id)` index is write cost for no read benefit.

### Four Compensating Controls

Because nothing enforces the reference, every logical FK carries all four:

1. The reference in a `COMMENT` — `logical FK: parent_table.parent_column`
2. **The index above** — mandatory
3. A named **integrity owner** — which service or module guarantees it on the write path
4. A scheduled orphan-detection query

```sql
SELECT c.chat_history_id
FROM chat_history c
LEFT JOIN user u ON u.user_id = c.user_id
WHERE u.user_id IS NULL
LIMIT 100;
```

If several writers exist (batch, admin tooling, external integrations), the integrity owner must be
a shared layer they all pass through — not one application's validation code. If no such layer can
exist, say so in the design rather than quietly adding the constraint back.

## PostgreSQL — Allowed by Default, Created When Conditions Are Met

PostgreSQL stores rows in a heap, has no clustering-index penalty, supports FKs on partitioned
tables, and can add a constraint to a large table without a long exclusive validation. The costs
that make FKs untenable on InnoDB are materially smaller here, so **the default posture is to allow
them.**

"Allowed by default" is not "always create". Create the constraint when **all** of these hold —
each is a gate, and a failing gate means either fix it first or fall back to a logical FK with the
four compensating controls.

| # | Condition | If it fails |
|---|---|---|
| 1 | Parent column is a **PK or UNIQUE** | Fix the parent model. A non-unique target is a modeling error, not a constraint option |
| 2 | Referencing column is **indexed** — create it unless an existing index already leads with that column | Create the index in the same migration. Without it, every parent delete or key update sequentially scans the child |
| 3 | No **redundant** index introduced | Reuse the existing leading-column index; do not add a duplicate |
| 4 | If `CASCADE`: the child's **lifecycle is genuinely dependent** on the parent (order → order_item) | Use `RESTRICT` and delete explicitly. Never cascade across an aggregate boundary or from a high-fan-out parent |
| 5 | `NOT DEFERRABLE` unless a **circular reference must resolve inside one transaction** | Keep it non-deferrable. Deferred constraints are PostgreSQL-only — mark the schema non-portable if you use them |
| 6 | On a **large existing table**: added `NOT VALID`, then `VALIDATE CONSTRAINT` separately | Do the two-step. A single-step add holds a strong lock for the whole validation scan |

```sql
-- Condition 2 first, in the same migration
CREATE INDEX idx_orders_customer_id ON app.orders (customer_id);

ALTER TABLE app.orders
  ADD CONSTRAINT fk_orders_customer
  FOREIGN KEY (customer_id) REFERENCES app.customer (customer_id)
  ON DELETE RESTRICT;
```

```sql
-- Condition 6: two-step add on a large existing table
ALTER TABLE app.orders
  ADD CONSTRAINT fk_orders_customer
  FOREIGN KEY (customer_id) REFERENCES app.customer (customer_id)
  ON DELETE RESTRICT
  NOT VALID;

ALTER TABLE app.orders VALIDATE CONSTRAINT fk_orders_customer;
```

### Costs That Remain

Allowing FKs does not make them free. These still apply and are reasons to choose a logical FK for a
specific relationship:

- **Extra write I/O** — each child write does a parent lookup the statement does not show
- **Parent-row lock contention** — validation takes a `FOR KEY SHARE` lock. Child writes are
  mutually compatible, but a parent-key update or delete conflicts with all of them — on a hot
  parent row the two sides stall each other
- **Cascade scope** — `ON DELETE CASCADE` on a high-fan-out parent turns one statement into a long
  transaction with lock and bloat consequences
- **Bulk load and restore ordering** — `pg_restore` and backfills must order operations or run with
  constraints disabled, meaning the guarantee is absent during exactly the operations most likely to
  corrupt data

When a relationship has a very hot parent row or extreme write volume, dropping to a logical FK with
the four compensating controls is a legitimate choice. Say why.

### A `NOT VALID` Constraint Is Not a Guarantee

A constraint left `NOT VALID` prevents *new* violations but never checked the existing rows. Until
`VALIDATE CONSTRAINT` succeeds, treat the reference as a logical FK and run the orphan query.

## Reference Target Rule Applies to Logical FKs Too

**A reference must target a PK or UNIQUE column** — enforced by PostgreSQL, deprecated-but-permitted
historically on MySQL, and equally required for a *logical* FK where nothing enforces it. A
documented reference to a non-unique column is ambiguous by construction: "which parent row?" has no
single answer, and the orphan-detection query cannot be written correctly. Treat it as a modeling
error.

## Cost of a UUID as the Referenced Key

A UUID PK is sound for referential integrity. The cost is repetition: **16 bytes in every child row
plus 16 bytes in every index on that child column**, versus 8 for `bigint`. At scale that is storage
and, more importantly, cache pressure. On InnoDB it compounds — the PK value is also copied into
every secondary index of the parent. Weigh this before choosing a UUID PK for a table with many
high-volume children; see `identifier-selection.md`.

## Inherited MySQL Schemas

When an InnoDB schema you did not author already has FK constraints, do not rip them out
opportunistically. Dropping the FK leaves its auto-created child index in place — but under an
auto-generated name that invites deletion by cleanup jobs. Plan it: drop the constraint, verify the
index with `SHOW INDEX` and rename it to the `idx_` convention (or create the explicit index if a
suitable one is missing), then add the remaining compensating controls.
