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

## MySQL 8.4 LTS 점검

| 항목 | 8.4 기준 동작 | 적용 방법 |
|---|---|---|
| 인증 | `caching_sha2_password` 기본. `mysql_native_password`는 기본 비활성 | 드라이버·TLS를 검증한 뒤 계정을 전환. 구형 인증을 다시 켜는 것을 기본 해법으로 쓰지 않음 |
| 제거된 설정·명령 | `default_authentication_plugin`, `SHOW SLAVE STATUS` 등 | 설정 파일·관리 스크립트를 점검. `SHOW REPLICA STATUS` 사용 |
| FK 부모 키 | `restrict_fk_on_non_standard_key=ON` 기본 | PK/UNIQUE를 참조. 옵션을 끄지 말고 비표준 참조를 수정 |
| Adaptive hash index | `innodb_adaptive_hash_index=OFF` 기본 | 예전 설정 파일의 ON을 복사하지 말고 실제 부하로 비교 |
| Change buffer | `innodb_change_buffering=none` 기본 | 저장장치·보조 인덱스 쓰기 부하를 측정한 뒤 검토 |
| I/O capacity | `innodb_io_capacity=10000` 기본 | 실제 지속 쓰기 성능·checkpoint 지연에 맞춤. 8.0의 200을 관성적으로 복사하지 않음 |
| Redo 크기 | `innodb_redo_log_capacity` 사용 | 예전 `innodb_log_file_size`/`innodb_log_files_in_group` 중심 설정을 갱신 |

```sql
-- 권한 있는 진단 세션에서 읽기만 수행한다.
SELECT @@version, @@transaction_isolation,
       @@innodb_adaptive_hash_index, @@innodb_change_buffering,
       @@innodb_io_capacity, @@innodb_redo_log_capacity,
       @@restrict_fk_on_non_standard_key;
SELECT user, host, plugin FROM mysql.user ORDER BY user, host;
```

8.0→8.4에서는 MySQL Shell `util.checkForServerUpgrade()`를 실제 목표 버전으로 실행하고
설정·인증·예약어·비표준 FK·드라이버·백업 복원을 확인한다. 체크 결과만으로 업그레이드를
완료 처리하지 않고 복제 환경에서 주요 쿼리·쓰기·failover를 검증한다.
MySQL 9.x/HeatWave의 기능을 8.4 Community 기능으로 안내하지 않는다. 특히 pgvector의
`vector`, HNSW, cosine 연산자는 MySQL 8.4 SQL이 아니다.

| Feature | MySQL 8.0+ | MariaDB |
|---|---|---|
| Referencing inserted values in `ON DUPLICATE KEY UPDATE` | Row alias `AS new` — **8.0.19+**; `VALUES(col)` deprecated from **8.0.20** (so on 8.0.0-8.0.18, `VALUES(col)` is the only form) | `VALUES(col)` is the documented form |
| Cross-engine safe choice | — | Use `VALUES(col)` for mixed fleets |

```sql
-- MySQL row-alias form (confirm target is MySQL first)
INSERT INTO member_setting (member_id, setting_key, setting_value)
VALUES (?, ?, ?) AS new
ON DUPLICATE KEY UPDATE
  setting_value = new.setting_value,
  updated_at = NOW();
```

## Pagination — the `OFFSET` Trap

`LIMIT n OFFSET m` makes the server **read the first `m` rows and throw them away** before
returning the next `n`. The cost grows with the page number, which is why the tail of an infinite
scroll or a deep page link is slow even when an index covers the sort.

| Cause | What happens |
|---|---|
| Read-and-discard | The server walks `offset + limit` rows in order and discards the front. An index on the sort columns removes the sort, **not the scan** |
| No covering index → extra random I/O | The sort index yields PKs; each row then needs a lookup into the clustered index. That random I/O accumulates page by page |
| `LIMIT` with no `ORDER BY` | With no deterministic order, the returned rows can shift between executions and pagination silently breaks |

### Fix 1 — keyset (seek) pagination

Carry the last row seen instead of an offset. With an index range scan, the work stays close to the
page size. On MySQL, expand the two-column inequality: a row-constructor predicate
`(created_at, product_id) < (?, ?)` can scan the entire index prefix instead of seeking to the cursor.

