# Changelog

## 0.4.1

Codex compatibility, a flow audit, and the guard scripts that grew out of two user-caught
regressions. Everything here is a correction or a tripwire — no new capability.

**Codex compatibility** — the plugin now actually loads everything on Codex

- **Four skill descriptions exceeded Codex's 1,024-character limit** (1,025 / 1,074 / 1,895 /
  1,603) and were rejected there. Compressed to 673–900 characters. The compression initially cost
  high-precision trigger literals; a token-level old/new diff restored the ones nothing else
  covers: `UPSERT`, `INET_ATON`, `eq_range_index_dive_limit`, single-table inheritance /
  discriminator, 1NF/2NF, `valid_from`/`valid_to`, `lock wait timeout`, `too many connections`.
- **Removed `commands/*.toml`.** Codex plugins do not register custom slash commands — verified
  against all nine official bundled plugins (zero `commands/` directories, zero manifest fields).
  On Codex, invoke a skill as `$easy-rdbms:<skill-name>`; the README documents the mapping from
  the Claude Code commands.
- **Codex does not auto-trust plugin hooks.** The install steps now say to review and approve the
  `SessionStart` hook via `/hooks`, or automatic engine detection never runs.
- Codex-side manifests: category corrected to `Developer Tools`, `longDescription` now names
  SQLite alongside MySQL and PostgreSQL.

**Flow audit** — no instruction anywhere may point against the intended pipeline
(hook → `db-select` → `rdbms-modeling` → engine guideline → `rdbms-review` →
`database-migrations`). Extracting every directional statement and grading the back-edges found
four violations:

- The three engine guidelines listed **"Designing … schemas" as their own activation condition**,
  which let an agent skip the conceptual and logical gates entirely. New table design now starts
  in `rdbms-modeling`; the engine guideline is what its Stage 3 loads.
- `rdbms-modeling` Stage 3 told the agent to re-confirm a repository-inferred engine — the exact
  question the session hook forbids. It now takes a hook-named engine as given and confirms only
  the **version and deployment form**, which the hook cannot detect.
- `db-select`'s description said it routes to the engine guideline, contradicting its own body
  (new design goes through `rdbms-modeling` first).
- The mysql/postgres closing sections said `db-select` "routes back here" — for new design the
  return path is via `rdbms-modeling` Stage 3, and now says so.

Every remaining back-edge is conditional ("engine undecided", "needs redesigning, not patching",
"outgrown SQLite").

**Corrections caught in use**

- The Korean comparison table still said the `int` runway was ~5 days after the English side had
  been corrected to ~2.5 — the second time a numeric fix landed in only one language.
- The review total said 267 while the listed rounds sum to 272.
- The `rdbms-modeling` reference-file count said eleven; the skill owns ten
  (`cost-evaluation.md` belongs to `db-select`).
- The README claimed 16 hook-test cases after the suite had grown to 23.
- Korean section copyedited out of translationese; English grammar fixes (subject inheritance,
  pronoun references) without touching voice.

**Guards** — `scripts/check-readme-bilingual.py`, run from the repo root

- Fails when a factual number goes stale in one language or drifts from the repository: exhaustion
  day counts, the review total vs. the round sequence beside it, the reference-file count and
  filenames vs. `skills/*/references/` on disk, and the hook-test count vs.
  `hooks/detect-db.test.sh`.
- Filesystem checks that cannot run say `SKIPPED` out loud instead of passing silently — a check
  that quietly degrades to `ok` is worse than no check.
- Every guard was verified against the historical commit containing the bug it exists to catch.

## 0.4.0

**Positioning:** this is a database plugin for vibe coders. New doc —
[The same app, designed twice](docs/with-and-without.md) — walks one realistic schema through both
paths (unaided AI agent vs. this plugin), with a table of eleven differences ordered by when each
one bites and what it costs to fix later. It includes a "what this plugin does not do" section,
because a comparison document without one is marketing.

