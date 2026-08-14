---
name: mysql-guideline
description: >
  MySQL 8.0+ schema design, table/index creation, query optimization, partitioning, connection
  management, development principles and anti-patterns, JDBC driver selection. Triggers: CREATE
  TABLE, ALTER TABLE, slow query analysis, index design, RANGE partition, MySQL migration,
  utf8mb4, InnoDB, transaction management, UPSERT, Covering Index, composite index,
  normalization, data type selection, INET_ATON, UUID_TO_BIN, DATETIME TIMESTAMP, stored
  procedure, COUNT(*), random PK, JSON column, JDBC, Connector/J, AWS Advanced JDBC Wrapper,
  Aurora failover, keyset pagination, SKIP LOCKED queue, deadlock, replica lag,
  read-after-write, GRANT least privilege, my.cnf tuning, slow query log, SHOW ENGINE INNODB
  STATUS, MariaDB divergence, FULLTEXT MATCH AGAINST, connection pool sizing, integer type
  ranges, IN subquery slow, DEPENDENT SUBQUERY, semi-join optimization,
  eq_range_index_dive_limit, Index Merge, OR condition slow, deep pagination, OFFSET slow,
  deferred join, PK type choice, int vs bigint PK, AUTO_INCREMENT exhaustion, UNSIGNED,
  IoT/log table design related tasks.
---

# MySQL Database Guideline

## When to Activate

- Writing MySQL queries or migrations
- Designing MySQL database schemas
- Troubleshooting slow queries
- Creating partitioned tables
- Setting up connection management

## MySQL Version and Defaults
- MySQL 8.4 LTS (or 9.7 LTS) — pick an **LTS track** for production; see `release-policy.md`
- Character set: utf8mb4, collation `utf8mb4_0900_ai_ci` (team standard; `utf8mb4_general_ci` is legacy)
- Engine: InnoDB

## Naming Rules

Common RDBMS naming conventions (snake_case, singular form, time-column standard, prefix/postfix
rules, abbreviation dictionary, column prefix/suffix system, case-folding, 63-char limit) follow the
**`rdbms-naming` skill as the single source of truth.** Summary:

- Tables/Columns: lowercase snake_case, tables in singular form (e.g. `member`, `member_chat_setting`, `member_id`)
- Time columns: past-participle standard `created_at` / `updated_at` / `deleted_at` (the old active-voice
  `create_date` rule is retired)
- Boolean: `is_`/`has_` prefix + `TINYINT(1)` 0/1 (not the old `use_yn` CHAR(1) 'Y'/'N')
- Constraints/Indexes: **lowercase prefix** (uppercase suffix `_IDX` breaks PostgreSQL case-folding)
  - `pk_<table>` · `fk_<child>_<parent>` · `uq_<table>_<col>` · `chk_<table>_<rule>` · `idx_<table>_<col>` · `fts_<table>_<col>`
  - Examples: `idx_book_like_member_id`, `uq_member_email`, `fts_book_name`

## Data Type Guide

### Integer Ranges — pick from the real value range

Smaller types mean less storage, smaller indexes (so more of the index stays in the buffer pool),
and less network traffic. `TINYINT` vs `INT` is 1B vs 4B — at 100 million rows, 100 MB vs 400 MB.

| Type | Size | Signed range | Unsigned range |
|------|------|--------------|----------------|
| `tinyint` | 1B | −128 ~ 127 | 0 ~ 255 |
| `smallint` | 2B | −32,768 ~ 32,767 | 0 ~ 65,535 |
| `mediumint` | 3B | −8,388,608 ~ 8,388,607 | 0 ~ 16,777,215 |
| `int` | 4B | ≈ −2.1B ~ 2.1B | 0 ~ ≈ 4.2B |
| `bigint` | 8B | ≈ −9.2×10¹⁸ ~ 9.2×10¹⁸ | 0 ~ ≈ 1.8×10¹⁹ |

For an **ordinary column**, widening later is usually manageable and narrowing risks data loss — so
size to the observed value range and monitor growth rather than padding "just in case".

**The PK is not an ordinary column. Get it right at `CREATE TABLE` time.**

> `ALTER TABLE … MODIFY member_id bigint unsigned` on the primary key requires **`ALGORITHM=COPY`** —
> MySQL has no in-place path for changing an integer's type. That means a full table rebuild, and
> because InnoDB appends the PK to **every secondary index**, all of them are rebuilt too. Add the
> disk for a second copy, the replication lag while it runs, and the fact that every referencing
> column (logical FK children included — this policy makes them plain columns) has to change in
> lockstep across separate migrations.
>
> On a table small enough to rebuild in a maintenance window this is annoying. On a table with a
> billion rows it is a `pt-online-schema-change` / `gh-ost` project with a cutover plan — which is
> exactly the table where `int` runs out.

