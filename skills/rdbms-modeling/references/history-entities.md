# History and Audit Entities

Identify **which** history problem the code actually has before designing a structure. The methods
differ in cost by an order of magnitude, and the wrong one is either useless or unaffordable.

Three different questions get conflated as "history":

| Kind | The question it answers |
|---|---|
| **Audit history** | Who changed what data, and when |
| **Business history** | Which business state changed, and why |
| **Valid-time history** | What value was in effect at a given point in time |

A design that answers one does not answer the others. `updated_at` answers none of them.

## Methods

| Method | Fits | Character |
|---|---|---|
| **Audit columns** | Simple CRUD | `created_at`, `updated_at`, actor only |
| **Current + history table** | Ordinary business entities | Current row plus a full snapshot per version |
| **State-transition history** | Orders, approvals, contracts | Records from-state, to-state, actor, reason |
| **Valid-period model** | Prices, contracts, policies | `valid_from` / `valid_to` business validity |
| **Bi-temporal model** | Finance, insurance, regulated domains | Business valid time **and** database record time |
| **Trigger audit** | Changes can bypass the application | Captures admin SQL and batch writes |
| **Event sourcing** | Event-centric domains | Events are the source of truth; state is rebuilt |
| **CDC** | Analytics, downstream integration | Ships changes from the DB log to other systems |

**CDC is not a history design.** It carries no business reason for the change, so it cannot answer
"why". Use it to feed other systems, never as the only history mechanism.

## Choosing

- Only need to know *whether* something changed → **audit columns**
- Need to read or restore past data → **current + history table**
- The state change *is* the business act → **state-transition history**
- Future-dated or retroactive application → **valid-period model**
- Must reproduce both "what was in effect then" and "what the system believed then" →
  **bi-temporal**
- Must capture batch and admin SQL as well → add **trigger audit**
- Event replay is itself a core requirement → **event sourcing**, and only then

Start at the top. Each step down costs more to build and more to operate.

### Trigger Audit Is a Narrow, Named Exception

Both guideline skills prohibit triggers. **Trigger audit is the one sanctioned exception**, because
application-level history structurally cannot capture what never passes through the application —
admin SQL, migration scripts, batch jobs writing directly.

Conditions for using it:

- There is a **real, identified** write path outside the application. Not a hypothetical one.
- It writes **only** to an audit table — no business logic, no cascading effects, no derived columns.
- It is documented as an exception, with the bypassing write path named.
- It supplements the business history; it does not replace it. A trigger sees the row change, not
  the reason for it.

If every write goes through the application, do not add the trigger. Handle history in the write
path where the reason and the actor are actually known.

## Standard History Entity

```text
history_id        history record identifier
entity_id         source entity identifier (logical reference)
version           per-entity sequential version
operation         INSERT | UPDATE | DELETE
recorded_at       when the DB recorded it (system time)
changed_by        user or system identifier
source            API | BATCH | ADMIN | MIGRATION
reason_code       business reason for the change
request_id        request / transaction correlation id
valid_from        business validity start
valid_to          business validity end
snapshot          full post-change data, or the significant attributes
```

`(entity_id, version)` must be **UNIQUE**. History is **append-only** — never updated, never deleted
except by retention policy.

**No physical FK from history to the source entity, on either engine.** This is not just the MySQL FK
policy — an FK here forces a choice among three outcomes, and none of them is what history needs:

| Referential action | What happens to the parent delete | What happens to history |
|---|---|---|
| `CASCADE` | Succeeds | **Deleted** — the record that the row existed is gone |
| `RESTRICT` / `NO ACTION` | **Blocked** — the row can never be deleted while history exists | Preserved, at the cost of making deletion impossible |
| `SET NULL` | Succeeds | Preserved but **orphaned** — it no longer says whose history it is |

History needs the parent to be deletable *and* the record to survive intact, which no action
provides. Record `entity_id` as a logical reference with a `COMMENT`, index it, and enforce the
"parent existed at write time" rule in the application. **`ON DELETE CASCADE` from an entity to its
history is the worst of the three** — it deletes the evidence.

## Current + History Flow

```text
begin transaction
→ lock the current row, or use optimistic locking on version
→ validate business rules
→ update the current entity
→ insert the post-change snapshot as a new version in the history table
→ commit
```

Create and update write the current row and its history **in the same transaction**. On delete,
record the final state with `operation = 'DELETE'` first, then perform the hard or soft delete.

## State-Transition Flow