**Round 10 of two-way review** — Claude self-review plus two independent Codex passes (engine facts;
cross-file consistency and flow). 116 findings. A large share were introduced by round 9's own
changes, which is the recurring lesson of this exercise.

**Corrected facts** (wrong facts are the worst failure mode for a guidance plugin)

- **PostgreSQL `int` runway was wrong by 2×.** `integer` is signed — 2.1B — so 10k inserts/s
  exhausts it in **~2.5 days**, not the ~5 days that MySQL's `int unsigned` gets from the same 4
  bytes. The MySQL figure had been copied into the PostgreSQL files, the README, and the new doc.
- **`UNSIGNED` underflow errors; it does not wrap.** MySQL raises
  `ERROR 1690 (22003): BIGINT UNSIGNED value is out of range` (and clamps to 0 in a non-strict
  `UPDATE`). C-style wraparound is not MySQL behaviour.
- **`tinyint(1)` does not constrain values to 0/1** — `(1)` is display width. The boolean row is now
  `tinyint unsigned` plus a named `CHECK (col IN (0,1))`.
- **Gap locks at `REPEATABLE READ` are not unconditional** — a unique-index equality lookup that
  finds its row takes only a record lock.
- **`DROP PARTITION` is not `ALGORITHM=INSTANT`** — in-place and no table copy, but it takes a
  metadata lock that can block concurrent statements.
- **Losing semi-join eligibility does not imply `DEPENDENT SUBQUERY`** — subquery materialization is
  a separate optimization. `NOT IN`/`NOT EXISTS` becomes an **antijoin** from 8.0.17.
- **Implicit type conversion is not symmetric** — numeric values against an indexed *string* column
  convert the column and kill the index; the reverse usually converts the constants.
- **`eq_range_index_dive_limit` is a threshold**, so a 200-value list already uses statistics.
- **Version gates split correctly**: row aliases 8.0.19+, `VALUES()` deprecation 8.0.20+,
  `EXPLAIN ANALYZE` 8.0.18+, `JSON_SCHEMA_VALID` 8.0.17+.
- **SQLite:** `STRICT` performs lossless coercions (text `'12'` enters an `INTEGER` column); `->>`
  is **3.38+**, so it is a syntax error on the stated 3.37 baseline; FTS5 is a compile-time option;
  `busy_timeout` does not cover `SQLITE_BUSY_SNAPSHOT`; `INTEGER PRIMARY KEY` is the rowid only in
  rowid tables; NFS is an unverifiable corruption *risk*, not a guaranteed failure.
- **PostgreSQL:** `ON CONFLICT` infers any non-deferrable unique index, not only a named constraint;
  `n_dead_tup` is not a bloat measurement; `RESTRICT` and `NO ACTION` are not defined as identical.

**Procedures that would have broken in production**

- The **default-partition replacement sequence was not atomic** — between `DETACH` and re-`ATTACH`,
  inserts outside existing bounds fail. Now wrapped in a transaction, with the lock cost stated and a
  low-lock exclusion-`CHECK` variant added.
- The **advisory-lock job claim allowed double claims** — a lock serializes only while held, so the
  next caller re-claimed a job already in progress. The state check now lives in the `UPDATE`.
- The **deferred-join pagination query had no outer `ORDER BY`**; a derived table's order is not
  preserved, so the page came back in arbitrary order.
- A **column-swap timeline dropped the old column while the application still dual-wrote it.**
- **`CREATE INDEX CONCURRENTLY IF NOT EXISTS`** skips the invalid index a failed build leaves behind
  and reports success.
- **PK cutover is not "one transaction" on MySQL** — DDL cannot be wrapped in one. The procedure now
  splits by engine, including sequence/`AUTO_INCREMENT` ownership, which the previous version left
  undefined.

**Consistency and flow**

- Integer-PK growth class reached four files it had missed, so the plugin no longer says both
  "always bigint" and "by growth class".
