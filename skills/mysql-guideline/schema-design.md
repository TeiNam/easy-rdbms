# Schema Design

## Primary Key Policy
- Use `AUTO_INCREMENT` with appropriate unsigned integer type
- Choose type by expected row count: `tinyint` < `smallint` < `int` < `bigint`

```sql
CREATE TABLE `user` (
  `user_id` int unsigned NOT NULL AUTO_INCREMENT,
  `email` varchar(255) NOT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

## Foreign Key Policy
- Logical FK only (no physical FK constraints)
- Referential integrity managed at application level
- Document relationships via COMMENT

```sql
CREATE TABLE `chat_history` (
  `chat_history_id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` int unsigned NOT NULL COMMENT 'logical FK: user.user_id — same type as the parent PK, always',
  `conversation_id` char(18) NOT NULL COMMENT 'logical FK: conversation_session.conversation_id',
  `user_message` text NOT NULL,
  `bot_response` text NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`chat_history_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

## Application-Level Referential Integrity

```python
async def create_chat_history(user_id: int, conversation_id: str, message: str, response: str):
    user = db.select("user", where={"user_id": user_id, "is_active": 1})
    if not user:
        raise ValueError("User does not exist")

    conversation = db.select("conversation_session", where={"conversation_id": conversation_id})
    if not conversation:
        raise ValueError("Conversation session does not exist")

    return db.insert("chat_history", {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "user_message": message,
        "bot_response": response
    })
```

## Soft Delete Pattern

Standardize tables requiring soft delete with the `is_active` column.

```sql
`is_active` tinyint(1) NOT NULL DEFAULT 1  -- 1: active, 0: deleted
```

- Physical DELETE prohibited (audit trail, recovery capability)
- Always include `WHERE is_active = 1` in queries
- Place at front of composite index if queried frequently

```sql
-- Even with low selectivity, add to composite index if query pattern always includes it
CREATE INDEX idx_user_active_email ON user (is_active, email);  -- lowercase idx_ prefix (see rdbms-naming)
```

> WARNING: a standalone `is_active` index is *usually* wasted — but low cardinality alone does not
> decide it. If the queried value is rare (say 0.5% of rows are inactive and you query those), the
> index is selective for that value. Judge by skew and the plan; the composite form above serves
> the common case either way.


- [ ] No physical FK constraints (logical only, documented with COMMENT)
- [ ] AUTO_INCREMENT with appropriate unsigned type
- [ ] Log tables evaluated as partitioning candidates against the evidence rules (see `partitioning.md`)
- [ ] Appropriate indexes created
- [ ] Engine: InnoDB, Charset: utf8mb4
- [ ] No procedures/triggers/events
- [ ] `created_at` included (mandatory for all tables)
- [ ] `updated_at` included (except immutable log/history tables)
      Note: append-only tables like `chat_history`, `audit_log`, `access_log` may omit, recommend documenting in COMMENT
