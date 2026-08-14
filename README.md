# Easy RDBMS

![Claude Code](https://img.shields.io/badge/Claude%20Code-Plugin-D97757.svg) ![Codex](https://img.shields.io/badge/Codex-Plugin-412991.svg) ![MySQL](https://img.shields.io/badge/MySQL-8.4%20LTS-4479A1.svg) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%2B-336791.svg) ![SQLite](https://img.shields.io/badge/SQLite-3.37%2B-003B57.svg) ![Shell](https://img.shields.io/badge/Shell-POSIX%20sh-89E051.svg) ![Markdown](https://img.shields.io/badge/Markdown-Skills-000000.svg) ![License](https://img.shields.io/badge/License-MIT-green.svg)

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/teinam)

## Overview

**18 years of production DBRE practice, packaged as a plugin.** Not textbook normal forms — the
things you only learn by running databases:

- The foreign key you add today, which quietly makes that table impossible to partition next year.
- One popular parent row that slows down writes to a completely unrelated table.
- A partition-creation job that stops without raising an error, so nobody notices for months.
- An index that costs more on every write than it ever gives back on reads.

Works in both **Claude Code** and **Codex** from one shared `skills/` directory. It picks the
database for your scale and budget, keeps naming consistent, takes requirements through
conceptual → logical → physical modeling instead of straight to DDL, and reviews schemas,
queries, and migrations before they ship. Covers MySQL 8.4 LTS+ and PostgreSQL 16+ (including
Aurora variants), plus SQLite for the embedded and prototype end.

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

Either harness also installs from a local checkout — pass the path instead of the repo slug.

### Updating

```bash
claude plugin marketplace update easy-rdbms && claude plugin update easy-rdbms@easy-rdbms
codex plugin marketplace upgrade
```

## What's inside

Eight skills, shared by both harnesses. They activate on their own when a task mentions relevant
work; you can also name one explicitly.

| Skill | Use it for |
|---|---|
| `db-select` | Which database, which topology, and what it costs over three years |
| `rdbms-modeling` | Conceptual → logical → physical design with a confirmation gate between stages |
| `rdbms-review` | Reviewing existing SQL, schemas, and migrations |
| `rdbms-naming` | Table, column, index, and constraint naming; data type selection |
| `mysql-guideline` | MySQL 8.4 LTS+ / Aurora MySQL mechanics |
| `postgres-guideline` | PostgreSQL 16+ / Aurora PostgreSQL mechanics |
| `sqlite-guideline` | SQLite 3.37+ — embedded, local, prototype |
| `database-migrations` | Zero-downtime schema change and rollback strategy |

`rdbms-modeling` carries **eleven reference files** loaded on demand, so the policy detail costs
nothing until the model actually needs it.

### Commands

| Command | Does |
|---|---|
| `/db-select` | Up to three candidates with one named default, a cost assessment, and measurable re-evaluation triggers |
| `/schema-design` | Conceptual → logical → physical with a gate between each, ending in DDL and migration SQL |
| `/schema-review` | Findings ordered CRITICAL → HIGH → MEDIUM, each with impact and an exact fix |

### Subagents (Claude Code only)

`rdbms-modeler` and `rdbms-reviewer` — thin wrappers over the skills. Codex plugins cannot
register named subagents, so on Codex the same procedures live entirely in the skill bodies.

### Session hook

On session start the hook reads `docker-compose.yml`, `.env`, `alembic.ini`,
`prisma/schema.prisma`, `package.json`, `requirements.txt`, `Cargo.toml`, `go.mod`, and similar,
then reports the engine once. It distinguishes **MariaDB** and **SQLite** from MySQL/PostgreSQL,
and when more than one engine is present it tells the agent to **ask which one the task targets**
rather than guessing a dialect. Silent when nothing is found.

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
   it grades low/medium/high **and says it graded rather than priced**.

