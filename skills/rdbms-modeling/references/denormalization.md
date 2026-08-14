# Denormalization

Denormalization deliberately duplicates, merges, or pre-computes normalized data to improve read
performance or operational efficiency. It is a **physical-model** technique.

**Every denormalization needs four things: a measured problem, a named source of truth, a
synchronization mechanism, and a rebuild path.** Missing any one of them makes it a future
data-integrity bug rather than an optimization.

## Principles

- The logical model is normalized to 3NF. Denormalization never happens there.
- Apply it only at the physical-model stage.
- Judge on **actual queries and execution plans**, not expected performance.
- Try the simpler things first — indexes, query rewriting, batch fetching.
- Every duplicated value has exactly **one** source of truth. Name it.
- If the write and synchronization cost exceeds the read benefit, do not apply it.
- Denormalized data must be **regenerable** from its source.

## Methods

| Method | Example | Principal risk |
|---|---|---|
| Duplicated column | Customer name or region on the order | Divergence when the source changes |
| Stored computed value | Total, balance, count | Concurrent updates and calculation drift |
| Aggregate table | Daily revenue, per-customer statistics | Refresh lag and re-aggregation cost |
| Table merge | A 1:1 entity always read together | Wider rows, increased coupling |
| Snapshot | Product name and price at order time | PII retention and storage growth |
| Read model | Search, list, dashboard-specific structure | Eventual consistency; needs rebuild |
| Materialized result | Complex join or aggregate output | Refresh cost and staleness |
| Embedded JSON | Rarely-changing child data | Weakens constraints and partial search |

### Snapshots of Business Facts Are Not Denormalization

The price on an order line at the time of purchase is **not** a cached copy of the product price — it
is the transaction's own data. The product price may change tomorrow; the order's price must not.

Treat these as **business source data**, not performance duplication. They need no synchronization
mechanism, because they are not supposed to track the source. Getting this backwards produces a
"consistency fix" that corrupts historical orders.

Ask: if the source changes, should this value change too? **No → business fact.
Yes → denormalization**, and it needs all four requirements.

## Analysis Order

```text
identify the slow feature
→ collect the actual queries and their call frequency
→ analyse execution plans and I/O
→ check indexes, query shape, and N+1 patterns
→ apply what the normalized structure allows
→ select denormalization candidates
→ compare read benefit against write cost
→ decide synchronization and rebuild
→ load test, then apply
```

Required metrics:

- Call frequency and peak concurrency
- Mean, p95, p99 latency
- Rows scanned vs rows returned
- Join count and the size of what is joined
- Read/write ratio
- Data growth rate
- **Rows touched by one source change** — this is the write-amplification figure
- Storage and index growth
- Tolerable staleness
- Rebuild time after a failure

**With code but no runtime metrics, propose candidates — do not apply.** State exactly which figure
is missing.

## Try These First

Denormalization is near the end of the list, not the start:

1. Missing or wrong indexes
2. Removing unnecessary columns and joins
3. N+1 → batch fetching
4. Pagination and bounded result sets
5. Execution plan and statistics problems
6. Partitioning and partition pruning (see `partitioning.md`)
7. Application or distributed cache
8. Read replicas
9. Asynchronous analytics store or warehouse

Most "we need to denormalize" turns out to be item 1 or 3. Say which of these you checked.

## Synchronization

| Mechanism | Consistency | Use when |
|---|---|---|
| **Same transaction** | Strong | Balance, inventory, permissions — must match immediately |
| Event-driven | Eventual | Search, list, and statistics read models |
| CDC-driven | Eventual | External analytics and search systems |
| Scheduled batch | Bounded lag | Daily or hourly reports |
| ~~Trigger~~ | Strong | **Not this plugin's path** — see below |

**Same-transaction update is the default.** The write that changes the source also updates the
derived value, so the two cannot diverge.

