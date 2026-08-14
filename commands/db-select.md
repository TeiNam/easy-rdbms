---
description: Pick the right database for this project's scale, then route to its guideline
argument-hint: [what you're building, expected scale, any constraints]
---

Use the `db-select` skill to recommend a database for the following.

$ARGUMENTS

Follow the skill exactly:

1. Collect the facts in its gate table. Ask for everything missing in one message — do not
   guess at data volume, QPS, or who operates the database.
2. Decide whether an RDBMS fits at all before comparing engines.
3. Place the workload in a scale tier using the 12-month projection.
4. Present up to three candidates with **one clearly named default** — never three options
   without a recommendation, never one option with no alternatives shown.
5. Give every deferred item a measurable trigger.
6. Route to `mysql-guideline`, `postgres-guideline`, or `sqlite-guideline` for the follow-up work.

If the project already has a database (the session may say so), do not re-litigate the
choice unless asked. Review whether the current tier still fits instead.
