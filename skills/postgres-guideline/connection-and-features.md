# Connection Management and PostgreSQL Features

## psycopg 3 Connection Pool

```python
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

pool = ConnectionPool(
    conninfo="host=localhost port=5432 dbname=myapp user=app",
    min_size=4, max_size=10,
    kwargs={"row_factory": dict_row, "autocommit": False}
)
```

## Transaction Management

```python
# with block = auto transaction (commit on success, rollback on exception)
with pool.connection() as conn:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("UPDATE account SET balance = balance - 100 WHERE id = 1")
            cur.execute("UPDATE account SET balance = balance + 100 WHERE id = 2")
```

## Async Support

```python
import asyncio
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

async def get_member(pool, member_id: int):
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT member_id, email, is_active, created_at"
                " FROM app.member WHERE member_id = %(member_id)s",
                {"member_id": member_id},
            )
            return await cur.fetchone()

async def main() -> None:
    # open=False + explicit open/close: opening in the constructor is deprecated
    pool = AsyncConnectionPool(
        conninfo="host=localhost port=5432 dbname=myapp user=app",
        min_size=4, max_size=10,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    await pool.open()
    try:
        print(await get_member(pool, 1))
    finally:
        await pool.close()

asyncio.run(main())
```

## Transaction Isolation — PostgreSQL Defaults to READ COMMITTED

The default is **`READ COMMITTED`** — the opposite default from MySQL InnoDB, which matters when
porting code or reasoning shared across both engines. PostgreSQL has **no gap locks**: `REPEATABLE
READ` already prevents phantoms through its transaction-wide MVCC snapshot, and `SERIALIZABLE`
adds SSI on top to catch write-skew — neither blocks the way InnoDB's next-key locks do.

| Level | Behaviour | Use |
|---|---|---|
| `READ COMMITTED` (default) | Each statement sees the latest committed snapshot | Correct for most OLTP; SELECT-then-act races handled with explicit locking |
| `REPEATABLE READ` | Transaction-wide snapshot (phantoms prevented); **`40001` possible** on write conflicts | Multi-statement reads needing one consistent view (reports, exports) |
| `SERIALIZABLE` | SSI — detects dangerous patterns, aborts with `40001` | Invariants spanning several rows/tables that no constraint can express |

Practical rules:

- At `READ COMMITTED`, two transactions can both pass a `SELECT`-based check and both act on it.
  Guard invariants with `FOR UPDATE`, a `UNIQUE` constraint, or advisory locks — not with a
  bare read.
- `REPEATABLE READ` and `SERIALIZABLE` can abort with **`40001` serialization failures** on write
  conflicts — row-lock waits still block as usual, and deadlocks (`40P01`) can happen at any
  level. The application must retry the whole transaction on either code. No retry loop → do
  not raise the level.
- `SERIALIZABLE` costs predicate tracking; keep such transactions short and touch few rows.

```sql
SHOW default_transaction_isolation;
BEGIN ISOLATION LEVEL SERIALIZABLE;
```

## Advisory Lock

