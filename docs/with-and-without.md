# The Same App, Designed Twice

A side-by-side comparison of what a database looks like when an AI coding agent designs it
unaided, and what it looks like with `easy-rdbms` loaded.

**The honest headline: on day one, both work.** The naive schema is not incompetent — it is
*plausible*. It passes review, it serves traffic, the feature ships. Every difference below is
invisible until the table is full, and by then the fix is a migration project instead of a
one-character edit.

That gap is the whole problem this plugin exists for. Vibe coding optimizes for velocity, and
schema decisions are the one part of a codebase where velocity and reversibility trade against
each other hardest. You can refactor a function in an afternoon. You cannot refactor a primary
key on a billion-row table in an afternoon — you cannot refactor it in a *week*.

---

## The scenario

An AI chat product. Users sign up, hold conversations, send messages, and are billed per token.
PostgreSQL, because that is what Supabase and Neon give you and that is where most of these
projects start.

The prompt to the agent is the one a real person types:

> Build the database for an AI chat app. Users, conversations, messages, and usage tracking for
> billing.

---

## Round 1 — without the plugin

This is a faithful reconstruction of what agents emit for that prompt. Nothing here is a straw
man; every line is a defensible default in isolation.

```sql
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  name VARCHAR(255),
  password_hash VARCHAR(255) NOT NULL,
  settings JSONB DEFAULT '{}',
  is_deleted BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE conversations (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  title VARCHAR(255),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE messages (
  id SERIAL PRIMARY KEY,
  conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id),
  role VARCHAR(50),
  content TEXT,
  tokens INTEGER,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE usage (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  month VARCHAR(7),
  total_tokens INTEGER DEFAULT 0,
  cost FLOAT DEFAULT 0,
  updated_at TIMESTAMP DEFAULT NOW()
);
```

Ten thousand rows in, this is a good schema. It has constraints, it cascades deletes, it uses
`JSONB` instead of a pile of columns, it timestamps everything. A code reviewer would approve it.

## Round 2 — with the plugin

Same prompt. The plugin routes it through three stages with confirmation gates — concepts, then
logical entities, then physical DDL — and applies its naming, identifier, and index policies.

