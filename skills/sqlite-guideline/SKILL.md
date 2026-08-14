---
name: sqlite-guideline
description: >
  SQLite 3.37+ schema design, type affinity and STRICT tables, PRAGMA baseline, single-writer
  concurrency, indexes, identifiers, FTS5, JSON, and the growth path to a server engine.
  Triggers: SQLite, sqlite3, better-sqlite3, rusqlite, aiosqlite, STRICT table, type affinity,
  PRAGMA journal_mode WAL, PRAGMA foreign_keys, busy_timeout, database is locked, SQLITE_BUSY,
  rowid, INTEGER PRIMARY KEY, AUTOINCREMENT, WITHOUT ROWID, FTS5, json_extract, VACUUM INTO,
  local database, embedded database, file database, single-file DB, on-device storage,
  desktop app database, CLI tool storage, outgrowing SQLite, migrate SQLite to Postgres.
---

# SQLite Guideline

SQLite is an embedded, single-file engine — the right default for local tools, desktop and
mobile apps, CI, and Tier-0 prototypes (see `db-select`). It is not a smaller MySQL: the type
system, concurrency model, and FK behaviour all differ in ways that bite anyone arriving from a
server engine.

## When to Activate

- Designing or reviewing a schema stored in SQLite
- A local tool, desktop/mobile app, or edge deployment needs persistence
- `database is locked` / `SQLITE_BUSY` errors
- Deciding whether the project has outgrown SQLite

## Version and Baseline

- SQLite **3.37+** (for `STRICT` tables; 2021). Prefer the newest bundled with the driver.
- Every connection runs this baseline — SQLite configuration is **per-connection PRAGMAs**,
  not a server config file:

```sql
PRAGMA journal_mode = WAL;      -- readers proceed during a write; set once per database
PRAGMA foreign_keys = ON;       -- FK enforcement is OFF by default — every connection, every time
PRAGMA busy_timeout = 5000;     -- wait instead of failing immediately with SQLITE_BUSY
PRAGMA synchronous = NORMAL;    -- safe with WAL; FULL only for the most critical data
```

**`PRAGMA foreign_keys = ON` is the one everyone forgets.** FK constraints in the DDL are parsed
and stored but **not enforced** unless each connection turns them on. A schema full of
`REFERENCES` clauses with the pragma off has logical FKs wearing physical-FK syntax.

## Type System — Affinity, Not Types

SQLite columns have **type affinity**, not types: by default any value fits in any column
(`INSERT INTO t (age) VALUES ('abc')` succeeds). This is the largest single divergence from
MySQL/PostgreSQL.

**Declare every table `STRICT`** (3.37+) — it rejects wrong-type values at write time:

```sql
CREATE TABLE member (
  member_id   INTEGER PRIMARY KEY,
  email       TEXT NOT NULL UNIQUE,
  is_active   INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  balance_cents INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;
```

Conventions where SQLite has no native type — pick one per project and `CHECK` it:

| Need | Use | Never |
|---|---|---|
| Boolean | `INTEGER` 0/1 + `CHECK (col IN (0,1))` | `'Y'`/`'N'` strings |
| Timestamp | `TEXT` ISO-8601 UTC (sortable, readable) or `INTEGER` unix epoch — one convention project-wide | Mixing both; local-time strings |
| Money | **`INTEGER` minor units (cents)** — SQLite has no `DECIMAL`; `REAL` is IEEE float | `REAL` for money |
| UUID | `BLOB` (16 bytes) or `TEXT` if debuggability outweighs size | — |
| JSON | `TEXT` + `json_valid()` `CHECK`; generated column + index for queried paths | Queried business fields living only inside JSON |

Naming follows `rdbms-naming` unchanged (snake_case, singular tables, `created_at`/`updated_at`,
lowercase index prefixes).

## Identifiers

**`INTEGER PRIMARY KEY` is the rowid** — the table's actual storage key, fast and auto-assigned.
This is the default surrogate PK.

- **`AUTOINCREMENT` is almost always unnecessary** — it only prevents rowid *reuse* after the
  maximum is deleted, at the cost of a bookkeeping table. Use plain `INTEGER PRIMARY KEY`
  unless rowid reuse is a genuine correctness problem (e.g., IDs leaked to an external system).
- `WITHOUT ROWID` tables suit small lookup tables with a natural non-integer PK; measure before
  using them elsewhere.
- Distributed generation is not SQLite's problem — if multiple nodes generate IDs, you have
  outgrown SQLite (see the growth path below).

## Concurrency — One Writer, Full Stop

SQLite permits **one writer at a time, database-wide**. WAL mode lets readers proceed during a
write, but writers still serialize. Design for it:

- **Keep write transactions short.** A long transaction blocks every other writer — the
  `database is locked` reports almost always trace to this plus a missing `busy_timeout`.
- Use `BEGIN IMMEDIATE` for read-then-write transactions — it takes the write lock up front
  instead of failing at upgrade time.
