---
name: rdbms-review
description: >
  Review existing SQL, schemas, and migrations for performance, correctness, security, and
  concurrency problems on MySQL and PostgreSQL. Triggers: review this schema, review this
  query, review this migration, why is this query slow, is this index right, missing index, seq
  scan, full table scan, N+1 query, EXPLAIN output, EXPLAIN ANALYZE, deadlock, lock wait
  timeout, table bloat, vacuum, slow query log, connection pool exhausted, too many
  connections, RLS policy review, GRANT audit, database security review, duplicate tables,
  over-generalized schema, EAV anti-pattern, nullable everything, subtype vs status, type
  column holding a state, missing role table, foreign key constraint, ON DELETE CASCADE, orphan
  rows, referential integrity, is this schema safe to deploy.
---

# RDBMS Review

Review database code that already exists. For designing something new, use `rdbms-modeling`
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

Then load the matching skill: `postgres-guideline` or `mysql-guideline`. If the engine
cannot be determined, say so and scope the review to engine-neutral findings only — do not
guess a dialect.

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
- Transactions spanning external API calls (holds locks for the duration of a network round trip)
- Inconsistent lock ordering across code paths → deadlock. Require `ORDER BY <pk> FOR UPDATE`
- `SKIP LOCKED` used outside queue claims — it returns a deliberately inconsistent view and
  must never back an accounting, balance, or permission read
- Read-after-write routed to a replica (stale user-facing state)
- Migration that locks a large table without a stated maintenance window — see `database-migrations`

### 2. Query Performance (CRITICAL)

- WHERE / JOIN / ORDER BY columns unindexed
- **Referencing (logical FK) columns unindexed** — always a finding, both engines. Dropping the
  physical constraint does not remove the need for the index; joins and parent-side lookups still
  depend on it. PostgreSQL never auto-indexes the referencing side even when an FK exists
- Sequential/full scan on a large table in an interactive path
- N+1 query patterns
- Composite index column order wrong — equality → sort → range
- A column wrapped in a function is not seekable (`WHERE YEAR(created_at) = 2026`) — needs a
  functional index or generated column
- `OFFSET` pagination on a large table → keyset/cursor pagination
- Individual inserts in a loop → multi-row `INSERT` (MySQL) or `COPY` (PostgreSQL)

What to read in the plan:

| PostgreSQL | MySQL | Signal |
|---|---|---|
| `Seq Scan` on a large table | `type: ALL` | No usable index |
| `rows` estimate far from actual | `rows` very high | Stale statistics or an unselective index |
| `Sort` / external merge | `Using filesort` | Index does not satisfy the ordering |
| `Nested Loop` with a high outer count | `Using temporary` | Join strategy or missing index |

### 3. Schema Design (HIGH)

- **Physical `FOREIGN KEY` constraint present** — a policy violation and an operational finding.
  It adds parent-index I/O to every child write that the statement does not show, takes locks on
  the parent row that serialize unrelated child writes, and blocks routine maintenance (InnoDB
  cannot put an FK on a partitioned table at all). Report the constraint, the drop statement, and
  the four compensating controls that must land with it: `COMMENT`, index on the referencing
  column, named integrity owner, scheduled orphan check. Flag `ON DELETE CASCADE` as CRITICAL —
  one statement becoming an unbounded transaction
- **Logical FK with no compensating controls** — the mirror finding. A documented reference with
  no orphan check and no named integrity owner means violations are accumulating unobserved. Run
  the orphan query during the review and report the count
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
- Indexes justified by a real query. Each one costs write throughput, migration time, backup
  size, and buffer-pool space
- Soft deletes backed by a partial index (PostgreSQL) or composite index (MySQL), not a
  standalone flag index

### 4. Security (CRITICAL)

- Application user holds `GRANT ALL` or database-wide privileges → least privilege
- Migration/admin credentials shared with the runtime application user
- Credentials in code, config files, or examples instead of a secret manager
- TLS not required for connections crossing hosts or networks
- PostgreSQL: RLS enabled on multi-tenant tables; policy functions wrapped as
  `(SELECT fn())` so they evaluate once per query rather than once per row; policy columns
  indexed; `REVOKE ALL ON SCHEMA public FROM public`
- MySQL: anonymous accounts removed; no direct DML against `mysql.user`

### 5. Operations (MEDIUM)

- Pool recycle interval above the server idle timeout → stale connections
- No `statement_timeout` / `idle_in_transaction_session_timeout` (PostgreSQL) or
  `innodb_lock_wait_timeout` (MySQL)
- Slow query logging disabled, so there is no evidence to review next time
- Unbounded log or history table with no partitioning or retention plan
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