```sql
-- Schema separation: entity tables and event tables have different growth,
-- retention, and backup needs. Splitting them now costs nothing.
CREATE SCHEMA app;
CREATE SCHEMA log;

-- Entity table: one row per real person. The real world caps this, so int is enough.
-- `member`, not `user` — `user` is reserved in PostgreSQL and would need quoting forever.
CREATE TABLE app.member (
  member_id     int GENERATED ALWAYS AS IDENTITY,
  public_id     uuid NOT NULL,            -- UUIDv7, what the API exposes; never the PK
  email         text NOT NULL,            -- text + CHECK, not varchar(255): the 255 is arbitrary
  display_name  text,
  password_hash text NOT NULL,
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  deleted_at    timestamptz,              -- nullable timestamp, not a boolean flag
  CONSTRAINT pk_member PRIMARY KEY (member_id),
  CONSTRAINT uq_member_public_id UNIQUE (public_id),
  CONSTRAINT uq_member_email UNIQUE (email),
  CONSTRAINT chk_member_email_length CHECK (char_length(email) <= 320)
);

-- Settings normalized out: a JSONB blob you later need to filter or aggregate on
-- becomes a migration. One row per member, so the join is free.
CREATE TABLE app.member_setting (
  member_id    int NOT NULL,
  setting_data jsonb NOT NULL DEFAULT '{}',
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_member_setting PRIMARY KEY (member_id),
  CONSTRAINT fk_member_setting_member FOREIGN KEY (member_id)
    REFERENCES app.member (member_id)
);

CREATE TABLE app.conversation (
  conversation_id bigint GENERATED ALWAYS AS IDENTITY,
  member_id       int NOT NULL,           -- same type as the parent PK, always
  title           text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_conversation PRIMARY KEY (conversation_id),
  CONSTRAINT fk_conversation_member FOREIGN KEY (member_id)
    REFERENCES app.member (member_id)
);
CREATE INDEX idx_conversation_member_created
  ON app.conversation (member_id, created_at DESC);

-- Event table: one row per message. Rows = rate x time, with no cap, so bigint is not
-- optional. No member_id here: it is reachable through conversation_id, and storing a
-- second copy would be a transitive dependency (3NF) that can drift from its source.
-- Logical FK rather than physical: this is the hot write path. The referencing column
-- gets an explicit index instead -- nothing creates one for you without the constraint.
CREATE TABLE log.message (
  message_id      bigint GENERATED ALWAYS AS IDENTITY,
  conversation_id bigint NOT NULL,
  message_role    text NOT NULL,
  content         text NOT NULL,
  token_count     int NOT NULL DEFAULT 0,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_message PRIMARY KEY (message_id, created_at),
  CONSTRAINT chk_message_role CHECK (message_role IN ('user', 'assistant', 'system')),
  CONSTRAINT chk_message_token_count CHECK (token_count >= 0)
) PARTITION BY RANGE (created_at);

-- A partitioned parent holds no rows. Create the current period before the first insert,
-- and alert on the creation job -- a stalled one looks fine until every recent row is
-- sitting in a single unpruned partition.
CREATE TABLE log.message_2026m08 PARTITION OF log.message
  FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');

CREATE INDEX idx_message_conversation_created
  ON log.message (conversation_id, created_at DESC);

-- Metering: money is numeric, never float. Precision sized to the currency and use.
CREATE TABLE app.member_monthly_usage (
  member_id    int NOT NULL,
  usage_month  date NOT NULL,             -- a real date, not VARCHAR(7)
  total_tokens bigint NOT NULL DEFAULT 0,
  cost_amount  numeric(19,6) NOT NULL DEFAULT 0,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_member_monthly_usage PRIMARY KEY (member_id, usage_month),
  CONSTRAINT chk_member_monthly_usage_month CHECK (usage_month = date_trunc('month', usage_month)::date),
  CONSTRAINT chk_member_monthly_usage_tokens CHECK (total_tokens >= 0)
);
```

Longer, and it asked more questions on the way. That is the trade.

Note the split on foreign keys: `conversation` and `member_setting` get real `FOREIGN KEY`
constraints, `message` does not. That is the plugin's engine-split policy, not inconsistency —
PostgreSQL FKs are allowed when a set of conditions holds, and a high-rate partitioned event
table fails them. On MySQL the same design would carry no physical FK at all, and every
referencing column would need its index declared explicitly.

---

## What actually differs, and when it bites

Sorted by how expensive the fix gets, not by how clever the point is.

