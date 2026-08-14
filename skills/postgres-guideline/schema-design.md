# Schema Design

## Primary Key Policy
- Use `GENERATED ALWAYS AS IDENTITY` (not SERIAL)
- UUID allowed for distributed or external-facing IDs

```sql
CREATE TABLE app.user (
  user_id int GENERATED ALWAYS AS IDENTITY,
  email varchar(255) NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),  -- updated by application, not triggers
  CONSTRAINT user_pk_user_id PRIMARY KEY (user_id)
);

-- External-facing ID with UUID
CREATE TABLE app.user (
  user_id int GENERATED ALWAYS AS IDENTITY,
  public_id uuid NOT NULL DEFAULT gen_random_uuid(),
  email varchar(255) NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT user_pk_user_id PRIMARY KEY (user_id),
  CONSTRAINT uidx_user_public_id UNIQUE (public_id)
);
```

## Foreign Key Policy
- Logical FK only (no physical FK constraints)
- Referential integrity managed at application level
- Avoids lock contention and performance degradation

```sql
CREATE TABLE app.chat_history (
  chat_history_id bigint GENERATED ALWAYS AS IDENTITY,
  user_id int NOT NULL,              -- logical FK: app.user.user_id
  conversation_id char(18) NOT NULL, -- logical FK: app.conversation_session
  user_message text NOT NULL,
  bot_response text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT chat_history_pk PRIMARY KEY (chat_history_id)
);

COMMENT ON COLUMN app.chat_history.user_id IS 'logical FK: app.user.user_id';
```

### Application-Level Referential Integrity

```python
async def create_chat_history(user_id: int, conversation_id: str, message: str, response: str):
    user = await db.execute_query(
        "SELECT user_id FROM app.user WHERE user_id = %(user_id)s AND is_active = true",
        {"user_id": user_id}
    )
    if not user:
        raise ValueError("User does not exist")

    result = await db.execute_command(
        """INSERT INTO log.chat_history (user_id, conversation_id, user_message, bot_response)
           VALUES (%(user_id)s, %(cid)s, %(msg)s, %(resp)s)
           RETURNING chat_history_id""",
        {"user_id": user_id, "cid": conversation_id, "msg": message, "resp": response}
    )
    return result
```

## Soft Delete Pattern

Tables requiring logical deletion standardize on the `is_active` column.

```sql
`is_active` boolean NOT NULL DEFAULT true
```

- Physical DELETE prohibited (ensures audit trail and recovery capability)
- Always include `WHERE is_active = true` in queries
- Use Partial Index to index only active records → reduces index size

```sql
-- Partial index: index only active users (excludes deleted users)
CREATE INDEX idx_user_active_email ON app.user (email) WHERE is_active = true;
```

> WARNING: Standalone B-tree index on `is_active` is ineffective due to low cardinality.
> Use PostgreSQL's Partial Index or composite indexes.

## Row Level Security (RLS)

```sql
ALTER TABLE app.orders ENABLE ROW LEVEL SECURITY;

-- Optimized RLS policy (wrap auth call in SELECT to avoid per-row evaluation)
-- Note: auth.uid() is project-specific — replace with platform-appropriate function (Supabase, etc.)
CREATE POLICY user_orders ON app.orders
  USING (
    (SELECT auth.uid()) = user_id
    AND (SELECT is_active FROM app.user WHERE user_id = (SELECT auth.uid()))
  );

-- Always index RLS policy columns
CREATE INDEX idx_orders_user_id ON app.orders (user_id);

REVOKE ALL ON SCHEMA public FROM public;
```

## JSONB Usage

```sql
CREATE TABLE app.user_setting (
  user_id int NOT NULL,
  setting_data jsonb NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT user_setting_pk PRIMARY KEY (user_id)
);

-- Query
SELECT setting_data->>'theme' AS theme FROM app.user_setting WHERE user_id = 1;

-- Partial update
UPDATE app.user_setting
SET setting_data = setting_data || '{"theme": "dark"}'::jsonb, updated_at = now()
WHERE user_id = 1;

-- Key existence check
SELECT * FROM app.user_setting WHERE setting_data ? 'theme';
```

## Table Creation Checklist
- [ ] PK uses `GENERATED ALWAYS AS IDENTITY` (not SERIAL)
- [ ] No physical FK constraints (logical only, documented with COMMENT)
- [ ] `timestamptz` used (never `timestamp`)
- [ ] `boolean` type used (never 'Y'/'N' strings)
- [ ] `created_at` included (required for all tables)
- [ ] `updated_at` included (except append-only log tables) — updated by application, not triggers
- [ ] Soft Delete tables use `is_active boolean DEFAULT true` + Partial Index
- [ ] No procedures/triggers/rules
- [ ] Schema separated by purpose (`app`, `log`, `ref`)