- `db-select` routed new table design straight to the engine guidelines as a peer option, bypassing
  the conceptual and logical gates. New design now goes to `rdbms-modeling` first.
- Nothing routed **to** `rdbms-review` from the engine guidelines, naming, or migrations — the
  commonest entry path had no exit into review.
- Commands and agents were restating skill policy, which `AGENTS.md` forbids — and the copies had
  already drifted, omitting SQLite from the FK split and contradicting the denormalization rule.
  Trimmed to pointers plus genuinely invocation-specific behaviour.
- The session hook told the agent not to re-ask the engine while `rdbms-modeling` required
  confirming it; the hook now says the engine is inferred and the *version* still needs confirming.
- Unactionable thresholds got derivable criteria: partitioning, delta history, `CASCADE` fan-out
  severity, external pooler, built-in queue, BCNF exception, `socketTimeout`.
- Money was told to be an integer minor unit in one place and fixed-point `decimal` in two others.
- Soft delete was `is_active` in the standard and `deleted_at` in three examples.
- `pk_<table>` is impossible on MySQL (the PK index is always `PRIMARY`) and on SQLite (the rowid
  alias must be inline) — documented as engine exceptions instead of an unsatisfiable rule.

**Examples now follow the plugin's own rules** — generic `id` columns renamed to `<table>_id`,
reserved identifiers removed (`user` table, `role` column, `rank` alias), join-key types matched to
their parent, redundant indexes separated by access pattern, ORM examples (Prisma CUID, Drizzle
UUIDv4, Kysely `bigint` on a bounded entity) corrected with named constraints, missing `created_at`
added, and snippets that referenced undefined `db`/`pool` made callable.

## 0.3.1

Integer PK sizing, corrected. The previous guidance said widening a column later is comparatively
easy — true for an ordinary column, **wrong for a primary key**, which is where it mattered most.

**Fixed**

- **PK type is a one-way decision.** MySQL has no in-place path for changing an integer's type, so
  `ALTER TABLE … MODIFY` on the PK requires `ALGORITHM=COPY`: a full table rebuild, plus a rebuild of
  **every secondary index** (InnoDB appends the PK to all of them). On PostgreSQL,
  `ALTER COLUMN … TYPE bigint` rewrites the table under `ACCESS EXCLUSIVE`. Both cases also require
  every referencing column to move in lockstep — and under this plugin's logical-FK policy those are
  plain columns needing their own migrations.
- **PK size now follows growth class, not current row count.** An *entity* table (one row per real
  thing) is capped by the real world — `member` cannot exceed the human population, so `int unsigned`
  and its 4.2 billion is enough. An *event/log* table has no cap: rows = insert rate × elapsed time.
  At 10,000 inserts/s an `int unsigned` is exhausted in about **five days**. IoT telemetry, audit
  trails, message history, access logs, metering, outbox → `bigint unsigned` from the start.
- **Retention does not reclaim ID space.** `AUTO_INCREMENT` and sequences never reuse values, so
  deleting old rows or dropping old partitions frees storage but not range. A 30-day-retention log
  table burns through the range at the full insert rate as if nothing were ever deleted.
- **`UNSIGNED` is now the MySQL default for non-negative columns.** The old text preferred
  `CHECK (col >= 0)` for portability, which gave up `UNSIGNED` for a requirement nobody had.
  `UNSIGNED` doubles the positive range for the same bytes — free runway on exactly the columns most
  likely to run out. Added the two traps: `UNSIGNED` subtraction below zero **wraps to a huge
  positive value** rather than erroring (absent `NO_UNSIGNED_SUBTRACTION`), and mixing signed with
  unsigned across a join key is a type mismatch.
- `rdbms-naming`'s Bad/Good table had `member` in both columns — a bulk rename had made the example
  teach nothing. Restored to `users` → `member`.
- Example schemas now demonstrate the entity/event contrast (`member` `int unsigned`,
  `chat_history` `bigint unsigned`) instead of applying one type everywhere.

