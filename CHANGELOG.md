# Changelog

## 0.3.1

Integer PK sizing, corrected. The previous guidance said widening a column later is comparatively
easy — true for an ordinary column, **wrong for a primary key**, which is where it mattered most.

**Fixed**

- **PK type is a one-way decision.** MySQL has no in-place path for changing an integer's type, so
  `ALTER TABLE … MODIFY` on the PK requires `ALGORITHM=COPY`: a full table rebuild, plus a rebuild of
  **every secondary index** (InnoDB appends the PK to all of them). On PostgreSQL,
  `ALTER COLUMN … TYPE bigint` rewrites the table under `ACCESS EXCLUSIVE`. Both cases also require
  every referencing column to move in lockstep — and under this plugin's logical-FK policy those are
  plain columns needing their own migrations.
- **PK size now follows growth class, not current row count.** An *entity* table (one row per real
  thing) is capped by the real world — `member` cannot exceed the human population, so `int unsigned`
  and its 4.2 billion is enough. An *event/log* table has no cap: rows = insert rate × elapsed time.
  At 10,000 inserts/s an `int unsigned` is exhausted in about **five days**. IoT telemetry, audit
  trails, message history, access logs, metering, outbox → `bigint unsigned` from the start.
- **Retention does not reclaim ID space.** `AUTO_INCREMENT` and sequences never reuse values, so
  deleting old rows or dropping old partitions frees storage but not range. A 30-day-retention log
  table burns through the range at the full insert rate as if nothing were ever deleted.
- **`UNSIGNED` is now the MySQL default for non-negative columns.** The old text preferred
  `CHECK (col >= 0)` for portability, which gave up `UNSIGNED` for a requirement nobody had.
  `UNSIGNED` doubles the positive range for the same bytes — free runway on exactly the columns most
  likely to run out. Added the two traps: `UNSIGNED` subtraction below zero **wraps to a huge
  positive value** rather than erroring (absent `NO_UNSIGNED_SUBTRACTION`), and mixing signed with
  unsigned across a join key is a type mismatch.
- `rdbms-naming`'s Bad/Good table had `member` in both columns — a bulk rename had made the example
  teach nothing. Restored to `users` → `member`.
- Example schemas now demonstrate the entity/event contrast (`member` `int unsigned`,
  `chat_history` `bigint unsigned`) instead of applying one type everywhere.

## 0.3.0

Eight rounds of review — Claude self-review plus independent Codex passes — found and fixed 151
issues. Several passes caught bugs introduced by *earlier* fixes, which is why there were eight.

**New**

- `sqlite-guideline` — SQLite 3.37+ as a first-class third engine: type affinity and `STRICT`
  tables, the PRAGMA baseline (`foreign_keys` is OFF by default), single-writer design,
  `INTEGER PRIMARY KEY`/rowid, FTS5, and the growth path back to `db-select`.
- Transaction isolation per engine — InnoDB's `REPEATABLE READ` with gap locks on locking reads
  vs PostgreSQL's `READ COMMITTED` with no gap locks and `40001` serialization failures.
- Multi-tenancy shape in `db-select` — shared tables + `tenant_id`, schema per tenant, database
  per tenant, with the consequences of each.

**Corrected engine claims** (the ones most likely to have misled)

- Dropping an InnoDB FK does **not** drop its auto-created child index — the index survives under
  an auto-generated name, which cleanup jobs then remove.
- FK parent-row shared locks do **not** serialize child writes against each other; they conflict
  with parent-key updates and deletes.
- PostgreSQL has no `ALTER TABLE … SPLIT PARTITION` (proposed, then reverted before release).
- `NOTIFY` takes no bind parameters — use `pg_notify()`; compose `LISTEN` channels with
  `sql.Identifier`.
- Session-level advisory locks are not released by returning a pooled connection; a process crash
  *does* release them.
- `ADD COLUMN … NOT NULL` with no default **fails** on a non-empty table; it does not rewrite it.
- `CREATE INDEX CONCURRENTLY` is PostgreSQL-only and unsupported on a partitioned parent.
- `UUID_TO_BIN`'s swap flag is for UUIDv1 only — applying it to a UUIDv7 destroys its ordering.
- MySQL LTS support is roughly Premier 8y + Extended 3y, and only the `9.7.x` series is LTS.
- Superusers and `BYPASSRLS` roles bypass RLS even under `FORCE ROW LEVEL SECURITY`.

**Ordering bugs in procedures that would break production**

- The `NOT NULL` migration path added its `CHECK` before writers populated the column — a
  `NOT VALID` check still enforces on new writes, so running inserts would fail.
- The column-rename procedure backfilled before deploying dual writes, leaving rows written in
  between with a `NULL`.

**Examples that could not run**

`MySQLConnector` called undefined methods; PostgreSQL `schema-design.md` created the same table
twice; a Prisma schema referenced an undefined model and used `#` for comments; golang-migrate's
`CREATE INDEX CONCURRENTLY` sat inside an implicit transaction; a Django "batched" backfill ran
inside one transaction; advisory-lock snippets used top-level `async with`; a UUID literal
contained ellipses. All Python examples now pass `ast.parse`, and the logical-FK examples were
rewritten against the real psycopg3 and mysql-connector APIs.

**Examples that violated the plugin's own rules**

`SELECT *` in application queries, PostgreSQL `varchar(255)`, reserved and plural table names
(`users`, `orders` → `member`, `purchase_order` per `rdbms-naming`), retired `uidx_`/`ftx_`
prefixes, redundant indexes, join keys whose type did not match the parent, and logical FKs
missing their four compensating controls.

**Other**

- Full-text index prefix `ftx_` → `fts_` (`FTX` is not standard terminology). Existing `ftx_*`
  indexes may remain; rename opportunistically.
- `rdbms-modeling/SKILL.md` compressed 600 → ~510 lines by moving detail into reference files,
  with no behaviour change.
- Session hook now detects MariaDB and SQLite separately, and **asks which engine applies** when
  more than one is present instead of suppressing the question.

## 0.2.0

Added `sqlite-guideline`; first two review passes applied.

## 0.1.0

Initial release. Eight skills shared by Claude Code and Codex, three command pairs, two Claude
Code subagents, and a session-start database-detection hook.
