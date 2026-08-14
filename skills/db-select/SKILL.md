---
name: db-select
description: >
  Pick the database before designing the schema. Decides whether an RDBMS is the right fit at
  all, which engine (MySQL vs PostgreSQL), which deployment form and topology the current scale
  justifies, and which candidate has the lowest three-year total cost of ownership — then
  routes to the matching guideline skill. Triggers: which database should I use, MySQL or
  PostgreSQL, do I need NoSQL, DynamoDB vs RDBMS, MongoDB or Postgres, is Postgres enough, do I
  need sharding, do I need read replicas, Aurora vs RDS, RDS vs self-managed, managed vs
  self-hosted database, Supabase Neon PlanetScale, serverless database, SQLite in production,
  distributed SQL, CockroachDB TiDB, choosing a DB for a new project, database cost, TCO, how
  much will the database cost, is this database too expensive, database budget, do we need a
  DBA, multi-tenant, multi-tenancy, tenant isolation, schema per tenant, database per tenant,
  SaaS tenancy, scaling the database, database for a prototype, separate analytics database,
  OLTP vs OLAP separation.
---

# Database Selection

Choose the engine, the topology, and the cost position **before** writing DDL. Retrofitting
a wrong choice costs far more than the ten minutes this takes.

## When to Activate

- Starting a new project or service that needs persistence
- A stakeholder proposes a specific database and the reasoning is not yet stated
- The current database is straining and someone suggests switching engines
- Database spend is being questioned, or a budget has to be defended
- Weighing self-managed against managed, or managed against serverless
- Deciding whether analytics needs its own store
- Reviewing an architecture doc that names a database

## Gate: Facts You Need First

Do not recommend anything until you have these. Ask for the missing ones — **one message,
all of them**. Estimates and ranges are fine. "Unknown" is also an answer, and it pushes the
recommendation toward the boring, replaceable option.

| # | Fact | Why it changes the answer |
|---|---|---|
| 1 | Expected users and peak traffic | Sets the scale tier |
| 2 | Data size now, and monthly growth | Drives partitioning, storage cost, and the 12-month tier |
| 3 | Read/write ratio | Read-heavy scales with replicas; write-heavy is the real ceiling |
| 4 | Access patterns — fixed and enumerable, or exploratory? | Fixed + no joins is the only honest case for a key-value store |
| 5 | Tolerable downtime (RTO) and acceptable data loss (RPO) | Decides HA topology, backup tier, and much of the cost |
| 6 | Consistency requirement per flow | Money, inventory, and permissions rarely tolerate eventual consistency |
| 7 | Is there a dedicated DBA or infra owner, and how many? | With none, self-managed is usually the most expensive option |
| 8 | Is cloud or product lock-in acceptable? | Eliminates or permits managed and proprietary options |
| 9 | PII, financial, or audit requirements? | Can force encryption, audit logging, retention, and residency costs |
| 10 | Budget for year 1 and for three years | A monthly figure alone hides setup, staffing, and scaling cost |
| 11 | Is traffic steady or irregular/spiky? | Steady favors fixed instances; spiky favors serverless |
| 12 | Existing data to migrate from another DB? | Migration cost can outweigh the saving from switching |
| 13 | Existing stack and team experience | An engine the team knows beats a marginally better one they don't |

If the requester cannot answer volume and traffic even to an order of magnitude, they are at
prototype scale. Treat it as Tier 0 and say so.

## Step 1 — Is an RDBMS Even Right?

**Default answer: yes, and specifically PostgreSQL.** Relational is the correct default
because it is the only option that does not require you to know your access patterns in
advance. Teams routinely pay a permanent modeling tax to avoid a scaling problem they never
reach.

**Full ACID transactions are the baseline requirement**, not a feature to trade for
throughput. Any flow touching money, inventory, permissions, or a state machine needs
atomicity and isolation across multiple rows and tables. MySQL/InnoDB and PostgreSQL provide
this as the default execution model; the alternatives below bolt transactions on with real limits
(DynamoDB caps them at 100 items and double cost, MongoDB treats multi-document transactions as
the exception). Designing every money flow around those limits is the cost the table understates.

