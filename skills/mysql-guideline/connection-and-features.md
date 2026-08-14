# Connection Management and MySQL Features

## MySQLConnector Pattern

> WARNING: **Environment prerequisite:** This pattern is safe only in **single-thread / single-process** environments.
> - In multi-threaded/async environments like FastAPI, Django async views, Celery, connection/transaction state is shared across threads, risking data corruption.
> - Async environments: use `aiomysql` pool pattern below
> - Multi-threaded sync environments: use `ConnectionPool` pattern

```python
class MySQLConnector:
    """Singleton connection manager for MySQL

    WARNING: Single-thread / single-process only.
    For multi-threaded or async environments, use ConnectionPool or aiomysql instead.
    """

    def __init__(self):
        self._connection = None
        self.config = MYSQL_CONFIG
        self.is_transaction_active = False  # race condition risk when shared across threads

    def get_connection(self):
        """Create connection if not exists"""
        self.connect()
        return self._connection
```

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
    collation="utf8mb4_0900_ai_ci"
)

conn = pool.get_connection()
```

## Transaction Management

```python
db = MySQLConnector()
try:
    db.begin_transaction()
    db.execute_raw_query("UPDATE account SET balance = balance - 100 WHERE id = 1", {})
    db.execute_raw_query("UPDATE account SET balance = balance + 100 WHERE id = 2", {})
    db.commit_transaction()
except Exception as e:
    db.rollback_transaction()
    raise
```

## Async Support (aiomysql)

```python
import aiomysql

pool = await aiomysql.create_pool(
    host="localhost", port=3306,
    user="app", db="myapp",
    charset="utf8mb4",
    minsize=4, maxsize=10
)

async def get_user(user_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT * FROM user WHERE user_id = %s", (user_id,)
            )
            return await cur.fetchone()
```

## MySQL-Specific Features

### JSON Column Operations

```sql
SELECT JSON_EXTRACT(setting_data, '$.theme') AS theme FROM user_setting WHERE user_id = 1;
SELECT setting_data->>'$.theme' AS theme FROM user_setting WHERE user_id = 1;

UPDATE user_setting
SET setting_data = JSON_SET(setting_data, '$.theme', 'dark')
WHERE user_id = 1;
```

### Generated Columns

```sql
ALTER TABLE user ADD COLUMN full_name varchar(200)
  GENERATED ALWAYS AS (CONCAT(first_name, ' ', last_name)) VIRTUAL;
```

### Window Functions

```sql
SELECT user_id, message_count,
  ROW_NUMBER() OVER (ORDER BY message_count DESC) AS rank
FROM (
  SELECT user_id, COUNT(*) AS message_count
  FROM chat_history GROUP BY user_id
) t;
```

## Performance Checklist
- [ ] Connection pooling configured
- [ ] Transaction scope minimized
- [ ] Appropriate indexes on WHERE/JOIN columns
- [ ] `innodb_buffer_pool_size` tuned (70-80% of available RAM)
- [ ] Slow query log enabled for analysis
- [ ] `EXPLAIN` verified for complex queries