- One writing connection per process is a sane pattern; serialize writes in the application
  (a queue or a mutex) rather than relying on `busy_timeout` retries under contention.
- **Multiple processes on one machine: fine. Multiple machines on network storage (NFS, SMB):
  no.** File locking on network filesystems is unreliable — this is corruption territory, not a
  performance tradeoff.

## Foreign Keys — Physical FKs Are Fine Here

The MySQL prohibition (see `rdbms-modeling/references/foreign-keys.md`) rests on costs SQLite
does not have: there is no partitioning to block, no parent-row lock contention (one writer),
and no online-DDL tooling to break. **Declare physical FKs** — with two rules:

1. `PRAGMA foreign_keys = ON` on **every connection**, verified in code review — otherwise the
   constraints are decorative.
2. Index the referencing column yourself. Like PostgreSQL, **SQLite never auto-creates the
   child index**, and an unindexed FK makes parent deletes scan the child table.

`ON DELETE CASCADE` is acceptable for genuine lifecycle dependency (order → order_item), same
rule as PostgreSQL. History tables still never take an FK from their entity — that rule is
engine-independent (`rdbms-modeling/references/history-entities.md`).

## Indexes

B-tree only — no GIN/BRIN/hash. What carries over and what replaces them:

- Composite order is the same: equality → range → sort (see
  `rdbms-modeling/references/index-design.md` for the method; evidence rules apply unchanged).
- **Partial indexes** (`WHERE deleted_at IS NULL`) work and are the soft-delete strategy here.
- **Expression indexes** work: `CREATE INDEX idx_member_email_lower ON member (lower(email))`.
- Covering: put the extra columns at the end of the composite index (no `INCLUDE`).
- Verify with `EXPLAIN QUERY PLAN` — look for `SCAN` on large tables where you expected
  `SEARCH`.
- `PRAGMA optimize;` at connection close keeps the planner statistics fresh.

## Full-Text Search and JSON

- **FTS5** virtual tables provide FTS; keep the FTS table in sync with triggers *on the FTS
  table's content options* or the external-content pattern — this is the documented FTS5
  mechanism, not a business-logic trigger, so it does not violate the routine policy.
- JSON: `json_extract` / `->>` plus a **generated column + index** for any queried path:

```sql
ALTER TABLE event ADD COLUMN event_type TEXT
  GENERATED ALWAYS AS (json_extract(payload, '$.type')) STORED;
CREATE INDEX idx_event_type ON event (event_type);
```

## Operations

- **Backup**: `VACUUM INTO 'backup.db'` (online, consistent) or the `.backup` API. Copying the
  file while a writer is active is not a backup — it is a race.
- **Retention**: no partitioning exists. Bounded `DELETE` batches + periodic `PRAGMA
  incremental_vacuum` (with `auto_vacuum = INCREMENTAL` set **before** the tables grow), or one
  database file per period with `ATTACH` for cross-period reads.
- **Size watch**: `PRAGMA page_count * page_size`. WAL file growth is bounded by checkpointing —
  a WAL that grows without bound means a long-lived reader is pinning it.

## The Growth Path

SQLite is out of runway when any of these are true — route back to `db-select`, which will land
on PostgreSQL (Tier 1) in most cases:

- Writers on more than one machine
- Sustained concurrent write contention that serialization cannot absorb
- The database must live on network storage
- Row-level access control, replication, or online schema change becomes a requirement

Design today to make that migration cheap: keep timestamps ISO-8601 UTC, keep money in integer
cents, keep `CHECK` constraints explicit, and avoid rowid-specific tricks in application code —
every one of those maps 1:1 onto PostgreSQL.

## Anti-Patterns

| Anti-pattern | Fix |
|---|---|
| Tables without `STRICT` | `STRICT` on every new table; affinity accepts anything otherwise |
| `REFERENCES` clauses with `foreign_keys` pragma off | Enable per connection, or the FKs are decorative |
| `REAL` for money | `INTEGER` minor units |
| Mixed timestamp conventions (TEXT here, epoch there) | One convention project-wide, `CHECK`ed |
| `AUTOINCREMENT` by reflex | Plain `INTEGER PRIMARY KEY` unless rowid reuse is a real problem |
| Long write transactions | Short transactions + `BEGIN IMMEDIATE` + app-side write serialization |
| SQLite on NFS/SMB with multiple writers | A server engine — this is corruption, not slowness |
| File copy as backup while writes run | `VACUUM INTO` or the backup API |
| Unindexed FK columns | Index the referencing column — never auto-created |

## Related

- `db-select` — Tier 0 placement and when SQLite stops being the answer
- `rdbms-naming` — naming rules apply unchanged; types follow this file's conventions
- `rdbms-modeling` — the three-stage flow applies; Stage 3 routes here for SQLite targets
- `rdbms-review` — reviewing existing SQLite schemas (check the pragma baseline first)
