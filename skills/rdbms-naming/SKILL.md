---
name: rdbms-naming
description: >
  Common RDBMS naming and data type conventions (single source for MySQL and PostgreSQL).
  Table/column snake_case, singular, past-participle time columns, prefix/postfix, abbreviation
  dictionary, column prefix/suffix system, index/constraint naming (lowercase prefix pk_/fk_/uq_/chk_/idx_/fts_),
  identifier case-folding, 63-char limit, data type selection. Triggers: table/column/index design,
  DDL authoring, schema review, naming conventions, snake_case, abbreviations, PK/FK naming,
  boolean columns, DECIMAL, settlement amount columns.
---

# RDBMS Naming Conventions

**Naming governance** (snake_case, singular, time-column standard, prefix/postfix, abbreviations,
index/constraint naming, case-folding) is common across MySQL and PostgreSQL, making this skill the
**single source**. **Data types** differ by engine, so apply only the target DB column from the
"Data Types (by DB)" table below; see `mysql-guideline` / `postgres-guideline` for deeper details.

## When to Activate

When creating tables, columns, or indexes; authoring or reviewing DDL; or deciding naming conventions.
Target: RDBMS (MySQL 8.x / PostgreSQL).

## 0. Case Folding — the portability rule to understand first

Each engine auto-transforms **unquoted identifiers**, so a name that "works" on one engine can silently
change on another.

| Engine | Unquoted identifier handling | Example |
|--------|------------------------------|---------|
| PostgreSQL | folds to **lowercase** | `Book_IDX` → actually `book_idx` |
| MySQL | depends on `lower_case_table_names` | easy to assume case is preserved |
| (Oracle, for reference) | folds to **uppercase** | mind this if you ever port |

**Conclusions:**

1. **Write every identifier in lowercase snake_case.** Rules that assign meaning to uppercase
   (e.g. an uppercase suffix) break automatically on PostgreSQL — do not use them.
2. **Keep identifiers ≤ 63 bytes** (PostgreSQL 63, MySQL 64 → safe floor is 63).
3. Name things so you never need quotes (`"..."`, `` `...` ``). Quotes hurt both portability and readability.

## 1. Common Rules

- **snake_case, all lowercase**: `authUser` → `auth_user`, `Book_IDX` → `book_idx`.
- **Descriptive and intuitive**: Names should be self-explanatory. Use `delivery_log` / `order_log`
  instead of vague `log`. Prefer simple words.
- **Time columns use the industry-standard past-participle form**: `created_at` / `updated_at` /
  `deleted_at`. These are the prevailing convention across the Django, Rails, JPA, Prisma, and TypeORM ecosystems
  (not every framework generates them automatically), so they win on portability and collaboration. Other time/date columns use `<purpose>_at` / `<purpose>_date`
  (e.g. `publish_at`, `expire_at`, `open_date`).
  - **Note — the old "active voice" rule is retired.** A prior version forced `create_date`-style active
    voice, but that collides with the `created_at` industry standard. Time columns now follow the
    past-participle standard for portability.