(ACID and normalization are separate concerns — ACID is how a transaction stays safe,
normalization is how the schema avoids redundancy. Neither substitutes for the other. See
`rdbms-modeling` for the normalization policy.)

Leave the RDBMS only when a row below matches the workload **as stated** — not as imagined:

| Leave for | Only when all of these hold | What you give up |
|---|---|---|
| **DynamoDB** | Access patterns are fixed and enumerable up front; no ad-hoc queries; no multi-entity joins; single-digit-ms latency at very high, spiky throughput is a stated requirement | Ad-hoc querying, joins, flexible aggregation. Transactions exist (`TransactWriteItems`) but are capped at 100 items and cost double capacity. Every new access pattern is a table or GSI redesign |
| **MongoDB** | Documents genuinely vary in shape per record (not "we might add fields"); the aggregate is read and written whole; per-document atomicity covers most flows | Multi-document transactions exist but cost more and are the exception, not the model; mature relational query planning |
| **Redis** | Data is ephemeral, derived, or reconstructible — cache, session, rate limit, leaderboard, lock, lightweight queue | Durability guarantees. **Redis complements an RDBMS; it does not replace one** |
| **ClickHouse / DuckDB / warehouse** | Workload is analytical: wide scans, aggregation over millions of rows, few concurrent writers | Row-level OLTP performance, transactional writes. **Add alongside OLTP, never instead** |
| **Search engine** (OpenSearch, Meilisearch, Typesense) | Typo tolerance, relevance ranking, faceting, or per-language analysis are product requirements | It is an index, not a source of truth. Keep the RDBMS authoritative |

### Objections That Do Not Justify Leaving

| Claim | Reality |
|---|---|
| "Our schema will change a lot" | Postgres `jsonb` with a generated column + index handles variable fields. `ALTER TABLE ADD COLUMN` with a **non-volatile** default is metadata-only on PostgreSQL 11+, and MySQL `ALGORITHM=INSTANT` covers many (not all) cases — verify per change rather than assuming |
| "We need to scale to millions of users" | A single well-indexed Postgres or MySQL instance serves thousands of QPS. Reach the ceiling before designing for beyond it |
| "SQL doesn't scale" | Reads scale with replicas, writes with partitioning then sharding. Both are well-trodden |
| "We need a queue" | `SELECT ... FOR UPDATE SKIP LOCKED` is a correct queue up to meaningful throughput. Add a broker when it actually binds |
| "We need full-text search" | Postgres `tsvector` + GIN, or MySQL `FULLTEXT` with the `ngram` parser, covers a lot before a search cluster earns its keep |
| "We need to store events/JSON" | `jsonb` / `json` columns exist. Keep tenancy, ownership, and lifecycle fields relational |

Record the decision and the reason. If you are keeping the RDBMS, say which objection you
considered and why it did not apply.

## Step 2 — Scale Tier

Find the row your **12-month** projection lands in. Where volume and traffic disagree, take the
higher tier. The tier describes the *workload* — ops headcount does not change it, but it does
constrain the **deployment form** (Step 4): a team with no operator picks managed at every tier.

| Tier | Data | Peak QPS | Recommended | Explicitly do NOT yet |
|---|---|---|---|---|
| **0 — Prototype** | < 10 GB | < 50 | SQLite (single writer — see `sqlite-guideline`) or one Postgres container | No replicas, no pooler, no partitioning, no separate analytics DB |
| **1 — Early production** | < 100 GB | < 500 | One managed instance (RDS / Cloud SQL / Neon / Supabase). Automated backups + PITR. Pooling in the app | No read replicas, no sharding. Add a replica only when a measured read path needs it |
| **2 — Growth** | < 1 TB | < 5,000 | Managed primary + 1–2 read replicas. External pooler (PgBouncer / ProxySQL / RDS Proxy) once connection count exceeds the server's comfort. Evaluate partitioning on the largest append-only tables **when query and retention evidence supports it**. Analytics moved off the primary | No application-level sharding |
| **3 — Large** | 1–10 TB | 5,000–50,000 | Aurora (or equivalent) for storage/failover decoupling. Partitioning becomes routine — still per the evidence rules. Dedicated analytical store. Cross-region replica if the RTO requires it | Sharding only after partitioning, replicas, and query work are exhausted |
| **4 — Very large** | > 10 TB | > 50,000 | Shard by tenant or entity, or adopt distributed SQL (Vitess, Citus, CockroachDB, TiDB, Aurora Limitless). Requires dedicated data engineering staffing | — |

