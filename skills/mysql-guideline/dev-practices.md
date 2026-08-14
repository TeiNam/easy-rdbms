# MySQL Development Practices

Principles to follow and anti-patterns to avoid in MySQL projects.
Order: normalization → optimal data types → avoid SP/Trigger → indexes → anti-patterns.

## 1. Data Normalization Required

The essence of relational DB is "split, store, join to output".

- MySQL is an RDBMS — normalization is the fundamental strategy for performance, consistency, and integrity.
  3NF blocks most anomalies (insert/update/delete) in practice.
- More blocks to read one row increases I/O.
- **Stuffing JSON/HTML into one column is an anti-pattern** (see 5.5).
- Use the `rdbms-modeling` skill for normalization level and denormalization decisions.

> **When is denormalization justified?** Normalization is the default. Denormalize only when reads
> vastly outnumber writes **and** JOIN cost is a confirmed bottleneck — e.g. a cache column like
> `orders.total_price`. Requirement: **explicitly define who owns re-syncing** the denormalized value with
> its source (triggers are discouraged in §3 → sync in the application layer or a batch). Without a defined
> sync owner, consistency breaks silently.

## 2. Data Type Selection

### 2.1 Use the Smallest Type

Smaller types bring four benefits: storage space (`TINYINT` 1B vs `INT` 4B → 100 million
rows = 100MB vs 400MB), reduced index size (higher memory load rate → faster searches),
buffer pool and cache efficiency, network bandwidth. Choose the minimal type without
exceeding representable range.

### 2.2 String Types

| | CHAR | VARCHAR | TEXT |
|---|------|---------|------|
| Length | Fixed (≤255 **chars**), padded with trailing spaces | Variable — `n` is **char count** (max `n` bound by 65,535B row limit) | Variable: `tinytext`(255B)/`text`(64KB)/`mediumtext`(16MB)/`longtext`(4GB); large values off-page in InnoDB |
| Pros | Consistent width → less row movement on update | Space efficient | Very large strings |
| Cons | Space wasted on short values, trailing-space trim | — | Prefix index only (`col(100)`); may spill to disk temp table on sort/`GROUP BY` |

Fixed-length codes → `CHAR`, general variable strings → `VARCHAR`, large content not
used in search conditions → `TEXT`.

> **`VARCHAR(n)` — `n` is character count, not bytes** (MySQL 4.1+). `VARCHAR(500)` stores 500 chars even
> in utf8mb4 (unlike Oracle `VARCHAR2(n)`, which is byte semantics by default). **But how large `n` can be
> is bounded by bytes**: the row-wide 65,535B cap means a single utf8mb4 `VARCHAR` column tops out around
> **16,383 chars** (4B/char). Length prefix grows 1B→2B once stored length exceeds 255B. `CHAR(n)` `n` is
> also char count; internal bytes scale with charset.

### 2.3 DATETIME vs TIMESTAMP

| | DATETIME | TIMESTAMP |
|---|----------|-----------|
| Storage | **5B packed binary** (5.6.4+; not a string, not 8B) — value stored as-is, no tz conversion | 4B, UTC epoch — session-tz→UTC on write, UTC→session-tz on read |
| Range | 1000-01-01 ~ 9999-12-31 | 1970-01-01 ~ **2038-01-19 03:14:07 UTC** |
| Timezone | Agnostic (stores value as-is) | Auto-converts by session `time_zone` |
| Fractional sec | +1~3B (`DATETIME(3)` etc.: 1–2 digits +1B, 3–4 +2B, 5–6 +3B) | same +1~3B |
| Use case | Wide range, future/expiry dates, tz-invariant | Global services, `created_at`/`updated_at` UTC + auto-update, ≤ 2038 |

> **Two common myths.** (1) DATETIME is **not** "stored as a string / 8 bytes" — since 5.6.4 it is **5B
> packed binary** (8B was pre-5.6.4). (2) Fractional-second precision adds 1~3B by digit count.

> **Y2038 (danger):** `TIMESTAMP` overflows at 2038-01-19 03:14:07 UTC. Expiry dates or future reservations
> that can cross 2038 **must** use `DATETIME` (or app-managed explicit UTC). Auto-update
> (`DEFAULT CURRENT_TIMESTAMP` / `ON UPDATE CURRENT_TIMESTAMP`) works on **both** types (5.6.5+), so
> "DATETIME + always store UTC in the app" is a valid pattern that sidesteps tz conversion side effects.

### 2.4 Space and Integrity via Functions

- **`INET_ATON` / `INET_NTOA`** — Store IPv4 as `INT UNSIGNED`(4B). Space savings vs string
  + blocks malformed IP (integrity). **IPv4-only** — returns `NULL` for IPv6.
  ```sql
  INSERT INTO ip_log (ip) VALUES (INET_ATON('192.168.0.1'));  -- 3232235521
  SELECT INET_NTOA(ip) FROM ip_log;
  ```