Also: **multi-tenancy shape** — shared tables + `tenant_id`, schema per tenant, database per
tenant — with the consequences of each, including that schema-per-tenant is namespace and
privilege isolation, not resource or failure isolation.

Output is up to three candidates with one named default, a graded cost assessment, and
re-evaluation triggers that must be **measurable** ("when we get bigger" is rejected).

### `rdbms-modeling` — three stages, eleven reference files

A rigor gate first: payments, inventory, permissions, contracts, ledgers, and audit get all three
stages in full; a personal tool may compress the first two — but must say so.

**Stage 1 — conceptual.** Business concepts, relationships, and the terms *users* use. No columns,
no types, no keys, no DB product. Flags specialization candidates by reading the IS-A sentence
aloud, and separates what a thing **is** from what it is **doing** (states and roles are neither).
Stops at a confirmation gate — terminology corrections are cheapest here.

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
| `cost-evaluation.md` | *(under `db-select`)* Cost components, three-year TCO and outage-risk formulas, decision rules |

### Normalization, generalization, denormalization

**3NF is required.** BCNF is *checked on every entity* — test each table for a determinant that is
not a superkey — and decomposed when that determinant can produce a real anomaly. Staying at 3NF is
allowed when decomposition cannot preserve functional dependencies or explodes the join count, but
the reason must be named. `"BCNF: no violations"` is a valid and expected result.

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
Guarded from the other side too: a supertype where every meaningful column ended up nullable traded
database constraints for application checks, and an entity/attribute/value table gave up on the
schema entirely.

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
| Physical `FOREIGN KEY` | **Not created** | Allowed — through six gates | Allowed |
| Integrity owner | The application | The database, once valid | The database, if the pragma is on |
| Referencing-column index | **Mandatory, manual** | Create it (never auto-created) | Create it (never auto-created) |

**Why MySQL differs.** InnoDB cannot put a foreign key on a partitioned table in either direction,
and log and history tables are the usual partitioning candidates — so an FK today is a blocked
partition tomorrow. Add the parent-index I/O on every child write, the parent-row locks that make
hot-parent key updates and child writes stall each other, and the special handling
`pt-online-schema-change` and `gh-ost` need.

**The trap that is easy to miss:** InnoDB auto-creates the child index only *when the FK is
created*. Under a no-FK policy nothing creates it for you, so the referencing-column index is
deliberate and manual. (On an inherited schema, dropping an FK *leaves* its auto-named index
behind — verify with `SHOW INDEX` and rename it before a cleanup job removes it.)

**The six PostgreSQL gates:** parent is PK/UNIQUE · referencing column indexed · no redundant index
· `CASCADE` only for genuine lifecycle dependency · `NOT DEFERRABLE` · large tables via `NOT VALID`
then `VALIDATE CONSTRAINT`. A failing gate means fix it or fall back to a logical FK and say why.

Every **logical** FK carries four compensating controls: the reference in a `COMMENT`, the index, a
named **integrity owner**, and a **scheduled orphan-detection query**. And on SQLite, `PRAGMA
foreign_keys = ON` per connection — otherwise every `REFERENCES` clause in the schema is decoration.

### History — purpose before structure