- **No reserved words**: Avoid words reserved in **either** MySQL or PostgreSQL — a word reserved in only
  one engine is still off-limits. Common traps: `user`, `order`, `group`, `table`, `column`, `type`,
  `default`, `check`, `limit`, `offset`, `desc`, `role`.
  ([MySQL keywords](https://dev.mysql.com/doc/refman/8.0/en/keywords.html) ·
  [PostgreSQL keywords](https://www.postgresql.org/docs/current/sql-keywords-appendix.html))

## 2. Table / Column

- **Singular form**: Table names are singular (entity = 1 row, aligns with the `member_id` PK convention).
  `users` → `user` → and since `user` is reserved, `member` (see the reserved-word rule below).
- **No postfix / limited prefix**: `tb_user`, `user_tbl` → `member`. Use a prefix only to group attribute
  tables subordinate to a master table: `member_auth` (child of `member`), `book_like` (child of `book`).
- **Reserved-word collision**: when the singular name is reserved (e.g. `user` in PostgreSQL), **rename
  rather than quote**: `user` → `member`, `order` → `purchase_order` / `order_info`, `group` → `user_group`.
- **M:N join tables**: name as `<table_a>_<table_b>` in **alphabetical order** to prevent duplicate tables
  across the team (`book` × `tag` → `book_tag`). If the relationship has a clear domain meaning, prefer the
  domain name (`book_like`, `member_role`).
- **Lookup (code) tables instead of ENUM**: MySQL `ENUM` / PostgreSQL `enum type` are painful to extend and
  port. Use a **lookup table + FK** named `<domain>_code` or `<domain>_type` (e.g. `order_status_code`).
- **Limited abbreviations**: Avoid abbreviations; if unavoidable, use lowercase and register them in the
  **abbreviation dictionary** (§4) for team-wide use. `create_dt` → `created_date`, `user_cd` → `member_code`.

### Column Prefix/Suffix System

| Purpose | Rule | Example |
|---------|------|---------|
| PK | `<table>_id` | `member_id` |
| FK | `<parent_table>_id` | `member_id` |
| Date (DATE) | `<purpose>_date` | `open_date` |
| Date+Time (DATETIME) | `<purpose>_at` | `publish_at` (create/update/delete → `created_at`/`updated_at`/`deleted_at`) |
| Code | `<purpose>_code` | `member_code` |
| Number | `<purpose>_no` | `order_no` |
| **Boolean** | **`is_` / `has_` prefix** | `is_active`, `is_deleted`, `has_coupon` |

> **Boolean policy.** Use an `is_`/`has_` prefix + a native boolean, **not** the old `use_yn` CHAR(1)
> 'Y'/'N' pattern. Rename `use_yn` → `is_used`, `del_yn` → `is_deleted`. Storage type by engine: PostgreSQL
> `BOOLEAN`, MySQL `TINYINT(1)` 0/1. Legacy Y/N data with heavy app coupling may stay for migration-cost
> reasons, but **new designs must follow the standard.** Do not encode a type in a suffix (`_yn`); name by
> domain meaning.

## 3. Constraint / Index Naming — lowercase prefix

> **Two retired conventions.** (1) An uppercase postfix (`_IDX`) — see below. (2) The full-text prefix
> `ftx_`, now **`fts_`**: `FTX` is not standard terminology, while FTS (Full-Text Search) is what every
> engine's documentation uses. Existing `ftx_*` indexes may remain — rename them when a table is
> already being changed, not in a migration of their own.
>
> A prior version used an uppercase postfix (`_IDX`). That **breaks under PostgreSQL case-folding** and blows
> past the 63-char limit on composite indexes. Use a **lowercase prefix** instead — prefixes also sort by type,
> which helps management. **Always name constraints/indexes explicitly**: engine-generated names (`SYS_C00…`,
> random `fk_…`) are the worst for debugging and portability.

| Type | Rule | Example |
|------|------|---------|
| Primary Key | `pk_<table>` | `pk_member` |
| Foreign Key | `fk_<child>_<parent>` | `fk_order_member` — PostgreSQL only; MySQL creates no physical FK |
| Unique | `uq_<table>_<col…>` | `uq_member_email` |
| Check | `chk_<table>_<rule>` | `chk_order_amount_positive` |
| General index | `idx_<table>_<col…>` | `idx_book_like_member_id` |
| Composite index | `idx_<table>_<col1>_<col2>…` | `idx_actor_first_name_last_name` |
| Fulltext index | `fts_<table>_<col…>` | `fts_book_name` |

**63-char overflow** — when listing every column exceeds 63 chars, shorten in this order:
1. Apply an abbreviation registered in the dictionary (§4) (e.g. `authentication` → `auth`).
2. If still too long, keep the key columns and end with a meaningful suffix
   (`idx_order_member_created_at` → `idx_order_member_created`).
3. Record which rule you applied in a migration-script comment.

## 4. Abbreviation Dictionary

Principle: abbreviate only long words where the abbreviation loses no meaning and is agreed upon. Keep the
list **minimal**.

| Full Term | Abbreviation |
|-----------|--------------|
| number | `no` |
| address | `addr` |
| episode | `ep` |
| transaction | `tx` |
| count | `cnt` |
| authentication | `auth` |
| introduce | `intro` |

## 5. Data Types (by DB)

Type selection varies by DB engine. Follow the **common principles** below, but use the target DB column for
concrete types. See `mysql-guideline` / `postgres-guideline` for deeper type tables. SQLite has no
real types (affinity + `STRICT`) — its conventions live in `sqlite-guideline`; the naming rules here
apply to it unchanged.

### Common Principles (DB-agnostic)

- **PK is integer-based by default**, and its **width follows growth class** — this is one decision you
  cannot cheaply revisit, because widening a PK later is a full table rebuild:
  - **Entity** table (one row per real thing — `member`, `product`): `INT`/`int unsigned` is enough. The
    real world caps the count. Record what caps it.
  - **Event/log** table (one row per occurrence — `*_log`, `*_history`, IoT, audit): **`BIGINT`, no
    exceptions.** Rows = rate × time with no cap, and sequences never reuse values, so retention does
    not reclaim range.
  - Decision procedure and per-engine cost: `rdbms-modeling/references/identifier-selection.md`.
  Reach for UUID when distributed generation across DBs/shards is required (no central
  sequence) **or** an externally visible identifier is needed — and prefer **UUID v7** (time-sortable) over
  random v4. Join keys should be **narrow and type-matched to the parent**, which usually means integer —
  but a UUID PK propagating into children is a supported design, not a violation.
  The reasoning differs by engine: on **InnoDB** the PK *is* the clustering index and is copied into every
  secondary index, so PK width and ordering are storage decisions; on **PostgreSQL** rows live in a heap, so a
  UUID PK costs less — but not nothing, since index locality still applies to write-heavy tables.
  Full criteria in `rdbms-modeling/references/identifier-selection.md`.
  - **MySQL**: `AUTO_INCREMENT`, `UNSIGNED` (never negative). `int unsigned` / `bigint unsigned` by class
  - **PostgreSQL**: `GENERATED ALWAYS AS IDENTITY` (SQL standard; do not use `SERIAL`). No `UNSIGNED`
    exists, so `int` gives 2.1B where MySQL's `int unsigned` gives 4.2B — the event/log threshold
    arrives twice as fast
- **Amounts / settlement**: Floating-point (`float`/`double`/`real`) is **absolutely prohibited** → use
  fixed-point (`DECIMAL` = standard `NUMERIC`). **Size precision/scale per currency and use — never a blanket
  `(10,2)`:**

  | Use | Recommended | Note |
  |-----|-------------|------|
  | KRW amount | `DECIMAL(15, 0)` | KRW has no minor unit → **scale 0** |
  | Multinational amount | `DECIMAL(19, 4)` | covers most currencies (2–4 dp), safe for large sums |
  | Exchange rate / unit price | `DECIMAL(19, 6)` | match to required precision |
  | Ratio (0.1234 = 12.34%) | `DECIMAL(5, 4)` | |

- **JOIN keys**: integer types, and **both sides of a join must have identical types**.
- **Strings**: bounded → `VARCHAR(n)` (`n` sized to real max length); unbounded long text → engine-specific
  large type. `CHAR(n)` only for truly fixed widths (e.g. country code `CHAR(2)`); PostgreSQL gives `CHAR` no
  performance benefit, so do not overuse it.
- **Positive-only columns**: on **MySQL, use `UNSIGNED`** whenever the column cannot hold a negative
  value (PK, counts, quantities, ages). It is not just a constraint — it **doubles the positive range
  for the same bytes** (`int unsigned` reaches 4.2B where `int` stops at 2.1B), which is free runway on
  exactly the columns most likely to run out. PostgreSQL has no `UNSIGNED`, so there the equivalent is
  **`CHECK (col >= 0)`**. Use `CHECK` on MySQL too when cross-engine portability is a stated
  requirement — but do not give up `UNSIGNED` for a portability need nobody has. See
  `mysql-guideline/dev-practices.md` for the signed/unsigned mixing caveats.
- **Avoid NULL**: for indexed columns prefer `NOT NULL` and normalize optional attributes into a joined table.
  Allow NULL only when the data is small or rarely used.
- **Charset**: standardize on UTF-8 — MySQL `utf8mb4`, PostgreSQL `UTF8`.

### Type Mapping

| Purpose | MySQL | PostgreSQL |
|---------|-------|------------|
| Boolean | `TINYINT(1)` 0/1 (`BOOLEAN`/`BOOL` is an alias). No native boolean. Name `is_`/`has_` | **native `boolean`**. 'Y'/'N' strings prohibited |
| PK (auto, integer) | **`AUTO_INCREMENT`**. Width by growth class: entity table `int unsigned`, event/log table `bigint unsigned` | **`GENERATED ALWAYS AS IDENTITY`** (SQL standard — do not use `SERIAL`). Same widths: `int` / `bigint` |
| Amount | `DECIMAL(p,s)` | `numeric(p,s)` |
| Date+Time | `datetime` (+`DEFAULT CURRENT_TIMESTAMP`); `TIMESTAMP` only for auto-UTC ≤ 2038 | `timestamptz` (timezone required) |
| Date | `date` | `date` |
| Long text | `TINYTEXT`(255B)/`TEXT`(64KB)/`MEDIUMTEXT`(16MB)/`LONGTEXT`(4GB) 4 tiers | Variable `text` **single** (no length distinction) |
| JSON | `json` (8.0+ native) | `jsonb` (indexing support, not `json`) |
| Positive-only | **`UNSIGNED`** (doubles the positive range) — add `CHECK (col >= 0)` only if the schema must port | `CHECK (col >= 0)` (no UNSIGNED in PostgreSQL) |
| Fixed display width | (avoid) `ZEROFILL` deprecated 8.0.17 → pad in app/`LPAD` | No display width → app or `LPAD` |
| External ID (not PK) | `binary(16)`, app-generated UUIDv7, `UUID_TO_BIN(v)` **no swap** (swap=1 is v1-only) | `uuid` — `uuidv7()` on PG 18+, else app-generated v7; `gen_random_uuid()` is v4 |
| IPv4 / IPv6 | `int unsigned` via `INET_ATON` / `varbinary(16)` via `INET6_ATON` | `inet` (native) |
| Array | (none → normalize or JSON) | `type[]` (e.g., `text[]`) |

> MySQL-specific: `UNSIGNED`, TEXT 4 tiers, `AUTO_INCREMENT`, `INET6_ATON`/`UUID_TO_BIN`.
> `ZEROFILL` + display width are deprecated (8.0.17); `DECIMAL/FLOAT/DOUBLE UNSIGNED` also deprecated (8.0.17).
> PostgreSQL-specific: native `boolean`, `timestamptz`, `jsonb`, `inet`, arrays, `IDENTITY`, `numeric`.
> Do not mix; apply only the target DB column.

## Bad / Good Summary

| Bad | Good | Reason |
|-----|------|--------|
| `authUser` | `auth_user` | snake_case |
| `Book_IDX` | `idx_book` | lowercase (PG folds uppercase) |
| `users` | `member` | singular form, and `user` is reserved on PostgreSQL |
| `tb_user` | `member` | unnecessary prefix |
| `create_date` (as create time) | `created_at` | past-participle time-column standard |
| `create_dt` | `created_date` | abbreviation overuse |
| `use_yn` CHAR(1) | `is_used` TINYINT(1) / BOOLEAN | boolean prefix + native type |
| `book_user_id_IDX` | `idx_book_user_id` | lowercase prefix, not uppercase suffix |
| `DECIMAL(10,2)` for KRW | `DECIMAL(15,0)` | KRW has no minor unit |

## Related

- `mysql-guideline` — MySQL-specific defaults, types, prohibitions, JDBC, release policy. Based on these rules.
- `postgres-guideline` — PostgreSQL-specific differences (single text type, IDENTITY, no UNSIGNED, etc.).
- `rdbms-modeling` — Applies these conventions for normalization and table design.
- `sqlite-guideline` — SQLite-specific differences (type affinity, `STRICT` tables, rowid PK).
- `rdbms-review` — Audits an existing schema against these conventions and reports violations by severity.
- `db-select` — Picks the engine in the first place (RDBMS vs not, MySQL vs PostgreSQL, scale tier).
