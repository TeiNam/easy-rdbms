---
name: rdbms-review
description: >
  Review existing SQL, schemas, and migrations for performance, correctness, security, and
  concurrency problems on MySQL, PostgreSQL, and SQLite. Triggers: review this schema, review
  this query, SQLite PRAGMA, STRICT table, review this migration, why is this query slow, is
  this index right, missing index, seq scan, full table scan, N+1 query, EXPLAIN output,
  EXPLAIN ANALYZE, deadlock, lock wait timeout, table bloat, vacuum, slow query log, connection
  pool exhausted, too many connections, RLS policy review, GRANT audit, database security
  review, duplicate tables, over-generalized schema, EAV anti-pattern, nullable everything,
  subtype vs status, type column holding a state, missing role table, foreign key constraint,
  ON DELETE CASCADE, orphan rows, referential integrity, partition pruning, partitions not
  pruned, MAXVALUE partition, default partition filling up, partition key missing from WHERE,
  history table, audit table, audit trail, versioning, temporal table, valid_from valid_to,
  event sourcing, point-in-time query, stored procedure, trigger audit, database event,
  denormalized column out of sync, aggregate table stale, write amplification, unused index,
  redundant index, invisible index, covering index, heap fetches, index only scan, filesort,
  LIKE wildcard slow, full text search, FULLTEXT ngram, pg_trgm, tsvector, search engine
  migration, view performance, nested views, materialized view, REFRESH MATERIALIZED VIEW,
  CONCURRENTLY, summary table stale, IN subquery slow, DEPENDENT SUBQUERY, Index Merge, OR
  condition slow, deep pagination, OFFSET slow, is this schema safe to deploy.
---

# RDBMS Review

Review database code that already exists — MySQL, PostgreSQL, or SQLite. For designing something new, use `rdbms-modeling`
instead; for choosing the engine, `db-select`.

## When to Activate

- Reviewing SQL, DDL, or a migration before it merges or deploys
- Investigating a slow query or a lock/deadlock incident
- Auditing schema or grants for security
- Checking whether an index earns its cost

## Step 0 — Establish the Engine and Version

Every finding below depends on it. Never review a query without knowing what will run it.

```sql
-- PostgreSQL
SELECT version();

-- MySQL / MariaDB
SELECT VERSION();
SHOW VARIABLES LIKE 'version_comment';
```

```sql
-- SQLite
SELECT sqlite_version();
PRAGMA foreign_keys;    -- 0 means every REFERENCES clause in the schema is decorative
```

Then load the matching skill: `postgres-guideline`, `mysql-guideline`, or `sqlite-guideline`.
On SQLite, check the PRAGMA baseline first — `foreign_keys` off and missing `STRICT` are the
two highest-yield findings there. If the engine cannot be determined, say so and scope the
review to engine-neutral findings only — do not guess a dialect.

## Diagnostics

### PostgreSQL

```sql
-- Slowest statements (requires pg_stat_statements)
SELECT query, mean_exec_time, calls
FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;

-- Largest tables
SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) AS size
FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 20;

-- Unused indexes (write cost with no read benefit)
SELECT indexrelname, idx_scan, idx_tup_read
FROM pg_stat_user_indexes ORDER BY idx_scan ASC LIMIT 20;

-- Bloat / vacuum health
SELECT relname, n_dead_tup, last_vacuum, last_autovacuum
FROM pg_stat_user_tables WHERE n_dead_tup > 1000 ORDER BY n_dead_tup DESC;
```

### MySQL

```sql
SHOW FULL PROCESSLIST;
SHOW ENGINE INNODB STATUS\G;           -- capture immediately after a deadlock

-- Unused indexes (requires sys schema)
SELECT * FROM sys.schema_unused_indexes;

-- Statement digests by total latency
SELECT digest_text, count_star, avg_timer_wait
FROM performance_schema.events_statements_summary_by_digest
ORDER BY sum_timer_wait DESC LIMIT 10;
```

