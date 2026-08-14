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

# RISKY: session-level lock + manual unlock.
# A crash is actually safe — the backend terminates and session locks release with it.
# The real leak is the pooled path: if the unlock is skipped (early return, exception
# before finally, a code path added later), the connection goes back to the pool still
# holding the lock and the next borrower inherits it.
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

## Server Configuration Template

```sql
-- Reloadable — takes effect with pg_reload_conf()
ALTER SYSTEM SET work_mem = '8MB';
ALTER SYSTEM SET idle_in_transaction_session_timeout = '30s';
ALTER SYSTEM SET statement_timeout = '30s';
SELECT pg_reload_conf();

-- Restart-required — pg_reload_conf() does NOT apply these
ALTER SYSTEM SET max_connections = 100;
ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';
-- ...restart the server, then:
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

REVOKE ALL ON SCHEMA public FROM public;
```

## Performance Checklist
- [ ] Connection pooling configured (psycopg_pool or PgBouncer)
- [ ] Transaction scope minimized
- [ ] Partial indexes used where applicable
- [ ] autovacuum status verified
- [ ] `work_mem`, `maintenance_work_mem` tuned
