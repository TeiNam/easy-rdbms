# Index Strategy and Query Patterns

## Index Types

| Index Type | Use Case | Example |
|-----------|----------|---------|
| B-tree (default) | Equality, range | `CREATE INDEX idx_t_col ON t (col)` |
| Composite | Multi-column WHERE | `CREATE INDEX idx_t_a_b ON t (a, b)` |
| Unique | Duplicate prevention | `CREATE UNIQUE INDEX uq_t_col ON t (col)` |
| Fulltext (ngram) | Text search | `CREATE FULLTEXT INDEX fts_t_col ON t (col) WITH PARSER ngram` |
| Prefix | Long varchar columns | `CREATE INDEX idx_t_col ON t (col(20))` |

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
-- WHERE status='ACTIVE' AND created_at BETWEEN ... ORDER BY member_id
-- status(equality) → member_id(sort) → created_at(range)
CREATE INDEX idx_purchase_order_status_user_created ON purchase_order (status, member_id, created_at);
```

> **Common mistake:** leading with a range column (`(created_at, status)`) — after `created_at` scans a wide
> range, `status` degrades to a per-row filter and the composite index barely helps.

A column wrapped in a function is not seekable (`WHERE YEAR(created_at)=2026` → no index); work around with a
**functional index** (8.0.13+, `CREATE INDEX idx_t_created_year ON t ((YEAR(created_at)))`) or a generated column. The
constant side may use functions freely (`WHERE created_at >= DATE_SUB(NOW(), INTERVAL 1 DAY)` is fine).

## Key Index Patterns

```sql
-- Composite: equality → sort → range
CREATE INDEX idx_chat_history_user_date ON chat_history (member_id, created_at);

-- Unique index
CREATE UNIQUE INDEX uq_member_email ON member (email);

-- Fulltext with ngram parser (Korean/CJK support)
CREATE FULLTEXT INDEX fts_small_talk_search
ON small_talk (eng_sentence, kor_sentence) WITH PARSER ngram;

-- Covering index: WHERE(status) → ORDER BY(created_at) → SELECT additional columns(member_id, total_amount)
-- Place lookup-only columns at end to enable index-only scan
CREATE INDEX idx_purchase_order_status_covering ON purchase_order (status, created_at, member_id, total_amount);
```

## Range-Column Pair Optimization (`start_date` / `end_date`)

Finding rows valid on a date with two range predicates scans unbounded history, because InnoDB effectively
uses **one** range per index scan — once `start_date <= :d` seeks, `end_date` is only an ICP filter, so the
scan widens as data grows:

```sql
-- WRONG: start_date range has no lower bound → scans all past rows
SELECT promotion_id, name, start_date, end_date
FROM promotion WHERE start_date <= '2026-07-17' AND end_date >= '2026-07-17';
```

If the **maximum validity span N is guaranteed** by business rules (e.g. coupons ≤ 90 days), then
`start_date ≤ target ≤ end_date` with `end_date − start_date ≤ N` implies `target − N ≤ start_date ≤ target`
— so you can bound `start_date` on both sides into a single narrow range:

```sql
SET @target := '2026-07-17';
SET @max_days := 90;                     -- business-guaranteed max validity span
SELECT promotion_id, name, start_date, end_date
FROM promotion
WHERE start_date BETWEEN DATE_SUB(@target, INTERVAL @max_days DAY) AND @target
  AND end_date >= @target;               -- now just an ICP filter on the narrowed set
-- backing index: KEY idx_promotion_start_date (start_date)  [or (start_date, end_date) for covering]
```

Scan volume becomes fixed at "last N days" instead of growing forever.

> **Caution:** `N` must be the **truly guaranteed** max span — one longer-lived row and it silently drops from
> results. Enforce with `CHECK (end_date >= start_date AND DATEDIFF(end_date, start_date) <= 90)` (8.0.16+) —
> without the first clause a reversed period yields a negative `DATEDIFF` and passes or app validation. If no max
> span can be guaranteed, use an interval-tree structure, a search engine, or split into a `UNION` instead.

## When an Index Helps, and When It Does Not

Judge from the plan and the data distribution, not from the list — but these are the shapes that
usually decide it.

**Usually worth an index**

| Condition | Why |
|---|---|
| High-cardinality column | One predicate eliminates most rows (PK, email, external UID) |
| Appears often in `WHERE` / `JOIN` / `ORDER BY` / `GROUP BY` | Direct gain from seek or from skipping the sort |
| Queried mainly by `=` or `IN` | The search narrows to exact points |
| A covering index is achievable | Index-only scan — no random I/O back to the clustered index |
| Large table, small result fraction | The bigger the table, the more a seek beats a scan |

**Usually not worth it, or actively harmful**

| Condition | Why |
|---|---|
| Low-cardinality column, indexed alone | Sex, boolean, a 3–4 value status — barely narrows anything, and the optimizer may pick a full scan anyway. **Exception**: a *rare* value (0.5% of rows) that you actually query is selective — decide by skew, not by cardinality alone |
| Small table | A sequential scan beats index seeks; the optimizer knows this |
| The column is wrapped in a function or cast | `WHERE YEAR(created_at) = 2026` is not seekable — use a functional index or generated column |
| Leading wildcard `LIKE '%word'` | No prefix to seek on → full scan |
| Very write-heavy column | Every DML pays the B-tree maintenance (see above) |
| Very high NULL ratio | NULLs cluster into one group, so selectivity collapses |
| Extremely skewed distribution | If one value is most of the table, querying *that* value gets a full scan regardless |
| `OR` across different columns | Single-column indexes force the optimizer onto **Index Merge**, which is often slower than either a rewritten `UNION` or a redesigned composite index |

An `OR` that Index Merge handles badly usually rewrites cleanly:

```sql
-- Index Merge candidate — often slower than the union below
SELECT member_id, email FROM member WHERE email = ? OR phone = ?;

