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

- Physical DDL or review for a schema stored in SQLite — **new table design still starts in
  `rdbms-modeling`** (its Stage 3 routes here for SQLite targets)
- A local tool, desktop/mobile app, or edge deployment needs persistence
- `database is locked` / `SQLITE_BUSY` errors
- Deciding whether the project has outgrown SQLite

## Version and Baseline

- SQLite **3.37+** (for `STRICT` tables; 2021). Prefer the newest bundled with the driver.
- Configuration is PRAGMAs, not a server config file — and scope matters: some persist in the
  database, most are per-connection:

```sql
-- Persistent database properties (set once; journal_mode survives reconnects)
PRAGMA journal_mode = WAL;      -- readers proceed during a write

-- Connection-local — every connection, every time
PRAGMA foreign_keys = ON;       -- off in default upstream builds (a build with
                                -- SQLITE_DEFAULT_FOREIGN_KEYS flips it) and it is
                                -- per-connection either way: set and verify it every time
PRAGMA busy_timeout = 5000;     -- waits out retryable lock contention. It does NOT cover
                                -- everything: SQLITE_BUSY_SNAPSHOT (a deferred read
                                -- transaction trying to upgrade to a write after another
                                -- writer committed) returns immediately, because waiting
                                -- cannot make that snapshot writable. Use BEGIN IMMEDIATE
                                -- for anything that will write.
PRAGMA synchronous = NORMAL;    -- no corruption with WAL, but the most recent commits can be
                                -- lost on power failure. Data that cannot lose a committed
                                -- transaction uses FULL and pays the fsync
```

**`PRAGMA foreign_keys = ON` is the one everyone forgets.** FK constraints in the DDL are parsed
and stored but **not enforced** unless each connection turns them on. A schema full of
`REFERENCES` clauses with the pragma off has logical FKs wearing physical-FK syntax.

## Type System — Affinity, Not Types

In a non-`STRICT` table, SQLite columns have **type affinity**, not types: outside
`INTEGER PRIMARY KEY` and explicit `CHECK`s, a column accepts values of any type
(`INSERT INTO t (age) VALUES ('abc')` succeeds). This is the largest single divergence from
MySQL/PostgreSQL.

**Declare every ordinary table `STRICT`** (3.37+). Be precise about what it buys: it rejects values
that **cannot be losslessly converted** to the declared storage class, and still performs the lossless
ones — text `'12'` is accepted into an `INTEGER` column, and integer `42` is accepted into a `TEXT`
column and stored as `'42'`. So `STRICT` kills the "any type in any column" behaviour, but it is not
MySQL/PostgreSQL type checking; a `CHECK` is still what enforces a real domain.
(Virtual tables such as FTS5 cannot be `STRICT`; the keyword applies to ordinary tables only.)