`EXPLAIN ANALYZE` **executes** the statement on both engines. Use plain `EXPLAIN` (or
`EXPLAIN FORMAT=JSON` / `EXPLAIN (FORMAT JSON)`) unless running the query is known to be
safe.

## Review Order

Work top to bottom. A CRITICAL finding outranks any number of style notes.

### 1. Correctness and Concurrency (CRITICAL)

- Unparameterized SQL — string-concatenated user input is an injection defect, not a style issue
- **SELECT-then-act race** — a check with a plain `SELECT` followed by a write assumes the check
  still holds. At the engines' defaults (InnoDB `REPEATABLE READ`, PostgreSQL `READ COMMITTED`)
  it does not. Require `FOR UPDATE`, a `UNIQUE` constraint, or an advisory lock on the invariant
- **Isolation level assumed, not stated** — the two engines default differently, and InnoDB's RR
  takes gap locks that RC does not. Code ported between engines, or a deadlock analysis, is wrong
  until the level is confirmed. Raised levels (`REPEATABLE READ`+ on PG) without a `40001` retry
  loop are a finding
- Transactions spanning external API calls (holds locks for the duration of a network round trip)
- Inconsistent lock ordering across code paths → deadlock. Require `ORDER BY <pk> FOR UPDATE`
- `SKIP LOCKED` used outside queue claims — it returns a deliberately inconsistent view and
  must never back an accounting, balance, or permission read
- Read-after-write routed to a replica (stale user-facing state)
- Migration that locks a large table without a stated maintenance window — see `database-migrations`

### 2. Query Performance (CRITICAL)

- WHERE / JOIN / ORDER BY columns unindexed **on a hot path or a large table, with the plan showing
  a scan** — flag with the evidence, per `rdbms-modeling/references/index-design.md`. A cold small
  table with no index is not a finding
- **Referencing (logical FK) columns unindexed** — always a finding, both engines. Dropping the
  physical constraint does not remove the need for the index; joins and parent-side lookups still
  depend on it. PostgreSQL never auto-indexes the referencing side even when an FK exists
- Sequential/full scan on a large table in an interactive path
- N+1 query patterns
- Composite index column order wrong — equality columns must lead; then sort-before-range when the
  query needs the index's ordering, or range-first when it is highly selective. A range column in
  the middle silently disables seek and ordering for everything after it
- A column wrapped in a function is not seekable (`WHERE YEAR(created_at) = 2026`) — needs a
  functional index or generated column
- `OFFSET` pagination on a large table → keyset/cursor pagination. When the UI needs clickable page
  numbers and a cursor is impossible, a **deferred join** (fetch PKs through a covering index, then
  join the wide columns) cuts the random I/O — but the offset scan remains, so say so
- **`IN (subquery)` running as a `DEPENDENT SUBQUERY`** — `EXPLAIN`'s `select_type` is the tell. A
  `GROUP BY`/`HAVING`/aggregate, `UNION`, or `LIMIT` in the subquery, or an `IN` sitting under `OR`,
  disables semi-join optimization and the subquery can re-execute per outer row. Rewrite as an
  explicit derived-table join
- **`IN` with a very long literal list** — past `eq_range_index_dive_limit` (default 200) the
  optimizer stops per-value index dives and estimates from coarse statistics, which makes a wrong
  full-scan choice more likely. Load the values into a temporary table and join
- **Type mismatch between an `IN` list and its column** — an integer list against a `varchar` column
  (or the reverse) forces implicit conversion on the column side and defeats the index, exactly like
  wrapping it in a function
- **`OR` across different columns** — pushes the optimizer onto Index Merge, often slower than a
  `UNION` rewrite or a redesigned composite index
- Individual inserts in a loop → multi-row `INSERT` (MySQL) or `COPY` (PostgreSQL)

What to read in the plan:

| PostgreSQL | MySQL | Signal |
|---|---|---|
| `Seq Scan` on a large table | `type: ALL` | No usable index |
| `rows` estimate far from actual | `rows` very high | Stale statistics or an unselective index |
| `Sort` / external merge | `Using filesort` | Index does not satisfy the ordering |
| `Nested Loop` with a high outer count | `Using temporary` | Join strategy or missing index |