```sql
SELECT product_id, name, created_at
FROM product
WHERE created_at < ?
   OR (created_at = ? AND product_id < ?)
ORDER BY created_at DESC, product_id DESC
LIMIT 50;

CREATE INDEX idx_product_created_id ON product (created_at, product_id);
```

Bind the cursor timestamp twice, then its ID. Both sort columns must be non-null.
The tie-breaker column (`product_id`) is required — without it, rows sharing a `created_at` value
can be skipped or repeated across pages. Confirm an index range scan with `EXPLAIN ANALYZE` on a
deep cursor. On a 100,000-row MySQL 8.4 test, the tuple predicate read 90,051 index rows for a
50-row page; the expanded predicate read 50. This is a measured example, not a guarantee for
every distribution or optimizer version.

### Fix 2 — deferred join, when a cursor is impossible

Some UIs need clickable page numbers, so there is no cursor to carry. Then fetch only the PKs
through a covering index and join the wide columns onto the narrowed set — the random I/O drops
from `offset + limit` rows to `limit` rows.

```sql
SELECT p.product_id, p.name, p.description, p.created_at
FROM product p
JOIN (
  SELECT product_id
  FROM product
  ORDER BY created_at DESC, product_id DESC
  LIMIT 50 OFFSET 100000
) AS page USING (product_id)
ORDER BY p.created_at DESC, p.product_id DESC;   -- REQUIRED: a derived table's order is not preserved
```

Without that outer `ORDER BY` the page comes back in whatever order the join produced — the inner
`ORDER BY` only decides *which* rows, not the order you receive them in. The subquery touches only
indexed columns, so it stays index-only. **The offset scan itself is
still there** — this reduces the per-row cost, not the row count. Prefer keyset pagination whenever
the UI allows it, and for exports or batch work drop pagination entirely in favour of cursor-based
streaming or chunked processing.

## Full-Text Search Query

Index creation (with the `ngram` parser for Korean/CJK) is in `index-and-query.md`.
The query side:

```sql
SELECT article_id, title, MATCH(title, body) AGAINST (? IN NATURAL LANGUAGE MODE) AS score
FROM article
WHERE MATCH(title, body) AGAINST (? IN NATURAL LANGUAGE MODE)
ORDER BY score DESC
LIMIT 20;
```

Move to an external search engine when you need typo tolerance, complex ranking,
cross-table facets, or language analysis beyond the built-in parsers.

## Transaction Isolation — InnoDB Defaults to REPEATABLE READ

InnoDB's default is **`REPEATABLE READ`**. Plain reads get their consistency from an MVCC
snapshot; **locking** reads and writes additionally take **gap and next-key locks**, which is how
RR blocks phantoms for them — and the most common deadlock source that surprises teams arriving
from other databases.

This is not unconditional. A **unique-index equality lookup that finds its row takes only a record
lock** — no gap. Gap and next-key locking is what range scans and non-unique index searches do. So
"my `SELECT ... FOR UPDATE` by primary key deadlocked" usually means the predicate was not the
unique-equality shape you assumed; check the plan before blaming the isolation level.

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

SELECT account_id, balance
FROM account
WHERE account_id IN (?, ?)
ORDER BY account_id    -- deterministic order prevents lock-cycle deadlocks
FOR UPDATE;

UPDATE account SET balance = balance - ? WHERE account_id = ?;
UPDATE account SET balance = balance + ? WHERE account_id = ?;

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

SELECT job_id
FROM job
WHERE status = 'pending'
ORDER BY created_at
LIMIT 1
FOR UPDATE SKIP LOCKED;

UPDATE job
SET status = 'processing', started_at = NOW()
WHERE job_id = ? AND status = 'pending';   -- state check in the UPDATE, not just the lock

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