"History" conflates three questions, and a design answering one answers neither other:

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
orphans it.

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
  query needs the index's ordering, or range-first when it is highly selective.
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
where the SQL lives. Acceleration means a PostgreSQL materialized view or a MySQL summary table
(8.4 has no native MView), which inherits the denormalization requirements. Nested views get
special attention: each layer looks reasonable while the composed query does something nobody
intended.

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
| Single DB, ordinary table | `bigint unsigned AUTO_INCREMENT` | `bigint GENERATED ALWAYS AS IDENTITY` |
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
| **PostgreSQL** | 16.7+ defaults, schema separation (`app`/`log`/`ref`), `GENERATED ALWAYS AS IDENTITY` over `SERIAL`, `timestamptz`, `jsonb`, GIN/GiST/BRIN/partial/expression indexes, `READ COMMITTED` default and `40001` retries, RLS with the role prerequisites that actually make it enforce, advisory locks and the pooling leak, `LISTEN`/`NOTIFY` done safely, declarative partitioning with a `DEFAULT` partition, pg_partman 5.x, reload-vs-restart configuration |
| **SQLite** | 3.37+ `STRICT` tables, the PRAGMA baseline (`foreign_keys` is OFF by default), conventions where no native type exists (integer cents for money), `INTEGER PRIMARY KEY` as rowid and why `AUTOINCREMENT` is usually unnecessary, single-writer design with `BEGIN IMMEDIATE`, why network filesystems are out, FTS5, `VACUUM INTO` backups, and the growth path back to `db-select` |

## How it was verified

Eight review rounds — Claude self-review plus independent Codex passes — found and fixed **151
issues**. Findings per pass: 33 → 18 → 11 → 17 → 32 → 31 → 6 → 3.

The count did not fall monotonically, and the reason is worth stating: passes 1–4 concentrated on
newly written content, so pass 5 was the first deep read of the **ported** guideline files and found
32 issues there. Pass 6 then found 31 — several of them **bugs introduced by pass 5's own fixes** (an
invalid Prisma comment, a naming rule accidentally reversed by a bulk rename, an invented CLI flag,
async code left unwrapped). Reviewing the fixes turned out to matter as much as reviewing the
original.

What that surfaced, by category:

- **Engine claims that would have misled** — dropping an InnoDB FK does not drop its child index; FK
  parent-row locks do not serialize child writes against each other; PostgreSQL has no
  `SPLIT PARTITION`; `NOTIFY` takes no bind parameters; `ADD COLUMN NOT NULL` without a default
  *fails* rather than rewrites; session advisory locks survive a pooled connection's return but not a
  crash.
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
sh hooks/detect-db.test.sh    # 16 cases: PostgreSQL / MySQL / MariaDB / SQLite / Aurora /
                              # managed platforms / multi-engine confirmation / silence when absent