### 3. Schema Design (HIGH)

- **Foreign keys — the policy splits by engine, so establish the engine before judging.**

  **MySQL / InnoDB — a physical `FOREIGN KEY` is a finding.** It adds parent-index I/O to every child
  write the statement does not show, takes parent-row shared locks that make hot-parent key updates
  and all child writes block each other, needs special handling in `pt-online-schema-change`/`gh-ost`,
  and **blocks
  partitioning outright** — InnoDB cannot have an FK on a partitioned table in either direction.
  Report the drop, and the follow-up: the auto-created child index **survives** the drop but keeps
  its auto-generated name — verify with `SHOW INDEX`, rename it to the `idx_` convention (or create
  a proper one if missing), then the four compensating controls.

  **PostgreSQL — a physical FK is fine; audit its six conditions instead.** Flag any that fail:
  non-unique parent target; **referencing column unindexed** (PostgreSQL never auto-creates it — the
  most common defect); a redundant index duplicating an existing leading-column one; `CASCADE` where
  the child's lifecycle is not genuinely dependent on the parent; `DEFERRABLE` without a circular
  reference to justify it; a constraint left **`NOT VALID`** with no validation step — it never
  checked the existing rows, so treat that reference as a logical FK and run the orphan query.

  `ON DELETE CASCADE` on a **high-fan-out parent** is CRITICAL on either engine — one statement
  becomes an unbounded transaction.

- **Logical FK with no compensating controls** — a documented reference with no orphan check and no
  named integrity owner means violations are accumulating unobserved. Run the orphan query during the
  review and report the count. On MySQL this applies to every relationship; on PostgreSQL, to the
  ones deliberately left without a constraint
- **Normalization**: 3NF is the baseline. Flag transitive dependencies and partial dependencies
  on composite PKs. Then check for a **determinant that is not a superkey** (BCNF violation) —
  usually a table with overlapping candidate keys — and flag it only when it can produce a real
  update, insert, or delete anomaly. A table deliberately kept at 3NF is fine if dependency
  preservation or join cost justified it; a table nobody ever checked is the finding
- **Denormalized columns without a stated synchronization mechanism** are a data-integrity
  finding, not a style note. Duplicated data that no code keeps in sync will drift. Check for
  a `COMMENT` naming the source and the sync path
- **Type vs state confusion** — the highest-value finding in this category. Subtype tables (or a
  type code) holding what is really a lifecycle value (`pending` / `paid` / `cancelled`) means
  every transition is a cross-table move instead of an `UPDATE`. If the value changes in normal
  operation, has constrained transitions, or its history matters, it belongs in a status column
  with a history table
- **Overlapping types forced into a single type code** — if an entity can legitimately hold two
  classifications at once (manager *and* instructor), a single `type` column cannot express it
  and the application will be encoding it in strings or duplicate rows. Needs a role table
- **Missed generalization** — near-duplicate tables in a true IS-A relationship
  (`corporate_customer` / `individual_customer` with no `customer`) mean every shared change
  lands twice. Confirm IS-A actually holds before flagging; attribute overlap alone is not it
- **Over-generalization** — a supertype where every meaningful column is nullable has traded
  constraints for application checks; an entity/attribute/value table (`entity`, `attr_name`,
  `attr_value`) has discarded typing, constraints, and the planner. Where a single-table subtype
  strategy is used, check that conditional `CHECK` constraints recover the `NOT NULL` guarantees
  it gave up, and that a separate surrogate key was not minted on subtype rows
- Types: `bigint` for growing IDs, `numeric`/`decimal` for money (never float), timezone-aware
  timestamps (`timestamptz` on PostgreSQL), native boolean over `'Y'`/`'N'`