export async function listOrders(accountId) {
  const [rows] = await pool.execute(
    'SELECT purchase_order_id, total_amount FROM purchase_order WHERE account_id = ? LIMIT 50',
    [accountId],
  );
  return rows;
}
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
-- 인덱스 미사용 쿼리 전체 로깅은 기본 활성화하지 않는다.
-- 필요할 때 별도 제한된 진단 구간에서 로그 유입량을 측정한다.
```

`EXPLAIN ANALYZE` is **8.0.18+** (earlier 8.0 releases reject the syntax) and it **executes** the statement. Use it only when running the query is safe;
on production-sized data it can be expensive. Prefer plain `EXPLAIN` / `EXPLAIN FORMAT=JSON`
for plan inspection.

## Replication and Replica Lag

Read replicas lag. Do **not** route these to a replica right after a write:

- read-your-own-write paths
- checkout / payment flows
- permission and entitlement checks
- idempotency-key reads

```sql
-- MySQL 8.4. 복제가 구성되지 않은 서버에서는 빈 결과가 정상이다.
SHOW REPLICA STATUS\G;
SELECT channel_name, worker_id, service_state, last_error_number, last_error_message
FROM performance_schema.replication_applier_status_by_worker;
```

Check the engine and version before standardizing on one command. Monitor the replication
SQL thread health, IO thread health, and lag — not merely whether the TCP connection is up.

`Seconds_Behind_Source = 0`만으로 특정 쓰기를 읽을 수 있다고 판정하지 않는다.
기본은 primary에서 read-after-write를 처리한다. GTID 기반 read routing을 이미 운영한다면:

```sql
-- 애플리케이션이 확보한 해당 쓰기의 커밋 GTID를 바인딩한다.
-- replica의 같은 연결에서 대기 성공을 확인한 뒤 읽는다. 1은 대기 예산(초)의 예다.
SELECT WAIT_FOR_EXECUTED_GTID_SET(?, 1) AS wait_result;
```

결과 `0`일 때만 해당 replica 연결에서 읽고, timeout(`1`)·NULL·에러이면 primary로
fallback한다. 새 연결로 바꿔 읽거나 고정 sleep을 쓰면 인과적 읽기를 보장하지 못한다.
오래된 RR snapshot이 열린 연결도 재사용하지 않는다. GTID는 쓰기의 실제 커밋을 확인한
드라이버/session tracking 경로에서 얻으며 `@@GLOBAL.gtid_executed` 전체를 토큰으로 쓰지 않는다.
Aurora는 토폴로지와 엔진별 일관성 기능이 다르므로 이 흐름을 그대로 이식하지 않는다.

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
- Keep migration/admin accounts separate from the runtime application account.
- Audit public network exposure and `bind_address` before tuning performance.
- Use `CREATE USER` / `ALTER USER` / `DROP USER`. Direct DML against `mysql.user` risks
  corrupting the grant tables.
- TLS는 서버 인증서·호스트명 검증까지 구성한다. `caching_sha2_password` 연결 오류를
  `allowPublicKeyRetrieval=true`나 구형 인증으로 일괄 우회하지 않는다.

## Server Configuration Baseline

```ini
[mysqld]
innodb_flush_log_at_trx_commit = 1
sync_binlog = 1

wait_timeout = 300
interactive_timeout = 300
innodb_lock_wait_timeout = 10

slow_query_log = ON
long_query_time = 1
log_queries_not_using_indexes = OFF

log_bin = mysql-bin
# binlog_format은 8.4의 기본 ROW를 사용한다. 불필요한 deprecated 설정은 복사하지 않는다.
binlog_expire_logs_seconds = 604800
```

Treat these as a prompt for review, not a universal preset. Size memory, connections, log
retention, and durability from the actual workload, hardware, backup policy, and recovery
objectives.
`innodb_buffer_pool_size`는 실제 메모리와 연결/연산 버퍼를 함께 계산하고,
`max_connections`는 모든 앱 인스턴스의 pool 합계와 운영 여유를 기준으로 정한다.
장비 크기를 모르는 상태에서 4G·300연결 같은 값을 복사하지 않는다.

## 공식 근거

- [MySQL 8.4 변경 사항](https://dev.mysql.com/doc/refman/8.4/en/mysql-nutshell.html)
- [8.4 인증 변경](https://dev.mysql.com/doc/refman/8.4/en/native-pluggable-authentication.html)
- [InnoDB 설정](https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html)
- [GTID 대기 함수](https://dev.mysql.com/doc/refman/8.4/en/gtid-functions.html)
- [MySQL Shell 업그레이드 검사](https://dev.mysql.com/doc/mysql-shell/8.4/en/mysql-shell-utilities-upgrade.html)

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
