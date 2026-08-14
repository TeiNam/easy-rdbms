# Operations: MariaDB Divergence, Diagnostics, Replication, Security, Config

Covers the runtime and operational side that `schema-design.md` / `index-and-query.md` /
`connection-and-features.md` do not: engine divergence, lock diagnostics, replica lag,
grants, and server configuration.

## Engine and Version Check First

```sql
SELECT VERSION();
SHOW VARIABLES LIKE 'version_comment';
```

MySQL and MariaDB have diverged in SQL details. Confirm the engine before applying a
version-specific pattern.

| Feature | MySQL 8.0+ | MariaDB |
|---|---|---|
| Referencing inserted values in `ON DUPLICATE KEY UPDATE` | Row alias `AS new` (`VALUES(col)` deprecated) | `VALUES(col)` is the documented form |
| Cross-engine safe choice | — | Use `VALUES(col)` for mixed fleets |

```sql
-- MySQL row-alias form (confirm target is MySQL first)
INSERT INTO user_setting (user_id, setting_key, setting_value)
VALUES (?, ?, ?) AS new
ON DUPLICATE KEY UPDATE
  setting_value = new.setting_value,
  updated_at = NOW();
```

## Keyset Pagination

Deep `OFFSET` makes the server scan and discard rows before returning the page. Use a
cursor whose columns match a backing index.

```sql
SELECT id, name, created_at
FROM product
WHERE (created_at, id) < (?, ?)
ORDER BY created_at DESC, id DESC
LIMIT 50;

CREATE INDEX idx_product_created_id ON product (created_at, id);
```

The tie-breaker column (`id`) is required — without it, rows sharing a `created_at`
value can be skipped or repeated across pages.

## Full-Text Search Query

Index creation (with the `ngram` parser for Korean/CJK) is in `index-and-query.md`.
The query side:

```sql
SELECT id, title, MATCH(title, body) AGAINST (? IN NATURAL LANGUAGE MODE) AS score
FROM article
WHERE MATCH(title, body) AGAINST (? IN NATURAL LANGUAGE MODE)
ORDER BY score DESC
LIMIT 20;
```

Move to an external search engine when you need typo tolerance, complex ranking,
cross-table facets, or language analysis beyond the built-in parsers.

## Transaction Isolation — InnoDB Defaults to REPEATABLE READ

InnoDB's default is **`REPEATABLE READ`**, and unlike most engines it prevents phantoms at RR by
using **gap locks and next-key locks** — which are also the most common deadlock source that
surprises teams coming from other databases.

| Symptom | Cause at RR |
|---|---|
| Deadlocks on concurrent `INSERT`s near the same index range | Gap locks taken by locking reads / `INSERT ... SELECT` |
| Lock waits with no row conflict visible | Next-key lock covers the *gap*, not just the row |
| A plain `SELECT` sees stale data mid-transaction | Consistent snapshot from first read — by design |

Practical rules:

- **High-concurrency OLTP often runs better at `READ COMMITTED`** — gap locks largely disappear.
  Requirement: effective row-based logging — `binlog_format = ROW` (the 8.x default; `MIXED`
  auto-switches to row for RC statements, `STATEMENT` is unsafe). Set per session or globally,
  and record the choice in the design.
- A locking read (`FOR UPDATE` / `FOR SHARE`) at RC reads the **latest committed** row, not the
  transaction snapshot — SELECT-then-act logic must tolerate that.
- Do not mix isolation levels across services touching the same tables without documenting it —
  the deadlock behaviour differs per level and debugging assumes one.
- `SERIALIZABLE` on InnoDB converts plain reads into locking reads (when autocommit is disabled);
  it is rarely the right tool — prefer explicit `FOR UPDATE` on the rows that matter.

```sql
SELECT @@transaction_isolation;
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
```

## Locking, Deadlocks, and Queues

Lock rows in a deterministic order across every code path:

```sql
START TRANSACTION;

SELECT id, balance
FROM account
WHERE id IN (?, ?)
ORDER BY id            -- deterministic order prevents lock-cycle deadlocks
FOR UPDATE;

UPDATE account SET balance = balance - ? WHERE id = ?;
UPDATE account SET balance = balance + ? WHERE id = ?;

COMMIT;
```

Deadlock and lock-wait checklist:

- Lock rows in a deterministic order across code paths.
- Do external API calls **before** opening the transaction, never inside it.
- Index the predicates used in `UPDATE`, `DELETE`, and locking reads — an unindexed
  predicate escalates to a much wider lock range.
- On deadlock, roll back and retry the whole transaction with a bounded retry budget.
- Capture `SHOW ENGINE INNODB STATUS\G` immediately after a deadlock; it holds only the
  most recent one and is overwritten by later events.

Queue-style worker claim:

```sql
START TRANSACTION;

SELECT id
FROM job
WHERE status = 'pending'
ORDER BY created_at
LIMIT 1
FOR UPDATE SKIP LOCKED;

UPDATE job
SET status = 'processing', started_at = NOW()
WHERE id = ?;

COMMIT;
```