| # | Naive choice | What goes wrong | When | Cost to fix later |
|---|---|---|---|---|
| 1 | `messages.id SERIAL` (`int`, 2.1B ceiling) | Rows are rate × time with no cap. PostgreSQL `integer` is **signed** — a 2.1B ceiling — so at 10k messages/s the range is gone in **~2.5 days**; even at a modest 100/s, ~8 months. (MySQL's `int unsigned` doubles that to ~5 days.) Retention does not help — a sequence never reuses values, so deleting old rows frees storage but **not ID range** | The busiest table, at the worst moment | **Weeks.** Full table rewrite under `ACCESS EXCLUSIVE`, every index rebuilt, every referencing column migrated in lockstep, application deploys in the middle |
| 2 | `users` as a table name | `user` is reserved in PostgreSQL; the plural also breaks the singular convention. Every hand-written query and every migration carries the inconsistency | Immediately, then forever | **Days, spread over months.** A rename touches every query, ORM model, migration, and dashboard |
| 3 | `ON DELETE CASCADE` from `users` to `messages` | Deleting one account walks the largest table in the database inside a single transaction. Meanwhile, a physical FK on a hot parent takes a shared lock on the parent row — unrelated writes to that member queue behind it | First GDPR deletion request, or the first popular account | **Hours of incident**, then a redesign of the deletion path |
| 4 | `cost FLOAT` | Binary floating point cannot represent `0.1`. Per-call rounding error accumulates across millions of rows until the invoice and the ledger disagree | First reconciliation | **Painful.** Recomputing historical billing from logs, if the logs are even sufficient |
| 5 | `TIMESTAMP` without time zone | Stores wall-clock with no offset. The first non-UTC deployment, DST boundary, or cross-region replica produces silently wrong ordering and windowing | First timezone that is not the developer's | **Full column migration** plus an audit of which existing values meant what |
| 6 | `month VARCHAR(7)` | `'2026-9'` and `'2026-09'` both insert. Range queries do string comparison. No date arithmetic | First aggregation bug nobody can reproduce | Data cleanup with no reliable source of truth |
| 7 | No index on `messages.conversation_id` | The plugin's naming rule and PostgreSQL both leave the referencing column unindexed unless you say so. Loading a conversation sequentially scans the message table | ~100k messages | Cheap to add — **`CREATE INDEX CONCURRENTLY` on a table that is now huge**, and the slow queries were shipping the whole time |
| 8 | `settings JSONB` for everything | Fine until a query needs "all members whose notification setting is X". Now it needs an expression index per key, or a migration to columns | First feature that filters on a setting | Medium — an expression index buys time, normalization is the real fix |
| 9 | `is_deleted BOOLEAN` | Records the current flag, not who deleted the row, when, or why. It is not an audit trail | First dispute or compliance question | Unrecoverable — **the history was never written** |
| 10 | `messages.user_id` duplicated alongside `conversation_id` | `user_id` is determined by `conversation_id`, not by the message key — a transitive dependency, so 3NF is violated. Two sources of truth for one fact: reassign a conversation and the copies disagree | First time the two are compared | Cheap to drop, but every report already built on the stale copy has to be re-verified |
| 11 | No partitioning on `messages` | Retention means `DELETE` over millions of rows, generating bloat and vacuum pressure, instead of `DROP PARTITION` | First retention policy | Partitioning an existing large table requires a full data migration |

Numbers 1 through 5 are the ones that turn into incidents. Numbers 2 and 9 are the ones that can
never be fully undone.

---

## The pattern

Every row in that table shares a shape:

- **The cost of getting it right is near zero at `CREATE TABLE` time.** Four bytes per row.
  A different word for a table. `numeric` instead of `float`.
- **The cost of fixing it rises with the row count** — and the tables that hit these limits are,
  by definition, the ones with the most rows.
- **Nothing fails on day one.** There is no test that catches it, no linter, no code review
  comment. The schema is correct for the data it currently holds.

This is why "we will fix the schema when we need to scale" does not work. The moment you need to
scale is the moment the fix became expensive.

---

## What this plugin actually does

Three things, and it is worth being precise, because the value is narrower than "makes your
database good".

1. **It front-loads the irreversible decisions.** Integer width, key choice, table and column
   names, time zone handling, money representation, entity vs event separation. These are decided
   before the first `INSERT`, because that is the only time they are cheap.

2. **It makes the agent ask instead of assume.** Three stages with confirmation gates — concepts,
   logical model, physical DDL. An agent cannot know that `message` is an event table and `member`
   is an entity table, or that your currency has no minor unit, or that deletion needs an audit
   trail. It stops and asks rather than picking a default that reads fine.

3. **It refuses guesses that look like expertise.** No index without a stated query and plan. No
   denormalization without a measured problem. No partitioning without evidence. Left to itself, a
   model will happily produce a confident-sounding index strategy for a query nobody runs.

## What it does not do

- **It does not tune a running database.** No query rewriting at runtime, no plan analysis of your
  production traffic, no index recommendations from real statistics. It has diagnostic queries and
  tells you which to run; reading the results is on you.
- **It does not replace capacity planning.** It asks for your projected volume and rate. If those
  numbers are wrong, its recommendations are wrong.
- **It does not know your business rules.** Whether an order can exist without a customer, whether
  a subscription can overlap, whether deleted means gone — it asks, it does not infer.
- **It is slower than not using it.** The confirmation gates are the point, and they cost you
  turns. On a throwaway prototype that is a bad trade, and the plugin says so: it has a compressed
  path for personal tools and asks you to name the rigor level rather than skipping silently.

---

## The one-line version

The plugin does not make your schema fast. It stops you from making the handful of decisions that
you cannot take back — at the only moment when taking them back is free.
