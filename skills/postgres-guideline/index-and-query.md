# Index Strategy and Query Patterns

## Index Cheat Sheet

| Query Pattern | Index Type | Example |
|--------------|------------|---------|
| `WHERE col = value` | B-tree | `CREATE INDEX idx_t_col ON t (col)` |
| `WHERE col > value` | B-tree | `CREATE INDEX idx_t_col ON t (col)` |
| `WHERE a = x AND b > y` | Composite | `CREATE INDEX idx_t_a_b ON t (a, b)` |
| `WHERE jsonb @> '{}'` | GIN | `CREATE INDEX idx_t_col ON t USING gin (col)` |
| `WHERE tsv @@ query` | GIN | `CREATE INDEX idx_t_col ON t USING gin (col)` |
| Time-series ranges | BRIN | `CREATE INDEX idx_t_col ON t USING brin (col)` Note: Effective only when physical insertion order correlates with values (append-only logs). Can be slower than B-tree if insertion order is mixed |
| Range/geo data | GiST | `CREATE INDEX idx_t_col ON t USING gist (col)` |

## Key Index Patterns

These are **shapes, not prescriptions** — every index still needs its justifying query, the plan
that shows the improvement, its write cost, and a rollback (see
`rdbms-modeling/references/index-design.md`).

```sql
-- Composite: equality first, then range
CREATE INDEX idx_chat_history_user_created
  ON log.chat_history (member_id, created_at DESC);

-- Covering index: enables an index-only scan (does NOT guarantee it — the visibility map
-- decides; check Heap Fetches in EXPLAIN ANALYZE)
CREATE INDEX idx ON member (email) INCLUDE (name, created_at);

-- Partial index (smaller, targeted)
CREATE INDEX idx_member_active_email ON app.member (email) WHERE is_active = true;

-- Unique index
CREATE UNIQUE INDEX uq_member_email ON app.member (email);
```

## Query Patterns

### Cursor Pagination (index seek per page, vs OFFSET scanning and discarding)

```sql
-- Simple PK cursor (single id sort)
SELECT product_id, name, created_at FROM product
WHERE product_id > %(last_id)s ORDER BY product_id LIMIT 20;

-- Composite cursor (created_at + id tie-breaking)
-- Guarantees order by id when created_at values are identical
SELECT product_id, name, created_at FROM product
WHERE (created_at, product_id) > (%(last_created_at)s::timestamptz, %(last_id)s)
ORDER BY created_at ASC, product_id ASC
LIMIT 20;

-- Reverse (previous page)
SELECT product_id, name, created_at FROM product
WHERE (created_at, product_id) < (%(last_created_at)s::timestamptz, %(last_id)s)
ORDER BY created_at DESC, product_id DESC
LIMIT 20;
```

> Note: Composite cursor comparison `(a, b) > (x, y)` uses PostgreSQL row comparison and can leverage indexes.
> Recommend a matching index on `(created_at, product_id)`.

### Queue Processing (SKIP LOCKED)

```sql
UPDATE job SET status = 'processing'
WHERE id = (
  SELECT id FROM job WHERE status = 'pending'
  ORDER BY created_at LIMIT 1
  FOR UPDATE SKIP LOCKED
) RETURNING job_id, status, started_at;
```

### UPSERT

```sql
-- Requires the conflict target to be a real unique constraint:
--   CREATE TABLE app.member_setting (
--     member_id bigint NOT NULL,          -- logical FK: app.member.member_id (type matches parent)
--     setting_key text NOT NULL,
--     setting_value text NOT NULL,
--     created_at timestamptz NOT NULL DEFAULT now(),
--     updated_at timestamptz NOT NULL DEFAULT now(),
--     CONSTRAINT pk_member_setting PRIMARY KEY (member_id, setting_key)
--   );
--   CREATE INDEX idx_member_setting_member_id ON app.member_setting (member_id);
INSERT INTO app.member_setting (member_id, setting_key, setting_value, updated_at)
VALUES (%(member_id)s, %(key)s, %(value)s, now())
ON CONFLICT (member_id, setting_key)
DO UPDATE SET setting_value = EXCLUDED.setting_value, updated_at = now();
```

### CTE for Readability

```sql
WITH recent AS (
  SELECT conversation_id, member_id, created_at
  FROM log.chat_history
  WHERE member_id = %(member_id)s AND created_at >= now() - interval '7 days'
),
stats AS (
  SELECT conversation_id, count(*) AS msg_count FROM recent GROUP BY conversation_id
)
SELECT r.conversation_id, s.msg_count
FROM recent r JOIN stats s ON r.conversation_id = s.conversation_id
ORDER BY r.created_at DESC;
```

### Bulk Insert (COPY)

```python
with pool.connection() as conn:
    with conn.cursor() as cur:
        with cur.copy("COPY log.chat_history (member_id, conversation_id, user_message, bot_response) FROM STDIN") as copy:
            for r in records:
                copy.write_row((r['member_id'], r['cid'], r['msg'], r['resp']))
    conn.commit()
```

## Anti-Pattern Detection Queries

```sql
-- Find FK columns with no index LEADING on them (a non-leading appearance does not serve
-- the parent-side lookup, so match indkey[0], not ANY(indkey))
SELECT conrelid::regclass, a.attname
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
WHERE c.contype = 'f'
  AND NOT EXISTS (
    SELECT 1 FROM pg_index i
    WHERE i.indrelid = c.conrelid
      AND i.indkey[0] = a.attnum
      AND i.indisvalid                -- a failed CONCURRENTLY build is not coverage
      AND i.indpred IS NULL           -- a partial index covers only its predicate
  );
-- Multi-column FKs: compare the full conkey vector against the index prefix by hand

-- Find slow queries
SELECT query, mean_exec_time, calls
FROM pg_stat_statements WHERE mean_exec_time > 100
ORDER BY mean_exec_time DESC;

-- Check table bloat
SELECT relname, n_dead_tup, last_vacuum
FROM pg_stat_user_tables WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC;
```

## Query Checklist
- [ ] Parameterized queries (`%(name)s` style)
- [ ] Partition key included in WHERE for partitioned tables
- [ ] `EXPLAIN (ANALYZE, BUFFERS)` checked for complex queries
- [ ] Only needed columns selected (avoid `SELECT *`)
- [ ] `COPY` used for bulk inserts
- [ ] No N+1 query patterns
