# Views and Materialized Views

## Role Split

| Mechanism | Stores results | Purpose |
|---|---|---|
| **View** | No | Query reuse, security, interface abstraction |
| **PostgreSQL materialized view** | Yes | Accelerating repeated joins and aggregation |
| **MySQL summary table** | Yes | Stands in for MViews; incremental or batch refresh |

**A plain view is not a performance cache.** PostgreSQL rewrites a view reference into a query
against the base tables and then plans it by cost. MySQL either merges the view into the outer query
(`MERGE`) or materializes it into an internal temporary table (`TEMPTABLE`). Either way, the work is
still done — the view only moved where the SQL lives.

PostgreSQL materialized views store the result like a table and are queried directly. **MySQL 8.4 has
no native materialized view**, so the equivalent is a summary or aggregate table you maintain
yourself.

A materialized view or summary table is a **denormalization** — the requirements in
`denormalization.md` apply to it: a named source of truth, a synchronization mechanism, and a rebuild
path. Its scheduled refresh is a sanctioned operational routine under
`db-internal-routines.md` (Category 1).

## Choosing

**Use a plain view when:**

- The same joins and filters are reused by several features
- You need a stable read interface that hides table structure
- Per-user column or row access must be restricted
- The data must always be current
- The underlying query cost is already low enough

**Use a materialized view or summary table when:**

- Complex joins or aggregation repeat at high frequency
- A dashboard, statistics, or search read model is needed
- Some staleness is acceptable
- Repeated-read savings exceed the refresh cost
- Full regeneration from the source is possible

**Never use a materialized view as the source of truth** for real-time inventory, balances, or
permissions. Anything needing immediate consistency reads the base tables.

## Evidence Required

Schema, source and result row counts, cardinality, execution plans, call frequency, change volume,
tolerable staleness, expected refresh duration, and storage.

**With gaps, do not generate a `VIEW`, materialized view, or summary table** — output a conditional
recommendation naming the missing figure.

## Indexing a View

**You do not index a view.** Design so that the *final query executed through the view* uses the base
tables' indexes.

- Outer `WHERE` predicates must land on base columns directly
- Index the join keys, filter columns, and sort columns on the **base tables**
- A function or cast applied to an indexed column defeats it — consider an expression index
- List the needed keys and columns instead of `SELECT *`
- Put `ORDER BY` in the final query, not inside the view
- `EXPLAIN ANALYZE` the **actual usage query**, not the view definition
- For nested views, always check the final SQL and its plan

That last point is where most view performance problems live: each layer looks reasonable and the
composed query does something nobody intended.

## MySQL Views

Prefer a structure that can use the `MERGE` algorithm — the outer predicates combine with the base
table's, so existing B-tree indexes are usable.

Aggregate functions, window functions, `DISTINCT`, `UNION`, and `LIMIT` block merging and can force
materialization into an internal temporary table. MySQL may build a temporary index on that
intermediate result at execution time, but **you cannot define a permanent index on a view**.

```sql
CREATE ALGORITHM = MERGE VIEW active_order AS
SELECT purchase_order_id, customer_id, created_at, total_amount
FROM purchase_order
WHERE deleted_at IS NULL;

-- The index that actually matters lives on the base table
CREATE INDEX idx_purchase_order_active_customer_created
ON purchase_order (deleted_at, customer_id, created_at DESC);
```

An `ORDER BY` inside a view can be ignored when the outer query has its own. **Never assume a view
guarantees ordering.**

## PostgreSQL Views

PostgreSQL rewrites the view reference into a base-table query, then chooses a cost-based plan. So the
index policy for a plain view is simply the base tables' index policy.

- Build ordinary, partial, and expression indexes for the frequently used filters
- Use `security_barrier` **only** when security requires it
- A security view restricts predicate pushdown and limits statistics use — inspect its plan
  separately rather than assuming it matches the non-barrier version

## Indexing a PostgreSQL Materialized View

Two different index sets, serving two different queries:

| Indexes on | Speed up |
|---|---|
| The **base tables** | The refresh query |
| The **materialized view** | User queries against it |

Build the MView's indexes from the queries that read it — not from the source's access patterns.

```sql
CREATE MATERIALIZED VIEW customer_monthly_sales AS
SELECT customer_id,
       date_trunc('month', ordered_at) AS month,
       sum(total_amount) AS total_amount
FROM app.purchase_order
GROUP BY customer_id, date_trunc('month', ordered_at)
WITH NO DATA;

-- Required for REFRESH ... CONCURRENTLY (plain columns, covers all rows)
CREATE UNIQUE INDEX uq_customer_monthly_sales
ON customer_monthly_sales (customer_id, month);

CREATE INDEX idx_customer_monthly_sales_month
ON customer_monthly_sales (month DESC, total_amount DESC);
```

**`WITH NO DATA` leaves the MView unscannable** — any query against it errors until the first
`REFRESH`. Either populate it in the same migration or make the first refresh part of the deployment
step, and say which.

B-tree is not the only option: GIN, GiST, and trigram indexes can all be created on a materialized
view. An `ORDER BY` in the MView's defining query does **not** guarantee row order after a refresh —
use an outer `ORDER BY` with a matching index.

## Refresh

A plain `REFRESH MATERIALIZED VIEW` **replaces the contents entirely** and blocks readers for the
duration. `CONCURRENTLY` avoids blocking reads, at the cost of being slower.

```sql
REFRESH MATERIALIZED VIEW customer_monthly_sales;
REFRESH MATERIALIZED VIEW CONCURRENTLY customer_monthly_sales;
```

Constraints on `CONCURRENTLY`:

- Requires a **UNIQUE index on plain columns covering every row** — the index above exists for this
- **Cannot be used on a never-populated MView**, so the first refresh must be non-concurrent
- Only **one refresh at a time** per materialized view — overlapping schedules will queue or fail, so
  the job needs a lock or a skip-if-running guard

MySQL summary tables refresh by one of:

| Mechanism | Consistency |
|---|---|
| Same-transaction update | Strong |
| Event or CDC-driven `UPSERT` | Eventual |
| Scheduled batch re-aggregation | Bounded lag — statistics and reports |
| Build a staging table, then swap | Full rebuild |

Incremental refresh must handle **duplicate events, deletes, reordering, reprocessing, and the
last-processed position**. A delete that the incremental path ignores leaves a permanently wrong
aggregate — which is why the full-rebuild path is not optional.

## Prohibited

- Assuming a view improves performance merely by existing
- Treating a materialized view as always-current data
- Building a large materialized view for a low-frequency query
- Not measuring refresh duration and its locking impact
- No consistency check between source and result, and no rebuild procedure
- Nesting several views without checking the final execution plan
- Conflating MySQL's execution-time temporary materialization with a persistent materialized view

## Output

Recommend one of view / materialized view / summary table, and deliver with it: the base-table and
result indexes, the execution plans, data freshness, refresh interval, consistency mechanism, refresh
cost, failure recovery, and the rebuild procedure.