```text
read current state
→ validate the transition is permitted
→ update the current state
→ record from-state, to-state, actor, reason
→ commit in the same transaction
```

A state-transition table represents **business acts** — approved, cancelled, paid — not raw column
changes. If the rows read like a diff rather than a decision, the design has drifted into audit
logging.

## Valid-Period Flow

```text
read the currently effective period
→ close the existing period
→ insert the new period
→ check for overlapping periods on the same entity
→ commit
```

**Never conflate `valid_from` (business time) with `recorded_at` (system time).** They answer
different questions, and merging them makes retroactive correction unrepresentable.

For a retroactive correction, **add a new version — do not overwrite the existing record.** The old
record is what the system believed at the time, which is precisely what an audit needs.

Overlap checking has no built-in enforcement under a logical-constraint policy. PostgreSQL can
enforce it with an exclusion constraint on a range type; MySQL requires an application check plus a
detection query. State which one is in use.

## Snapshot vs Delta

- **Full snapshot is the default.** Point-in-time reconstruction is a single row read.
- Consider deltas **only** when storage is genuinely large and the changing attribute set is narrow.
- With deltas, restoring a point in time means replaying every version up to it — and one lost or
  misordered row corrupts everything after it.
- **A generic JSON audit log is not a substitute for a business history entity.** It has no schema,
  no constraints, and no reason code; it cannot answer "why", and queries against it cannot be
  planned.

## Indexes and Partitioning

Index candidates: `(entity_id, version)` — also the uniqueness constraint — plus
`(entity_id, recorded_at)` and `(recorded_at)`.

History tables are strong partitioning candidates, but the same evidence rule applies (see
`partitioning.md`): recommend RANGE only where accumulation, time-range reads, and retention-based
deletion are actually present in the code.

- **MySQL**: `RANGE COLUMNS (recorded_at)` with a trailing `p_maxvalue` partition — but every PK and
  UNIQUE index must contain the partition key, and folding `recorded_at` into `(entity_id, version)`
  **weakens the guarantee** to per-period uniqueness. It is a genuine either/or: keep
  database-enforced global `(entity_id, version)` uniqueness and do **not** partition, or partition
  and move that uniqueness to an application-enforced invariant with a detection query. Decide it
  explicitly — do not fold the column in and call the constraint intact.
- **PostgreSQL**: same either/or applies — a partitioned table's `UNIQUE` constraints must also
  include the partition key, so global `(entity_id, version)` uniqueness and partitioning are
  mutually exclusive here too. RANGE on `recorded_at` with a trailing `DEFAULT` partition (see `partitioning.md`
  for why `DEFAULT` beats a `MAXVALUE` bound).
- **Decide partitioning for the current entity and its history independently.** They have different
  access patterns and different retention.

Partition on `recorded_at`, not `valid_from` — system time is monotonic and immutable, business
validity is neither.

## Prohibited

- Writing the current-row change and its history in **different transactions**
- Using `updated_at` as a substitute for history
- Using mutable business data as the history identifier
- **`ON DELETE CASCADE` from the entity to its history** — deleting a row must not delete the record
  that it existed
- A significant state change recorded without an actor and a reason
- Personal data kept in snapshots **with no retention limit** — history is where PII quietly becomes
  permanent. Name the retention period and the purge path
- Event sourcing applied by default to ordinary CRUD entities

## Code Analysis Signals

| Signal | Points to |
|---|---|
| `status`, `state`, `approved_at`, `cancelled_at`, state-change methods | State-transition history |
| `effective_from`, `effective_to`, scheduled-application code | Valid-period model |
| Point-in-time queries, restore features, audit screens | Current + history table |
| APIs accepting a change reason and an actor | Business history, with `reason_code` |
| Direct writes from batch, admin tools, or migrations | Trigger audit as a supplement |
| Jobs deleting or archiving old history | Retention window and partitioning |
| Event publication and reprocessing code | Possibly event sourcing — verify replay is a requirement |

Report: recommended method, the evidence, storage unit (snapshot vs delta), transaction flow,
retention period, partitioning, and **confidence**. Where the evidence is thin, do not generate a
history structure — list what needs confirming.

## Final Principle

> Identify the purpose first. Ordinary business data defaults to current + history snapshots; state
> changes use state-transition history; scheduled or retroactive application uses the valid-period
> model. Add triggers, a bi-temporal model, or event sourcing only when audit, restore, or regulatory
> requirements actually demand it.
