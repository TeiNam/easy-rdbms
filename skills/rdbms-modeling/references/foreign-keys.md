# Foreign Keys — Engine Differences and the Index Consequence

The *meaning* of a foreign key is the same on both engines. The implementation and operational
behaviour are not, and the differences change what you must do by hand.

## Engine Differences

| Aspect | MySQL / InnoDB | PostgreSQL |
|---|---|---|
| **Child (referencing) index** | **Auto-created** if no index already leads with the FK column | **Never auto-created** |
| **Parent (referenced) target** | Historically permitted a non-unique index; that is deprecated | **PK or UNIQUE only** |
| **Check timing** | Immediate | Immediate, or deferrable to end of transaction |
| **Adding an FK to a large table** | Validates immediately | Can add `NOT VALID`, then `VALIDATE CONSTRAINT` separately |
| **`NO ACTION` vs `RESTRICT`** | Effectively identical — both check immediately | `NO ACTION` can defer to end of transaction; `RESTRICT` blocks immediately |

## The Index Consequence for This Plugin's Policy

This plugin does not create physical FK constraints (see the Hard Rule in `SKILL.md`). That has a
direct, easily-missed consequence on MySQL:

> **InnoDB's automatic child index comes *from* the FK constraint. Remove the constraint and the
> automatic index goes with it.**

So under a logical-FK policy, an explicit index on the referencing column is **mandatory on both
engines** — for different reasons:

- **MySQL**: the index InnoDB would have created for you no longer exists. Nothing will warn you.
- **PostgreSQL**: it was never created automatically, FK or not. A missing child index makes every
  parent delete or key update a sequential scan of the child table.

Do not create a redundant index. If a composite index already **leads** with the referencing
column — `(customer_id, created_at)` — that index already serves the lookup. A separate
`(customer_id)` index would be duplicate write cost for no read benefit.

```sql
-- Needed unless an existing index already leads with customer_id
CREATE INDEX idx_orders_customer_id ON orders (customer_id);
```

## Reference Target Rule (Applies to Logical FKs Too)

**A reference must target a PK or a UNIQUE column.** PostgreSQL enforces this; MySQL historically
allowed a non-unique target and that behaviour is deprecated.

The rule matters just as much for a *logical* FK, where nothing enforces it: a documented reference
to a non-unique column is ambiguous by construction — "which parent row?" has no single answer, and
the orphan-detection query cannot be written correctly. Treat a logical reference to a non-unique
column as a modeling error, not a shortcut.

## Cost of a UUID as the Referenced Key

A UUID PK is perfectly sound for referential integrity. The cost is repetition: **16 bytes in every
child row plus 16 bytes in every index on that child column**, versus 8 for `bigint`. At scale that
is storage and, more importantly, buffer-pool/cache pressure.

On InnoDB the effect compounds — the PK value is also copied into every secondary index of the
parent table. Weigh this before choosing a UUID PK for a table with many high-volume children;
see `identifier-selection.md`.

## Exception Path: When a Physical FK Must Exist

Sometimes the constraint is not yours to remove — an inherited schema, an organisational mandate, or
a table written by tools you do not control. When a physical FK exists or must be added, these rules
apply:

1. **Parent target is PK or UNIQUE.** Never a non-unique index.
2. **Create the child index explicitly** on PostgreSQL. On MySQL, verify what InnoDB auto-created
   rather than assuming it matches your query needs.
3. **`CASCADE` only where the lifecycle is genuinely dependent** — order → order_item. Never across
   an aggregate boundary, and never on a parent with high fan-out: one statement becomes an
   unbounded transaction.
4. **Default to `NOT DEFERRABLE`.** Deferred constraints are a PostgreSQL-only feature; reach for
   them only to resolve a circular reference inside a single transaction, and mark the schema as
   non-portable when you do.
5. **Adding to a large existing table**: on PostgreSQL, add `NOT VALID` first, then
   `VALIDATE CONSTRAINT` in a separate step so the validation scan does not hold a strong lock for
   the whole operation. MySQL validates immediately — plan a window, and see `database-migrations`.

```sql
-- PostgreSQL: two-step add on a large table
ALTER TABLE orders
  ADD CONSTRAINT fk_orders_customer
  FOREIGN KEY (customer_id) REFERENCES customer (customer_id)
  ON DELETE RESTRICT
  NOT VALID;

ALTER TABLE orders VALIDATE CONSTRAINT fk_orders_customer;
```

Note the semantic difference when choosing the action: on PostgreSQL `RESTRICT` blocks immediately
while `NO ACTION` can defer to the end of the transaction; on MySQL InnoDB the two are effectively
the same. A schema relying on that difference is not portable.

Whichever path applies, the four compensating controls from the Hard Rule still earn their keep — a
physical FK does not remove the need for a named integrity owner, and it does not help during bulk
loads run with checks disabled.
