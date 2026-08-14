---
description: Design a data model in three staged steps — conceptual, logical, then physical DDL
argument-hint: [the feature or domain to model]
---

Use the `rdbms-modeling` skill to design the data model for the following.

$ARGUMENTS

**Do not go from these requirements straight to DDL.** Run the skill's three stages in order,
stopping at each confirmation gate:

1. **Conceptual** — business concepts, relationships, and the user's own terminology. No
   columns, no types, no keys, no DB product. Then ask what is missing or misnamed and wait.
2. **Logical** — entities, attributes, PK/FK, cardinality, NOT NULL and UNIQUE, normalized to
   3NF with the BCNF check emitted for **every** entity (including "none" results), plus the
   generalization check (IS-A test — not attribute overlap; and nothing that is really a state
   or a role modeled as a subtype). Generic types only — no
   `bigint unsigned`, no `timestamptz`. Then ask whether the keys, cardinalities, and subtype
   structure match the business rules and wait.
3. **Physical** — only after the target RDBMS is confirmed. If it is undecided, use
   `db-select` at this point. Then produce DDL in the correct dialect, constraints, indexes,
   partitioning, ordered migration SQL, and a sample-data constraint test. **FK policy splits by
   engine**: on MySQL emit no physical `FOREIGN KEY` (and create the referencing-column index
   explicitly — InnoDB's auto-created one disappears with the constraint); on PostgreSQL physical
   FKs are allowed but only when all six conditions hold. Anything left logical carries a
   `COMMENT`, an index, a named integrity owner, and an orphan-detection query.

First state the rigor level: payments, inventory, permissions, and contracts get all three
stages in full; a personal tool may compress stages 1 and 2 into one short pass — but say so
rather than skipping silently.

Apply `rdbms-naming` for every identifier in stage 3.

Do not denormalize. That requires a measured performance problem, the cheaper alternatives
already tried, and a stated synchronization mechanism. If asked to denormalize without a
measurement, deliver the normalized design and say what evidence would justify revisiting it.
