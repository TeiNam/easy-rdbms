---
name: postgres-guideline
description: >
  PostgreSQL 16+ schema design, table/index creation, query optimization, partitioning,
  and psycopg3 connection management. Triggers: CREATE TABLE, GENERATED ALWAYS AS IDENTITY, PK type choice, int vs bigint PK,
  sequence exhaustion,
  EXPLAIN ANALYZE, GIN/BRIN/GiST indexes, RLS, PARTITION BY RANGE, pg_partman,
  LISTEN/NOTIFY, Advisory Lock, UPSERT ON CONFLICT, CTE, timestamptz operations.
---

# PostgreSQL Database Guideline

## When to Activate

- Writing SQL queries or migrations
- Designing database schemas
- Troubleshooting slow queries
- Implementing Row Level Security
- Setting up connection pooling
- Creating partitioned tables

## PostgreSQL Version and Defaults
- PostgreSQL 16.7+
- Character set: UTF-8
- Schema separation by purpose (`public` schema direct use discouraged)

```sql
CREATE DATABASE myapp
  ENCODING 'UTF8'
  LC_COLLATE 'en_US.UTF-8'
  LC_CTYPE 'en_US.UTF-8'
  TEMPLATE template0;

CREATE SCHEMA app;    -- application tables
CREATE SCHEMA log;    -- log tables
CREATE SCHEMA ref;    -- reference/master tables
```

## Naming Rules

Common RDBMS naming conventions (snake_case, singular form, past-participle time columns, prefix/postfix patterns, abbreviation registry, column prefix/suffix system, case-folding, 63-char limit) follow the **`rdbms-naming` skill as single source of truth.**
Summary + PostgreSQL-specific:

- Tables/Columns: lowercase snake_case, tables singular (e.g. `member`, `member_id`). PG folds unquoted
  identifiers to lowercase — never rely on uppercase, never quote to preserve case.
- Time columns: past-participle standard `created_at` / `updated_at` / `deleted_at` (the old active-voice
  `create_date` rule is retired)
- Boolean: `is_`/`has_` prefix + native `boolean` (never 'Y'/'N' strings)
- Constraints/Indexes: **lowercase prefix** — `pk_<table>` / `fk_<child>_<parent>` / `uq_<table>_<col>` /
  `chk_<table>_<rule>` / `idx_<table>_<col>` / `fts_<table>_<col>`. (Uppercase suffix `_IDX` breaks under PG
  case-folding — do not use.)
- Sequences (PG-specific): `{table}_{column}_seq` (auto-created with IDENTITY)

## Data Type Guide

| Use Case | Recommended Type | Notes |
|----------|-----------------|-------|
| **Event/log table PK** (`*_log`, `*_history`, IoT, audit) | **`bigint`** | **No exceptions.** Rows = rate × time with no bound; `int` at 10k/s dies in ~5 days, and a sequence never reuses values so retention does not reclaim range. `ALTER COLUMN … TYPE bigint` rewrites the whole table under `ACCESS EXCLUSIVE` — see `schema-design.md` |
| Entity table PK (`member`, `product`) | `int` | Fine — 2.1B, and the real world caps the entity count. Record what bounds it |
| Bounded lookup/code table PK | `smallint` | Fixed code domain |
| Small integer | `smallint` | -32768 ~ 32767 |
| Boolean | `boolean` | Never use 'Y'/'N' strings |
| Variable string | `varchar(n)` or `text` | Use `text` if no length limit |
| Fixed string | `char(n)` | Fixed-length codes only |
| Timestamp | `timestamptz` | Timezone required |
| Date only | `date` | |
| JSON data | `jsonb` | Not `json` (indexing support) |
| Money | `numeric(p,s)` | Never use float. Scale from the currency's minor unit, precision from the domain maximum: KRW `numeric(15,0)` (no minor unit), USD `numeric(p,2)` with `p` sized to the largest amount, ratio `numeric(5,4)` (0.1234=12.34%). No blanket `(10,2)` |
| IP address | `inet` | PostgreSQL native type |
| Arrays | `type[]` | Simple lists (e.g. `text[]`) |
| IDs (external) | `uuid` — **UUIDv7**: `uuidv7()` on PG 18+, app-generated on 16/17. `gen_random_uuid()` is v4 (use only when unpredictability matters more than index locality) |

## Foreign Keys — Differs from MySQL

Physical `FOREIGN KEY` constraints **are allowed here**, unlike in `mysql-guideline` (InnoDB cannot
put an FK on a partitioned table, and log/history tables are the usual partitioning candidates).
Allowed by default is not always create — `schema-design.md` has the six conditions, the costs that
remain, and the compensating controls for relationships left as logical FKs. PostgreSQL never
auto-creates the referencing-column index, so condition 2 is the one most often missed.

## Prohibited Items
- Stored Procedures / functions: prohibited for **business logic** — the sanctioned
  operational-utility and audit-trigger exceptions are in
  `rdbms-modeling/references/db-internal-routines.md`
- Triggers: prohibited for business logic (handle `updated_at` in the application)
- Events/Schedulers: use external (cron, Airflow)
- Views: simple read-only views are fine for query reuse, security, and interface abstraction —
  **complex or nested views are discouraged** (a view is not a performance cache; PostgreSQL rewrites
  it into a base-table query). Materialized views **are** available for repeated joins and aggregation.
  See `rdbms-modeling/references/views-and-materialized-views.md`
- RULE: prohibited (unpredictable behavior)
- SERIAL type: discouraged — use `GENERATED ALWAYS AS IDENTITY` (SQL standard, prevents accidental override; SERIAL still works but is proprietary). PostgreSQL wiki: "Don't use serial."

## Reference Files
- `schema-design.md` — PK/FK policy, RLS, checklists
- `index-and-query.md` — Index strategy, query patterns, pagination, queue
- `partitioning.md` — Partitioning strategy, pg_partman, management
- `connection-and-features.md` — psycopg 3, Advisory Lock, LISTEN/NOTIFY, server config

## Choosing a Database

If the target DB is not decided yet — or you are weighing PostgreSQL against MySQL, or an
RDBMS against DynamoDB / MongoDB / Redis — use the `db-select` skill first. It routes back
here once PostgreSQL is confirmed.

## After Writing the Schema

Hand the DDL to the `rdbms-review` skill before it ships. It checks this file's rules plus the
cross-engine ones (PostgreSQL defaults, `rdbms-naming` conventions, normalization level, index
justification, physical-FK policy) and reports findings by severity — the checklists here tell you
what *good* looks like, not whether a given schema got there.

Changing a schema that already holds data is a different problem: use `database-migrations`.
