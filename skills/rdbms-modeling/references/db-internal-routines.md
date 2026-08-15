# Stored Procedures, Triggers, and Events

**Default: do not use them.** Business logic belongs in the application, where it is version
controlled, testable, reviewable, and visible in a stack trace. Logic hidden in the database is
found during an incident, not during development.

But the prohibition has a shape. Three categories, and the difference is *what the routine does*,
not *what kind of object it is*.

## Category 1 — Sanctioned: Infrequent Operational Utilities

**Allowed.** Scheduled maintenance work with no business semantics, running on a low duty cycle.

| Use | Why it fits |
|---|---|
| Automatic partition creation / rotation | Must run whether or not the application is deployed; pure DDL housekeeping |
| Retention purge (`DROP PARTITION`, bounded `DELETE`) | Operational lifecycle, not a business decision |
| Statistics refresh, `VACUUM`/`ANALYZE` orchestration | Database maintenance by definition |
| Consistency-check queries for logical FKs and denormalized columns | Read-only detection, no writes |
| Materialized view refresh | Operational, on a schedule |

Conditions:

- **No business logic and no business decisions.** It maintains structure, not meaning.
- **Runs on a schedule, infrequently** — hourly at most, typically daily. Not per-row, not per-write.
- **Idempotent and safe to re-run.** A failed run is retried, not repaired by hand.
- **Version controlled in the repo** like any migration, not created ad hoc in a session.
- **Logged and monitored.** A silently stalled partition-creation job is exactly the failure mode the
  safety partition exists to survive (see `partitioning.md`).

Where the platform offers an external scheduler, prefer it — cron, Airflow, `pg_cron`, an operator
job. An in-database event is acceptable when no external scheduler exists and the alternative is the
work not happening.

## Category 2 — Narrow Exception: Audit Triggers

**Allowed only to close a correctness gap nothing else can.** This one *does* run per-write, which
is why it is an exception rather than a Category 1 utility.

Justification: application-level history structurally cannot capture writes that never pass through
the application — admin SQL, migration scripts, batch jobs writing directly. No amount of application
code closes that gap.

Conditions (all of them):

- A **real, identified** bypassing write path exists. Not a hypothetical one.
- The trigger writes **only** to an audit table. No business logic, no derived columns, no cascading
  effects.
- Documented as an exception, naming the write path that justifies it.
- **Supplements** business history; does not replace it. A trigger sees the row change, not the reason.

If every write goes through the application, do not add it. See `history-entities.md`.

## Category 3 — Prohibited: Business Logic in the Database

**Not allowed**, regardless of how convenient it looks:

| Anti-pattern | Use instead |
|---|---|
| Trigger maintaining a denormalized column or aggregate | The application transaction that changed the source (see `denormalization.md`) |
| Trigger setting `updated_at` | Set it in the application write path |

> **Named exception: MySQL's `ON UPDATE CURRENT_TIMESTAMP`.** It is a *column attribute*, not a
> routine — no stored program, no hidden branch, nothing to version separately — so it is outside
> this policy and the MySQL examples use it. Two consequences to accept knowingly: the **database
> clock** stamps the row rather than the application's, and it fires only when the `UPDATE` actually
> changes a value. PostgreSQL has no equivalent, so there the application owns `updated_at`; a
> trigger to emulate it is still prohibited.
| Trigger enforcing a business rule or state transition | Application validation; `CHECK` for structural invariants |
| Stored procedure holding a business workflow | Application service code |
| Event running business processing on a timer | Application job or external scheduler |
| Trigger cascading writes into other business tables | Explicit application logic in one transaction |

A trigger that maintains denormalized data is the most common request in this category and the most
tempting, because it appears to guarantee consistency. It does not qualify under Category 1 — it runs
on every write, and keeping a derived business value correct *is* business logic. The synchronization
mechanism belongs in the transaction that changed the source, where it is visible and testable.

## MySQL-Specific Note

Stored programs are additionally weak on MySQL: the stored-program cache is **per-session**, with no
global shared pool like Oracle's. (PostgreSQL's prepared-statement and PL/pgSQL plan caches are also
per-backend.) Connection-pool churn re-pays the parse and compile cost
on each connection's first call. See `mysql-guideline/dev-practices.md`.

## Review Position

When reviewing an existing schema:

- A routine doing Category 1 work → fine. Check it is version controlled, monitored, and idempotent.
- An audit trigger meeting all Category 2 conditions → fine. Check it writes only to the audit table.
- Anything else → a finding. Report what the routine does, why it belongs in the application, and the
  migration path.

Report the **inventory** too. Undocumented routines are the real hazard: a trigger nobody knows about
will contradict the application eventually, and the debugging session that finds it is expensive.

```sql
-- MySQL
SELECT trigger_name, event_object_table, action_timing, event_manipulation
FROM information_schema.triggers WHERE trigger_schema = DATABASE();
SELECT routine_name, routine_type FROM information_schema.routines
WHERE routine_schema = DATABASE();
SHOW EVENTS;

-- PostgreSQL
SELECT tgname, relname FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid WHERE NOT tgisinternal;
SELECT proname FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema');
```