- `NOT NULL` and `CHECK` constraints present where the domain requires them
- Identifiers are unquoted lowercase `snake_case` — see `rdbms-naming`
- Indexes justified by a real query. Each one costs write throughput, migration time, backup size, and
  buffer-pool space. Report the **unused and redundant** inventory, not just missing indexes —
  MySQL `sys.schema_unused_indexes` / `sys.schema_redundant_indexes`, PostgreSQL
  `pg_stat_user_indexes` where `idx_scan = 0`
- **Indexes on frequently-updated columns of a write-heavy table** — on InnoDB a wide PK propagates
  into every secondary index; on PostgreSQL indexing a churning column disables HOT updates for those
  writes, which costs more than the index itself. Check `fillfactor` and consider BRIN for large
  naturally-ordered append tables
- **`INCLUDE` columns assumed to give an index-only scan (PostgreSQL)** — verify **Heap Fetches** is
  actually low. On a churning table the visibility map keeps heap access alive regardless
- **Leading-wildcard `LIKE '%x%'` on a large table** — no plain B-tree can serve it. MySQL needs
  `FULLTEXT`; PostgreSQL needs `pg_trgm` or full-text search. Also check non-C-locale prefix search for
  a missing `text_pattern_ops`
- **A full-text index whose search configuration differs between index and query (PostgreSQL)** — the
  index is silently unused. On MySQL, check that CJK content uses `WITH PARSER ngram`
- **A view presented as a performance fix** — a plain view does the same work, it just moves where the
  SQL lives. Check the plan of the *actual usage query*, not the view definition. Nested views are the
  common case: each layer looks reasonable and the composed query does something nobody intended
- **MySQL view blocked from `MERGE`** — aggregates, window functions, `DISTINCT`, `UNION`, or `LIMIT`
  force internal materialization, and no permanent index can be defined on a view. Check whether the
  outer predicates can still reach base-table indexes
- **Code relying on `ORDER BY` inside a view or materialized view** — neither guarantees row order.
  A finding wherever the application assumes it
- **Materialized view read as if current** — check the refresh interval against what the feature
  actually needs, and confirm nothing requiring immediate consistency (balance, inventory, permissions)
  reads it
- **`REFRESH CONCURRENTLY` without its prerequisites** — needs a UNIQUE index on plain columns covering
  all rows, cannot run on a never-populated MView, and only one refresh per MView at a time. Check the
  job has a lock or skip-if-running guard; overlapping schedules queue or fail
- **Materialized view or summary table with no consistency check and no rebuild path** — same finding as
  any denormalization. For an incrementally-refreshed summary table, verify deletes are handled; an
  ignored delete leaves a permanently wrong aggregate
- **Search workload outgrowing in-database FTS** — signal a dedicated search engine when tuned FTS
  misses the latency target, the index pressures memory or replication, or the product needs typo
  tolerance, synonyms, autocomplete, or complex ranking. Do not use a fixed row-count threshold
- Soft deletes backed by a partial index (PostgreSQL) or composite index (MySQL), not a
  standalone flag index

### 4. Security (CRITICAL)

- Application user holds `GRANT ALL` or database-wide privileges → least privilege
- Migration/admin credentials shared with the runtime application user
- Credentials in code, config files, or examples instead of a secret manager
- TLS not required for connections crossing hosts or networks
- PostgreSQL: RLS enabled on multi-tenant tables — **and the runtime role actually subject to it**:
  not a superuser, no `BYPASSRLS`, not the table owner (or `FORCE ROW LEVEL SECURITY` is set).
  Policies on a table the app owns are decoration; check the role, not just the policy. Policy
  functions wrapped as `(SELECT fn())` so they evaluate once per query rather than once per row;
  policy columns indexed; `REVOKE ALL ON SCHEMA public FROM public`
- MySQL: anonymous accounts removed; no direct DML against `mysql.user`

### 5. Operations (MEDIUM)

- Pool recycle interval above the server idle timeout → stale connections
- No `statement_timeout` / `idle_in_transaction_session_timeout` (PostgreSQL) or
  `innodb_lock_wait_timeout` (MySQL)