So decide from **what makes the row count grow**, not from today's row count:

| Growth class | Bounded by | PK |
|---|---|---|
| **Entity** — one row per real thing | The real world: people, products, branches. `member` cannot exceed the human population; `int unsigned` reaches **4.2 billion** | `int unsigned` is genuinely enough |
| **Event / log** — one row per occurrence | Nothing. Row count = **insert rate × elapsed time**, and time does not stop | **`bigint unsigned`, no exceptions** |

Event tables are where `int` actually breaks, and the arithmetic is unforgiving:

| Insert rate | `int unsigned` (4.2B) lasts | `bigint unsigned` lasts |
|---|---|---|
| 100/s | ~1.3 years | effectively forever |
| 1,000/s | ~49 days | effectively forever |
| 10,000/s (IoT telemetry) | **~5 days** | effectively forever |

**Retention and partition pruning do not help.** `AUTO_INCREMENT` never reuses a value, so deleting
or dropping old partitions frees storage but **not ID space** — a 30-day-retention log table burns
through the range at the full insert rate as if nothing were ever deleted. Hitting the ceiling means
`Duplicate entry '4294967295' for key 'PRIMARY'` on every insert, on the busiest table you own,
with the hardest possible migration ahead of you.

So: IoT telemetry, audit trails, chat/message history, access and event logs, metering records,
outbox tables — `bigint unsigned` from the start. If a table is called `*_log`, `*_history`,
`*_event`, or contains a reading from a device, that decision is already made.

For entity tables, `int unsigned` is a reasonable choice — but write down **what bounds it**, and
re-check if the entity turns out to be machine-generated rather than human (per-device rows, ad
impressions, generated variants: those are event tables wearing an entity name).

`decimal` follows the same principle: money that needs no fractional part is cheaper and simpler as
an integer in the minor unit than as a `decimal`.

### `UNSIGNED` — use it whenever negatives are impossible

`UNSIGNED` is not merely a constraint. It **doubles the positive range for the same bytes**, so on
the columns most likely to run out it is free runway:

| Column | Signed ceiling | Unsigned ceiling |
|---|---|---|
| `int` PK | ≈ 2.1 billion | ≈ 4.2 billion |
| `bigint` PK | ≈ 9.2×10¹⁸ | ≈ 1.8×10¹⁹ |

Apply it to any integer column whose domain excludes negatives — surrogate PKs, counts, quantities,
ages, byte sizes. Skipping it throws away half the range for nothing.

Two things to keep straight:

- **Mixing signed and unsigned is where it bites.** `UNSIGNED` subtraction that would go below zero
  **wraps to a huge positive number** rather than erroring (unless `NO_UNSIGNED_SUBTRACTION` is in
  `sql_mode`), so compute differences by casting to signed. And a join between a signed column and an
  unsigned one is a type mismatch — keep both sides of a join key identical, `UNSIGNED` included.
- **Portability**: PostgreSQL has no `UNSIGNED`; there the equivalent is `CHECK (col >= 0)`. Add the
  `CHECK` on MySQL as well **only when porting the schema is a stated requirement** — not for a
  portability need nobody has.

`DECIMAL`/`FLOAT`/`DOUBLE UNSIGNED` is deprecated (8.0.17) — this rule is for integer types.

### Type Selection