claude plugin validate .      # official manifest validation
```

Plus per-commit checks that every Python example parses, every reference path resolves, no example
contains an undefined name, and manifests and frontmatter are well-formed.

## Design decisions

**One skill directory, both harnesses.** `skills/` is shared. Frontmatter is `name` + `description`
only — the intersection of what Claude Code and Codex accept. Commands ship as `.md` (Claude Code)
and `.toml` (Codex) pairs. Codex plugins cannot register named subagents, so modeling and review
procedures live in the skill bodies and Claude Code gets thin agent wrappers pointing at them.

**Progressive loading.** Eleven reference files keep the policy detail out of the always-on cost.
Always-on is roughly 2.1k tokens across all eight skills; the heaviest skill costs ~7k only when it
actually fires.

**Scale-aware, not scale-maximal.** `db-select` tells you *not* to add read replicas, partitioning,
or sharding you have not earned. Each tier costs roughly an order of magnitude more operational
attention than the one below it — the wasted spend is visible, but the wasted attention is what
slows a team down.

**Cost is part of the choice.** A free database still needs someone to operate it, and that salary
is usually the largest line item at small scale. Comparisons run over three years, never per month.

**MySQL, PostgreSQL, and SQLite only.** Other relational engines are out of scope, and the plugin
says so rather than pretending to advise on them.

## Development

```bash
sh hooks/detect-db.test.sh          # hook detection tests (16 cases)
sh scripts/sync-from-harness.sh     # show upstream drift for the four ported skills
claude plugin validate .            # manifest validation
claude plugin details easy-rdbms    # component inventory and projected token cost
```

Four skills are ported from a private harness and carry deliberate local edits (dropped filename
prefixes, stripped harness-only frontmatter, cross-references repointed). `sync-from-harness.sh` is
diff-only for that reason — never blind-copy over them. See `AGENTS.md` for repo conventions.

## Changelog

See [CHANGELOG.md](CHANGELOG.md). Current: **0.3.0**.

## License

MIT

---

## 한국어

**18년 현업 DBRE 경험을 플러그인으로 옮겼습니다.** 교과서에 나오는 정규형이 아니라, 데이터베이스를
직접 운영해봐야 알게 되는 것들입니다.

- 지금 편하게 걸어둔 외래키 하나 때문에, 내년에 그 테이블을 파티셔닝할 수 없게 되는 일
- 많이 조회되는 부모 행 하나가, 전혀 상관없는 테이블의 쓰기까지 느리게 만드는 일
- 파티션을 미리 만들어주는 작업이 에러도 없이 멈춰서, 몇 달 뒤에야 발견하는 일
- 인덱스를 하나 추가했는데, 읽기에서 얻는 것보다 매번 쓰기에서 잃는 게 더 큰 일

**Claude Code**와 **Codex** 양쪽에서 하나의 `skills/` 디렉토리로 동작합니다. 규모와 예산에 맞는
DB를 고르고, 네이밍을 일관되게 잡고, 요구사항을 DDL로 직행시키지 않고 개념 → 논리 → 물리로
설계하며, 배포 전에 스키마·쿼리·마이그레이션을 리뷰합니다. MySQL 8.4 LTS+ / PostgreSQL 16+
(Aurora 포함), 그리고 임베디드·프로토타입용 SQLite를 다룹니다.

일관된 주제 하나: **구조적 비용은 근거 없이 지불하지 않습니다.** 비정규화는 측정, 파티셔닝은
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

### 구성

| 스킬 | 용도 |
|---|---|
| `db-select` | 어떤 DB를, 어떤 구성으로, 3년 비용은 얼마인지 |
| `rdbms-modeling` | 개념 → 논리 → 물리 3단계 + 단계별 확인 게이트 (참조파일 11개) |
| `rdbms-review` | 기존 SQL·스키마·마이그레이션 리뷰 |
| `rdbms-naming` | 테이블·컬럼·인덱스·제약 네이밍, 데이터 타입 |
| `mysql-guideline` | MySQL 8.4 LTS+ / Aurora MySQL |
| `postgres-guideline` | PostgreSQL 16+ / Aurora PostgreSQL |
| `sqlite-guideline` | SQLite 3.37+ — 임베디드·로컬·프로토타입 |
| `database-migrations` | 무중단 스키마 변경, 롤백 전략 |

커맨드는 `/db-select`, `/schema-design`, `/schema-review`. 스킬은 관련 작업이 언급되면 자동
발동하므로 커맨드를 꼭 쓸 필요는 없습니다.

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
- **FK는 엔진별 정책입니다.** MySQL/InnoDB는 물리 FK 미생성(파티션 테이블에 FK 불가 + 부모 락 +
  온라인 DDL 도구 문제), PostgreSQL은 6개 게이트 통과 시 허용, SQLite는 허용(단 연결마다
  `PRAGMA foreign_keys = ON`). 놓치기 쉬운 귀결: 자식 인덱스 자동 생성은 FK를 **만들 때만**
  일어나므로, FK 없는 정책에서는 참조 컬럼 인덱스가 의도적·수동입니다.
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

### 검증

Claude 자체 리뷰 + Codex 독립 리뷰 **8패스, 151건** 반영 (33 → 18 → 11 → 17 → 32 → 31 → 6 → 3).
5패스에서 이식 파일이 사각지대로 드러났고, 6패스는 **5패스 수정이 만든 버그**를 잡았습니다 —
수정을 검증하는 패스가 원본을 검증하는 것만큼 중요했습니다.

리뷰어끼리 상충하고 오프라인 검증이 불가한 건(`kysely-ctl` 커맨드 형식)은 **어느 쪽도 단정하지
않고** `kysely --help` 확인을 안내합니다.

