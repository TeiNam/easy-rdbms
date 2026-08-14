---
description: Review a schema, query, or migration for performance, security, and lock risk
argument-hint: [file, migration, or query to review — defaults to uncommitted changes]
---

Use the `rdbms-review` skill to review the following.

$ARGUMENTS

If nothing is specified above, review the uncommitted database changes in this repo
(migrations, DDL, and SQL in the working tree).

Establish the engine and version first — every dialect finding depends on it. If it cannot
be determined, say so and limit the review to engine-neutral findings.

Report in the skill's format: findings ordered CRITICAL → HIGH → MEDIUM, each with impact
and an exact fix, then the verification steps, then the engine you assumed and how you
determined it.

If nothing is wrong, say so in one line. Do not manufacture findings.
