# Partitioning — Recommend From Code, Do Not Create by Default

**Partitioning is not created by default.** Analyse the schema, the queries, and the data-lifecycle
code, then *recommend* a strategy with the evidence that supports it.

If the code alone cannot establish the data volume, **do not generate partitioning** — emit it as a
candidate that needs confirmation, and say what figure is missing.

This mirrors the denormalization rule: a structural cost is paid only against evidence, not against
an expectation.

## What to Analyse

| Source | What you are looking for |
|---|---|
| ORM models and migrations | Table shape, existing indexes, declared retention |
| `WHERE`, `ORDER BY`, aggregate predicates | Whether queries concentrate on a time range — and whether the candidate key actually appears |
| Retention and deletion code | `DELETE ... WHERE created_at < …` is the strongest single signal |
| Batch and archiving jobs | Bulk moves by period, export-then-purge cycles |
| Insert-only vs update-heavy | Append-only tables partition cleanly; update-heavy ones may move rows across partitions |
| Row-count estimates, daily growth, retention window | The volume evidence. Missing → candidate only |
| PK, UNIQUE, FK definitions | Conflicts with the candidate partition key |
| Whether the key can change | A mutable partition key means row movement between partitions |

## Recommend RANGE When Several of These Hold

- Data accumulates continuously — events, logs, history
- A time column (`created_at`, `occurred_at`) is **never updated** after insert
- Reads concentrate on a bounded time range
- Data is purged in bulk once a retention period passes
- The deletion code is shaped like `WHERE created_at < …`
- Backup, archival, or deletion is wanted at partition granularity

**The partition key must appear in the main `WHERE` predicates.** Without that, pruning never
happens and the partitioning is pure overhead — more objects to manage, no read benefit.

## Do Not Recommend Partitioning When

- Access is mostly single-row lookup by PK
- The table is small and grows slowly
- The candidate partition key is updated during normal operation
- It conflicts with a global `UNIQUE` requirement, or with an FK the schema needs
- No time-range query and no retention policy can be found in the code
- The only stated reason is "this table will probably get big"

That last one is the common case. Say plainly that the evidence is not there yet, and name the
threshold that would change the answer. **Derive that threshold, do not invent a row count** — take
whichever of these the project actually has:

- **A retention or deletion SLA.** If rows must disappear after N days and a bulk `DELETE` of one
  day's rows already exceeds the maintenance window (or generates more bloat/vacuum load than the
  window absorbs), that is the threshold — partitioning turns the delete into a `DROP PARTITION`.
- **A measured maintenance limit.** The point where an index rebuild, `VACUUM`, `ANALYZE`, or a
  restore of this one table no longer fits its window. State the current duration and the window.
- **A measured query limit.** A time-ranged read path whose plan already scans far more than the
  range needs, where pruning would cut it — with the plan attached.

If the project has none of the three, the honest output is "no threshold is derivable yet; revisit
when a retention policy or a maintenance window exists", not a number you made up.

## Recommendation Output

```text
Partitioning:   recommended | conditional | not needed
Engine:         MySQL | PostgreSQL
Method:         RANGE | RANGE COLUMNS | LIST | HASH
Partition key:  created_at
Interval:       day | week | month | quarter | year
Confidence:     high | medium | low
Evidence:       the queries and retention code found, with file references
Conflicts:      impact on PK, UNIQUE, FK
Safety part.:   how the trailing partition is created and maintained (MySQL p_maxvalue / PG DEFAULT)
Needs input:    daily growth rate, expected retention window
```

Confidence is **low** whenever the volume figures were assumed rather than found. State the
assumption; do not launder it into a recommendation.

## MySQL Policy — RANGE Family Only

MySQL supports `RANGE`, `LIST`, `HASH`, and `KEY` partitioning, and prunes all of them. **This
plugin generates only `RANGE` / `RANGE COLUMNS` — a deliberate scope limitation, not a technical
one.** RANGE is where code analysis can establish the need reliably and where the operational payoff
is direct: time-bounded reads, partition-granular archival, and `DROP PARTITION` instead of a mass
`DELETE`. LIST, HASH, and KEY are excluded because their benefit is narrower and they are easy to
misapply — not because they are slow. If a project has a specific case for them, that is a decision
to make outside this plugin's defaults.

Rules when generating RANGE on MySQL:

1. Prefer **`RANGE COLUMNS (created_at)`** over an integer expression like
   `RANGE (YEAR(created_at) * 100 + MONTH(created_at))`. Column-based bounds compare dates directly,
   keep the DDL readable, and avoid an expression that has to be mirrored in every query.