**Rule of thumb.** Each tier costs roughly an order of magnitude more in operational
attention than the one below it. Do not buy a tier you have not reached: the wasted spend is
visible, but the wasted attention is what actually slows the team down.

Escalation order when a tier starts to strain — do these in order, measuring each. Note that
this is also **cheapest-first**:

1. Fix the queries and the indexes. Most "we need to scale the DB" is a missing index or an N+1.
2. Cache what is read repeatedly and changes rarely.
3. Add read replicas; route only replica-safe reads (see the read-after-write rules in the guideline skills).
4. Scale up the instance.
5. Partition the largest tables on time or tenant.
6. Move analytics off the OLTP store.
7. Only then shard.

## Step 3 — MySQL or PostgreSQL

If the team has real production experience with one, that usually wins. Otherwise:

**Default to PostgreSQL.** It has the broader feature surface, so it is the choice you are
less likely to regret.

| Pick PostgreSQL when | Pick MySQL when |
|---|---|
| Complex queries, CTEs, window functions, rich planning | Workload is simple, high-volume primary-key and range reads |
| `jsonb` with indexing; arrays; ranges; `PostGIS` | Team, tooling, or hosting is already MySQL-shaped |
| Row Level Security is part of the authorization model | Aurora MySQL is the standardized platform |
| Extensions matter (`pg_stat_statements`, `pg_partman`, `pgvector`, `TimescaleDB`) | Vitess-style horizontal scaling is the planned end state |
| Strict SQL standard conformance and transactional DDL | Existing replication topology and runbooks are MySQL |
| Vector search is on the roadmap (`pgvector`) | — |

Not a tiebreaker: raw single-row read benchmarks. At Tier 0–2 both engines are far faster
than the application around them.

This plugin's design guidance covers **MySQL, PostgreSQL, and SQLite**. If the project is committed
to a different relational engine, say that the follow-up guidance here does not apply rather than
recommending against their platform.

## Step 4 — Deployment Form

| Form | Fits | Watch out for |
|---|---|---|
| **Container / self-managed** | Local dev, CI, Tier 0 | Nobody backs it up. Never let this become production by accident |
| **Managed instance** (RDS, Cloud SQL) | Tier 1–2, the common answer | Verify backup retention, PITR, and that a restore has actually been rehearsed |
| **Aurora** | Tier 2–3 on AWS | Failover is fast but not free — the driver must handle it (see `mysql-guideline/jdbc-driver.md`). I/O-based pricing can surprise on write-heavy loads |
| **Serverless / autoscaling** (Aurora Serverless v2, Neon) | Spiky or intermittent traffic; per-branch dev databases | Cold starts; scale-to-zero pauses; cost is unpredictable under sustained load |
| **Platform DB** (Supabase, PlanetScale) | Small teams wanting auth, APIs, and branching bundled | Platform-specific idioms leak into the schema. Confirm the migration path out before committing |
| **Distributed SQL** (CockroachDB, TiDB, Citus, Aurora Limitless) | Tier 4, or a hard multi-region write requirement | Real SQL and operational differences, paid from day one. Do not adopt for Tier 2 problems |

### Multi-Tenancy Shape

If the product serves multiple tenants, the isolation shape is part of the topology decision —
retrofitting it is a full migration.

| Shape | Fits | Cost |
|---|---|---|
| **Shared tables + `tenant_id`** | The default. Hundreds-to-millions of tenants, uniform schema | Every **tenant-owned** table carries `tenant_id` and tenant-scoped uniqueness includes it (global/reference tables legitimately do not). On PostgreSQL, RLS enforces the scoping; on MySQL it is application-carried |
| **Schema per tenant** (PostgreSQL) | Tens-to-hundreds of tenants needing namespace/privilege separation or per-tenant customization — **not** resource or failure isolation; schemas share the instance | Migrations run N times; `search_path` hygiene on shared pools is easy to get wrong; cross-tenant reporting needs UNION machinery |
| **Database per tenant** | Few, large, contractually isolated tenants (compliance, residency) | Full operational cost multiplies per tenant — backups, monitoring, upgrades |