```sql
CREATE TABLE member (
  member_id   INTEGER PRIMARY KEY,          -- the rowid; naming a PK constraint is the one
                                            -- place SQLite differs, see Identifiers below
  email       TEXT NOT NULL,
  is_active   INTEGER NOT NULL DEFAULT 1,
  balance_cents INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  -- SQLite supports named UNIQUE and CHECK constraints, so the uq_/chk_ convention applies here
  CONSTRAINT uq_member_email UNIQUE (email),
  CONSTRAINT chk_member_is_active CHECK (is_active IN (0, 1))
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

> **Naming note:** `pk_<table>` does not apply to the rowid alias — `INTEGER PRIMARY KEY` has to be
> written inline to *be* the rowid, and wrapping it in `CONSTRAINT pk_member PRIMARY KEY (member_id)`
> makes it an ordinary key instead. `uq_`/`chk_`/`idx_` names work normally. (MySQL has the same kind
> of exception for a different reason: its PK index is always named `PRIMARY`.)

**In a rowid table, `INTEGER PRIMARY KEY` *is* the rowid** — the table's actual storage key, fast and
auto-assigned, and always 64-bit, which is why the int-vs-bigint sizing problem does not exist here.
This is the default surrogate PK. Two qualifications: the alias needs exactly that spelling (the
historical `INTEGER PRIMARY KEY DESC` is not the rowid), and a **`WITHOUT ROWID` table has no rowid**,
so there an integer primary key is an ordinary key column.

- **`AUTOINCREMENT` is almost always unnecessary** — its guarantee is that a generated rowid is
  strictly greater than every previously **committed** generated rowid (values from rolled-back
  transactions can reappear), at the cost of a bookkeeping table. Use plain `INTEGER PRIMARY KEY` unless ID reuse is a genuine correctness
  problem (e.g., IDs leaked to an external system that must never see a recycled one).
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
- **Multiple processes on one machine: fine. Network storage (NFS, SMB): no.** WAL requires
  same-host shared memory outright, and rollback-journal mode depends on the filesystem's
  locking being honest — historically the unsafe assumption. Multiple machines needing one
  database is a server engine's job.

## Foreign Keys — Physical FKs Are Fine Here

The MySQL prohibition (see `rdbms-modeling/references/foreign-keys.md`) rests on costs SQLite
does not have: there is no partitioning to block, no parent-row lock contention (one writer),
and no online-DDL tooling to break. **Declare physical FKs** — with two rules:

1. `PRAGMA foreign_keys = ON` on **every connection**, verified in code review — otherwise the
   constraints are decorative.
2. Index the referencing column yourself. Like PostgreSQL, **SQLite never auto-creates the
   child index**, and an unindexed FK makes parent deletes scan the child table.

`ON DELETE CASCADE` is acceptable for genuine lifecycle dependency (order → purchase_order_item), same
rule as PostgreSQL. History tables still never take an FK from their entity — that rule is
engine-independent (`rdbms-modeling/references/history-entities.md`).

## Indexes

B-tree only — no GIN/BRIN/hash. What carries over and what replaces them:

- Composite order follows the same conditional rule as the server engines — equality first,
  then sort-or-range by what the query needs (see `rdbms-modeling/references/index-design.md`;
  evidence rules apply unchanged).
- **Partial indexes** work, and are how the plugin-wide soft-delete standard is indexed here:
  `CREATE INDEX idx_member_active_email ON member (email) WHERE is_active = 1`. Use `is_active`,
  not a `deleted_at` of your own — the standard is set in `rdbms-modeling` and applies unchanged.
- **Expression indexes** work: `CREATE INDEX idx_member_email_lower ON member (lower(email))`.
- Covering: put the extra columns at the end of the composite index (no `INCLUDE`).
- Verify with `EXPLAIN QUERY PLAN` — look for `SCAN` on large tables where you expected
  `SEARCH`.
- `PRAGMA optimize;` at connection close keeps the planner statistics fresh.

## Full-Text Search and JSON

- **FTS5** virtual tables provide FTS — but it is a **compile-time option**
  (`SQLITE_ENABLE_FTS5`), so a conforming 3.37+ library can still answer
  `CREATE VIRTUAL TABLE ... USING fts5` with `no such module: fts5`. Verify at startup
  (`SELECT 1 FROM pragma_compile_options WHERE compile_options = 'ENABLE_FTS5'`) rather than
  assuming the version implies it. With the external-content pattern, synchronization
  triggers go **on the content table** (insert/update/delete mirroring into the FTS index) —
  this is the documented FTS5 mechanism, not a business-logic trigger, so it does not violate
  the routine policy. A contentless or content-bearing FTS table changes the maintenance story;
  pick the pattern deliberately.
- JSON: **`json_extract` on the 3.37 baseline** — the `->` and `->>` operators arrived in **3.38**, so
  `->>` is a syntax error on 3.37. On 3.37 the JSON functions also need a build with JSON1 enabled
  (built in by default only from 3.38). Add a **generated column + index** for any queried path:

```sql
-- ALTER TABLE cannot add a STORED generated column in SQLite — use VIRTUAL
-- (STORED is possible only in the original CREATE TABLE, or via a table rebuild)
ALTER TABLE event ADD COLUMN event_type TEXT
  GENERATED ALWAYS AS (json_extract(payload, '$.type')) VIRTUAL;
CREATE INDEX idx_event_type ON event (event_type);
```

## Operations

- **Backup**: `VACUUM INTO 'backup.db'` (online, consistent) or the `.backup` API. Copying the
  file while a writer is active is not a backup — it is a race.
- **Retention**: no partitioning exists. Bounded `DELETE` batches + periodic `PRAGMA
  incremental_vacuum` — note `auto_vacuum = INCREMENTAL` only takes effect if set **before any
  table is created**, or after a full `VACUUM` on an existing database. Alternatively one
  database file per period with `ATTACH` for cross-period reads.
- **Size watch**: `SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size();`
  WAL growth is bounded by checkpointing — unbounded growth means checkpoints are starved
  (a long-lived reader pinning the WAL), disabled, or repeatedly failing.

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
| SQLite on NFS/SMB with multiple writers | A server engine. **WAL is unsupported** across machines outright; rollback-journal mode is only as safe as the filesystem's locking and durability, which many NFS/SMB setups do not implement honestly. So it is a corruption *risk* you cannot verify away, not a guaranteed failure — either way, do not ship it |
| File copy as backup while writes run | `VACUUM INTO` or the backup API |
| Unindexed FK columns | Index the referencing column — never auto-created |

## Related

- `db-select` — Tier 0 placement and when SQLite stops being the answer
- `rdbms-naming` — naming rules apply unchanged; types follow this file's conventions
- `rdbms-modeling` — the three-stage flow applies; Stage 3 routes here for SQLite targets
- `rdbms-review` — reviewing existing SQLite schemas (check the pragma baseline first)