- **`INET6_ATON` / `INET6_NTOA` + `VARBINARY(16)`** — dual-stack (IPv4 + IPv6). Accepts both, returns 4B/16B
  binary. For any environment that might see IPv6, standardize on `VARBINARY(16)` up front.
  ```sql
  INSERT INTO ip_log (ip) VALUES (INET6_ATON('2001:db8::1'));
  SELECT INET6_NTOA(ip) FROM ip_log;
  ```
- **`UUID_TO_BIN` / `BIN_TO_UUID`** — UUID as `BINARY(16)`(36B→16B), faster binary comparison.
  `UUID_TO_BIN(uuid, 1)` (swap_flag=1) reorders v1 timestamp bits to the front → **time-ordered binary** →
  less InnoDB B-tree fragmentation. Readability drops as a JOIN key → integers still preferred for PK (5.2).
  ```sql
  SELECT UUID_TO_BIN(UUID(), 1);  -- time-ordered binary
  ```
  > MySQL `UUID()` is **v1-only** (no v7 as of 2026-07). For time-sortable + globally-unique keys, generate
  > **UUID v7 in the application** and store as `BINARY(16)` (see 5.2).

## 3. Avoid Stored Procedure · Trigger · Event Scheduler

MySQL's stored-program cache is **per-connection (session)**, not shared across connections — there is no
Oracle-style global shared-pool compile cache. Each connection re-parses/compiles on its **first** call and
reuses it only within that connection; the compiled form dies with the connection.

- **Connection-pool interaction**: a pool that churns connections re-pays the "first call" parse cost on
  every new connection. A pool reusing long-lived connections keeps the cache warm from the 2nd call on.
- **So**: "recompiled on *every* call" is an overstatement — but the **lack of a global shared cache** means
  SP caching benefits are weaker than Oracle/PostgreSQL, which (with the reasons below) argues against SP overuse.

Problem areas: maintenance (logic scattered, IDE debugging impossible), portability (DBMS vendor lock-in),
performance (caching integration with Redis etc. difficult, scale-out limitations), productivity (version
control, testing, deployment automation absent), logic duplication (app<->SP consistency degraded), security
(DEFINER/INVOKER confusion; **string-concatenated dynamic SQL inside an SP is an injection risk**). Keep
business logic in the application layer.

## 4. Indexes

### Why They Slow DML

INSERT/UPDATE triggers B-tree node split, merge, reorganization. More indexes = each
updated individually, costs accumulate. Composite indexes consider multiple columns,
making updates costlier than single-column.

### Creation Guidelines

- Create only needed indexes (DML cost <-> query benefit tradeoff).
- Write-heavy LOG tables → single-column index on high-cardinality columns.
- Read speed critical → composite index (ESR/order see `index-and-query`).
- **Function in WHERE clause → index invalidated** (`WHERE DATE(col)=...` → index not used).
  Work around with generated column or functional index.
- **`LIKE '%word'` (leading wildcard) → Full Table Scan** → load, failures. If text search
  is frequent, use Fulltext index; if insufficient, migrate to Elasticsearch.

## 5. Anti-Patterns (What Not to Do)

### 5.1 Using `COUNT(*)` in Validation Logic

**Why InnoDB `COUNT(*)` is not instant — MVCC.** Each transaction sees a different snapshot, so InnoDB
cannot keep one "current visible row count"; it scans the smallest index and counts each time. (MyISAM keeps
row count in metadata → instant `COUNT(*)` without `WHERE` — the origin of "MySQL COUNT is slow".)
Note: "Oracle stores `row_num` so it's fast" is **false** — Oracle also scans or relies on stats.

For an **existence check**, don't total everything — short-circuit:

```sql
-- WRONG: existence via full count
SELECT COUNT(*) FROM orders WHERE user_id = 42;
-- OK: stop at first row
SELECT EXISTS(SELECT 1 FROM orders WHERE user_id = 42);
SELECT 1 FROM orders WHERE user_id = 42 LIMIT 1;
```

For an **approximate total** on a big table, use `information_schema.TABLES.TABLE_ROWS` (InnoDB estimate) or
a counter table/cache. `COUNT(*)` covered by an index can still be fast — the anti-pattern is *totaling to
check existence*, not `COUNT` itself.

### 5.2 Random Keys as PK

MySQL PK is a **clustered index** — physically sorted by PK order. Random keys (UUIDv4 etc.)
trigger page reorganization and splits on every insert, degrading write performance.
**PK should be `INT` family + `AUTO_INCREMENT`** by default. If distributed globally-unique keys are
essential, prefer **UUID v7** (timestamp-based, sortable) generated in the application and stored as
`BINARY(16)` over random v4 — this minimizes index fragmentation. (v1 + `UUID_TO_BIN(…, 1)` is a fallback;
MySQL `UUID()` is v1-only.) Accept reduced FK-JOIN readability either way.

### 5.3 Composite Keys as PK