2. The partition key must be **`NOT NULL`**.
3. **Every `PRIMARY KEY` and `UNIQUE` index must contain the partition key.** This is an InnoDB
   requirement, and it is the constraint that most often kills a partitioning plan — check it before
   recommending, not after.
4. **No physical `FOREIGN KEY` on a partitioned table** — InnoDB does not permit it in either
   direction. (The MySQL FK policy already prohibits physical FKs; see `foreign-keys.md`.)
5. Always end with a **`MAXVALUE`** partition.

```sql
CREATE TABLE event (
  event_id   bigint unsigned NOT NULL AUTO_INCREMENT,
  event_type varchar(64) NOT NULL,
  payload    json NOT NULL,
  created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (event_id, created_at),         -- partition key required in the PK
  KEY idx_event_type_created (event_type, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
PARTITION BY RANGE COLUMNS (created_at) (
  PARTITION p202608     VALUES LESS THAN ('2026-09-01'),
  PARTITION p202609     VALUES LESS THAN ('2026-10-01'),
  PARTITION p_maxvalue  VALUES LESS THAN (MAXVALUE)
);
```

### Adding Partitions: REORGANIZE, Not ADD

While a `MAXVALUE` partition exists, `ADD PARTITION` fails — `MAXVALUE` can only be the last
definition. Split it instead; `REORGANIZE PARTITION` moves the data without loss.

```sql
ALTER TABLE event REORGANIZE PARTITION p_maxvalue INTO (
  PARTITION p202610    VALUES LESS THAN ('2026-11-01'),
  PARTITION p_maxvalue VALUES LESS THAN (MAXVALUE)
);
```

Retention drop:

```sql
ALTER TABLE event DROP PARTITION p202608;
```

## PostgreSQL Policy — RANGE, LIST, or HASH

PostgreSQL may use whichever fits the access pattern found in the code:

| Method | Recommend when |
|---|---|
| `RANGE` | Time-range reads, retention, bulk deletion |
| `LIST` | A small, fixed set of values — region, business line |
| `HASH` | High-cardinality equality lookups needing even distribution |

For `RANGE`, always create a trailing safety partition — and on PostgreSQL that means **`DEFAULT`,
not `TO (MAXVALUE)`**:

```sql
CREATE TABLE event_default PARTITION OF event DEFAULT;
```

| | Catches future rows | Catches rows **below** the first partition |
|---|---|---|
| `FOR VALUES FROM (x) TO (MAXVALUE)` | Yes | **No** — the insert fails |
| `PARTITION OF … DEFAULT` | Yes | **Yes** |

A backfill or a corrected timestamp predating the first partition is exactly what a safety partition
should absorb, and `MAXVALUE` bounds reject it. Both carry the same operational constraint, so
`DEFAULT` costs nothing extra.

**The safety partition covers the range you want to add next.** Creating the new partition directly
makes PostgreSQL scan the catch-all and succeeds **only if** it holds no rows in that range (a
matching `CHECK` on the default partition can prove emptiness and skip the scan). On a
fallen-behind default it fails, so the reliable procedure is:

1. `DETACH` the default partition
2. Create the new regular partition for the next period
3. Move any rows that landed in the detached partition into it
4. Re-`ATTACH` the default partition

(`SPLIT PARTITION` was proposed for core PostgreSQL and reverted before release — do not assume it
exists. The detach-and-move procedure above is the reliable path on 16, 17, and 18.)

## Safety-Partition Operating Rules

The trailing partition — `p_maxvalue` on MySQL, `DEFAULT` on PostgreSQL — is a **safety net against
dropped rows, not a normal load target.**

- **Alert when data lands in it.** It means partition creation fell behind, or data is arriving
  outside the expected window.
- Pre-create the next **2–3 periods** of regular partitions.
- Move its rows into the correct regular partition once that partition exists.
- **Never drop it before that move completes** — it is holding real rows.
- Monitor two things: rows accumulating in the safety partition, and the end date of the last
  regular partition.

Without the alert, a partition-creation job that silently stops looks fine until every recent row is
in one unpruned partition.

## Verify Pruning

Recommending partitioning without checking that pruning happens is half the work.

```sql
-- MySQL: the "partitions" column should list only the expected ones
EXPLAIN SELECT event_id, event_type, created_at FROM event
WHERE created_at >= '2026-09-01' AND created_at < '2026-10-01';

-- PostgreSQL: the plan should show only the matching partitions scanned
EXPLAIN SELECT event_id, event_type, created_at FROM event
WHERE created_at >= '2026-09-01' AND created_at < '2026-10-01';
```

A query that omits the partition key scans every partition. If the application's main read path
cannot include the key, the partitioning recommendation was wrong.