| Use Case | Recommended Type | Notes |
|----------|-----------------|-------|
| **Event/log table PK** (`*_log`, `*_history`, IoT, audit) | **`bigint unsigned`** | **No exceptions.** Rows = rate × time, with no upper bound. `int` at 10k/s dies in ~5 days, and retention does not reclaim `AUTO_INCREMENT` values |
| Entity table PK (`member`, `product`) | `int unsigned` | Fine — 4.2B, and the real world caps the entity count. Record what bounds it |
| Bounded lookup/code table PK | `tinyint`/`smallint unsigned` | Fixed code domain |
| Flag / small enumerated value | `tinyint unsigned` | 0~255 |
| Boolean | `tinyint(1)` 0/1 | `BOOLEAN`/`BOOL` is an alias for `tinyint(1)`. Name with `is_`/`has_`. (Legacy `char(1)` 'Y'/'N' only where already entrenched — new designs use `tinyint(1)`) |
| Variable string | `varchar(n)` | `n` = **character count** (MySQL 4.1+), sized to real max length. Row-wide 65,535B cap limits max `n` (utf8mb4 ≈ 16,383 chars single-column) |
| Long text | `text` | 4 tiers: `tinytext`(255B)/`text`(64KB)/`mediumtext`(16MB)/`longtext`(4GB). Prefix index only |
| Fixed string | `char(n)` | Truly fixed-width codes only (e.g. `char(2)` country code) |
| Date+Time | `datetime` (5B packed binary, 5.6.4+) | With `DEFAULT CURRENT_TIMESTAMP`. Use for values past 2038 (Y2038). +1~3B for fractional seconds |
| Auto-UTC timestamp | `timestamp` (4B) | Session-tz→UTC auto-conversion, but **≤ 2038-01-19** — never for future/expiry dates |
| JSON data | `json` | MySQL 8.0+ native (binary format). Index via generated column or multi-valued index (8.0.17+) |
| IPv4 | `int unsigned` via `INET_ATON` | 4B. IPv4-only |
| IPv4/IPv6 | `varbinary(16)` via `INET6_ATON` | Dual-stack safe (INET_ATON returns NULL for IPv6) |
| UUID (external, not PK) | `binary(16)` via `UUID_TO_BIN(v)` | **swap_flag=1 is for UUIDv1 only** (MySQL `UUID()` is v1). Prefer app-generated **UUIDv7** and store it with **no swap** — v7 is already time-ordered, and swapping destroys that. Never `char(36)` |
| Money | `decimal(p,s)` | Never float. **Per-currency:** KRW `(15,0)` (no minor unit), multinational `(19,4)`, rate `(19,6)`, ratio `(5,4)`. No blanket `(10,2)` |

## Prohibited Items
- Stored Procedures: discouraged (stored-program cache is **per-session**, not a global shared cache
  like Oracle's — connection-pool churn re-pays parse/compile cost; plus maintenance/portability/security)
- Triggers: prohibited for business logic
- Events: prohibited for business processing — the operational-utility exception (partition
  rotation etc. when no external scheduler exists) follows `rdbms-modeling/references/db-internal-routines.md`
- Views: simple read-only views are fine for query reuse, security, and interface abstraction —
  **complex or nested views are discouraged** (a view is not a performance cache; aggregates, window
  functions, `DISTINCT`, `UNION`, `LIMIT` block `MERGE` and force internal materialization). MySQL has
  no native materialized view — use a summary table. See
  `rdbms-modeling/references/views-and-materialized-views.md`

## Reference Files
- `schema-design.md` — PK/FK policy, checklists
- `index-and-query.md` — Index strategy (composite ESR order, range-column optimization), when an
  index helps vs hurts (skew, NULL ratio, `OR`/Index Merge), the two ways `IN` loses the index
  (semi-join breakdown, `eq_range_index_dive_limit`), query patterns
- `partitioning.md` — Partitioning strategy, management
- `connection-and-features.md` — Connection management, transactions
- `dev-practices.md` — Development principles and anti-patterns: normalization + denormalization criteria,
  minimal types, `UNSIGNED` range benefit and the signed/unsigned mixing traps, VARCHAR char-semantics, INET_ATON/INET6_ATON/UUID_TO_BIN, DATETIME vs TIMESTAMP (Y2038),
  session-local SP cache, index anti-patterns, COUNT(*) MVCC reason, random PK (UUID v7), composite PK,
  no physical FK (extra write I/O, parent-row lock contention, blocks partitioning and online DDL —
  with the four compensating controls required instead), JSON (multi-valued index)
- `jdbc-driver.md` — Java driver selection (2026-07): AWS Advanced JDBC Wrapper (top choice) vs Connector/J
  9.x; MariaDB Connector/J Aurora EOL, Aurora JDBC Driver EOL; failover tuning
- `release-policy.md` — Innovation vs LTS tracks: 8.4.x / 9.7.x are LTS, 9.0–9.6 Innovation; production = LTS
- `operations.md` — MySQL vs MariaDB SQL divergence, the `OFFSET` trap with keyset pagination and
  the deferred-join fallback, FULLTEXT query, deadlock
  checklist + `SKIP LOCKED` queue claims, Node.js pool sizing and the `wait_timeout` rule, diagnostics,
  replica lag / read-after-write routing, GRANT least privilege + TLS, `my.cnf` baseline, ops anti-patterns

## Choosing a Database

If the target DB is not decided yet — or you are weighing MySQL against PostgreSQL, or an
RDBMS against DynamoDB / MongoDB / Redis — use the `db-select` skill first. It routes back
here once MySQL is confirmed.