**Triggers are not the mechanism here.** Keeping a derived business value correct is business logic,
and it runs on every write — so it falls outside the sanctioned use for database routines. See
`db-internal-routines.md`; the synchronization belongs in the transaction that changed the source,
where it is visible, testable, and appears in a stack trace.

Asynchronous mechanisms must handle **duplicate, reordered, and missing events** — so they require
idempotent application and a reprocessing path. An event-driven read model with no replay capability
is unrecoverable, which disqualifies it.

## Costs

Denormalization reduces joins, aggregation, round trips, and repeated calculation. It adds:

- **Write amplification** — one change updating several tables
- Longer transactions and wider lock scope
- Increased deadlock probability
- Larger tables and indexes
- Larger replication logs and backups
- Reduced cache efficiency (fewer useful rows per page)
- Ongoing consistency-check and repair work

Engine-specific:

- **MySQL / InnoDB** — a wider PK propagates into every secondary index; check the total storage
  effect before adding duplicated columns to a table with many indexes.
- **PostgreSQL** — frequently updating a duplicated column creates a new row version each time.
  Check the resulting bloat and `VACUUM` load; a hot denormalized counter can cost more in vacuum
  pressure than it saves in reads.

## Apply Only When All of These Hold

- A bottleneck is confirmed in **real production queries**
- Improvements available within the normalized structure cannot reach the target
- The read benefit exceeds the write amplification
- The source of truth for each duplicated value is unambiguous
- The acceptable consistency level is defined and written down
- A rebuild path and a consistency-check query exist
- A load test confirms the improvement

Seven conditions. If you cannot state all seven, the answer is not yet.

## Code Analysis Signals

| Pattern | Candidate |
|---|---|
| List APIs repeating the same multi-join | Read model or duplicated column |
| `SUM`, `COUNT`, `MAX` executed per request | Stored computed value or aggregate table |
| The same derived value recalculated repeatedly | Stored computed value |
| N+1 queries | **Fix the N+1 first** — usually not a denormalization case |
| Code walking several tables to sort or search | Read model |
| Always fetching the latest row from a state-history table | Current-state column on the entity |
| Read models updated by events or batch jobs | Existing denormalization — audit its rebuild path |
| A duplicated column updated on some write paths but not all | **Existing defect**, report it |

That last row is the highest-value finding: a duplicated column with an incomplete update path is
already producing wrong data.

Report: recommended method, expected effect, source of truth, synchronization mechanism, tolerable
staleness, rebuild path, and **confidence**.

## Integrity and Verification

Every denormalization ships with:

- A **consistency-check query** comparing the duplicate against its source
- A **recalculation or full-rebuild** command
- Tests covering concurrent modification and retry
- All-or-nothing behaviour: a mid-sequence failure rolls back or is reprocessed
- Before/after measurement under the **same** load
- Monitoring of staleness, mismatch count, and reprocessing failures

```sql
-- Consistency check: stored counter vs its source
SELECT o.order_id, o.item_count, count(i.order_item_id) AS actual
FROM orders o
LEFT JOIN order_item i ON i.order_id = o.order_id
GROUP BY o.order_id, o.item_count
HAVING o.item_count <> count(i.order_item_id);
```

A denormalization without this query is unverifiable, and an unverifiable duplicate diverges silently.

## Prohibited

- Duplicating a column to remove a join with no measurement
- Duplicated data with more than one source of truth
- An aggregate table with no named owner for its synchronization
- Computing in application memory and storing in a **separate** transaction
- An asynchronous read model with no rebuild path
- Duplicating personal data across tables unnecessarily — each copy is another retention and deletion
  obligation
- Removing a normalization rule without measuring first
- Replacing relationships and constraints with a general-purpose JSON column

## Final Policy

> Denormalization applies only at the physical-model stage, on top of a normalized logical model. The
> plugin analyses code and runtime metrics to confirm the bottleneck, and proposes the simpler
> improvements first. When it does recommend denormalization, it states the source of truth, the update
> transaction, the consistency level, the consistency-check query, the rebuild path, and the measured
> improvement.