-- Two clean index seeks
SELECT member_id, email FROM member WHERE email = ?
UNION
SELECT member_id, email FROM member WHERE phone = ?;
```

## `IN` — Two Ways It Silently Loses the Index

`WHERE col IN (…)` looks like it must use the index. Two situations turn it into a full scan.

### 1. `IN (subquery)` — when semi-join optimization does not apply

From MySQL 5.6, `IN (subquery)` normally gets **semi-join** treatment: the subquery is
materialized (temporary table plus an index) or run with a `FirstMatch` strategy, so it behaves
like a join. Any of the following disables that and falls back to a **dependent subquery**, which
can re-execute per outer row:

| In the subquery | Effect |
|---|---|
| `GROUP BY` / `HAVING` / an aggregate | Materialization unavailable |
| `UNION` | Not a semi-join candidate |
| `LIMIT` | Not a semi-join candidate |
| The `IN` is under `OR`/`NOT` rather than at the top of the `WHERE` tree | Optimization not applied |

```sql
-- Aggregate in the subquery — semi-join may not apply
SELECT o.purchase_order_id, o.total_amount
FROM purchase_order o
WHERE o.member_id IN (
  SELECT member_id FROM login_history GROUP BY member_id HAVING count(*) > 10
);
```

**Diagnose it**: `EXPLAIN` showing `select_type = DEPENDENT SUBQUERY` is the signal. **Fix it** by
writing the derived table as an explicit join:

```sql
SELECT o.purchase_order_id, o.total_amount
FROM purchase_order o
JOIN (
  SELECT member_id FROM login_history GROUP BY member_id HAVING count(*) > 10
) AS heavy_member ON heavy_member.member_id = o.member_id;
```

### 2. `IN (many literals)` — when the row estimate stops being accurate

The optimizer normally performs an **index dive** per `IN` value — it peeks at the index to
estimate how many rows that value matches. Once the list exceeds `eq_range_index_dive_limit`
(default **200** on MySQL 8.0), it stops diving and falls back to coarse index statistics. The
estimate degrades, and the optimizer becomes more likely to decide a full scan is cheaper.

Also, with thousands of values the statement's own parse and plan cost grows — and if the matched
rows really are a large fraction of the table, the full scan may genuinely be faster.

**A type mismatch is the worse failure**: an integer list against a `varchar` column (or the
reverse) triggers implicit conversion on the *column* side, which defeats the index exactly like
wrapping it in a function.

For large value sets, load them into a temporary table and join — the optimizer plans that far
better than a long literal list:

```sql
CREATE TEMPORARY TABLE tmp_target_member (
  member_id bigint unsigned NOT NULL,
  PRIMARY KEY (member_id)
) ENGINE=InnoDB;

INSERT INTO tmp_target_member (member_id) VALUES (1), (2), (3) /* … */;

SELECT m.member_id, m.email
FROM member m
JOIN tmp_target_member t ON t.member_id = m.member_id;
```

Raising `eq_range_index_dive_limit` widens the dive but costs planning time on every such query —
shortening the list is the better fix.

## Query Patterns

### Parameterized Queries (Required)

```python
def get_member(db, member_id: int):
    return db.execute_raw_query(
        "SELECT member_id, email, is_active, created_at"
        " FROM member WHERE member_id = %(member_id)s",
        {"member_id": member_id},
    )

def list_active_members(db):
    return db.select("member", columns=["member_id", "email"], where={"is_active": 1})
```

### UPSERT (INSERT ... ON DUPLICATE KEY)

```sql
-- MySQL 8.0.19+ row-alias form (VALUES(col) is deprecated on MySQL; see operations.md
-- for the MariaDB/mixed-fleet variant that still uses VALUES(col))
INSERT INTO member_setting (member_id, setting_key, setting_value, updated_at)
VALUES (%(member_id)s, %(key)s, %(value)s, NOW()) AS new
ON DUPLICATE KEY UPDATE
  setting_value = new.setting_value,
  updated_at = NOW();
```

### Batch Insert

```python
db.execute_raw_query("""
    INSERT INTO chat_history (member_id, conversation_id, user_message, bot_response)
    VALUES
    (%(u1)s, %(c1)s, %(m1)s, %(r1)s),
    (%(u2)s, %(c2)s, %(m2)s, %(r2)s)
""", params)
```

### EXPLAIN for Query Analysis

```sql
-- SELECT * allowed for EXPLAIN analysis (execution plan verification purpose)
EXPLAIN SELECT * FROM chat_history
WHERE member_id = 1 AND created_at >= '2024-01-01' AND created_at < '2024-02-01';

EXPLAIN FORMAT=JSON SELECT ...;
```

## Query Checklist
- [ ] Parameterized queries used (SQL injection prevention)
- [ ] Partition key included in WHERE for partitioned tables
- [ ] EXPLAIN checked for complex queries
- [ ] Only needed columns selected (avoid `SELECT *`)
- [ ] Batch INSERT for bulk operations
- [ ] No N+1 query patterns