## 0.3.0

Eight rounds of review — Claude self-review plus independent Codex passes — found and fixed 151
issues. Several passes caught bugs introduced by *earlier* fixes, which is why there were eight.

**New**

- `sqlite-guideline` — SQLite 3.37+ as a first-class third engine: type affinity and `STRICT`
  tables, the PRAGMA baseline (`foreign_keys` is OFF by default), single-writer design,
  `INTEGER PRIMARY KEY`/rowid, FTS5, and the growth path back to `db-select`.
- Transaction isolation per engine — InnoDB's `REPEATABLE READ` with gap locks on locking reads
  vs PostgreSQL's `READ COMMITTED` with no gap locks and `40001` serialization failures.
- Multi-tenancy shape in `db-select` — shared tables + `tenant_id`, schema per tenant, database
  per tenant, with the consequences of each.

**Corrected engine claims** (the ones most likely to have misled)

- Dropping an InnoDB FK does **not** drop its auto-created child index — the index survives under
  an auto-generated name, which cleanup jobs then remove.
- FK parent-row shared locks do **not** serialize child writes against each other; they conflict
  with parent-key updates and deletes.
- PostgreSQL has no `ALTER TABLE … SPLIT PARTITION` (proposed, then reverted before release).
- `NOTIFY` takes no bind parameters — use `pg_notify()`; compose `LISTEN` channels with
  `sql.Identifier`.
- Session-level advisory locks are not released by returning a pooled connection; a process crash
  *does* release them.
- `ADD COLUMN … NOT NULL` with no default **fails** on a non-empty table; it does not rewrite it.
- `CREATE INDEX CONCURRENTLY` is PostgreSQL-only and unsupported on a partitioned parent.
- `UUID_TO_BIN`'s swap flag is for UUIDv1 only — applying it to a UUIDv7 destroys its ordering.
- MySQL LTS support is roughly Premier 8y + Extended 3y, and only the `9.7.x` series is LTS.
- Superusers and `BYPASSRLS` roles bypass RLS even under `FORCE ROW LEVEL SECURITY`.

**Ordering bugs in procedures that would break production**

- The `NOT NULL` migration path added its `CHECK` before writers populated the column — a
  `NOT VALID` check still enforces on new writes, so running inserts would fail.
- The column-rename procedure backfilled before deploying dual writes, leaving rows written in
  between with a `NULL`.

**Examples that could not run**

`MySQLConnector` called undefined methods; PostgreSQL `schema-design.md` created the same table
twice; a Prisma schema referenced an undefined model and used `#` for comments; golang-migrate's
`CREATE INDEX CONCURRENTLY` sat inside an implicit transaction; a Django "batched" backfill ran
inside one transaction; advisory-lock snippets used top-level `async with`; a UUID literal
contained ellipses. All Python examples now pass `ast.parse`, and the logical-FK examples were
rewritten against the real psycopg3 and mysql-connector APIs.

**Examples that violated the plugin's own rules**

`SELECT *` in application queries, PostgreSQL `varchar(255)`, reserved and plural table names
(`users`, `orders` → `member`, `purchase_order` per `rdbms-naming`), retired `uidx_`/`ftx_`
prefixes, redundant indexes, join keys whose type did not match the parent, and logical FKs
missing their four compensating controls.

**Other**

- Full-text index prefix `ftx_` → `fts_` (`FTX` is not standard terminology). Existing `ftx_*`
  indexes may remain; rename opportunistically.
- `rdbms-modeling/SKILL.md` compressed 600 → ~510 lines by moving detail into reference files,
  with no behaviour change.
- Session hook now detects MariaDB and SQLite separately, and **asks which engine applies** when
  more than one is present instead of suppressing the question.

## 0.2.0

Added `sqlite-guideline`; first two review passes applied.

## 0.1.0

Initial release. Eight skills shared by Claude Code and Codex, three command pairs, two Claude
Code subagents, and a session-start database-detection hook.
