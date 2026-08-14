# Partitioning Strategy

## Log Tables: Monthly Declarative Partitioning

```sql
CREATE TABLE log.chat_history (
  chat_history_id bigint GENERATED ALWAYS AS IDENTITY,
  conversation_id char(18) NOT NULL,
  user_id int NOT NULL,
  user_message text NOT NULL,
  bot_response text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
) PARTITION BY RANGE (created_at);

CREATE TABLE log.chat_history_2024_01 PARTITION OF log.chat_history
  FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE log.chat_history_2024_02 PARTITION OF log.chat_history
  FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

-- Default partition (catches out-of-range data)
CREATE TABLE log.chat_history_default PARTITION OF log.chat_history DEFAULT;

-- Indexes automatically inherited by partitions
CREATE INDEX idx_chat_history_user_id ON log.chat_history (user_id);
CREATE INDEX idx_chat_history_created_at ON log.chat_history (created_at);
```

## Tables That Should Be Partitioned
- `chat_history`: chat logs
- `conversation_session`: conversation sessions (optional)
- `audit_log`: audit logs
- `access_log`: access logs

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

> WARNING: Adding a new partition directly when a `DEFAULT` partition exists will cause an error.
> If the default partition already contains data in that range, constraint violation occurs.
> Always follow the sequence below.

```sql
-- PASS: Correct sequence when DEFAULT partition exists
-- 1. Detach default partition
ALTER TABLE log.chat_history DETACH PARTITION log.chat_history_default;

-- 2. Create new monthly partition
CREATE TABLE log.chat_history_2024_05 PARTITION OF log.chat_history
  FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');

-- 3. Re-attach default partition
ALTER TABLE log.chat_history ATTACH PARTITION log.chat_history_default DEFAULT;

-- FAIL: Incorrect approach: errors if default partition contains 2024-05 data
-- CREATE TABLE log.chat_history_2024_05 PARTITION OF log.chat_history
--   FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');
-- ERROR: updated partition constraint for default partition "chat_history_default" would be violated

-- Detach old partition (preserves data, faster than DROP)
ALTER TABLE log.chat_history DETACH PARTITION log.chat_history_2024_01;

-- Drop detached partition
DROP TABLE log.chat_history_2024_01;

-- Or move to archive schema
ALTER TABLE log.chat_history_2024_01 SET SCHEMA archive;
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
def get_monthly_chat_history(user_id: int, year: int, month: int):
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month + 1:02d}-01" if month < 12 else f"{year + 1}-01-01"

    return db.execute_query("""
        SELECT chat_history_id, conversation_id, user_message, bot_response, created_at
        FROM log.chat_history
        WHERE user_id = %(user_id)s
          AND created_at >= %(start_date)s::timestamptz
          AND created_at < %(end_date)s::timestamptz
        ORDER BY created_at DESC
    """, {"user_id": user_id, "start_date": start_date, "end_date": end_date})
```
