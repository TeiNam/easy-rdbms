# Easy RDBMS

![Claude Code](https://img.shields.io/badge/Claude%20Code-Plugin-D97757.svg) ![Codex](https://img.shields.io/badge/Codex-Plugin-412991.svg) ![MySQL](https://img.shields.io/badge/MySQL-8.4%20LTS-4479A1.svg) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-336791.svg) ![SQLite](https://img.shields.io/badge/SQLite-3.37%2B-003B57.svg)
![Python](https://img.shields.io/badge/Python-3-blue.svg) ![Shell](https://img.shields.io/badge/Shell-POSIX%20sh-89E051.svg) ![Docker](https://img.shields.io/badge/Docker-Tests-2496ED.svg) ![Markdown](https://img.shields.io/badge/Markdown-Skills-000000.svg) ![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-CI%20%26%20Release-2088FF.svg) ![License](https://img.shields.io/badge/License-MIT-green.svg)

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/teinam)

## Overview

**A database plugin for vibe coders.** Ship at the speed you are used to, and get the schema a
database engineer would have designed — at the beginning, while it still costs nothing.

AI agents write good application code. Where they quietly fall short is the database, because a
schema is the one part of a codebase you cannot refactor in an afternoon. A function is a rewrite.
A primary key on a billion-row table is a multi-week migration project with production deploys in
the middle. Agents default to what *looks* right — `SERIAL` keys, `users` as a table name, `FLOAT`
for money, `CASCADE` everywhere — and every one of those is correct on day one and expensive at
month twelve.

This plugin front-loads exactly those decisions. **[The same app, designed twice →](docs/with-and-without.md)**
walks one realistic schema through both paths, side by side:

| Without the plugin | What happens | With the plugin |
|---|---|---|
| `messages.id SERIAL` | An event table grows as rate × time. PostgreSQL `int` is signed (a 2.1B ceiling), so at 10k inserts/s the range is gone in **~2.5 days** — and deleting old rows does not give it back | `bigint`, because rows have no cap |
| `CREATE TABLE users` | `user` is reserved in PostgreSQL. Quote it forever, or rename it later and touch every query | `member`, decided once |
| `ON DELETE CASCADE` to messages | One account deletion walks your largest table in a single transaction | Deletion is an explicit, batched path |
| `cost FLOAT` | Rounding error accumulates until the invoice and the ledger disagree | `numeric`, sized per currency |

None of those fail a test. None get caught in review. They surface when the table is already full.

**18 years of production DBRE practice, packaged as a plugin.** Not textbook normal forms — the
things you only learn by running databases:

- The foreign key you add today that quietly makes the table it sits on impossible to partition next
  year.
- One popular parent row that slows down writes to a completely unrelated table.
- A partition-creation job that stops without raising an error, so nobody notices for months.
- An index that costs more on every write than it ever gives back on reads.

Works in both **Claude Code** and **Codex** from one shared `skills/` directory. The plugin picks
the database for your scale and budget, keeps naming consistent, takes requirements through
conceptual → logical → physical modeling instead of straight to DDL, and reviews schemas, queries,
and migrations before they ship. Targets MySQL **8.4 LTS** and PostgreSQL **18**, with explicit
compatibility gates for existing PostgreSQL 16/17 and managed/Aurora variants, plus SQLite for
embedded and prototype workloads. A newer major is a separate upgrade decision.

The recurring theme: **structural cost is never paid without evidence.** Denormalization needs a
measurement, partitioning needs the queries and retention code, and an index needs the plan.

한국어 안내는 [아래](#한국어)에 있습니다.

## Install

### Claude Code

```bash
/plugin marketplace add TeiNam/easy-rdbms
/plugin install easy-rdbms@easy-rdbms
```

### Codex

```bash
codex plugin marketplace add TeiNam/easy-rdbms
codex plugin add easy-rdbms@easy-rdbms
```

Codex does not trust plugin hooks automatically. After installation, open `/hooks`, review the
Easy RDBMS `SessionStart` hook, and trust it to enable automatic engine detection.

Either harness also installs from a local checkout — pass the path instead of the repo slug.

### Updating

In Claude Code, run `/easy-rdbms:update`; in Codex, invoke `$easy-rdbms:update`.
The shared update skill refreshes this marketplace, updates the installed plugin, and verifies
the installed version. It operates on the current harness unless you request both.

For an older installation that does not have the update skill yet, use the native CLI commands:

```bash
# Claude Code
claude plugin marketplace update easy-rdbms && \
  claude plugin update easy-rdbms@easy-rdbms && \
  claude plugin list --json

# Codex: refresh the catalog, then update the installed plugin
codex plugin marketplace upgrade easy-rdbms && \
  codex plugin add easy-rdbms@easy-rdbms && \
  codex plugin list --marketplace easy-rdbms --json
```

Start a new Codex session afterwards. In Claude Code, run `/reload-plugins` or start a new session.
Local paths and pinned refs retain their configured source. Claude Code also supports marketplace
auto-update: `/plugin` → Marketplaces → easy-rdbms → Enable auto-update. This is opt-in for
third-party marketplaces; the plugin does not change that setting.

## What's inside

Nine skills, shared by both harnesses: eight for database work and one for plugin updates.
They activate when a task mentions relevant work; you can also name one explicitly.

| Skill | Use it for |
|---|---|
| `db-select` | Which database, which topology, and what it costs over three years |
| `rdbms-modeling` | Conceptual → logical → physical design with a confirmation gate between stages |
| `rdbms-review` | Reviewing existing SQL, schemas, and migrations |
| `rdbms-naming` | Table, column, index, and constraint naming; data type selection |
| `mysql-guideline` | MySQL 8.4 LTS+ / Aurora MySQL mechanics |
| `postgres-guideline` | PostgreSQL 18, 16/17 compatibility, managed/Aurora, FDW/PostGIS/pgvector |
| `sqlite-guideline` | SQLite 3.37+ — embedded, local, prototype |
| `database-migrations` | Zero-downtime schema change and rollback strategy |
| `update` | Update this plugin and verify its installed version |

`rdbms-modeling` carries **ten reference files** loaded on demand, so the policy detail costs
nothing until the model actually needs it.

### Explicit invocation

Skills activate automatically when the task matches. To invoke one explicitly:

| Task | Claude Code | Codex |
|---|---|---|
| Database selection | `/db-select` | `$easy-rdbms:db-select` |
| Schema design | `/schema-design` | `$easy-rdbms:rdbms-modeling` |
| Schema review | `/schema-review` | `$easy-rdbms:rdbms-review` |
| Plugin update | `/easy-rdbms:update` | `$easy-rdbms:update` |

Codex users can browse installed skills with `/skills`. Codex plugins do not register custom slash
commands.

### Subagents (Claude Code only)

`rdbms-modeler` and `rdbms-reviewer` — thin wrappers over the skills. Codex plugins cannot
register named subagents, so on Codex the same procedures live entirely in the skill bodies.

### Session hook

On session start the hook reads `docker-compose.yml`, `.env`, `alembic.ini`,
`prisma/schema.prisma`, `package.json`, `requirements.txt`, `Cargo.toml`, `go.mod`, and similar,
then reports the engine once. It recognizes PostGIS/pgvector images and Java build files, and
keeps both **MariaDB and MySQL** when both are configured. With multiple engines it preserves the
user's specified target and asks only when the target is unresolved. Silent when nothing is found.
An explicit project path takes priority; otherwise the hook checks the current directory and its
ancestors through the Git root. Outside Git it checks only the current directory.

## What's covered, in detail

### `db-select` — choosing the engine

A gate of **13 facts** it will ask for before recommending anything: 12-month volume and peak
traffic, read/write ratio, access patterns, RTO/RPO, per-flow consistency, whether a DBA exists,
lock-in tolerance, PII and audit requirements, one-year and three-year budget, traffic shape,
migration source, and existing team experience. "Unknown" is a valid answer and pushes the
recommendation toward the replaceable option.

Then five steps:

1. **Is an RDBMS even right** — default yes, specifically PostgreSQL. Leave-criteria for
   DynamoDB, MongoDB, Redis, ClickHouse/DuckDB, and search engines, each with what you give up.
   Plus six **objections that do not justify leaving** ("our schema will change a lot", "SQL
   doesn't scale", "we need a queue"…) answered individually. Full ACID is treated as a baseline
   requirement, not a feature to trade.
2. **Scale tier 0–4** — data volume × peak QPS, with an explicit *do NOT yet* column per tier, and
   a cheapest-first escalation order (fix the queries → cache → replicas → scale up → partition →
   move analytics off → only then shard).
3. **MySQL or PostgreSQL** — a per-column comparison, with the note that single-row read
   benchmarks are not a tiebreaker at tiers 0–2.
4. **Deployment form** — container, managed instance, Aurora, serverless, platform DB, distributed
   SQL, each with what to watch for.
5. **Three-year TCO** — `references/cost-evaluation.md` has the cost components, the TCO and
   outage-risk formulas, per-scale defaults, and decision rules. When real prices are unavailable
   `db-select` grades low/medium/high **and says it graded rather than priced**.

Also: **multi-tenancy shape** — shared tables + `tenant_id`, schema per tenant, database per
tenant — with the consequences of each, including that schema-per-tenant is namespace and
privilege isolation, not resource or failure isolation.

Output is up to three candidates with one named default, a graded cost assessment, and
re-evaluation triggers that must be **measurable** ("when we get bigger" is rejected).

### `rdbms-modeling` — three stages, ten reference files

A rigor gate first: payments, inventory, permissions, contracts, ledgers, and audit get all three
stages in full; a personal tool may compress the first two — but must say so.

**Stage 1 — conceptual.** Business concepts, relationships, and the terms *users* use. No columns,
no types, no keys, no DB product. Flags specialization candidates by reading the IS-A sentence
aloud, and separates what a thing **is** from what it is **doing** (neither states nor roles are
kinds). Stops at a confirmation gate — terminology corrections are cheapest here.

**Stage 2 — logical.** Entities, attributes, PK/FK, cardinality, NOT NULL and UNIQUE, using
generic types only. Runs normalization, the generalization check, and the history question. Stops
at a confirmation gate.

**Stage 3 — physical.** Only now is the engine confirmed — because the logical model is what makes
that choice answerable. Then naming, engine types, the identifier decision, constraints, indexes,
views, partitioning, and ordered migration SQL, closing with sample data that exercises the
constraints.

The reference files, loaded on demand:

| File | What it settles |
|---|---|
| `normalization.md` | 1NF→3NF rules, the BCNF check procedure, the denormalization bar |
| `generalization.md` | IS-A and substitutability, seven questions, three outcomes, identifier inheritance, physical mapping |
| `identifier-selection.md` | UID vs PK, per-engine storage model, UUIDv4/v7, the `UUID_TO_BIN` swap-flag trap, PG 18 `uuidv7()` |
| `foreign-keys.md` | The engine split, the six PostgreSQL gates, the reference-target rule, inherited schemas |
| `partitioning.md` | Code-based recommendation policy, recommend/exclude conditions, MySQL RANGE-only scope, safety-partition operating rules |
| `history-entities.md` | Audit vs business vs valid-time, eight methods, the standard history entity, transaction flows, the trigger-audit exception |
| `denormalization.md` | The measured-problem bar, eight methods, nine cheaper alternatives, synchronization mechanisms, seven apply-conditions |
| `db-internal-routines.md` | Procedures/triggers/events in three categories: sanctioned utilities, the narrow audit exception, prohibited business logic |
| `views-and-materialized-views.md` | View vs materialized view vs summary table, indexing base tables vs the MView, `REFRESH CONCURRENTLY` prerequisites |
| `index-design.md` | Evidence required, write-heavy tables per engine, covering indexes and Heap Fetches, pattern matching, FTS, search-engine migration signals |

### Normalization, generalization, denormalization

**3NF is required.** BCNF is *checked on every entity* — test each table for a determinant that is
not a superkey — and the entity is decomposed when that determinant can produce a real anomaly.
Staying at 3NF is allowed when decomposition cannot preserve functional dependencies or explodes the
join count, but the reason must be named. `"BCNF: no violations"` is a valid and expected result.

**Generalization is decided by IS-A, not attribute overlap.** Seven questions — genuine IS-A,
subtype-specific attributes, exclusivity, totality, type mutability, type-vs-state, query shape —
land on one of three outcomes:

| Situation | Build |
|---|---|
| Same attributes, relationships, rules; only the label differs | Type column with a `CHECK` |
| Mutable responsibilities, or several held at once | Role table with validity dates |
| Genuine IS-A with subtype-specific attributes or constraints | Supertype + subtypes |

The highest-value check is **type vs state**. `pending` / `paid` / `cancelled` are states of an
order, not subtypes — modeling them as subtypes turns every transition into a cross-table move.
Guarded from the other side too: a supertype whose meaningful columns all ended up nullable has
traded database constraints for application checks, and an entity/attribute/value table gave up on
the schema entirely.

**Denormalization requires a measurement**, the nine cheaper alternatives ruled out first, a named
source of truth, a synchronization mechanism, a consistency-check query, and a rebuild path — seven
conditions, all of them. One distinction that trips people up: a **snapshot of a business fact is
not denormalization**. The price on an order line at purchase time is the transaction's own data,
not a cached copy — if the source changes and this value should *not* follow, it needs no
synchronization.

ACID and normalization are treated as separate concerns: one keeps transactions safe, the other
keeps the schema from drifting. Neither substitutes for the other.

### Foreign keys — an engine-split policy, not one rule

| | MySQL / InnoDB | PostgreSQL | SQLite |
|---|---|---|---|
| Physical `FOREIGN KEY` | Logical by default; respect project policy on non-partitioned tables | Allowed — through six gates | Allowed |
| Integrity owner | Application for logical FKs; database for physical FKs | The database, once valid | The database, if the pragma is on |
| Referencing-column index | Verify it; create manually for logical FKs | Create it (never auto-created) | Create it (never auto-created) |

**Why the MySQL default differs.** InnoDB cannot put a foreign key on a partitioned table in either
direction, and online schema-change tools have FK limitations. Those are reasons to evaluate
logical FKs, not to remove every existing constraint. Respect project policy and measure write/lock
costs before changing the integrity mechanism.

**The trap that is easy to miss:** InnoDB auto-creates the referencing-column index only *when the
FK is created*. Under a no-FK policy nothing creates it for you, so the referencing-column index is
deliberate and manual. (On an inherited schema, dropping an FK *leaves* its auto-named index behind
— verify with `SHOW INDEX` and rename it before a cleanup job removes it.)

**The six PostgreSQL gates:** parent is PK/UNIQUE · referencing column indexed · no redundant index
· `CASCADE` only for genuine lifecycle dependency · `NOT DEFERRABLE` · a validation path within the
lock budget. Populated non-partitioned referencing tables can use `NOT VALID` then `VALIDATE`;
PostgreSQL 16/17 partitioned referencing tables cannot; PostgreSQL 18 supports it. Full version and rollout rules are in
`skills/rdbms-modeling/references/foreign-keys.md`.

Every **logical** FK carries four compensating controls: the reference in a `COMMENT`, the index, a
named **integrity owner**, and a **scheduled orphan-detection query**. And on SQLite, `PRAGMA
foreign_keys = ON` per connection — otherwise every `REFERENCES` clause in the schema is decoration.

### History — purpose before structure

"History" conflates three questions, and a design answering one answers neither of the others:

| Kind | Answers | Structure |
|---|---|---|
| Audit | Who changed what, when | Audit columns, or a history table |
| Business | Which state changed, and **why** | State-transition history with actor + reason |
| Valid-time | What was in effect at a point in time | `valid_from` / `valid_to` period model |

`updated_at` answers none of them. Eight methods are ranked by cost — audit columns, current +
history table, state-transition, valid-period, bi-temporal, trigger audit, event sourcing, CDC —
and you start at the top. CDC carries no business reason for a change, so it is never the only
mechanism.

Two rules hold regardless of method: the current row and its history are written in **one
transaction**, and **no FK links an entity to its history** — because every referential action is
wrong there. `CASCADE` deletes the evidence, `RESTRICT` makes the parent undeletable, `SET NULL`
orphans the history row.

### Indexes and partitioning — evidence, or nothing

An index recommendation **never ships alone**. It carries the query that justifies it, why the
columns are in that order, the write cost, the plan before and after, and the rollback. With no plan
or metrics available the answer is `needs measurement` — not an estimated improvement percentage.

Engine differences get real weight:

- **InnoDB** appends the PK to every secondary index, so a wide PK inflates all of them. An
  *invisible* index de-risks the read side but **still costs writes**.
- **PostgreSQL** loses HOT updates when a churning column is indexed — often costlier than the index
  itself. An `INCLUDE` column enables an index-only scan but does not guarantee one; **Heap Fetches**
  has to be checked.
- Composite order is conditional, not a mnemonic: equality first, then sort-before-range when the
  query needs the index's ordering, or range-first when the range is highly selective.
- `filesort` in a MySQL plan means an extra sort pass — **not necessarily a disk sort**.

**Partitioning is recommended, never applied by default.** The analysis reads the queries and the
retention/deletion code; no time-range query and no retention policy means no partitioning, only a
candidate needing volume figures. Confidence is reported, and it is **low** whenever the figures were
assumed rather than found.

MySQL generates only `RANGE`/`RANGE COLUMNS` — stated explicitly as a **scope decision, not a
technical limit**, since MySQL prunes LIST, HASH, and KEY too. PostgreSQL may use RANGE, LIST, or
HASH. Both get a trailing safety partition with operating rules: alert when rows land in it,
pre-create 2–3 periods, move rows out before dropping it.

### Views, routines, migrations

**A view is not a cache.** PostgreSQL rewrites it into a base-table query; MySQL merges it or
materializes it into a temporary table. Either way the work still happens — the view only moved
where the SQL lives. Acceleration means a PostgreSQL materialized view or a MySQL summary table (8.4
has no native materialized view); either option inherits the denormalization requirements. Nested
views get special attention: each layer looks reasonable while the composed query does something
nobody intended.

**Procedures, triggers, and events split by what the routine *does*:**

| Category | Verdict |
|---|---|
| Infrequent operational utilities — partition rotation, retention purge, statistics refresh, consistency checks | **Allowed** — scheduled, idempotent, version controlled, monitored |
| Audit trigger | **Narrow exception** — the only way to capture writes that bypass the application; audit table only |
| Business logic — maintaining a denormalized value, setting `updated_at`, enforcing a transition | **Prohibited** |

**Migrations** cover the safety checklist, PostgreSQL and MySQL mechanics, and workflows for Prisma,
Drizzle, Kysely, Django, and golang-migrate. The procedures are ordered correctly, which matters more
than it sounds: the `NOT NULL` path deploys writers *before* adding the check (a `NOT VALID` check
still enforces on new writes), and the column rename deploys dual writes *before* backfilling.

### Naming and identifiers

`rdbms-naming` is the single source: lowercase `snake_case`, singular tables, past-participle time
columns (`created_at` / `updated_at` / `deleted_at`), `is_`/`has_` boolean prefixes, and
**lowercase-prefix** constraints and indexes — `pk_` `fk_` `uq_` `chk_` `idx_` `fts_`. The uppercase
`_IDX` suffix is retired because it breaks under PostgreSQL case-folding, and `ftx_` was retired in
favour of `fts_` since FTX is not standard terminology.

Reserved words are renamed rather than quoted: `user` → `member`, `order` → `purchase_order`. A
63-byte identifier ceiling with an ordered shortening procedure. Case-folding differences between
engines are covered up front, because a name that "works" on one engine silently changes on another.

**Identifiers separate the logical UID from the physical PK.** A PK is `NOT NULL`, `UNIQUE`, and
immutable; business identifiers that can change or be exposed go in a `UNIQUE` constraint. Never a
raw timestamp alone, never `char(36)` for a UUID, and **a UUID is not a credential**.

| Situation | MySQL / InnoDB | PostgreSQL |
|---|---|---|
| Bounded entity table | `int unsigned AUTO_INCREMENT` | `int GENERATED ALWAYS AS IDENTITY` |
| Event/log table | `bigint unsigned AUTO_INCREMENT` | `bigint GENERATED ALWAYS AS IDENTITY` |
| Write-heavy | Sequential integer first | `IDENTITY` or UUIDv7 — not v4 |
| Generated on multiple nodes | UUIDv7 as `binary(16)` | native `uuid` with UUIDv7 |
| Exposed externally | Internal integer PK + public UID | UUID PK, or integer PK + public UID |

Two traps: `UUID_TO_BIN(v, 1)`'s swap flag is **UUIDv1-only** — applying it to a v7 destroys the
ordering you chose v7 for; and `uuidv7()` is built in only from **PostgreSQL 18**, while
`gen_random_uuid()` returns v4.

### Engine specifics

| | Covered |
|---|---|
| **MySQL** | 8.4 LTS track and release policy, InnoDB + utf8mb4 defaults, per-currency `decimal` precision, `DATETIME` vs `TIMESTAMP` (Y2038), `INET6_ATON`, composite index order, range-column pair optimization, `RANGE COLUMNS` partitioning with `REORGANIZE`, `REPEATABLE READ` and gap locks, deadlock checklist, `SKIP LOCKED` queues, keyset pagination, `FULLTEXT` with the `ngram` parser, replica lag and read-after-write routing, GRANT least privilege and TLS, `my.cnf` baseline, pool sizing against `wait_timeout`, JDBC driver selection for Aurora |
| **PostgreSQL** | 18 baseline: native UUIDv7, VIRTUAL/STORED gates, skip scan and async I/O; 16/17 compatibility; schema separation, identity, timestamptz/jsonb, GIN/GiST/BRIN, RLS and pool scope, partitioned FK validation, pg_partman; FDW/PostGIS/pgvector and extension operations below |
| **SQLite** | 3.37+ `STRICT` tables, the PRAGMA baseline (`foreign_keys` is OFF by default), conventions where no native type exists (integer cents for money), `INTEGER PRIMARY KEY` as rowid and why `AUTOINCREMENT` is usually unnecessary, single-writer design with `BEGIN IMMEDIATE`, why network filesystems are out, FTS5, `VACUUM INTO` backups, and the growth path back to `db-select` |

MySQL 8.4 guidance covers authentication changes, InnoDB defaults, standard FK targets, bounded
GTID waits and removed commands. SQLite keeps 3.37 as the compatibility floor, with JSONB gated
at 3.45 and modern `PRAGMA optimize` guidance at 3.46.

### PostgreSQL extensions

The existing `postgres-guideline` routes directly to these guides; no extra skill is required.
Choose extensions by workload and verify the provider's supported versions before installation.

| Need | Guide |
|---|---|
| Inventory, installation, permissions, preload, upgrades; pg_stat_statements, pg_trgm, btree_gist, pg_cron, pg_partman, pgstattuple, pgAudit | [Extension operations](skills/postgres-guideline/extensions.md) |
| External PostgreSQL access with postgres_fdw: TLS, mappings, pushdown, remote RLS and transaction limits | [FDW](skills/postgres-guideline/fdw.md) |
| Spatial types, SRID, meters vs degrees, GiST, ST_DWithin and KNN | [PostGIS](skills/postgres-guideline/postgis.md) |
| Embedding models/dimensions, exact/HNSW/IVFFlat, filtered ANN, RLS and recall | [pgvector](skills/postgres-guideline/pgvector.md) |
| PostgreSQL 18 features, 16/17 compatibility, major upgrades and Docker data paths | [Version and upgrade](skills/postgres-guideline/version-and-upgrade.md) |

Example requests: “Connect a read-only external PostgreSQL with FDW”, “Find locations within 1 km
using PostGIS”, or “Check pgvector recall with tenant filters”. There is no install-everything
bundle; pgvector stores/searches embeddings and does not run the embedding model.

## How it was verified

The updated suite passed on **2026-09-25** with PostgreSQL **18.6**, MySQL **8.4.11**, PostGIS
**3.6.4**, pgvector **0.8.6**, Django **5.2.17**, and the runner's SQLite **3.53.1**. The separate
PostgreSQL **16.15** compatibility run also passed; PostGIS/pgvector were exercised on 18.
The commands are in Development below. The earlier observations are retained separately:

### Executed against real servers

The claims that decide a schema were run on **MySQL 8.4.11** and **PostgreSQL 16.15** containers and
local **SQLite 3.51**, not asserted from memory:

| Claim | What the server did |
|---|---|
| Changing a PK's integer type needs `ALGORITHM=COPY` | `INSTANT` → `ERROR 1846`; `INPLACE` → `ERROR 1846 … Cannot change column type INPLACE. Try ALGORITHM=COPY`; only `COPY` succeeded |
| `UNSIGNED` subtraction below zero errors, and `sql_mode` does not change that | `ERROR 1690 (22003) BIGINT UNSIGNED value is out of range`, including under `sql_mode = ''`. `NO_UNSIGNED_SUBTRACTION` returned `-1` |
| `tinyint(1)` does not constrain to 0/1 | Accepted `2` and `-5`; `tinyint unsigned` accepted `200` |
| `CONSTRAINT pk_x PRIMARY KEY` is discarded on MySQL | `information_schema.statistics` reported the index name as `PRIMARY` |
| Gap locks at `REPEATABLE READ` are not unconditional | Unique-equality `FOR UPDATE` → the gap `INSERT` **succeeded** (record lock only); the same insert behind a **range** `FOR UPDATE` → `ERROR 1205` lock wait timeout |
| A partitioned table's PK must include the partition key | `ERROR: unique constraint on partitioned table must include all partitioning columns` |
| Detaching the `DEFAULT` partition opens a write-failure window | `ERROR: no partition of relation "d" found for row` — the same insert succeeded while it was attached |
| A prepared table and validated CHECKs allow attachment without detaching the default | `ATTACH PARTITION` completed with `ShareUpdateExclusiveLock` on the parent |
| `ON CONFLICT` infers a plain unique index, but not a `DEFERRABLE` one | Plain index upserted; `DEFERRABLE` → `ERROR: ON CONFLICT does not support deferrable unique constraints … as arbiters` |
| SQLite `STRICT` performs lossless coercions | `'12'` stored as integer `12`, `42` stored as text `'42'`, `'abc'` rejected |
| `WITHOUT ROWID` has no rowid | `SELECT rowid` is a parse error there; in a rowid table `INTEGER PRIMARY KEY` returned the rowid |

The example DDL was executed too — the "with the plugin" schema from [the comparison
doc](docs/with-and-without.md) creates cleanly on PostgreSQL 16 and every `CHECK` in the schema
actually rejects the value it is supposed to.

### Review rounds

Eleven rounds — Claude self-review plus independent Codex passes — found and fixed **292 issues**.
Findings per round: 33 → 18 → 11 → 17 → 32 → 31 → 6 → 3 → 5 → 116 → 20.

Round 10 was the largest, and not because the plugin got worse: it was the first round to run
two Codex passes with **separate mandates** (engine facts; cross-file consistency and flow) instead of
one general pass. A large share of what that round found had been introduced by the round before it.

The count did not fall monotonically, and the reason is worth stating: rounds 1–4 concentrated on
newly written content, so round 5 was the first deep read of the **ported** guideline files and
found 32 issues there. Round 6 then found 31 — several of them **bugs introduced by round 5's own
fixes** (an invalid Prisma comment, a naming rule accidentally reversed by a bulk rename, an
invented CLI flag, async code left unwrapped). Reviewing the fixes turned out to matter as much as
reviewing the original.

Round 11 added 20 corrections around PK cutovers, concurrent backfills, FK policies, partition
operations, naming, and hook discovery. `scripts/check-examples.py` runs the documented SQL and
Django code against disposable databases, alongside metadata, SQLite, and sync checks.

What that surfaced, by category:

- **Engine claims that would have misled** — dropping an InnoDB FK does not drop its
  referencing-column index; FK parent-row locks do not serialize child writes against each other;
  PostgreSQL has no `SPLIT PARTITION`; `NOTIFY` takes no bind parameters; `ADD COLUMN NOT NULL`
  without a default *fails* rather than rewrites; session advisory locks survive a pooled
  connection's return but not a crash.
- **Procedures whose ordering would break production** — the `NOT NULL` path and the column rename,
  both fixed above.
- **Examples that could not run** — a connection class calling undefined methods, a table created
  twice, a Prisma model referenced but never defined, `CREATE INDEX CONCURRENTLY` inside an implicit
  transaction, a "batched" Django backfill in one transaction, top-level `async with`.
- **Examples violating the plugin's own rules** — `SELECT *`, PostgreSQL `varchar(255)`, reserved and
  plural table names, redundant indexes, join keys whose type did not match the parent.

Where two reviewers disagreed and the claim could not be verified offline (the `kysely-ctl`
subcommand form), the plugin **does not assert either form** — it points at `kysely --help`.

Automated gates, all passing:

```bash
sh hooks/detect-db.test.sh    # 32 cases: PostgreSQL / MySQL / MariaDB / SQLite / Aurora /
                              # managed platforms / multi-engine confirmation / cwd and Git-root fallback
python3 scripts/check-readme-bilingual.py
python scripts/check-examples.py  # Docker and test dependencies required; see Development
claude plugin validate .      # official manifest validation
```

The example suite also parses Python snippets, validates JSON manifests, skill frontmatter,
plugin-version agreement and skill reference paths.

## Design decisions

**One skill directory, both harnesses.** `skills/` is shared. Frontmatter is `name` + `description`
only — the intersection of what Claude Code and Codex accept. Claude Code gets `.md` commands;
Codex invokes the same procedures through namespaced skills. Codex plugins cannot register named
subagents, so modeling and review procedures live in the skill bodies and Claude Code gets thin
agent wrappers pointing at them.

**Progressive loading.** Modeling and cost detail stays in eleven files under `references/`.
The eight database skill descriptions route to the relevant engine and extension guides, which are loaded
when needed.

**Scale-aware, not scale-maximal.** `db-select` tells you *not* to add read replicas, partitioning,
or sharding you have not earned. Each tier costs roughly an order of magnitude more operational
attention than the one below it — the wasted spend is visible, but the wasted attention is what
slows a team down.

**Cost is part of the choice.** A free database still needs someone to operate it, and that person's
salary is usually the largest line item at small scale. Comparisons run over three years, never per
month.

**MySQL, PostgreSQL, and SQLite only.** Other relational engines are out of scope, and the plugin
says so rather than pretending to advise on them.

## Development

```bash
sh hooks/detect-db.test.sh          # hook detection tests (32 cases)
python3 scripts/check-readme-bilingual.py
python scripts/check-examples.py   # documented SQL + Django regressions in disposable databases
sh scripts/sync-from-harness.sh     # show upstream drift for the four ported skills
claude plugin validate .            # manifest validation
claude plugin details easy-rdbms    # component inventory and projected token cost
```

Four skills are ported from a private harness and carry deliberate local edits (dropped filename
prefixes, stripped harness-only frontmatter, cross-references repointed). `sync-from-harness.sh` is
diff-only for that reason — never blind-copy over them. See `AGENTS.md` for repo conventions.

The example check requires Docker, OpenSSL, and test dependencies in a virtual environment:
`python -m pip install 'Django>=5.2,<5.3' 'psycopg[binary]>=3,<4'`.
It starts isolated PostgreSQL 18 and MySQL 8.4 containers and removes them afterwards; it does not
connect to an existing application database. It exercises post-cutover inserts, locked-row backfills,
concurrent edits, DB alias selection, partition writes, constraints, pagination plans, PostgreSQL
version gates, RLS session reuse, pg_stat_statements/pg_trgm, FDW TLS and read-only grants, and MySQL
8.4 authentication/FK defaults. Use `--pg-major 16` for the compatibility run.

With `uv` installed, run the same checks in an isolated dependency environment from the repo root:

```bash
uv run --no-project --with 'Django>=5.2,<5.3' --with 'psycopg[binary]>=3,<4' \
  python scripts/check-examples.py
```

For PostGIS and pgvector, build the disposable-test image and run the same harness:

```bash
docker build -f scripts/Dockerfile.postgres -t easy-rdbms-examples-pg18 .
uv run --no-project --with 'Django>=5.2,<5.3' --with 'psycopg[binary]>=3,<4' \
  python scripts/check-examples.py --extensions
uv run --no-project --with 'Django>=5.2,<5.3' --with 'psycopg[binary]>=3,<4' \
  python scripts/check-examples.py --pg-major 16
```

The extension run checks spatial radius results/GiST, vector dimensions, exact versus filtered
HNSW results, and RLS. Small fixtures prove behavior, not production latency or recall.
Runs print actual server/extension versions; tags and package repositories can move. The image
is kept for reuse, while test containers/data are removed. No existing application DB is changed.

## Release automation

Merging to `main` runs the same metadata, hook, PostgreSQL 16/18, MySQL 8.4, PostGIS, and pgvector
checks in GitHub Actions. After they pass, release-please creates or updates a release PR:

1. `feat:` raises the minor version; `fix:` or `perf:` raises the patch version.
   `feat!:` or `BREAKING CHANGE:` raises the major version. Docs/chore commits alone do not release.
2. The release PR updates `version.txt`, `.release-please-manifest.json`, both plugin manifests,
   both README version lines, and `CHANGELOG.md` together.
3. CI also runs on the release PR. Merge it after checks pass; Actions then publishes the matching
   `easy-rdbms--vX.Y.Z` tag and GitHub Release from that versioned commit.

Write release notes in the conventional commit/PR squash message. Do not create a release tag
before bumping the manifests or edit the version files independently. The action is pinned to a
commit and reuses release-please's release tracking when a run is retried.

Repository setup: allow GitHub Actions to create pull requests under Settings → Actions → General.
The workflow uses `GITHUB_TOKEN` and explicitly dispatches release-PR CI, so no additional PAT is
required. To retry the process from the repository root:

```bash
gh workflow run release.yml --ref main
```

For metadata-only checks without Docker or third-party Python packages:

```bash
python3 scripts/check-examples.py --metadata-only
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md). Current: **0.5.0**. <!-- x-release-please-version -->

## License

MIT

---

## 한국어

**바이브 코더를 위한 데이터베이스 플러그인입니다.** 지금 속도 그대로 만들면서,
아직 아무 비용도 들지 않는 맨 처음에 데이터베이스 엔지니어가 설계했을 스키마를 얻습니다.

AI 에이전트는 애플리케이션 코드를 잘 씁니다. 티가 잘 안 나는 약점이 데이터베이스입니다. 스키마는
코드베이스에서 유일하게 하루 만에 되돌릴 수 없는 부분이기 때문입니다. 함수는 다시 쓰면 됩니다.
10억 행 테이블의 기본키는 중간에 배포까지 끼는 몇 주짜리 마이그레이션 프로젝트입니다.
에이전트는 *그럴듯해 보이는* 기본값을 고릅니다 — `SERIAL` 키, `users` 라는 테이블 이름,
금액에 `FLOAT`, 곳곳에 `CASCADE`. 하나같이 첫날에는 맞지만 열두 달 뒤에 비용이 큽니다.

이 플러그인은 바로 그 결정을 앞으로 당겨옵니다. **[같은 앱을 두 번 설계하기 →](docs/with-and-without.md)**
에서 현실적인 스키마 하나를 두 경로로 나란히 보여줍니다.

| 플러그인 없이 | 무슨 일이 생기나 | 플러그인과 함께 |
|---|---|---|
| `messages.id SERIAL` | 이벤트 테이블은 쓰기 속도 × 시간으로 자랍니다. PostgreSQL `int`는 signed(상한 21억)라 초당 1만 건이면 범위가 **약 2.5일**에 소진되고, 오래된 행을 지워도 범위는 돌아오지 않습니다 | 상한이 없는 테이블이므로 `bigint` |
| `CREATE TABLE users` | `user` 는 PostgreSQL 예약어입니다. 영원히 따옴표를 붙이거나, 나중에 바꾸면서 모든 쿼리를 건드려야 합니다 | 한 번에 정한 `member` |
| messages 로 걸린 `ON DELETE CASCADE` | 계정 하나를 삭제하면 가장 큰 테이블을 단일 트랜잭션으로 훑습니다 | 삭제는 명시적·배치 경로로 |
| `cost FLOAT` | 반올림 오차가 쌓이면 청구서와 원장이 어긋납니다 | 통화별로 크기를 정한 `numeric` |

넷 다 테스트에서 실패하지도, 코드 리뷰에서 걸리지도 않습니다. 테이블이 이미 다 찬 뒤에야
드러납니다.

**18년 현업 DBRE 경험을 플러그인으로 옮겼습니다.** 교과서에 나오는 정규형이 아니라,
데이터베이스를 직접 운영해야 알 수 있는 내용입니다.

- 지금 편하게 걸어둔 외래키 하나 때문에, 내년에 그 테이블을 파티셔닝할 수 없게 되는 일
- 많이 조회되는 부모 행 하나가, 전혀 상관없는 테이블의 쓰기까지 느리게 만드는 경우
- 파티션을 미리 만들어주는 작업이 에러도 없이 멈춰서, 몇 달 뒤에야 발견되는 일
- 인덱스를 하나 추가했는데, 읽기에서 얻는 것보다 매번 쓰기에서 잃는 게 더 큰 상황

**Claude Code**와 **Codex** 양쪽에서 하나의 `skills/` 디렉토리로 동작합니다. 규모와 예산에 맞는
DB를 고르고, 네이밍을 일관되게 잡고, 요구사항을 DDL로 직행시키지 않고 개념 → 논리 → 물리로
설계하며, 배포 전에 스키마·쿼리·마이그레이션을 리뷰합니다. MySQL **8.4 LTS**와 PostgreSQL
**18**을 기준으로 Aurora 등 관리형의 호환 조건, 임베디드·프로토타입용 SQLite를 다룹니다.

일관된 원칙 하나: **구조적 비용은 근거 없이 지불하지 않습니다.** 비정규화는 측정, 파티셔닝은
쿼리와 보관 코드, 인덱스는 실행계획이 있어야 합니다.

### 설치

```bash
# Claude Code
/plugin marketplace add TeiNam/easy-rdbms
/plugin install easy-rdbms@easy-rdbms

# Codex
codex plugin marketplace add TeiNam/easy-rdbms
codex plugin add easy-rdbms@easy-rdbms
```

Codex는 플러그인 훅을 자동으로 신뢰하지 않습니다. 설치 후 `/hooks`에서 Easy RDBMS의
`SessionStart` 훅을 검토하고 승인해야 자동 엔진 감지가 켜집니다.

### 업데이트

Claude Code에서는 `/easy-rdbms:update`, Codex에서는 `$easy-rdbms:update`를 호출합니다.
현재 실행 환경에서 easy-rdbms 마켓플레이스와 설치된 플러그인을 차례로 갱신하고 버전을 확인합니다.
두 환경 모두 갱신하려면 호출할 때 이를 명시합니다.

업데이트 스킬이 없는 이전 버전은 아래 CLI 명령으로 한 번 갱신합니다.

```bash
# Claude Code
claude plugin marketplace update easy-rdbms && \
  claude plugin update easy-rdbms@easy-rdbms && \
  claude plugin list --json

# Codex: 목록 갱신 후 설치된 플러그인도 갱신
codex plugin marketplace upgrade easy-rdbms && \
  codex plugin add easy-rdbms@easy-rdbms && \
  codex plugin list --marketplace easy-rdbms --json
```

Codex는 새 대화에서 적용됩니다. Claude Code는 `/reload-plugins`를 실행하거나 새 세션을 시작합니다.
로컬 경로·고정 ref는 기존 출처를 유지합니다. Claude Code의 `/plugin` → Marketplaces →
easy-rdbms → Enable auto-update로 자동 갱신을 켤 수도 있습니다. 외부 마켓플레이스는 기본적으로
꺼져 있으며, 플러그인이 사용자 설정을 임의로 변경하지 않습니다.

### 구성

DB 작업용 8개와 플러그인 업데이트용 1개, 총 9개 스킬을 두 환경에서 공유합니다.

| 스킬 | 용도 |
|---|---|
| `db-select` | 어떤 DB를, 어떤 구성으로, 3년 비용은 얼마인지 |
| `rdbms-modeling` | 개념 → 논리 → 물리 3단계 + 단계별 확인 게이트 (참조파일 10개) |
| `rdbms-review` | 기존 SQL·스키마·마이그레이션 리뷰 |
| `rdbms-naming` | 테이블·컬럼·인덱스·제약 네이밍, 데이터 타입 |
| `mysql-guideline` | MySQL 8.4 LTS+ / Aurora MySQL |
| `postgres-guideline` | PostgreSQL 18, 기존 16/17 호환, 관리형/Aurora, FDW·PostGIS·pgvector |
| `sqlite-guideline` | SQLite 3.37+ — 임베디드·로컬·프로토타입 |
| `database-migrations` | 무중단 스키마 변경, 롤백 전략 |
| `update` | 플러그인 갱신과 설치 버전 확인 |

스킬은 관련 작업이 언급되면 자동 발동합니다. 명시적으로 호출할 때는 Claude Code에서
`/db-select`, `/schema-design`, `/schema-review`를, Codex에서 `$easy-rdbms:db-select`,
`$easy-rdbms:rdbms-modeling`, `$easy-rdbms:rdbms-review`를 사용합니다. Codex의 `/skills`에서
설치된 스킬을 찾아볼 수도 있습니다.
플러그인 업데이트는 Claude Code의 `/easy-rdbms:update`, Codex의 `$easy-rdbms:update`로 호출합니다.

Claude Code 전용 서브에이전트 `rdbms-modeler`·`rdbms-reviewer`는 스킬을 가리키는 얇은 래퍼입니다.
Codex 플러그인은 이름 붙은 서브에이전트를 등록할 수 없어서, 같은 절차를 스킬 본문에 넣었습니다.

세션 시작 시 훅이 `docker-compose.yml`, `.env`, `alembic.ini`, `prisma/schema.prisma`,
`package.json`, `requirements.txt`, `Cargo.toml`, `go.mod` 등의 파일을 읽고
감지한 엔진을 한 번 보고합니다.
**MariaDB와 SQLite를 MySQL/PostgreSQL과 구분**하고, 엔진이 둘 이상 감지되면 dialect를 추측하지
말고 **어느 쪽을 대상으로 하는지 묻게** 합니다. 아무것도 없으면 조용히 종료합니다.
명시된 프로젝트 경로가 없으면 현재 디렉토리부터 Git 루트까지 확인합니다.
Git 밖에서는 현재 디렉토리만 검사합니다. PostGIS·pgvector 이미지와 Java 빌드 파일도 감지하고,
MySQL·MariaDB가 함께 있으면 둘 다 표시합니다. 사용자가 지정한 대상은 다시 묻지 않습니다.
현재 `sh hooks/detect-db.test.sh`의 32개 케이스가 통과합니다.

### 반영된 내용

#### `db-select` — 엔진 선택

추천 전에 **13개 사실**을 먼저 묻습니다: 12개월 데이터량과 피크 트래픽, 읽기/쓰기 비율, 접근 패턴,
RTO/RPO, 흐름별 일관성 요구, 전담 DBA 유무, 벤더 종속(lock-in) 허용 여부, 개인정보·감사 요건,
1년·3년 예산, 트래픽 형태, 이전할 기존 DB, 팀 경험. **"모르겠다"도 유효한 답**이고, 그럴 때는
교체하기 쉬운 쪽에 무게를 둡니다.

그다음 5단계:

1. **RDBMS가 맞는지** — 기본은 예, 구체적으로 PostgreSQL. DynamoDB·MongoDB·Redis·ClickHouse·
   검색엔진으로 나갈 조건과 각각 무엇을 포기하는지. 그리고 **나갈 이유가 되지 못하는 반론 6개**
   ("스키마가 자주 바뀔 것 같다", "SQL은 확장이 안 된다", "큐가 필요하다"…)를 하나씩 반박합니다.
   ACID는 성능과 바꿀 수 있는 기능이 아니라 기본 요구로 둡니다.
2. **규모 티어 0~4** — 데이터량 × 피크 QPS. 티어마다 **"지금은 하지 마라"** 열이 따로 있고,
   비용이 싼 순서로 대응합니다(쿼리 수정 → 캐시 → 리플리카 → 스케일업 → 파티셔닝 →
   분석 분리 → 그다음에야 샤딩).
3. **MySQL vs PostgreSQL** — 항목별 비교. 티어 0~2에서 단건 읽기 벤치마크는 판단 근거가
   아니라고 명시합니다.
4. **배포 형태** — 컨테이너·매니지드·Aurora·서버리스·플랫폼 DB·분산 SQL, 각각의 주의점.
5. **3년 TCO** — `references/cost-evaluation.md`에 비용 구성, TCO·장애위험 공식, 규모별 기본값,
   판단 규칙이 있습니다. 실제 가격을 모를 때는 낮음/중간/높음으로 등급을 매기고 **가격이 아니라
   등급이라는 사실을 함께 밝힙니다**.

**멀티테넌시 형태**도 다룹니다 — 공유 테이블 + `tenant_id` / 테넌트별 스키마 / 테넌트별 DB.
테넌트별 스키마는 네임스페이스·권한 분리이고 **자원이나 장애 격리가 아니라는 점**을 포함합니다.

결과는 최대 3개 후보, 기본 추천 1개, 등급화된 비용 평가, 재검토 조건입니다. 재검토 조건은
**측정 가능**해야 하고, "더 커지면"은 조건으로 인정하지 않습니다.

#### `rdbms-modeling` — 3단계와 참조파일 10개

먼저 **어느 정도까지 엄격하게 할지** 정합니다. 결제·재고·권한·계약·원장·감사는 3단계를 전부
거치고, 개인 도구는 앞 두 단계를 축약할 수 있지만 **축약했다고 말해야** 합니다.

**1단계 개념** — 업무 개념, 관계, 그리고 *사용자가 쓰는* 용어. 컬럼·자료형·키·DB 제품은 없습니다.
`IS-A` 문장을 소리 내어 읽어서 서브타입 후보를 찾고, 어떤 것이 **무엇인지**와
**무엇을 하는 중인지**를 분리합니다(상태와 역할은 둘 다 "종류"가 아닙니다).
확인 게이트에서 멈춥니다 — 용어를 고치는 비용이 여기가 가장 쌉니다.

**2단계 논리** — 엔터티·속성·PK/FK·카디널리티·NOT NULL·UNIQUE를 일반 자료형으로만 표현합니다. 정규화,
일반화 검사, 이력 질문을 수행하고 확인 게이트에서 멈춥니다.

**3단계 물리** — 이제야 엔진을 확정합니다. 논리 모델이 나와야 그 선택에 답할 수 있기 때문입니다.
네이밍, 엔진 자료형, 식별자 결정, 제약, 인덱스, 뷰, 파티셔닝, 순서가 있는 마이그레이션 SQL, 그리고
제약을 실제로 검증하는 샘플 데이터로 마칩니다.

필요할 때만 로드되는 참조파일:

| 파일 | 결정하는 것 |
|---|---|
| `normalization.md` | 1NF~3NF 규칙, BCNF 검사 절차, 비정규화 기준선 |
| `generalization.md` | IS-A와 대체 가능성, 7질문, 3결과, 식별자 상속, 물리 매핑 |
| `identifier-selection.md` | UID vs PK, 엔진별 저장 모델, UUIDv4/v7, `UUID_TO_BIN` swap 함정, PG 18 `uuidv7()` |
| `foreign-keys.md` | 엔진 분기, PostgreSQL 6게이트, 참조 대상 규칙, 상속된 스키마 |
| `partitioning.md` | 코드 기반 권고 정책, 권고·제외 조건, MySQL RANGE 한정 범위, 안전 파티션 운영 규칙 |
| `history-entities.md` | 감사 vs 비즈니스 vs 유효시간, 8방식, 표준 이력 엔터티, 트랜잭션 플로우, 트리거 감사 예외 |
| `denormalization.md` | 측정 기준선, 8방식, 더 싼 대안 9개, 동기화 방식, 적용 7조건 |
| `db-internal-routines.md` | 프로시저·트리거·이벤트 3분류: 허용 유틸리티, 좁은 감사 예외, 금지되는 비즈니스 로직 |
| `views-and-materialized-views.md` | 뷰 vs MView vs 집계 테이블, 원본 테이블 vs MView 인덱싱, `REFRESH CONCURRENTLY` 전제 |
| `index-design.md` | 필요한 근거, 엔진별 쓰기 부담, 커버링 인덱스와 Heap Fetches, 패턴 매칭, FTS, 검색엔진 이관 신호 |

#### 엔진별로 다루는 것

| | 내용 |
|---|---|
| **MySQL** | 8.4 LTS 트랙과 릴리스 정책, InnoDB + utf8mb4 기본값, 통화별 `decimal` 정밀도, `DATETIME` vs `TIMESTAMP`(Y2038), `INET6_ATON`, 복합 인덱스 순서, 기간 컬럼 쌍 최적화, `RANGE COLUMNS` 파티셔닝과 `REORGANIZE`, `REPEATABLE READ`와 갭락, 데드락 체크리스트, `SKIP LOCKED` 큐, 키셋 페이지네이션, `ngram` 파서 `FULLTEXT`, 리플리카 지연과 read-after-write 라우팅, GRANT 최소권한과 TLS, `my.cnf` 기준선, `wait_timeout` 대비 풀 사이징, Aurora용 JDBC 드라이버 선정 |
| **PostgreSQL** | 18 기준 UUIDv7·VIRTUAL/STORED·skip scan·비동기 I/O, 16/17 호환 경계, 스키마 분리·identity·timestamptz/jsonb·GIN/GiST/BRIN, RLS·풀 설정 범위, 파티션 FK 단계별 검증, pg_partman, FDW·PostGIS·pgvector와 확장 운영 |
| **SQLite** | 3.37+ `STRICT` 테이블, PRAGMA 기준선(`foreign_keys`는 **기본 OFF**), 네이티브 타입이 없는 것들의 관례(돈은 정수 센트), rowid로서의 `INTEGER PRIMARY KEY`와 `AUTOINCREMENT`가 대개 불필요한 이유, `BEGIN IMMEDIATE` 기반 단일 라이터 설계, 네트워크 파일시스템을 배제하는 이유, FTS5, `VACUUM INTO` 백업, 그리고 `db-select`로 되돌아가는 전환 경로 |

MySQL 8.4의 인증·InnoDB 기본값·비표준 FK 제한·GTID 대기·제거된 명령도 구분합니다.
SQLite는 3.37 호환 하한을 유지하면서 JSONB는 3.45+, 최신 `PRAGMA optimize`는 3.46+로
나눕니다. PostgreSQL 16/17과 관리형/Aurora는 제공 버전과 호환 조건을 따로 확인합니다.
최신 major로 바꾸는 것은 별도의 업그레이드 판단입니다.

#### PostgreSQL 확장 가이드

기존 `postgres-guideline` 스킬이 아래 문서를 필요할 때 불러옵니다. 모두 설치하는 묶음이
아니라 실제 요구에 맞춰 선택하고, 관리형 서비스의 허용 버전부터 확인합니다.

| 필요한 기능 | 가이드 |
|---|---|
| 설치·권한·preload·업데이트, pg_stat_statements·pg_trgm·btree_gist·pg_cron·pg_partman·pgstattuple·pgAudit | [확장 선택과 운영](skills/postgres-guideline/extensions.md) |
| postgres_fdw 외부 DB 연동, TLS·mapping·pushdown·원격 RLS·트랜잭션 한계 | [FDW](skills/postgres-guideline/fdw.md) |
| 좌표 타입·SRID·미터/도·GiST·ST_DWithin·KNN | [PostGIS](skills/postgres-guideline/postgis.md) |
| 임베딩 모델·차원·exact/HNSW/IVFFlat·필터·RLS·recall | [pgvector](skills/postgres-guideline/pgvector.md) |
| PostgreSQL 18 기능·16/17 호환·major 전환·Docker 데이터 경로 | [버전과 업그레이드](skills/postgres-guideline/version-and-upgrade.md) |

“FDW로 외부 PostgreSQL을 읽기 전용 연결해줘”, “PostGIS로 1km 내 장소를 찾아줘”,
“테넌트 필터가 있는 pgvector 검색의 recall을 점검해줘”처럼 요청하면 됩니다.
pgvector는 임베딩을 저장·검색하며 임베딩 모델 자체는 앱이나 배치에서 실행합니다.

### 핵심 방침

- **요구사항이 바로 DDL이 되지 않습니다.** 개념 단계는 사용자 용어만 쓰고 DB 어휘를 배제하고, 논리
  단계는 일반 자료형으로 정규화하며, 엔진 확정이 필요한 시점은 물리 단계뿐입니다. 논리 모델이
  나와야 엔진 선택에 답할 수 있기 때문입니다. 결제·재고·권한·계약은 3단계를 모두 거치고, 개인
  도구는 앞 두 단계를 축약할 수 있지만 축약했다는 사실을 반드시 밝힙니다.
- **정규화는 정책입니다.** 3NF 필수, BCNF는 **모든 엔터티에 검사**하고 슈퍼키가 아닌 결정자로 실제
  이상이 생길 수 있을 때 분해합니다. 함수적 종속성 보존이 깨지거나 조인이 과도하면 3NF 유지를
  허용하되 이유를 남깁니다.
- **일반화는 속성 유사성이 아니라 `IS-A`로 판단합니다.** 7개 질문을 거쳐 타입 컬럼 / 역할 모델 /
  슈퍼타입+서브타입 중 하나로 갑니다. 가장 값진 검사는 **타입 vs 상태** — `주문대기`·`결제완료`·
  `취소`는 상태이지 종류가 아니고, 서브타입으로 만들면 상태 전이마다 테이블 간 이동이 됩니다.
- **비정규화는 측정된 문제에만.** 더 싼 대안 9개를 먼저 배제하고, 원본·동기화 방식·정합성 검사 쿼리·
  재구축 경로까지 7조건을 모두 충족해야 합니다. 단 **거래 사실 스냅샷은 비정규화가 아닙니다** —
  주문 당시 가격은 상품 가격의 캐시가 아니라 거래 자체의 데이터입니다.
- **FK는 엔진과 프로젝트 정책을 함께 봅니다.** MySQL 예제는 논리 FK가 기본이지만, 비파티션
  테이블의 기존 물리 FK를 이유 없이 제거하지 않습니다. 프로젝트 규칙과 측정된 쓰기·잠금 비용을
  먼저 확인합니다. PostgreSQL은 6개 게이트 통과 시 허용하며, 16/17의 파티션 참조 테이블에는
  `NOT VALID`를 쓸 수 없고 18부터 지원하므로 검증 경로를 나눕니다. SQLite는 연결마다
  `PRAGMA foreign_keys = ON`이 필요합니다. FK 없는 정책에서는 참조 컬럼 인덱스를 직접 만듭니다.
- **이력은 구조보다 목적이 먼저.** 감사 / 비즈니스 / 유효시간은 서로 다른 질문이고 `updated_at`은
  셋 다 답하지 못합니다. 방식과 무관하게 두 규칙 고정: 현재 행과 이력은 한 트랜잭션, 엔터티와
  이력 사이에 FK 금지(어떤 참조 동작도 옳지 않음 — `CASCADE`는 증거 삭제, `RESTRICT`는 부모 삭제
  불가, `SET NULL`은 고아화).
- **인덱스는 SQL만 던지지 않습니다.** 근거 쿼리·컬럼 순서 이유·쓰기 비용·전후 실행계획·롤백이 함께
  갑니다. 지표가 없으면 개선율을 추정하지 않고 `needs measurement`로 냅니다.
- **파티셔닝은 근거 기반 권고**이며 기본 생성하지 않습니다. MySQL이 RANGE 계열만 생성하는 것은
  **의도적 지원 제한**이고 기술적 불가가 아님을 명시합니다.
- **View는 캐시가 아닙니다.** 일이 그대로 수행되고 SQL의 위치만 옮깁니다. 가속은 MView나 집계
  테이블이며 비정규화 요구를 상속합니다.
- **DB 내부 루틴은 하는 일로 갈립니다.** 저빈도 운영 유틸리티는 허용, 감사 트리거는 좁은 예외,
  비즈니스 로직은 금지.
- **네이밍은 단일 출처입니다.** 소문자 `snake_case`, 단수형 테이블, 과거분사 시각 컬럼
  (`created_at`/`updated_at`/`deleted_at`), 불리언 `is_`/`has_` 접두어, 제약·인덱스는 **소문자
  접두어** `pk_` `fk_` `uq_` `chk_` `idx_` `fts_`. 대문자 `_IDX` 접미어는 PostgreSQL
  case-folding에서 깨져 은퇴, `ftx_`는 FTX가 표준 용어가 아니라 `fts_`로 교체했습니다. 예약어는
  인용부호로 감싸지 않고 이름을 바꿉니다 — `user` → `member`, `order` → `purchase_order`.
- **식별자는 논리 UID와 물리 PK를 분리합니다.** PK는 `NOT NULL`·`UNIQUE`·불변이고, 바뀌거나
  노출될 수 있는 업무 식별자는 `UNIQUE` 제약으로 갑니다. 원시 타임스탬프 단독 PK 금지, UUID를
  `char(36)`으로 저장 금지, **UUID는 자격증명이 아닙니다**.

  | 상황 | MySQL / InnoDB | PostgreSQL |
  |---|---|---|
  | 증가 상한이 있는 엔터티 테이블 | `int unsigned AUTO_INCREMENT` | `int GENERATED ALWAYS AS IDENTITY` |
  | 이벤트·로그 테이블 | `bigint unsigned AUTO_INCREMENT` | `bigint GENERATED ALWAYS AS IDENTITY` |
  | 쓰기가 많음 | 순차 정수 우선 | `IDENTITY` 또는 UUIDv7 — v4 아님 |
  | 다중 노드 생성 | `binary(16)` UUIDv7 | 네이티브 `uuid` + UUIDv7 |
  | 외부 노출 | 내부 정수 PK + 공개 UID | UUID PK 또는 정수 PK + 공개 UID |

  함정 둘: `UUID_TO_BIN(v, 1)`의 swap 플래그는 **UUIDv1 전용**이라 v7에 쓰면 v7을 택한 이유인
  시간 정렬이 깨집니다. 그리고 `uuidv7()`은 **PostgreSQL 18**부터이고 `gen_random_uuid()`는 v4입니다.

### 검증

2026-09-25 갱신본은 PostgreSQL **18.6**, MySQL **8.4.11**, PostGIS **3.6.4**, pgvector
**0.8.6**, Django **5.2.17**, 검증 runner의 SQLite **3.53.1**에서 통과했습니다.
PostgreSQL **16.15** 호환 검사도 별도로 통과했으며, PostGIS·pgvector는 18에서 실행했습니다.
아래에는 재현 명령과 이전 서버 검증 기록을 구분해 남겼습니다.

`python scripts/check-examples.py`는 문서의 SQL·Django 예제를 직접 읽어 실행합니다.
Docker·OpenSSL과 가상환경에 설치한 `Django>=5.2,<5.3`, `psycopg[binary]>=3,<4`가 필요합니다.
검사용 PostgreSQL 18·MySQL 8.4 컨테이너를 만들고 종료 후 삭제하며, 기존 앱 DB에는 접속하지 않습니다.
PK 교체·동시 백필·DB 별칭·파티션·제약·실행계획에 더해 PG 버전 경계, RLS 세션 재사용,
pg_stat_statements·pg_trgm, FDW TLS·읽기 전용 권한, MySQL 8.4 인증·FK 기본값을 검사합니다.
`--pg-major 16`으로 기존 버전 호환성도 검사합니다.
같은 스크립트가 Python 예제 문법, 매니페스트·스킬 frontmatter·버전 일치, SQLite PK와 동기화
스크립트, SQLite JSONB·optimize 버전 경계와 스킬 참조 경로도 검사합니다.

`uv`가 설치되어 있다면 저장소 루트에서 다음과 같이 의존성을 분리해 실행할 수 있습니다.

```bash
sh hooks/detect-db.test.sh
python3 scripts/check-readme-bilingual.py
uv run --no-project --with 'Django>=5.2,<5.3' --with 'psycopg[binary]>=3,<4' \
  python scripts/check-examples.py
```

PostGIS·pgvector 예제까지 실행하려면 검증용 이미지를 만들고 같은 스크립트를 사용합니다.

```bash
docker build -f scripts/Dockerfile.postgres -t easy-rdbms-examples-pg18 .
uv run --no-project --with 'Django>=5.2,<5.3' --with 'psycopg[binary]>=3,<4' \
  python scripts/check-examples.py --extensions
uv run --no-project --with 'Django>=5.2,<5.3' --with 'psycopg[binary]>=3,<4' \
  python scripts/check-examples.py --pg-major 16
```

공간 반경 결과·GiST, 벡터 차원·exact/필터 HNSW 결과·RLS를 검사합니다. 작은 검증 데이터의
통과를 운영 지연·recall 보장으로 제시하지 않습니다. 실행 시 실제 서버·확장 버전을 출력하며
이미지 태그와 패키지 저장소는 갱신될 수 있습니다. 이미지는 재사용을 위해 보관하고 검증용
컨테이너와 데이터는 삭제합니다.

**실제 서버에서 실행했습니다.** 스키마를 좌우하는 주장은 **MySQL 8.4.11** / **PostgreSQL 16.15**
컨테이너와 로컬 **SQLite 3.51**에서 직접 돌려 확인했습니다.

| 주장 | 서버가 실제로 낸 결과 |
|---|---|
| PK 정수 타입 변경은 `ALGORITHM=COPY` 필요 | `INSTANT` → `ERROR 1846`, `INPLACE` → `ERROR 1846 … Cannot change column type INPLACE. Try ALGORITHM=COPY`, `COPY`만 성공 |
| `UNSIGNED` 뺄셈 언더플로는 에러이고 `sql_mode`와 무관 | `sql_mode = ''`에서도 `ERROR 1690 (22003)`. `NO_UNSIGNED_SUBTRACTION` 설정 시 `-1` |
| `tinyint(1)`은 0/1로 제약하지 않음 | `2`와 `-5` 통과, `tinyint unsigned`는 `200` 통과 |
| MySQL은 `CONSTRAINT pk_x PRIMARY KEY` 이름을 버림 | `information_schema.statistics`의 인덱스명이 `PRIMARY` |
| RR의 갭 락은 무조건이 아님 | 유니크 등가 `FOR UPDATE` 중 갭 `INSERT` **성공**(레코드 락만), 같은 INSERT를 **범위** `FOR UPDATE` 뒤에 하면 `ERROR 1205` |
| 파티션 테이블의 PK는 파티션 키를 포함해야 함 | `ERROR: unique constraint on partitioned table must include all partitioning columns` |
| `DEFAULT` 파티션 detach는 쓰기 실패 창을 만듦 | `ERROR: no partition of relation "d" found for row` — 붙어 있을 때는 같은 INSERT가 성공 |
| 별도 테이블과 검증된 CHECK로 DEFAULT detach 없이 attach | `ATTACH PARTITION`이 부모에 `ShareUpdateExclusiveLock`을 잡고 완료 |
| `ON CONFLICT`는 plain 유니크 인덱스를 추론하지만 `DEFERRABLE`은 못 함 | plain은 upsert 성공, `DEFERRABLE`은 `ERROR: … does not support deferrable unique constraints … as arbiters` |
| SQLite `STRICT`는 무손실 강제변환을 허용 | `'12'`는 정수 `12`로, `42`는 텍스트 `'42'`로 저장, `'abc'`는 거부 |
| `WITHOUT ROWID`에는 rowid가 없음 | 거기서 `SELECT rowid`는 파싱 오류, rowid 테이블에서는 `INTEGER PRIMARY KEY`가 rowid |

예제 DDL도 실행했습니다 — [비교 문서](docs/with-and-without.md)의 "플러그인과 함께" 스키마가
PostgreSQL 16에서 그대로 생성되고, 안의 모든 `CHECK`가 실제로 막아야 할 값을 막습니다.

Claude 자체 리뷰 + Codex 독립 리뷰 **11라운드, 292건** 반영
(33 → 18 → 11 → 17 → 32 → 31 → 6 → 3 → 5 → 116 → 20).
5라운드에서 이식 파일이라는 사각지대가 드러났고, 6라운드는 **5라운드 수정이 만든 버그**를 잡았습니다 —
수정을 검증하는 패스가 원본을 검증하는 것만큼 중요했습니다. 10라운드가 가장 컸던 이유는
플러그인이 나빠져서가 아니라, 처음으로 Codex 패스를 **별도 임무**(엔진 사실 / 파일 간 일관성·흐름)로
나눠 돌렸기 때문입니다. 발견한 것의 상당수가 직전 라운드가 만든 것이었습니다.

11라운드에서는 PK 교체·동시 백필·FK 정책·파티션 절차·명명 규칙·훅 탐색 등 20건을 고쳤습니다.
문서 속 SQL·Django 예제를 직접 실행하는 회귀 검사를 추가해 수정된 절차를 다시 확인할 수 있습니다.

리뷰어끼리 상충하고 오프라인 검증이 불가한 건(`kysely-ctl` 커맨드 형식)은 **어느 쪽도 단정하지
않고** `kysely --help` 확인을 안내합니다.

### 릴리즈 자동화

`main`에 병합하면 GitHub Actions가 메타데이터·훅·PostgreSQL 16/18·MySQL 8.4·PostGIS·pgvector
검사를 실행합니다. 통과 후 release-please가 릴리즈 PR을 생성하거나 갱신합니다.

1. `feat:`는 minor, `fix:`·`perf:`는 patch, `feat!:`·`BREAKING CHANGE:`는 major를 올립니다.
   문서·관리용 `docs:`·`chore:`만으로는 릴리즈하지 않습니다.
2. 릴리즈 PR에서 `version.txt`·`.release-please-manifest.json`·두 플러그인 매니페스트·
   README의 양쪽 버전·`CHANGELOG.md`를 함께 갱신합니다.
3. 릴리즈 PR의 CI까지 통과하면 병합합니다. Actions가 버전을 올린 해당 커밋에
   `easy-rdbms--vX.Y.Z` 태그와 GitHub Release를 생성합니다.

변경 이력은 Conventional Commit 형식의 커밋 또는 PR squash 메시지에 작성합니다.
버전 파일을 따로 수정하거나 매니페스트를 올리기 전에 태그부터 만들지 않습니다.
액션은 커밋 SHA로 고정하며, 재실행 시 release-please의 기존 릴리즈 기록을 이용합니다.

저장소의 Settings → Actions → General에서 GitHub Actions의 PR 생성을 허용해야 합니다.
`GITHUB_TOKEN`과 릴리즈 PR의 명시적 CI 실행을 사용하므로 별도 PAT는 필요하지 않습니다.
저장소 루트에서 재실행하려면:

```bash
gh workflow run release.yml --ref main
```

Docker나 추가 Python 패키지 없이 버전·플러그인 메타데이터만 검사할 수도 있습니다.

```bash
python3 scripts/check-examples.py --metadata-only
```

현재 배포 버전은 **0.5.0**입니다. 변경 이력은 [CHANGELOG.md](CHANGELOG.md)에 있습니다. <!-- x-release-please-version -->
