---
description: Review a schema, query, or migration for performance, security, and lock risk
argument-hint: [file, migration, or query to review — defaults to uncommitted changes]
---

Use the `rdbms-review` skill to review the following, and follow its procedure and output format
exactly.

$ARGUMENTS

**If nothing is specified above, review the uncommitted database changes in this repo** —
migrations, DDL, and SQL in the working tree. That default is this command's only addition to the
skill.
