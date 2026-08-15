---
description: Pick the right database for this project's scale, then route to its guideline
argument-hint: [what you're building, expected scale, any constraints]
---

Use the `db-select` skill to recommend a database for the following, and follow it exactly — its
fact gate, its scale tiers, its cost evaluation, and its output contract are the specification.

$ARGUMENTS

Two things this command adds, because they are about *how it was invoked*:

- **Ask for every missing gate fact in one message**, rather than one question at a time. Do not
  guess at data volume, QPS, or who operates the database — "unknown" is a valid answer and the
  skill knows what to do with it.
- **If the project already has a database** (the session hook may have said so), do not re-litigate
  the choice unless asked. Review whether the current scale tier still fits instead.
