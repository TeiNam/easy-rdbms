# Index Strategy and Query Patterns

## Index Types

| Index Type | Use Case | Example |
|-----------|----------|---------|
| B-tree (default) | Equality, range | `CREATE INDEX idx ON t (col)` |
| Composite | Multi-column WHERE | `CREATE INDEX idx ON t (a, b)` |
| Unique | Duplicate prevention | `CREATE UNIQUE INDEX uidx ON t (col)` |
| Fulltext (ngram) | Text search | `CREATE FULLTEXT INDEX ftx ON t (col) WITH PARSER ngram` |
| Prefix | Long varchar columns | `CREATE INDEX idx ON t (col(20))` |

## Composite Index Column Order — "equality → sort → range"

A composite index's leading column is the sort key; later columns only help after earlier ones are narrowed.
Order columns by:

1. **Equality (`=`, `IN`) first** — pins the search to exact points, narrowing the most. Order among several
   equality columns doesn't change narrowing, but put the one reused as a leftmost-prefix by other queries first.
2. **Sort/group columns next** (`ORDER BY`/`GROUP BY`) — if already sorted after equality narrowing, **filesort
   is skipped**. The **direction must match**: `ORDER BY a ASC, b DESC` needs a **descending index**
   (`(a ASC, b DESC)`, 8.0+) or filesort still happens. Note MySQL 8.0 dropped `GROUP BY`'s implicit sort —
   add explicit `ORDER BY` when you need order.
3. **Range last** (`<`, `>`, `BETWEEN`, `LIKE 'x%'`) — any column **after** a range column can't be used for
   index seeking, only as a filter.
4. **Higher cardinality earlier** — but rules 1–3 (query shape) win over raw cardinality.

> The E→S→R order above optimizes for serving `ORDER BY` from the index. When the range predicate
> is **highly selective** and the query does not need index ordering (no `ORDER BY`, or sorting a
> handful of rows is cheap), equality → range wins instead — decide from the plan, not the mnemonic.

```sql
-- WHERE status='ACTIVE' AND created_at BETWEEN ... ORDER BY user_id
-- status(equality) → user_id(sort) → created_at(range)
CREATE INDEX idx_orders_status_user_created ON orders (status, user_id, created_at);
```

> **Common mistake:** leading with a range column (`(created_at, status)`) — after `created_at` scans a wide
> range, `status` degrades to a per-row filter and the composite index barely helps.

A column wrapped in a function is not seekable (`WHERE YEAR(created_at)=2026` → no index); work around with a
**functional index** (8.0.13+, `CREATE INDEX idx ON t ((YEAR(created_at)))`) or a generated column. The
constant side may use functions freely (`WHERE created_at >= DATE_SUB(NOW(), INTERVAL 1 DAY)` is fine).

## Key Index Patterns

```sql
-- Composite: equality → sort → range
CREATE INDEX idx_chat_history_user_date ON chat_history (user_id, created_at);

-- Unique index
CREATE UNIQUE INDEX uq_user_email ON user (email);

-- Fulltext with ngram parser (Korean/CJK support)
CREATE FULLTEXT INDEX fts_small_talk_search
ON small_talk (eng_sentence, kor_sentence) WITH PARSER ngram;

-- Covering index: WHERE(status) → ORDER BY(created_at) → SELECT additional columns(user_id, total_amount)
-- Place lookup-only columns at end to enable index-only scan
CREATE INDEX idx_orders_status_covering ON orders (status, created_at, user_id, total_amount);
```

## Range-Column Pair Optimization (`start_date` / `end_date`)

Finding rows valid on a date with two range predicates scans unbounded history, because InnoDB effectively
uses **one** range per index scan — once `start_date <= :d` seeks, `end_date` is only an ICP filter, so the
scan widens as data grows:

```sql
-- WRONG: start_date range has no lower bound → scans all past rows
SELECT * FROM promotions WHERE start_date <= '2026-07-17' AND end_date >= '2026-07-17';
```

If the **maximum validity span N is guaranteed** by business rules (e.g. coupons ≤ 90 days), then
`start_date ≤ target ≤ end_date` with `end_date − start_date ≤ N` implies `target − N ≤ start_date ≤ target`
— so you can bound `start_date` on both sides into a single narrow range:

```sql
SET @target := '2026-07-17';
SET @max_days := 90;                     -- business-guaranteed max validity span
SELECT * FROM promotions
WHERE start_date BETWEEN DATE_SUB(@target, INTERVAL @max_days DAY) AND @target
  AND end_date >= @target;               -- now just an ICP filter on the narrowed set
-- backing index: KEY idx_promotions_start (start_date)  [or (start_date, end_date) for covering]
```

Scan volume becomes fixed at "last N days" instead of growing forever.

> **Caution:** `N` must be the **truly guaranteed** max span — one longer-lived row and it silently drops from
> results. Enforce with `CHECK (DATEDIFF(end_date, start_date) <= 90)` (8.0.16+) or app validation. If no max
> span can be guaranteed, use an interval-tree structure, a search engine, or split into a `UNION` instead.

## Query Patterns

### Parameterized Queries (Required)

```python
db.execute_raw_query(
    "SELECT user_id, email, is_active, created_at FROM user WHERE user_id = %(user_id)s",
    {"user_id": user_id}
)

db.select("user", columns=["user_id", "email"], where={"is_active": 1})
```

### UPSERT (INSERT ... ON DUPLICATE KEY)

```sql
-- MySQL 8.0.19+ row-alias form (VALUES(col) is deprecated on MySQL; see operations.md
-- for the MariaDB/mixed-fleet variant that still uses VALUES(col))
INSERT INTO user_setting (user_id, setting_key, setting_value, updated_at)
VALUES (%(user_id)s, %(key)s, %(value)s, NOW()) AS new
ON DUPLICATE KEY UPDATE
  setting_value = new.setting_value,
  updated_at = NOW();
```

### Batch Insert

```python
db.execute_raw_query("""
    INSERT INTO chat_history (user_id, conversation_id, user_message, bot_response)
    VALUES
    (%(u1)s, %(c1)s, %(m1)s, %(r1)s),
    (%(u2)s, %(c2)s, %(m2)s, %(r2)s)
""", params)
```

### EXPLAIN for Query Analysis

```sql
-- SELECT * allowed for EXPLAIN analysis (execution plan verification purpose)
EXPLAIN SELECT * FROM chat_history
WHERE user_id = 1 AND created_at >= '2024-01-01' AND created_at < '2024-02-01';

EXPLAIN FORMAT=JSON SELECT ...;
```

## Query Checklist
- [ ] Parameterized queries used (SQL injection prevention)
- [ ] Partition key included in WHERE for partitioned tables
- [ ] EXPLAIN checked for complex queries
- [ ] Only needed columns selected (avoid `SELECT *`)
- [ ] Batch INSERT for bulk operations
- [ ] No N+1 query patterns
