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
from psycopg_pool import AsyncConnectionPool

async_pool = AsyncConnectionPool(
    conninfo="host=localhost port=5432 dbname=myapp user=app",
    min_size=4, max_size=10,
    kwargs={"row_factory": dict_row}
)

async def get_user(user_id: int):
    async with async_pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT user_id, email, is_active, created_at FROM app.user WHERE user_id = %(user_id)s",
                {"user_id": user_id}
            )
            return await cur.fetchone()
```

## Transaction Isolation — PostgreSQL Defaults to READ COMMITTED

The default is **`READ COMMITTED`** — the opposite default from MySQL InnoDB, which matters when
porting code or reasoning shared across both engines. PostgreSQL has **no gap locks**; phantom
prevention at higher levels uses Serializable Snapshot Isolation (SSI), not blocking.

| Level | Behaviour | Use |
|---|---|---|
| `READ COMMITTED` (default) | Each statement sees the latest committed snapshot | Correct for most OLTP; SELECT-then-act races handled with explicit locking |
| `REPEATABLE READ` | Transaction-wide snapshot; **serialization failures possible** on write conflicts | Multi-statement reads needing one consistent view (reports, exports) |
| `SERIALIZABLE` | SSI — detects dangerous patterns, aborts with `40001` | Invariants spanning several rows/tables that no constraint can express |

Practical rules:

- At `READ COMMITTED`, two transactions can both pass a `SELECT`-based check and both act on it.
  Guard invariants with `FOR UPDATE`, a `UNIQUE` constraint, or advisory locks — not with a
  bare read.
- `REPEATABLE READ` and `SERIALIZABLE` **fail with SQLSTATE `40001`/`40P01` instead of blocking**
  — the application must retry the whole transaction. No retry loop → do not raise the level.
- `SERIALIZABLE` costs predicate tracking; keep such transactions short and touch few rows.

```sql
SHOW default_transaction_isolation;
BEGIN ISOLATION LEVEL SERIALIZABLE;
```

## Advisory Lock

```python
# Session-level (pg_advisory_lock): automatically released on connection return
# Transaction-level (pg_advisory_xact_lock): automatically released on transaction end → recommended

# PASS: Transaction-level: lock auto-released when with conn.transaction() ends, no finally needed
async with async_pool.connection() as conn:
    async with conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute("SELECT pg_advisory_xact_lock(%(id)s)", {"id": job_id})
            result = await cur.fetchone()
            # Waits on lock acquisition failure (use pg_try_advisory_xact_lock for non-blocking)
            await cur.execute(
                "UPDATE app.job SET status = 'processing' WHERE job_id = %(id)s",
                {"id": job_id}
            )
        # Transaction commit + lock release handled atomically

# PASS: Non-blocking (returns immediately on lock acquisition failure)
async with async_pool.connection() as conn:
    async with conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute("SELECT pg_try_advisory_xact_lock(%(id)s)", {"id": job_id})
            result = await cur.fetchone()
            if not result["pg_try_advisory_xact_lock"]:
                return  # Another process is handling
            await cur.execute(
                "UPDATE app.job SET status = 'processing' WHERE job_id = %(id)s",
                {"id": job_id}
            )

# FAIL: Incorrect pattern: session-level lock + manual finally unlock
# Risk of lock leak if crash occurs after commit but before finally executes unlock
# async with conn.cursor() as cur:
# await cur.execute("SELECT pg_try_advisory_lock(...)")
# try:
# await conn.commit()
# finally:
# await cur.execute("SELECT pg_advisory_unlock(...)")  # ← Dangerous
```

## LISTEN/NOTIFY

```python
import psycopg

def notify(conn, channel: str, payload: str):
    conn.execute(f"NOTIFY {channel}, %(payload)s", {"payload": payload})
    conn.commit()

def listen(conninfo: str, channel: str):
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(f"LISTEN {channel}")
        for notify in conn.notifies():
            print(f"Received: {notify.payload}")
```

## Server Configuration Template

```sql
ALTER SYSTEM SET max_connections = 100;
ALTER SYSTEM SET work_mem = '8MB';
ALTER SYSTEM SET idle_in_transaction_session_timeout = '30s';
ALTER SYSTEM SET statement_timeout = '30s';
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
REVOKE ALL ON SCHEMA public FROM public;
SELECT pg_reload_conf();
```

## Performance Checklist
- [ ] Connection pooling configured (psycopg_pool or PgBouncer)
- [ ] Transaction scope minimized
- [ ] Partial indexes used where applicable
- [ ] autovacuum status verified
- [ ] `work_mem`, `maintenance_work_mem` tuned
