# Partitioning Strategy

## Do Not Partition by Default

Partitioning is **recommended from evidence in the code**, not applied because a table looks like it
might grow. The analysis procedure, recommend/exclude conditions, and output format are in
`rdbms-modeling/references/partitioning.md`. This file covers the PostgreSQL mechanics.

## Scope: RANGE, LIST, or HASH

Unlike the MySQL guideline (RANGE family only, by deliberate scope decision), PostgreSQL may use
whichever method the code's access pattern calls for:

| Method | Use when |
|---|---|
| `RANGE` | Time-range reads, retention, bulk deletion — the common case |
| `LIST` | A small, fixed set of values: region, business line, tenant class |
| `HASH` | High-cardinality equality lookups needing even distribution |

## The Safety Partition: `DEFAULT`, Not `TO (MAXVALUE)`

Both give you a trailing catch-all, but they are not equivalent:

| | Catches future rows | Catches rows **below** the first partition |
|---|---|---|
| `FOR VALUES FROM (x) TO (MAXVALUE)` | Yes | **No** — insert fails |
| `PARTITION OF … DEFAULT` | Yes | **Yes** |

**Use `DEFAULT` on PostgreSQL.** A backfill or a corrected timestamp that predates the first
partition is exactly the kind of row a safety partition should absorb, and `MAXVALUE` bounds reject
it. Both share the same operational constraint — creating a partition whose range the catch-all
already covers makes PostgreSQL scan it (see Partition Management below) — so `DEFAULT` costs
nothing extra.

### Operating Rules

- **Alert when rows land in the default partition.** It means partition creation fell behind, or data
  is arriving outside the expected window.
- Pre-create the next **2–3 periods** of regular partitions.
- Move default-partition rows into the correct regular partition once it exists.
- **Never drop the default partition before that move completes** — it is holding real rows.
- Monitor both the default-partition row count and the end date of the last regular partition.

Without the alert, a stalled partition-creation job looks fine until every recent row sits in one
unpruned partition.

(`SPLIT PARTITION` was proposed for core PostgreSQL and reverted before release — do not assume it
exists on any current version. Use the detach sequence below on 16, 17, and 18.)

## Log Tables: Monthly Declarative Partitioning

```sql
CREATE TABLE log.chat_history (
  chat_history_id bigint GENERATED ALWAYS AS IDENTITY,  -- event table: rows = rate x time, unbounded
  conversation_id char(18) NOT NULL,
  member_id int NOT NULL,         -- logical FK: app.member.member_id (type matches parent)
  user_message text NOT NULL,
  bot_response text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  -- PostgreSQL requires the partition key in every unique constraint on a partitioned table,
  -- so the PK is (id, created_at) rather than id alone.
  CONSTRAINT pk_chat_history PRIMARY KEY (chat_history_id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE log.chat_history_2026_08 PARTITION OF log.chat_history
  FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE log.chat_history_2026_09 PARTITION OF log.chat_history
  FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');

-- Default partition (catches out-of-range data)
CREATE TABLE log.chat_history_default PARTITION OF log.chat_history DEFAULT;

-- Indexes automatically inherited by partitions
CREATE INDEX idx_chat_history_member_id ON log.chat_history (member_id);
CREATE INDEX idx_chat_history_created_at ON log.chat_history (created_at);
```

## Candidate Tables

Append-only, time-queried, retention-bounded tables — chat logs, audit logs, access logs. Each is a
**candidate**, not a decision: the evidence rules apply (time-range queries and retention/deletion
code present, volume figures known — see the recommendation policy referenced above).

## pg_partman (Recommended)

```sql
-- pg_partman 5.x (the 4.x-era `p_type := 'native'` argument is gone)
CREATE SCHEMA IF NOT EXISTS partman;
CREATE EXTENSION pg_partman SCHEMA partman;

SELECT partman.create_parent(
  p_parent_table := 'log.chat_history',
  p_control      := 'created_at',
  p_interval     := '1 month',
  p_premake      := 3
);

-- Run periodically (external cron, or pg_cron where available)
SELECT partman.run_maintenance();
```

Check the installed version — the `create_parent` signature changed between 4.x and 5.x.

## Partition Management

> WARNING: creating a partition directly while a `DEFAULT` partition exists makes PostgreSQL
> **scan the default partition** (taking a lock) and error **only if** it holds rows in the new
> range. On an empty or clean default the direct create succeeds — but on a fallen-behind one it
> fails, so the safe sequence is detach → create → **move** → re-attach.

