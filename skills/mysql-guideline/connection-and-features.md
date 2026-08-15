# Connection Management and MySQL Features

## Connection Handling — Use a Pool, Not a Shared Connection

> A single module-level connection with transaction state on the object is **not safe** outside a
> single-threaded, single-process script: in FastAPI, Django async views, or Celery the connection
> and its in-flight transaction are shared across workers, which corrupts data. Use a pool
> (below) for threaded code and `aiomysql` for async code.

## Connection Pool (mysql-connector-python)

```python
import mysql.connector.pooling

pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="myapp",
    pool_size=10,
    host="localhost",
    port=3306,
    database="myapp",
    user="app",
    charset="utf8mb4",
    collation="utf8mb4_0900_ai_ci",
    autocommit=False,
)
```

## Transaction Management

A pooled connection must be returned — `close()` on a pooled connection releases it back to the
pool rather than dropping the socket. Without it the pool is exhausted after `pool_size` calls.

```python
def transfer(pool, from_id: int, to_id: int, amount: int) -> None:
    conn = pool.get_connection()
    try:
        with conn.cursor() as cur:
            # Deterministic lock order prevents deadlocks between concurrent transfers
            cur.execute(
                "SELECT account_id, balance FROM account WHERE account_id IN (%s, %s)"
                " ORDER BY account_id FOR UPDATE",
                (from_id, to_id),
            )
            rows = cur.fetchall()
            if len(rows) != 2:
                raise ValueError("account not found")

            cur.execute(
                "UPDATE account SET balance = balance - %s WHERE account_id = %s",
                (amount, from_id),
            )
            cur.execute(
                "UPDATE account SET balance = balance + %s WHERE account_id = %s",
                (amount, to_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()          # returns the connection to the pool
```

## Async Support (aiomysql)

```python
import asyncio
import aiomysql

async def main() -> None:
    pool = await aiomysql.create_pool(
        host="localhost", port=3306,
        user="app", db="myapp",
        charset="utf8mb4",
        minsize=4, maxsize=10,
    )
    try:
        row = await get_member(pool, 1)
        print(row)
    finally:
        pool.close()
        await pool.wait_closed()

async def get_member(pool, member_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT member_id, email, is_active, created_at"
                " FROM member WHERE member_id = %s",
                (member_id,),
            )
            return await cur.fetchone()

asyncio.run(main())
```

## MySQL-Specific Features

### JSON Column Operations

```sql
SELECT JSON_EXTRACT(setting_data, '$.theme') AS theme FROM member_setting WHERE member_id = 1;
SELECT setting_data->>'$.theme' AS theme FROM member_setting WHERE member_id = 1;

UPDATE member_setting
SET setting_data = JSON_SET(setting_data, '$.theme', 'dark')
WHERE member_id = 1;
```

### Generated Columns

```sql
ALTER TABLE member ADD COLUMN full_name varchar(200)
  GENERATED ALWAYS AS (CONCAT(first_name, ' ', last_name)) VIRTUAL;
```

### Window Functions

```sql
SELECT member_id, message_count,
  ROW_NUMBER() OVER (ORDER BY message_count DESC) AS row_rank   -- `rank` is reserved in MySQL 8
FROM (
  SELECT member_id, COUNT(*) AS message_count
  FROM chat_history GROUP BY member_id
) t;
```

## Performance Checklist
- [ ] Connection pooling configured
- [ ] Transaction scope minimized
- [ ] Appropriate indexes on WHERE/JOIN columns
- [ ] `innodb_buffer_pool_size` tuned — 70–80% of RAM applies to a **dedicated** host; on shared or
      containerized hosts size it from the workload and the whole process's memory budget
- [ ] Slow query log enabled for analysis
- [ ] `EXPLAIN` verified for complex queries
