# Index Design — MySQL and PostgreSQL

**Indexes are not created on a guess.** Each one costs write throughput, storage, backup size, and
buffer-pool space forever. Recommend from evidence, and say what evidence you had.

## Evidence Required

Ask for what is missing. With gaps, output `needs measurement` — **do not state an expected
improvement percentage.**

- DB product and version, storage engine, charset and collation
- Table DDL: PK, FK, existing indexes
- The actual SQL and its representative bind values
- Total rows, growth rate, table and index sizes
- Cardinality per column and per composite prefix, NULL ratio, value skew
- Read/write QPS, p95 and p99 latency
- MySQL `EXPLAIN ANALYZE`; PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)`
- Rows sorted, temporary tables, disk I/O, cache hit ratio

`EXPLAIN ANALYZE` **executes the statement** on both engines. For anything that modifies data, run it
inside a transaction you roll back, or on a copy.

## Design Order

```text
identify the top-cost queries
→ analyse predicates, joins, sorts, grouping
→ check data distribution and the execution plan
→ draft composite index candidates
→ review write cost and redundancy against existing indexes
→ measure before and after under the same load
→ decide: keep, revise, or drop
```

A composite B-tree candidate starts with equality columns first; then **either** the sort columns (when the query needs the index's ordering — a range column placed earlier makes later columns unusable for ordering) **or** the first range column (when it is highly selective and sorting few rows is cheap); covering columns last. Confirm with the plan. MySQL's classic ESR mnemonic
(equality → sort → range) is the ordering-first branch of the same rule.

A low-cardinality column is not automatically useless — combined with other predicates, or restricted
by a PostgreSQL partial index, it can still be selective.

## Write-Heavy Tables

- Keep only the PK, the required UNIQUE constraints, and the essential read indexes.
- Minimise indexes on frequently-updated columns.
- Avoid wide string columns, JSON, and long covering column lists in indexes.
- Remove redundant and unused indexes — after enough observation to be sure.
- Compare TPS, WAL/binlog volume, locking, replication lag, and storage before and after.

### MySQL / InnoDB

Every secondary index has the PK columns appended internally (index extensions), so **a wide PK
inflates every index on the table**. Keep both the PK and the secondary indexes narrow.

For a drop candidate, switch it to an **invisible index** first — the optimizer stops using it, so you
can observe the plan and workload effect before committing. **Note the limit: an invisible index is
still maintained on every write.** It de-risks the read side, not the write cost.

```sql
ALTER TABLE purchase_order ALTER INDEX idx_purchase_order_status INVISIBLE;
-- observe, then either
ALTER TABLE purchase_order ALTER INDEX idx_purchase_order_status VISIBLE;   -- roll back
ALTER TABLE purchase_order DROP INDEX idx_purchase_order_status;            -- commit
```

### PostgreSQL

A **HOT update** avoids touching indexes entirely, but only when **no indexed column is updated** and
the page has free space (PG 16+ exempts summarizing indexes — a column indexed only by BRIN can
still update HOT). So on a write-heavy table, indexing a frequently-changing column costs more
than the index itself — it disables HOT for those updates. Reduce indexes on churning columns, and
consider lowering `fillfactor` to leave in-page room.

For large, naturally-ordered append tables, **BRIN** on the time or sequence column is worth
evaluating: very small and lossy, effective only when physical order correlates with the value.

## Covering Indexes

| MySQL / InnoDB | PostgreSQL |
|---|---|
| Put WHERE, JOIN, and SELECT columns in the composite index | Use `INCLUDE` columns after the search keys |
| PK is automatically present in every secondary index | Every index is separate from the heap |
| Confirm with `Using index` in `EXPLAIN` | Confirm `Index Only Scan` **and check Heap Fetches** |

PostgreSQL's index-only scan depends on the **visibility map**. On a churning table, heap fetches
continue even with `INCLUDE` columns present — so verify Heap Fetches is actually low rather than
assuming the `INCLUDE` did the job. Wide payload columns increase index size and write cost on both
engines.

## ORDER BY and GROUP BY

```sql
WHERE tenant_id = ? AND status = ?
ORDER BY created_at DESC, id DESC
LIMIT 50
```

First candidate: `(tenant_id, status, created_at DESC, id DESC)`. For deep paging, recommend **keyset
pagination** on the trailing sort keys instead of a large `OFFSET`.

**MySQL** can skip the sort when the composite index's leading columns and the **sort direction** both
match. `filesort` in the plan means an extra sort pass — it does **not** necessarily mean a disk sort.
`GROUP BY` becomes a Loose or Tight Index Scan candidate when the grouping columns form a left prefix
of the same B-tree.

**PostgreSQL**: only B-tree returns sorted output directly. An ordered index helps for small result
sets and `LIMIT` queries; when the query reads most of the table, a sequential scan plus an explicit
sort is often cheaper. For mixed directions, declare them: `(a ASC, b DESC)`.

## Pattern Matching and Avoiding Full Scans

| Search shape | MySQL | PostgreSQL |
|---|---|---|
| `LIKE 'abc%'` | B-tree range scan candidate | B-tree — check collation |
| `LIKE '%abc'` | Plain B-tree unusable | Consider `pg_trgm` GIN/GiST |
| `LIKE '%abc%'` | `FULLTEXT` or a search engine | `pg_trgm`, or full-text search |
| Case-insensitive | Functional index matching the query's expression | Expression index on `lower(col)` |
| Natural language | `MATCH … AGAINST` | `tsvector @@ tsquery` |

**MySQL**: only a constant pattern with no leading wildcard can be used as a B-tree range condition. A
prefix index on a long string reduces size, but when the prefix does not distinguish full values the
engine must still examine the rows.

**PostgreSQL**: for prefix search under a non-C locale, evaluate `text_pattern_ops`. Leading-wildcard
and similarity searches can use `pg_trgm` with GIN or GiST.

## Full-Text Search (FTS)

**MySQL** — `FULLTEXT` index plus `MATCH … AGAINST`. For Korean, Chinese, and Japanese use
`WITH PARSER ngram`, and test token size, stopwords, result accuracy, and index growth before
committing.

```sql
ALTER TABLE article ADD FULLTEXT KEY fts_article_title_body (title, body) WITH PARSER ngram;