> **Wrap the whole sequence in one transaction.** Between the `DETACH` and the re-`ATTACH` the table
> has no default partition, so any insert whose `created_at` falls outside the existing regular bounds
> fails with `no partition of relation ... found for row`. Statement-by-statement (autocommit) this is
> a write outage of however long the row move takes. One transaction holds the locks throughout —
> which blocks writers instead of failing them — so run it off peak with a `lock_timeout`, or use the
> low-lock variant below that avoids the detach entirely.

```sql
BEGIN;
-- PASS: Correct sequence when DEFAULT partition exists
-- 1. Detach default partition
ALTER TABLE log.chat_history DETACH PARTITION log.chat_history_default;

-- 2. Create new monthly partition
CREATE TABLE log.chat_history_2026_10 PARTITION OF log.chat_history
  FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');

-- 3. Move rows for the new range OUT of the detached default — without this,
--    re-attach fails validation if any 2026-10 rows are present
--    Note: chat_history_id is GENERATED ALWAYS, so re-inserting its value needs
--    OVERRIDING SYSTEM VALUE and an explicit column list
WITH moved AS (
  DELETE FROM log.chat_history_default
  WHERE created_at >= '2026-10-01' AND created_at < '2026-11-01'
  RETURNING chat_history_id, conversation_id, member_id, user_message, bot_response, created_at
)
INSERT INTO log.chat_history
  (chat_history_id, conversation_id, member_id, user_message, bot_response, created_at)
OVERRIDING SYSTEM VALUE
SELECT chat_history_id, conversation_id, member_id, user_message, bot_response, created_at
FROM moved;

-- 4. Re-attach default partition
ALTER TABLE log.chat_history ATTACH PARTITION log.chat_history_default DEFAULT;
COMMIT;

-- LOW-LOCK VARIANT: no detach at all. If the default partition carries a valid CHECK proving it
-- holds no rows in the new range, PostgreSQL can skip scanning it, so the plain CREATE succeeds:
--   ALTER TABLE log.chat_history_default ADD CONSTRAINT chk_chat_history_default_excl_2026_10
--     CHECK (created_at < '2026-10-01' OR created_at >= '2026-11-01') NOT VALID;
--   ALTER TABLE log.chat_history_default VALIDATE CONSTRAINT chk_chat_history_default_excl_2026_10;
--   -- now CREATE TABLE ... PARTITION OF ... FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
--   -- then drop the helper constraint.
-- This only works when the default really holds no such rows; if it does, move them first.

-- FAIL: Incorrect approach: errors if default partition contains 2026-10 data
-- CREATE TABLE log.chat_history_2026_10 PARTITION OF log.chat_history
--   FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
-- ERROR: updated partition constraint for default partition "chat_history_default" would be violated

-- Detach the old partition first (preserves data, and detaching is cheaper than DROP)
ALTER TABLE log.chat_history DETACH PARTITION log.chat_history_2026_08;

-- Then EITHER discard it...
DROP TABLE log.chat_history_2026_08;

-- ...OR keep it by moving it to an archive schema. These two are mutually exclusive —
-- once dropped there is nothing left to move.
-- ALTER TABLE log.chat_history_2026_08 SET SCHEMA archive;
```

> Note: This process is automated when using pg_partman — manual operations only when needed.

## Partition Info Query

```sql
SELECT
  c.relname AS partition_name,
  pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
  pg_stat_get_live_tuples(c.oid) AS row_count
FROM pg_inherits i
JOIN pg_class c ON c.oid = i.inhrelid
JOIN pg_class p ON p.oid = i.inhparent
WHERE p.relname = 'chat_history'
ORDER BY c.relname;
```

## Partition Pruning

Always include partition key in WHERE clause:

```python
def get_monthly_chat_history(member_id: int, year: int, month: int):
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month + 1:02d}-01" if month < 12 else f"{year + 1}-01-01"

    return db.execute_query("""
        SELECT chat_history_id, conversation_id, user_message, bot_response, created_at
        FROM log.chat_history
        WHERE member_id = %(member_id)s
          AND created_at >= %(start_date)s::timestamptz
          AND created_at < %(end_date)s::timestamptz
        ORDER BY created_at DESC
    """, {"member_id": member_id, "start_date": start_date, "end_date": end_date})
```