Composite PK increases index size and search cost, reduces query simplicity and readability,
complicates FK references (multiple columns required), and introduces performance traps via
column order dependencies. **Use single surrogate key (`AUTO_INCREMENT`) as PK**, express
composite uniqueness via UNIQUE constraint/index.

### 5.4 Physical FK Constraints — Do Not Create Them

**Physical `FOREIGN KEY` constraints do not go into the physical model.** Referential integrity
is managed at the application layer, with the relationship documented via `COMMENT` (see
Application-Level Referential Integrity in `schema-design.md`).

Why this is a hard rule rather than a preference:

| Cost | What actually happens |
|---|---|
| **Extra internal I/O on every write** | Each `INSERT`/`UPDATE` on the child does a parent index lookup the query never asked for. Each parent `UPDATE`/`DELETE` scans children. The I/O is invisible in the SQL and unattributable in slow-query analysis |
| **Lock contention and deadlocks** | FK checks take shared locks on the parent row. A hot parent row (a tenant, a category, a config row) serializes unrelated child writes. These locks do not appear where engineers look for them, so the incidents are hard to diagnose |
| **Cascades have unbounded scope** | `ON DELETE CASCADE` turns one statement into an arbitrarily large transaction — long undo, replication lag, lock escalation |
| **Blocks partitioning outright** | InnoDB **cannot** have foreign keys on a partitioned table, in either direction. Since log and history tables are the usual partitioning candidates, an FK today is a blocked partition tomorrow |
| **Breaks online schema change** | `pt-online-schema-change` and `gh-ost` need special handling for FKs, and some paths are unsupported. Routine maintenance turns into a downtime negotiation |
| **Bulk and recovery operations need FK checks disabled** | Loads, backfills, and data repairs run with checks off — which means the guarantee was not there during exactly the operations most likely to corrupt data |

The trade-off is real and must be paid for, not ignored: **without a physical FK, orphan rows
are possible.** Every logical FK therefore requires all four:

1. The reference documented in a `COMMENT` (`logical FK: parent_table.parent_column`)
2. An index on the referencing column — still needed for joins and for parent-side lookups
3. Application-level validation on the write path, with the **owner named** (which service or
   module guarantees it)
4. A periodic orphan check, so violations surface instead of accumulating silently

```sql
-- Orphan detection — schedule this per logical FK
SELECT c.chat_history_id
FROM chat_history c
LEFT JOIN user u ON u.user_id = c.user_id
WHERE u.user_id IS NULL
LIMIT 100;
```

If multiple writers exist (batch, admin tools, external integrations) the integrity owner must
be a shared layer — a service or stored routine all of them go through — not one application's
validation logic. If that layer cannot exist, say so explicitly in the design rather than
quietly relying on a constraint this policy forbids.

### 5.5 JSON Column Overuse

JSON columns add write-time parse/validate overhead, cannot be directly indexed, only validate
"is valid JSON" (not field shape/type — `JSON_SCHEMA_VALID` + CHECK helps, at a cost), limit complex
queries/JOINs, and waste space (binary format, but **keys repeat per row**). **If data is inherently
document-oriented, a document store may be the better fit** — the `db-select` skill has the decision
criteria for leaving an RDBMS.

If you must use JSON (mitigations):
- **Generated Column + index**: extract `col->>'$.field'` into a generated column and index it for that path.
- **Multi-Valued Index** (8.0.17+): index JSON array values directly —
  `CREATE INDEX idx_tags ON t ((CAST(tags->'$[*]' AS CHAR(20) ARRAY)))`.
- Both are stopgaps; if the fields are stable, **normalize into columns/tables** for the real fix.

## Dev Practices Checklist

- [ ] Prioritize normalization; denormalize only with a defined sync owner; no monolithic JSON/HTML columns
- [ ] Select smallest type within representable range (grow later is easy, shrink is not)
- [ ] IPv4 → `INET_ATON`; IPv4/IPv6 → `INET6_ATON`+`VARBINARY(16)`; UUID → `BINARY(16)`, app-generated
      v7 with **no swap flag** (`UUID_TO_BIN(v,1)` is v1-only — swapping a v7 destroys its ordering)
- [ ] Choose DATETIME (5B, >2038 safe) vs TIMESTAMP (4B, auto-UTC, ≤2038) by range + timezone need
- [ ] No SP/Trigger/Event (session-local cache, no global share), logic in app layer
- [ ] Don't invalidate indexes with function conditions or `LIKE '%x'`
- [ ] Existence check with `EXISTS`/`LIMIT 1` instead of `COUNT(*)` (InnoDB MVCC → COUNT scans)
- [ ] PK is `INT`/`BIGINT`+`AUTO_INCREMENT` (avoid random v4; distributed → app UUID v7 BINARY(16); avoid composite PK)
- [ ] FK: **no physical `FOREIGN KEY` constraints.** Logical FK documented in `COMMENT`, referencing
      column indexed, integrity owner named, orphan check scheduled