```python
# Session-level (pg_advisory_lock): held until unlocked or the connection CLOSES —
#   returning a pooled connection does NOT close it, so the next borrower inherits the lock
# Transaction-level (pg_advisory_xact_lock): released at transaction end → the default choice,
#   because it cannot be leaked into a pooled connection. Session-level is usable only if the
#   unlock is guaranteed on every path (or the connection is reset before return)

async def claim_job(pool, job_id: int) -> bool:
    """PASS: transaction-level lock — released when conn.transaction() ends, no finally needed.

    The lock only serializes concurrent callers *while held*. It does not remember that the job
    was already claimed, so the state check has to be in the UPDATE itself — otherwise the next
    caller acquires the freed lock and re-claims a job that is already processing.
    """
    async with pool.connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # Blocks until acquired; use pg_try_advisory_xact_lock for non-blocking
                await cur.execute("SELECT pg_advisory_xact_lock(%(id)s)", {"id": job_id})
                await cur.execute(
                    "UPDATE app.job SET status = 'processing', started_at = now()"
                    " WHERE job_id = %(id)s AND status = 'pending'"
                    " RETURNING job_id",
                    {"id": job_id},
                )
                claimed = await cur.fetchone() is not None
        # transaction commit and lock release happen together
        return claimed

async def try_claim_job(pool, job_id: int) -> bool:
    """PASS: non-blocking — returns immediately if the lock is unavailable."""
    async with pool.connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT pg_try_advisory_xact_lock(%(id)s)", {"id": job_id}
                )
                row = await cur.fetchone()
                if not row["pg_try_advisory_xact_lock"]:
                    return False          # another worker holds it
                await cur.execute(
                    "UPDATE app.job SET status = 'processing', started_at = now()"
                    " WHERE job_id = %(id)s AND status = 'pending'"
                    " RETURNING job_id",
                    {"id": job_id},
                )
                claimed = await cur.fetchone() is not None
    return claimed          # holding the lock is not the same as winning the job

# FAIL: session-level lock + manual unlock.
# A crash is safe — the backend terminates and session locks release with it.
# The real leak is the pooled path: if the unlock is skipped (early return, an
# exception before finally, a code path added later), the connection returns to
# the pool still holding the lock and the next borrower inherits it.
#
#   await cur.execute("SELECT pg_try_advisory_lock(%(id)s)", {"id": job_id})
#   try:
#       ...
#   finally:
#       await cur.execute("SELECT pg_advisory_unlock(%(id)s)", {"id": job_id})
```

## LISTEN/NOTIFY

```python
import psycopg
from psycopg import sql

def notify(conn, channel: str, payload: str):
    # NOTIFY is a utility command — it takes no bind parameters.
    # pg_notify() is a regular function, so both arguments bind safely.
    conn.execute("SELECT pg_notify(%s, %s)", (channel, payload))
    conn.commit()

def listen(conninfo: str, channel: str):
    with psycopg.connect(conninfo, autocommit=True) as conn:
        # LISTEN takes an identifier — compose it, never f-string it
        conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(channel)))
        for notify in conn.notifies():
            print(f"Received: {notify.payload}")
```

## Pooling과 설정 범위

PgBouncer의 transaction pooling에서는 한 요청이 같은 서버 세션을 계속 쓴다고 가정하지
않는다. 요청별 설정은 트랜잭션의 `SET LOCAL`/`set_config(..., true)`로 전달한다.
LISTEN과 session advisory lock처럼 세션 유지가 필요한 작업은 전용 연결 또는 session
pooling을 사용한다. 드라이버의 prepared statement 지원은 설치한 PgBouncer 버전과
`max_prepared_statements` 설정까지 확인한다.

## Server Configuration

설정값을 일괄 적용하기 전에 현재 값과 재기동 여부를 확인한다.

```sql
SELECT name, setting, unit, context, pending_restart
FROM pg_settings
WHERE name IN ('work_mem', 'maintenance_work_mem', 'max_connections',
               'statement_timeout', 'idle_in_transaction_session_timeout',
               'shared_preload_libraries', 'io_method', 'track_io_timing')
ORDER BY name;
```

`work_mem`은 동시 연산·worker를 포함한 예산으로 정한다. `statement_timeout`은 서비스의
요청 deadline에 맞추고 긴 배치·마이그레이션 역할과 구분한다. reload 가능한 설정도
적용 범위와 기존 세션의 역할별 override를 확인한다.
`max_connections`, `shared_preload_libraries`, `io_method` 변경은 재기동이 필요하다.
preload 목록을 보존하는 확장 설치 절차는 `extensions.md`, 18의 I/O는
`version-and-upgrade.md`를 따른다.

## Performance Checklist
- [ ] Connection pooling configured (psycopg_pool or PgBouncer)
- [ ] Transaction scope minimized
- [ ] Partial indexes used where applicable
- [ ] autovacuum status verified
- [ ] `work_mem`, `maintenance_work_mem` tuned