SELECT id, title, MATCH(title, body) AGAINST (? IN NATURAL LANGUAGE MODE) AS score
FROM article
WHERE MATCH(title, body) AGAINST (? IN NATURAL LANGUAGE MODE)
ORDER BY score DESC LIMIT 20;
```

**PostgreSQL** — `to_tsvector` and `tsquery`, with **GIN** as the first choice for repeated searches.
**State the text search configuration identically in the index and the query**, or the index will not
be used. Use a stored `tsvector` column or an expression index.

```sql
ALTER TABLE article ADD COLUMN search_vector tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(body,''))) STORED;

CREATE INDEX idx_article_search ON article USING gin (search_vector);

SELECT id, title FROM article
WHERE search_vector @@ to_tsquery('simple', %(q)s);  -- same configuration as the index
```

Naming note: the full-text index prefix is **`fts_`** (see `rdbms-naming`). In prose use **FTS** or the
engine's own keyword `FULLTEXT`. An earlier convention used `ftx_`, which is not standard terminology —
existing `ftx_*` indexes can stay; rename them opportunistically, not in a dedicated migration.

## When to Signal a Move to a Search Engine

**Do not set a fixed row-count threshold.** Take the organisation's own thresholds for: rows searched,
source text size, FTS index size, search QPS, write volume, and p95/p99.

Signal that a dedicated search engine is worth evaluating when:

- A tuned in-database FTS still cannot meet the target latency
- The search index is pressuring database memory, write throughput, or replication
- Typo tolerance, synonyms, autocomplete, morphological analysis, or complex ranking is required
- Unified search across several entities with many facet aggregations is required
- Search load must scale independently of the transactional database

On migrating: **keep the RDBMS as the source of truth**, and design the outbox or CDC path, reindexing,
idempotency, and the eventual-consistency policy together. A search index is not a system of record.

## Verification

**MySQL** — check `sys.statement_analysis` for full scans, rows examined, temporary tables, and sort
volume. When estimates are far from actual, evaluate `ANALYZE TABLE` and column histograms.

```sql
SELECT query, exec_count, rows_examined_avg, rows_sent_avg, tmp_tables, rows_sorted
FROM sys.statement_analysis ORDER BY rows_examined_avg DESC LIMIT 10;

SELECT * FROM sys.schema_unused_indexes;
SELECT * FROM sys.schema_redundant_indexes;
```

**PostgreSQL** — `pg_stat_statements`, planner statistics, and `EXPLAIN (ANALYZE, BUFFERS)`.

```sql
SELECT query, mean_exec_time, calls FROM pg_stat_statements
ORDER BY mean_exec_time DESC LIMIT 10;

SELECT indexrelname, idx_scan FROM pg_stat_user_indexes
WHERE idx_scan = 0 ORDER BY pg_relation_size(indexrelid) DESC;
```

## Output Requirement

**Never emit index SQL alone.** Every recommendation ships with:

1. The query that justifies it
2. Why the columns are in that order
3. The expected read benefit — or `needs measurement` if the evidence was not there
4. The write cost, and any redundancy with existing indexes
5. The execution plan before and after
6. The rollback (drop, or `VISIBLE` restore on MySQL)
7. A search-engine migration signal, if the thresholds were crossed

An index recommendation without the plan that motivated it is a guess with SQL syntax.