`SKIP LOCKED` skips locked rows and therefore returns an inconsistent view. Use it for
queue-like claims only — never for accounting, balance, or integrity-sensitive reads.

## Connection Pool Sizing (Node.js and the wait_timeout Rule)

Python pools are in `connection-and-features.md`. Node.js `mysql2`:

```javascript
import mysql from 'mysql2/promise';

const pool = mysql.createPool({
  host: process.env.DB_HOST,
  user: process.env.DB_USER,
  password: process.env.DB_PASSWORD,
  database: process.env.DB_NAME,
  waitForConnections: true,
  connectionLimit: 10,
  queueLimit: 0,
  enableKeepAlive: true,
  keepAliveInitialDelay: 30000,
});

const [rows] = await pool.execute(
  'SELECT id, total_amount FROM orders WHERE account_id = ? LIMIT 50',
  [accountId],
);
```

**Recycle below the server timeout.** If the server has `wait_timeout = 300`, set client
recycling around 240s. A pool that recycles *above* `wait_timeout` hands out connections
the server has already closed. Keep a pre-ping/liveness check as well — it is what
recovers the pool after a network blip or Aurora failover.

## Diagnostics

First-pass commands:

```sql
SHOW FULL PROCESSLIST;
SHOW ENGINE INNODB STATUS\G;
SHOW VARIABLES LIKE 'slow_query_log';
SHOW VARIABLES LIKE 'long_query_time';
```

Enable the slow log in a controlled (non-production-peak) window:

```sql
SET GLOBAL slow_query_log = 'ON';
SET GLOBAL long_query_time = 1;
SET GLOBAL log_queries_not_using_indexes = 'ON';
```

`EXPLAIN ANALYZE` **executes** the statement. Use it only when running the query is safe;
on production-sized data it can be expensive. Prefer plain `EXPLAIN` / `EXPLAIN FORMAT=JSON`
for plan inspection.

## Replication and Replica Lag

Read replicas lag. Do **not** route these to a replica right after a write:

- read-your-own-write paths
- checkout / payment flows
- permission and entitlement checks
- idempotency-key reads

```sql
-- Newer terminology where supported
SHOW REPLICA STATUS\G;

-- Legacy terminology, still present in existing fleets
SHOW SLAVE STATUS\G;
```

Check the engine and version before standardizing on one command. Monitor the replication
SQL thread health, IO thread health, and lag — not merely whether the TCP connection is up.

## Security and Grants

```sql
CREATE USER 'app'@'%' IDENTIFIED BY 'use-a-secret-manager';
GRANT SELECT, INSERT, UPDATE, DELETE ON appdb.* TO 'app'@'%';

ALTER USER 'app'@'%' REQUIRE SSL;

-- Anonymous accounts allow unauthenticated local access
SELECT user, host FROM mysql.user WHERE user = '';
DROP USER IF EXISTS ''@'localhost';
DROP USER IF EXISTS ''@'%';
```

Review points:

- Never grant `ALL PRIVILEGES` or `*.*` to a runtime application user.
- Require TLS for application users whenever traffic crosses hosts or networks.
- Store credentials in the platform secret manager — not in scripts, examples, or the repo.
- Keep migration/admin users separate from runtime application users.
- Audit public network exposure and `bind_address` before tuning performance.
- Use `CREATE USER` / `ALTER USER` / `DROP USER`. Direct DML against `mysql.user` risks
  corrupting the grant tables.

## Server Configuration Baseline

```ini
[mysqld]
innodb_buffer_pool_size = 4G
innodb_flush_log_at_trx_commit = 1
sync_binlog = 1

max_connections = 300
thread_cache_size = 50

wait_timeout = 300
interactive_timeout = 300
innodb_lock_wait_timeout = 10

slow_query_log = ON
long_query_time = 1
log_queries_not_using_indexes = ON

log_bin = mysql-bin
binlog_format = ROW
binlog_expire_logs_seconds = 604800
```

Treat these as a prompt for review, not a universal preset. Size memory, connections, log
retention, and durability from the actual workload, hardware, backup policy, and recovery
objectives.

## Operational Anti-Patterns

| Anti-Pattern | Risk | Better |
|---|---|---|
| Deep `OFFSET` pagination | Linear scan per page | Keyset pagination |
| Unindexed FK join / delete predicate | Slow joins, wide locks | Index FK columns intentionally |
| Long transactions | Lock waits, large undo history | Commit small units of work |
| Pool recycle above `wait_timeout` | Stale pooled connections | Recycle below timeout + pre-ping |
| Replica read right after write | Stale user-facing state | Pin read-after-write flows to primary |
| Application user with admin grants | High blast radius | Least-privilege runtime user |
| Direct DML on `mysql.user` | Grant-table corruption | `CREATE`/`ALTER`/`DROP USER` |
| `SKIP LOCKED` on accounting reads | Silently inconsistent results | Restrict to queue claims |
