# Cost Evaluation — Three-Year TCO

Read this when a recommendation needs a defensible cost position: budget is a stated
constraint, a migration is on the table, or the choice is between self-managed, managed, and
serverless.

## Principles

1. **A free open-source database is not free.** It still needs someone to patch, tune,
   monitor, back up, and recover it. That person's time is the largest line item at small
   scale.
2. **A managed database with a higher sticker price is often cheaper overall.** It converts
   staffing and incident cost into a predictable invoice.
3. **The cheapest start can be the most expensive path.** A choice that saves money at Tier 0
   and forces a migration at Tier 2 has to carry that migration in its cost.
4. **Compare over three years, never per month.** Monthly pricing hides setup, training,
   incident, and scaling costs entirely.
5. **When requirements are genuinely unknown, evaluate managed PostgreSQL first.** It is the
   option least likely to need replacing.

## Cost Components

### Upfront

| Item | What to evaluate |
|---|---|
| Support contract | Paid support or subscription tier, where one is taken |
| Build-out | Servers, network, security, HA and backup configuration |
| Development | Schema design, ORM and driver integration |
| Data transfer | Converting, validating, and cutting over existing data |
| Training | Developer and operator learning curve |
| Validation | Performance, failover, security, and compatibility testing |

### Ongoing

| Item | What to evaluate |
|---|---|
| Infrastructure | Compute, memory, storage, IOPS |
| Availability | Replicas, multi-AZ, cluster operation |
| Backup | Backup storage, PITR, restore rehearsals |
| Operations staff | Patching, tuning, monitoring, incident response |
| Scaling | Scale-up, read replicas, sharding |
| Network | Cross-region replication and data transfer |
| Security | Encryption, audit logging, access control |
| Lock-in | Cost of leaving this cloud or product later |

## Formula

```text
3-year TCO =
    upfront build-out cost
  + 36 months of infrastructure and service fees
  + 36 months of operations staff cost
  + outage risk cost
  + expected scaling cost
  + expected migration cost
```

Outage risk cost:

```text
annual outage risk cost =
    expected outages per year
  × mean time to recover
  × business loss per hour
```

**When you cannot get real prices, grade relatively — low / medium / high — and say that you
did.** A graded comparison the reader can check beats a fabricated dollar figure. Never
invent specific prices or instance costs.

## Option Comparison

| Option | Upfront | Ongoing | Fits |
|---|---|---|---|
| **SQLite** | Very low | Very low | Local tools, single user, embedded apps, CI |
| **Self-managed PostgreSQL / MySQL** | Medium | Medium–High | Real operational capability in-house and cost optimization matters |
| **Managed PostgreSQL / MySQL** | Low–Medium | Medium | Most web services and business systems — the common answer |
| **Serverless RDBMS** | Low | Varies with usage | Low or irregular traffic; per-branch dev databases |
| **Distributed SQL** (CockroachDB, TiDB, Citus, Aurora Limitless) | High | High | Global writes, strong consistency at scale, or horizontal scale that is a present requirement |

Scope note: this plugin's design guidance covers MySQL, PostgreSQL, and SQLite. Other relational
engines are out of scope — if a project is already committed to one, say the follow-up
guidance does not apply rather than arguing about the platform.

## Default Recommendation by Scale

| Situation | Default |
|---|---|
| Personal project, prototype | SQLite, or the cheapest managed PostgreSQL tier |
| Early startup | Managed PostgreSQL / MySQL at minimum spec |
| Growing service | Managed RDBMS + read replicas, with backup and monitoring hardened |
| Large service | Compare the cost of indexing, query work, caching, and scale-up **before** sharding |
| Regulated industry | Price audit logging, encryption, retention, and restore verification first |
| Global service | Compare distributed-DB cost against per-region independent operation |

## Decision Rules

- **No dedicated DBA or infra owner → prefer managed over self-managed.** The salary line
  dominates every other cost at small and medium scale.
- **Low or irregular traffic → evaluate serverless.** Scale-to-zero is real savings when
  idle time is most of the day.
- **Sustained high load → check whether a fixed instance is cheaper.** Per-request pricing
  loses to a reserved instance past a certain duty cycle.
- **Drop SQLite the moment multi-server writes or HA are required.** It has no answer for
  either; carrying it further only grows the migration.
- **Choose distributed SQL for a present requirement, not a possible future one.** The
  operational and SQL differences are paid from day one.
- **If expected migration cost exceeds the three-year saving, keeping the current database
  is a valid candidate.** Include it explicitly rather than assuming a move.

## Final Criterion

Among the candidates that satisfy **all** of the following, recommend the one with the lowest
three-year TCO — not the cheapest option outright:

- Meets the required performance and data-integrity guarantees
- Meets the target availability and recovery objectives
- Can actually be operated by this organization, as staffed today
- Scales within the expected growth range
- Has a future exit cost the organization could absorb
