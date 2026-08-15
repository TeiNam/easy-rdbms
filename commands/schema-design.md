---
description: Design a data model in three staged steps — conceptual, logical, then physical DDL
argument-hint: [the feature or domain to model]
---

Use the `rdbms-modeling` skill to design the data model for the following, and follow it exactly —
its three stages, its confirmation gates, and its evidence rules are the specification. Do not
substitute a faster path.

$ARGUMENTS

Two things this command adds, because they are about *how it was invoked* rather than policy:

- **State the rigor level before you start.** Payments, inventory, permissions, and contracts get
  all three stages in full. A personal tool may compress the first two into one short pass — but say
  which you chose, rather than compressing silently.
- **Requirements arriving as one message are still not a licence to emit DDL in one step.** Run the
  conceptual stage even when the request looks complete enough to skip it.

Where the skill's rules split by engine — foreign keys especially, which differ across MySQL,
PostgreSQL, and SQLite — read `rdbms-modeling/references/foreign-keys.md` rather than working from
memory.
