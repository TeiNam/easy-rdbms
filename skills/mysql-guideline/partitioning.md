# Partitioning Strategy

## Do Not Partition by Default

Partitioning is **recommended from evidence in the code**, not applied because a table looks like it
might grow. The analysis procedure, the recommend/exclude conditions, and the output format are in
`rdbms-modeling/references/partitioning.md`. This file covers the MySQL mechanics.

## Scope: RANGE Family Only — a Deliberate Limitation

MySQL supports `RANGE`, `LIST`, `HASH`, and `KEY` partitioning, and performs partition pruning for
all of them. **This guideline generates only `RANGE` / `RANGE COLUMNS`.** That is a scope decision,
not a claim that the others perform badly: RANGE is where code analysis can establish the need
reliably and where the operational payoff is direct — time-bounded reads, partition-granular
archival, and `DROP PARTITION` instead of a mass `DELETE`. LIST, HASH, and KEY are excluded because
their benefit is narrower and they are easy to misapply.

## Requirements Before Partitioning a Table

1. Partition key is **`NOT NULL`**.
2. **Every `PRIMARY KEY` and `UNIQUE` index contains the partition key** — an InnoDB requirement, and
   the constraint that most often kills a partitioning plan. Check it before committing to the design.
3. **No physical `FOREIGN KEY`** — InnoDB does not allow foreign keys on a partitioned table in
   either direction. (Physical FKs are already prohibited on MySQL; see `dev-practices.md` §5.4.)
4. The partition key appears in the main `WHERE` predicates, or pruning never happens.

## Log Tables: Monthly RANGE COLUMNS Partitioning

Prefer **`RANGE COLUMNS (created_at)`** over an integer expression such as
`RANGE (YEAR(created_at) * 100 + MONTH(created_at))`. Column bounds compare dates directly, keep the
DDL readable, and avoid an expression that every query has to mirror.

```sql
CREATE TABLE `chat_history` (
  `chat_history_id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `conversation_id` char(18) NOT NULL,
  `user_id` int unsigned NOT NULL COMMENT 'logical FK: user.user_id',
  `user_message` text NOT NULL,
  `bot_response` text NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`chat_history_id`, `created_at`),   -- partition key required in the PK
  KEY `idx_chat_history_conversation_id` (`conversation_id`),
  KEY `idx_chat_history_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
PARTITION BY RANGE COLUMNS (created_at) (
  PARTITION p202608    VALUES LESS THAN ('2026-09-01'),
  PARTITION p202609    VALUES LESS THAN ('2026-10-01'),
  PARTITION p202610    VALUES LESS THAN ('2026-11-01'),
  PARTITION p_maxvalue VALUES LESS THAN (MAXVALUE)
);
```

`bigint unsigned` for the PK: log tables are exactly where `int unsigned` exhausts (~4.2 billion).

## Candidate Tables

Append-only, time-queried, retention-bounded tables — chat history, audit logs, access logs. Each
still needs the evidence check: a retention/deletion path in the code and volume figures. A table
that merely *looks* like a log is a candidate, not a decision.

## Partition Management

> WARNING: while a `MAXVALUE` partition exists, `ADD PARTITION` fails —
> `ERROR 1481: MAXVALUE can only be used in last partition definition`.
> Split it with `REORGANIZE PARTITION`, which moves data without loss.

```sql
-- PASS: split p_maxvalue into the new month partition + p_maxvalue
ALTER TABLE chat_history REORGANIZE PARTITION p_maxvalue INTO (
  PARTITION p202611    VALUES LESS THAN ('2026-12-01'),
  PARTITION p_maxvalue VALUES LESS THAN (MAXVALUE)
);

-- FAIL: errors while p_maxvalue exists
-- ALTER TABLE chat_history ADD PARTITION (
--   PARTITION p202611 VALUES LESS THAN ('2026-12-01')
-- );
```

```sql
-- Drop old partition (per data retention policy) — instant, unlike a mass DELETE
ALTER TABLE chat_history DROP PARTITION p202608;
```

### MAXVALUE Is a Safety Net, Not a Load Target

- **Alert when rows land in `p_maxvalue`** — it means partition creation fell behind.
- Pre-create the next **2–3 periods**.
- Move `MAXVALUE` rows into the correct regular partition once it exists, and **never drop
  `p_maxvalue` before that move completes** — it is holding real rows.
- Monitor both the `MAXVALUE` row count and the end date of the last regular partition.

Without the alert, a stalled partition-creation job looks fine until every recent row sits in one
unpruned partition.

## Partition Info Query

```sql
SELECT PARTITION_NAME, PARTITION_DESCRIPTION, TABLE_ROWS, DATA_LENGTH
FROM INFORMATION_SCHEMA.PARTITIONS
WHERE TABLE_NAME = 'chat_history'
AND PARTITION_NAME IS NOT NULL;
```

## Partition Pruning

Always include partition key in WHERE clause:

```python
def get_monthly_chat_history(user_id: int, year: int, month: int):
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month + 1:02d}-01" if month < 12 else f"{year + 1}-01-01"

    return db.execute_raw_query("""
        SELECT * FROM chat_history
        WHERE user_id = %(user_id)s
        AND created_at >= %(start_date)s
        AND created_at < %(end_date)s
        ORDER BY created_at DESC
    """, {"user_id": user_id, "start_date": start_date, "end_date": end_date})
```

## Verify Partition Pruning

```sql
EXPLAIN SELECT * FROM chat_history
WHERE created_at >= '2024-03-01' AND created_at < '2024-04-01';
-- Check "partitions" column shows only p202403
```