Rules that follow from the choice:

- Shared tables: `tenant_id` **leads** the indexes that serve tenant-scoped queries (global and
  administrative paths keep their own), and tenant-scoped uniqueness includes it — a per-tenant
  uniqueness rule that ignores the tenant is a bug
- Never mix shapes for the same entity; a hybrid ("big tenants get a database") is two systems
  with two operational stories — accept that explicitly or do not do it
- A missing `tenant_id` predicate is a data-leak bug, not a performance bug. PostgreSQL RLS
  scopes the query to the session's tenant even when the predicate is forgotten — **provided**
  the runtime role is **not a superuser**, does not hold `BYPASSRLS`, and does not own the table
  (owners bypass policies unless `FORCE ROW LEVEL SECURITY` is set; superusers and `BYPASSRLS`
  bypass regardless). Price that enforcement in when choosing the engine

Connection limits bite earlier than people expect — serverless application runtimes multiply
connections. Budget a pooler at Tier 2 regardless of engine.

## Step 5 — Three-Year Cost

**Read `references/cost-evaluation.md` before answering any question where budget, staffing,
or migration is in play.** It has the cost component breakdown, the TCO and outage-risk
formulas, the full option comparison, and the decision rules.

The three rules that most often change a recommendation:

1. **A free database is not free.** Operations staff time is the largest line item at small
   and medium scale. With no dedicated DBA, managed usually beats self-managed on total cost,
   not just on convenience.
2. **Compare three-year TCO, never monthly price.** Monthly pricing hides build-out,
   training, incident, scaling, and migration cost.
3. **If migration cost exceeds the three-year saving, keeping the current database is a valid
   candidate.** List it rather than assuming a move.

When real prices are unavailable, grade **low / medium / high** and say that you graded
rather than priced. Do not invent instance prices or dollar figures.

## Output Format

Present **up to three candidates** and name one default. Do not assert a single product with
no alternatives shown, and do not present three options with no recommendation.

```
Candidates:
1. <option>
2. <option>
3. <option>

Default recommendation: <option> <version> on <deployment form>

Scale tier: <tier> (<data volume>, <peak QPS>) — from <stated or estimated>
Topology:   <replicas / pooler / partitioning — or "single instance, none of these">

Why:
- <the decisive fact from the gate, e.g. no dedicated DBA>
- <the next decisive fact>
- <why each runner-up loses here, one line each>

Cost assessment (graded, not priced — or priced where known):
- Upfront:          <low | medium | high>
- Monthly running:  <low | medium | high>
- Operations staff: <low | medium | high>
- Scaling:          <low | medium | high>
- Lock-in risk:     <low | medium | high>

Re-evaluate when:
- <measurable trigger, e.g. monthly DB cost exceeds the staffing cost it replaces>
- <measurable trigger, e.g. largest table passes ~N rows>
- <measurable trigger, e.g. multi-region writes become a requirement>

Assumptions (correct these if wrong):
- <each estimate you had to supply yourself>
```

Every re-evaluation trigger must be **measurable**. "When we get bigger" is not a trigger.

## Next Step

| Decision | Go to |
|---|---|
| MySQL or Aurora MySQL | `mysql-guideline` |
| PostgreSQL or Aurora PostgreSQL | `postgres-guideline` |
| SQLite (Tier 0, embedded, local tools) | `sqlite-guideline` |
| Naming and data types (either engine) | `rdbms-naming` |
| Table and relationship design | `rdbms-modeling` |
| Migrating off the current database | `database-migrations` |
| Not an RDBMS after all | Say so plainly, name the store, and stop — this plugin does not cover it |

## Reference Files

- `references/cost-evaluation.md` — cost components, three-year TCO and outage-risk formulas,
  option comparison, per-scale defaults, decision rules, and the final selection criterion