- Slow query logging disabled, so there is no evidence to review next time
- Unbounded log or history table with no partitioning or retention plan
- **Partitioning present but never pruned** — the partition key is absent from the main `WHERE`
  predicates, so every query scans every partition. The worst case: all the management cost, none
  of the benefit. Verify with `EXPLAIN` (MySQL: the `partitions` column; PostgreSQL: which
  partitions appear in the plan)
- **Partitioning applied with no evidence** — no time-range query and no retention/deletion code
  in the repo. Report it as unjustified structure, not as a win
- **Safety partition accumulating rows** — data in MySQL's `p_maxvalue` or PostgreSQL's `DEFAULT`
  partition means partition creation fell behind. Check the runway of pre-created partitions;
  fewer than 2 periods is a finding, zero is imminent breakage
- **MySQL partitioned table where a PK or UNIQUE omits the partition key** — invalid on InnoDB;
  if such DDL exists, either the partitioning or the key is wrong
- **History written outside the transaction that changed the current row** — CRITICAL. A failure
  between the two leaves history that contradicts the data. Check that both writes share one
  transaction boundary
- **A physical FK from an entity to its history table** — every referential action is wrong here:
  `CASCADE` deletes the evidence, `RESTRICT`/`NO ACTION` makes the parent undeletable, `SET NULL`
  orphans the history. `CASCADE` is the worst and is CRITICAL. History needs a logical reference
- **`updated_at` presented as history** — it says something changed, not what or why. If the code has
  audit screens, restore features, or point-in-time queries, the structure does not support them
- **State changes recorded without an actor and a reason** — an approval or cancellation row that
  cannot say who or why is not usable as business history
- **PII in history snapshots with no retention limit** — history is where personal data quietly
  becomes permanent. Look for a purge path, not just a retention constant
- **Database internal routines** — inventory them first; an undocumented trigger will contradict the
  application eventually. A routine doing operational utility work (partition creation/rotation,
  retention purge, statistics refresh, materialized view refresh) on a schedule is **fine** — check it
  is version controlled, idempotent, and monitored. An audit trigger meeting all its conditions is
  **fine** — check it writes only to the audit table. **Anything carrying business logic is a finding**:
  a trigger maintaining a denormalized value or setting `updated_at`, a procedure holding a workflow, an
  event running business processing. Report what it does and the migration path. Inventory queries in
  `rdbms-modeling/references/db-internal-routines.md`
- **A duplicated column updated on some write paths but not all** — the highest-value denormalization
  finding, because it is already producing wrong data. Trace every writer of the source column
- **Denormalized data with no consistency-check query and no rebuild path** — unverifiable duplicates
  diverge silently. Run a check during the review and report the mismatch count
- **Denormalization with no measurement behind it** — report it as unjustified write amplification, and
  name the cheaper alternative (index, N+1 fix) that was likely skipped. On PostgreSQL also check the
  bloat and `VACUUM` load from a frequently-updated duplicated column
- Analytics queries running against the OLTP primary

## Output Format

Findings first, ordered by severity. No summary paragraph before them.

```
CRITICAL  <file>:<line> — <the defect>
          Impact: <what breaks, under what conditions>
          Fix:    <exact SQL or code change>

HIGH      ...
MEDIUM    ...

Verification:
- <EXPLAIN or query to run that proves the fix worked>
- <the metric to watch after deploy>

Engine assumed: <engine> <version> (<how it was determined>)
```

State the engine and version you assumed and how you determined it. If you inferred it from
a config file rather than a live query, say that — a wrong assumption invalidates dialect
findings.

If nothing is wrong, say so in one line. Do not manufacture findings to fill the report.

## Related

- `mysql-guideline` / `postgres-guideline` — engine rules, index strategy, operations
- `rdbms-naming` — naming and type conventions
- `database-migrations` — migration safety, lock impact, rollout ordering
- `rdbms-modeling` — when the review concludes the schema needs redesigning, not patching

---

**Remember**: verify with `EXPLAIN` instead of asserting. Index foreign keys and RLS policy
columns without exception. An index nobody queries is pure write-side cost.
