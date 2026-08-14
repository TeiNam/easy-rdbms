---
name: mysql-guideline
description: >
  MySQL 8.0+ schema design, table/index creation, query optimization, partitioning,
  connection management, development principles and anti-patterns, JDBC driver selection.
  Triggers: CREATE TABLE, ALTER TABLE, slow query analysis, index design, RANGE partition,
  MySQL migration, utf8mb4, InnoDB, transaction management, UPSERT, Covering Index,
  composite index, normalization, data type selection, INET_ATON, UUID_TO_BIN,
  DATETIME TIMESTAMP, stored procedure, COUNT(*), random PK, JSON column,
  JDBC, Connector/J, AWS Advanced JDBC Wrapper, Aurora failover, keyset pagination,
  SKIP LOCKED queue, deadlock, replica lag, read-after-write, GRANT least privilege,
  my.cnf tuning, slow query log, SHOW ENGINE INNODB STATUS, MariaDB divergence,
  FULLTEXT MATCH AGAINST, connection pool sizing related tasks.
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
  - `pk_<table>` · `fk_<child>_<parent>` · `uq_<table>_<col>` · `chk_<table>_<rule>` · `idx_<table>_<col>` · `ftx_<table>_<col>`
  - Examples: `idx_book_like_member_id`, `uq_member_email`, `ftx_book_name`

## Data Type Guide

| Use Case | Recommended Type | Notes |
|----------|-----------------|-------|
| Tiny PK/flag | `tinyint unsigned` | 0~255 |
| Small PK | `smallint unsigned` | 0~65535 |
| Standard PK | `int unsigned` | 0~4.2 billion |
| Large PK / default surrogate | `bigint unsigned` | Default choice; `int` risks exhaustion (~4.2B) on large tables |
| Boolean | `tinyint(1)` 0/1 | `BOOLEAN`/`BOOL` is an alias for `tinyint(1)`. Name with `is_`/`has_`. (Legacy `char(1)` 'Y'/'N' only where already entrenched — new designs use `tinyint(1)`) |
| Variable string | `varchar(n)` | `n` = **character count** (MySQL 4.1+), sized to real max length. Row-wide 65,535B cap limits max `n` (utf8mb4 ≈ 16,383 chars single-column) |
| Long text | `text` | 4 tiers: `tinytext`(256B)/`text`(64KB)/`mediumtext`(16MB)/`longtext`(4GB). Prefix index only |
| Fixed string | `char(n)` | Truly fixed-width codes only (e.g. `char(2)` country code) |
| Date+Time | `datetime` (5B packed binary, 5.6.4+) | With `DEFAULT CURRENT_TIMESTAMP`. Use for values past 2038 (Y2038). +1~3B for fractional seconds |
| Auto-UTC timestamp | `timestamp` (4B) | Session-tz→UTC auto-conversion, but **≤ 2038-01-19** — never for future/expiry dates |
| JSON data | `json` | MySQL 8.0+ native (binary format). Index via generated column or multi-valued index (8.0.17+) |
| IPv4 | `int unsigned` via `INET_ATON` | 4B. IPv4-only |
| IPv4/IPv6 | `varbinary(16)` via `INET6_ATON` | Dual-stack safe (INET_ATON returns NULL for IPv6) |
| UUID (external, not PK) | `binary(16)` via `UUID_TO_BIN(v)` | **swap_flag=1 is for UUIDv1 only** (MySQL `UUID()` is v1). Prefer app-generated **UUIDv7** and store it with **no swap** — v7 is already time-ordered, and swapping destroys that. Never `char(36)` |
| Money | `decimal(p,s)` | Never float. **Per-currency:** KRW `(15,0)` (no minor unit), multinational `(19,4)`, rate `(19,6)`, ratio `(5,4)`. No blanket `(10,2)` |

## Prohibited Items
- Stored Procedures: discouraged (stored-program cache is **per-session**, not a global shared cache like
  Oracle/PostgreSQL — connection-pool churn re-pays parse/compile cost; plus maintenance/portability/security)
- Triggers: prohibited
- Events: prohibited
- Complex Views: discouraged, simple read-only only

## Reference Files
- `schema-design.md` — PK/FK policy, checklists
- `index-and-query.md` — Index strategy (composite ESR order, range-column optimization), query patterns
- `partitioning.md` — Partitioning strategy, management
- `connection-and-features.md` — Connection management, transactions
- `dev-practices.md` — Development principles and anti-patterns: normalization + denormalization criteria,
  minimal types, VARCHAR char-semantics, INET_ATON/INET6_ATON/UUID_TO_BIN, DATETIME vs TIMESTAMP (Y2038),
  session-local SP cache, index anti-patterns, COUNT(*) MVCC reason, random PK (UUID v7), composite PK,
  no physical FK (extra write I/O, parent-row lock contention, blocks partitioning and online DDL —
  with the four compensating controls required instead), JSON (multi-valued index)
- `jdbc-driver.md` — Java driver selection (2026-07): AWS Advanced JDBC Wrapper (top choice) vs Connector/J
  9.x; MariaDB Connector/J Aurora EOL, Aurora JDBC Driver EOL; failover tuning
- `release-policy.md` — Innovation vs LTS tracks: 8.4.x / 9.7.x are LTS, 9.0–9.6 Innovation; production = LTS
- `operations.md` — MySQL vs MariaDB SQL divergence, keyset pagination, FULLTEXT query, deadlock
  checklist + `SKIP LOCKED` queue claims, Node.js pool sizing and the `wait_timeout` rule, diagnostics,
  replica lag / read-after-write routing, GRANT least privilege + TLS, `my.cnf` baseline, ops anti-patterns

## Choosing a Database

If the target DB is not decided yet — or you are weighing MySQL against PostgreSQL, or an
RDBMS against DynamoDB / MongoDB / Redis — use the `db-select` skill first. It routes back
here once MySQL is confirmed.
