# Schema Design

## Primary Key Policy
- Use `AUTO_INCREMENT` with appropriate unsigned integer type
- Choose type by expected row count: `tinyint` < `smallint` < `int` < `bigint`

```sql
CREATE TABLE `member` (
  `member_id` int unsigned NOT NULL AUTO_INCREMENT,
  `email` varchar(255) NOT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`member_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

## Foreign Key Policy
- Logical FK only (no physical FK constraints) — see `dev-practices.md` §5.4 for why
- Every logical FK carries **all four** compensating controls: the `COMMENT`, an index on the
  referencing column, a **named integrity owner**, and a **scheduled orphan-detection query**

```sql
CREATE TABLE `chat_history` (
  `chat_history_id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `member_id` int unsigned NOT NULL COMMENT 'logical FK: member.member_id — same type as the parent PK, always',
  `conversation_id` char(18) NOT NULL COMMENT 'logical FK: conversation_session.conversation_id',
  `user_message` text NOT NULL,
  `bot_response` text NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`chat_history_id`),
  -- Control 2: index every referencing column — nothing auto-creates it without an FK
  KEY `idx_chat_history_member_id` (`member_id`),
  KEY `idx_chat_history_conversation_id` (`conversation_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT 'integrity owner: chat-service ChatWriter (all writers go through it)';
```

### Control 4: Scheduled Orphan Detection

One query per logical FK, on a schedule. Without it, violations accumulate unobserved.

```sql
-- chat_history.member_id → user.member_id
SELECT c.chat_history_id
FROM chat_history c
LEFT JOIN member u ON u.member_id = c.member_id
WHERE u.member_id IS NULL
LIMIT 100;

-- chat_history.conversation_id → conversation_session.conversation_id
SELECT c.chat_history_id
FROM chat_history c
LEFT JOIN conversation_session s ON s.conversation_id = c.conversation_id
WHERE s.conversation_id IS NULL
LIMIT 100;
```

## Application-Level Referential Integrity

```python
async def create_chat_history(member_id: int, conversation_id: str, message: str, response: str):
    # An unlocked SELECT-then-INSERT is a race: the parent can be deleted between the check
    # and the insert. Lock each parent row FOR UPDATE inside the same transaction as the insert.
    # (At InnoDB's default REPEATABLE READ a plain read sees a snapshot, not the live row.)
    user = db.select_for_update("member", where={"member_id": member_id, "is_active": 1})
    if not user:
        raise ValueError("User does not exist")

    conversation = db.select_for_update(
        "conversation_session", where={"conversation_id": conversation_id}
    )
    if not conversation:
        raise ValueError("Conversation session does not exist")

    # The locks above and this insert must be ONE transaction — otherwise the parent can
    # be deleted between them and the check bought nothing.
    return db.insert("chat_history", {
        "member_id": member_id,
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

- Physical DELETE prohibited (recoverable logical deletion). **This is not an audit trail** — it
  records only the current flag, not who deleted it, when, or why. An audit requirement needs a
  history mechanism (`rdbms-modeling/references/history-entities.md`)
- Always include `WHERE is_active = 1` in queries
- Place at front of composite index if queried frequently

```sql
-- Even with low selectivity, add to composite index if query pattern always includes it
CREATE INDEX idx_member_active_email ON member (is_active, email);  -- lowercase idx_ prefix (see rdbms-naming)
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
- [ ] No procedures/triggers/events carrying **business logic** (the operational-utility and
      audit-trigger exceptions are in `rdbms-modeling/references/db-internal-routines.md`)
- [ ] `created_at` included (mandatory for all tables)
- [ ] `updated_at` included (except immutable log/history tables)
      Note: append-only tables like `chat_history`, `audit_log`, `access_log` may omit, recommend documenting in COMMENT
