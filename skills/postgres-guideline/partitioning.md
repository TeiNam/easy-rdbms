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
  chat_history_id bigint GENERATED ALWAYS AS IDENTITY,
  conversation_id char(18) NOT NULL,
  member_id bigint NOT NULL,      -- logical FK: app.member.member_id (type matches parent)
  user_message text NOT NULL,
  bot_response text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
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
CREATE EXTENSION pg_partman;

SELECT partman.create_parent(
  p_parent_table := 'log.chat_history',
  p_control := 'created_at',
  p_type := 'native',
  p_interval := 'monthly',
  p_premake := 3
);

-- Run periodically via cron
SELECT partman.run_maintenance();
```

## Partition Management

> WARNING: creating a partition directly while a `DEFAULT` partition exists makes PostgreSQL
> **scan the default partition** (taking a lock) and error **only if** it holds rows in the new
> range. On an empty or clean default the direct create succeeds — but on a fallen-behind one it
> fails, so the safe sequence is detach → create → **move** → re-attach.

```sql
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
  RETURNING *
)
INSERT INTO log.chat_history
  (chat_history_id, conversation_id, member_id, user_message, bot_response, created_at)
OVERRIDING SYSTEM VALUE
SELECT chat_history_id, conversation_id, member_id, user_message, bot_response, created_at
FROM moved;

-- 4. Re-attach default partition
ALTER TABLE log.chat_history ATTACH PARTITION log.chat_history_default DEFAULT;

-- FAIL: Incorrect approach: errors if default partition contains 2026-10 data
-- CREATE TABLE log.chat_history_2026_10 PARTITION OF log.chat_history
--   FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
-- ERROR: updated partition constraint for default partition "chat_history_default" would be violated

-- Detach old partition (preserves data, faster than DROP)
ALTER TABLE log.chat_history DETACH PARTITION log.chat_history_2026_08;

-- Drop detached partition
DROP TABLE log.chat_history_2026_08;

-- Or move to archive schema
ALTER TABLE log.chat_history_2026_08 SET SCHEMA archive;
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
