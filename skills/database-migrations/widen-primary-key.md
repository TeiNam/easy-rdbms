# Widening a Primary Key (MySQL and PostgreSQL) — Not an Ordinary Migration

If a request is "change the PK from `int` to `bigint`", stop and size the work before writing the
migration. There is no cheap path on either engine.

## Contents

- What Each Engine Does
- Before You Start
- The Expand-Contract Route
- PostgreSQL Cutover (Non-Partitioned Table)
- MySQL Cutover

## What Each Engine Does

| Engine | What actually happens |
|---|---|
| MySQL | No in-place path exists for changing an integer's type, so `ALTER TABLE … MODIFY` runs with **`ALGORITHM=COPY`**: full table rebuild, plus a rebuild of **every secondary index** (InnoDB appends the PK to all of them) |
| PostgreSQL | `ALTER COLUMN … TYPE bigint` rewrites the whole table under **`ACCESS EXCLUSIVE`** and rebuilds every index on the column |

And it is never one table. Every referencing column has to change in lockstep — under a logical-FK
policy those are plain columns with no catalog record, so they must be found by grep and migrated
separately, and a signed/unsigned or `int`/`bigint` mismatch left behind silently degrades the join.

## Before You Start

Expect weeks, with application deploys in the middle. **Do not start this without first confirming
the target table is not still accumulating rows faster than the backfill drains** — on a hot
event/log table the backfill can lose the race.

The migration you actually want is the one you avoid: size event/log PKs as `bigint` at
`CREATE TABLE` time. See `rdbms-modeling/references/identifier-selection.md`.

## The Expand-Contract Route

The expand-contract route moves the long backfill and index build out of the final cutover.
The cutover still needs a bounded lock window and a coordinated writer deployment:

```sql
-- 1. Add the wide column, nullable, no default (no rewrite on PostgreSQL; brief lock still required)
--    PostgreSQL — no UNSIGNED exists here:
ALTER TABLE log.chat_history ADD COLUMN chat_history_id_new bigint;
--    MySQL:
-- ALTER TABLE chat_history ADD COLUMN chat_history_id_new bigint unsigned NULL,
--   ALGORITHM=INSTANT;

-- 2. DEPLOY dual writes: both columns carry the SAME ID. Must precede the backfill.
-- 3. Backfill in bounded batches (see "Large Data Migrations" in SKILL.md), monitoring replica lag
-- 4. SET NOT NULL on the new column, add uq_chat_history_id_new, and verify:
--    equal IDs, no NULLs, no duplicates. PostgreSQL preparation is shown below.
-- 5. Widen EVERY referencing column before IDs can exceed the old range.
--    PostgreSQL: rebind physical FKs to the new UNIQUE key and validate before dropping the old PK.
--    MySQL: prepare the wide references and record every FK definition for the write-pause plan below.
-- 6. Drain writers and switch their column mapping with the engine-specific cutover below.
--    Afterwards writers use only the new PK; no reader or FK may depend on the old column.
-- 7. Remove the old column in a later contract migration.
```

Copy the seven steps into your response as a checklist and tick each only when it holds. If the
step 4 checks fail, return to step 3 — or to step 2 when new rows arrive without the wide ID. Do
not begin step 6 until steps 4 and 5 pass.

**Cutover differs by engine, and "swap it in one transaction" is only true on one of them.**

## PostgreSQL Cutover (Non-Partitioned Table)

Prepare the new key while dual writes still maintain it.
Run the concurrent index build outside a transaction wrapper. The validated CHECK avoids a
full-table scan during `SET NOT NULL`.

```sql
ALTER TABLE log.chat_history ADD CONSTRAINT chk_chat_history_id_new_not_null
  CHECK (chat_history_id_new IS NOT NULL) NOT VALID;
ALTER TABLE log.chat_history VALIDATE CONSTRAINT chk_chat_history_id_new_not_null;
ALTER TABLE log.chat_history ALTER COLUMN chat_history_id_new SET NOT NULL;
ALTER TABLE log.chat_history DROP CONSTRAINT chk_chat_history_id_new_not_null;
CREATE UNIQUE INDEX CONCURRENTLY uq_chat_history_id_new
  ON log.chat_history (chat_history_id_new);
```

For each physical FK, add its replacement referencing `chat_history_id_new`, validate it, then
remove the old FK; use the version/partition rules in
`rdbms-modeling/references/foreign-keys.md`. Do this **before** the cutover, never with
`DROP ... CASCADE`. Once old readers and writers are drained, the following DDL is atomic.
Deploy the new writer mapping before resuming writes. The old column becomes nullable because
new INSERTs no longer populate it.

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE log.chat_history DROP CONSTRAINT pk_chat_history;
ALTER TABLE log.chat_history ALTER COLUMN chat_history_id DROP IDENTITY IF EXISTS;
ALTER TABLE log.chat_history ALTER COLUMN chat_history_id DROP DEFAULT;
ALTER TABLE log.chat_history ALTER COLUMN chat_history_id DROP NOT NULL;
ALTER TABLE log.chat_history RENAME COLUMN chat_history_id TO chat_history_id_old;
ALTER TABLE log.chat_history RENAME COLUMN chat_history_id_new TO chat_history_id;
ALTER TABLE log.chat_history
  ADD CONSTRAINT pk_chat_history PRIMARY KEY USING INDEX uq_chat_history_id_new;
-- New inserts generate the wide ID; the empty-table case must start at 1 too.
ALTER TABLE log.chat_history
  ALTER COLUMN chat_history_id ADD GENERATED ALWAYS AS IDENTITY;
SELECT setval(pg_get_serial_sequence('log.chat_history', 'chat_history_id'),
              COALESCE(max(chat_history_id), 1), max(chat_history_id) IS NOT NULL)
FROM log.chat_history;
COMMIT;
```

Verify the first INSERT after cutover, the FK targets, and that only the new PK index remains.
Partitioned parents do not support this `PRIMARY KEY USING INDEX` procedure on PostgreSQL 16–18;
their unique key must also include the partition key. Plan and test that rollout
separately instead of copying this block.

## MySQL Cutover

**DDL cannot be wrapped in a transaction.** Put the parent-column changes in **one**
`ALTER TABLE` so that table is never in a half-swapped state. Plan a write pause for the rebuild.
The full rollout with physical FKs spans multiple committed statements.

**For this COPY cutover, temporarily remove physical FKs that involve the renamed columns.**
MySQL rejects renaming an FK column under `ALGORITHM=COPY`; simply switching this entire ALTER to
`INPLACE` also fails on the tested 8.4 table. Record the definitions, stop **all** writers first,
then drop the affected FKs. For example, if the prepared wide child is
`chat_reference.parent_id bigint unsigned`:

```sql
-- Only when this physical FK exists; all writers remain paused until it is restored below.
ALTER TABLE chat_reference DROP FOREIGN KEY fk_chat_reference_history;
```

```sql
-- Preparation included a UNIQUE index named uq_chat_history_id_new on the new column.
-- Old key here is int unsigned. Wide references are ready; affected physical FKs are removed.
-- This example explicitly chooses COPY and a maintenance window.
ALTER TABLE chat_history
  DROP PRIMARY KEY,
  CHANGE chat_history_id chat_history_id_old int unsigned NULL,
  CHANGE chat_history_id_new chat_history_id bigint unsigned NOT NULL AUTO_INCREMENT,
  DROP INDEX uq_chat_history_id_new,
  ADD PRIMARY KEY (chat_history_id),
  ALGORITHM=COPY;
```

Before resuming writes, recreate and validate every recorded FK against the new wide key.
Keep `foreign_key_checks=1` so the add actually checks existing data:

```sql
ALTER TABLE chat_reference ADD CONSTRAINT fk_chat_reference_history
  FOREIGN KEY (parent_id) REFERENCES chat_history (chat_history_id);
```

If any step fails, keep writers paused and repair the rollout; a partially restored FK set is not
completion. Logical-FK tables skip these FK DDL steps but still need every writer and child type
switched before accepting IDs outside the old range.

An `AUTO_INCREMENT` column must be indexed as a key, which is why the `ADD PRIMARY KEY` has to be in
the same statement — split it and MySQL rejects the intermediate state. Test the first INSERT here
too. For an online-tool alternative, verify `gh-ost` / `pt-online-schema-change` support for the
actual table, FK topology, and ALTER before choosing it.
