# Normalization Detail

Full rules for each normal form, the BCNF check procedure, and the denormalization bar.
The policy summary lives in `SKILL.md`; read this file when actually normalizing a model.

### 1NF — Atomic Values

- No multi-value columns: no CSV, no pipe-delimited strings
- Split repeating groups into their own tables
- **Exception**: MySQL `json` / PostgreSQL `jsonb` is acceptable **only** for configuration
  data that is neither queried nor indexed. The moment a field is filtered or joined on,
  extract it into a real column or table.

### 2NF — No Partial Functional Dependencies

- On a composite PK, any column depending on only part of the key moves to its own table
- A single `AUTO_INCREMENT` / `IDENTITY` PK usually satisfies 2NF by construction
- Still audit dependencies when a surrogate PK sits alongside a business `UNIQUE` constraint

### 3NF — No Transitive Dependencies

- If a non-key column depends on another non-key column, split it out
- Usual suspects: addresses, category and code masters, rarely-changing profile attributes

**Stop here and state that 3NF is reached.** This is the required baseline; everything below
is a judgment call you must show your work on.

### BCNF — Check Always, Decompose Selectively

3NF still permits an anomaly when a table has a **determinant that is not a superkey**. This
happens with overlapping candidate keys — most often a table with two composite keys over the
same columns.

The test, applied to every table:

1. List the functional dependencies.
2. For each `X → Y`, ask whether `X` is a superkey (does `X` determine the whole row?).
3. If some `X` is a determinant but **not** a superkey, the table violates BCNF.
4. Ask whether that violation can actually produce an update, insert, or delete anomaly given
   the real business rules — not in theory.

Decompose to BCNF when step 4 says yes.

**Keep 3NF instead when either of these holds** — and say which one:

- **Dependency preservation fails.** The decomposition cannot enforce one of the original
  functional dependencies without a cross-table constraint the engine will not express. A
  dependency you cannot enforce is worse than the redundancy it removed.
- **Join cost becomes unreasonable.** The decomposition forces additional joins into ordinary
  read paths, and the anomaly it prevents is already ruled out by an application-level
  constraint or a `UNIQUE` index.

Record the outcome either way:

```
BCNF check: <table>
  FDs:        <the dependencies>
  Violation:  <the non-superkey determinant, or "none">
  Decision:   decomposed | kept at 3NF
  Reason:     <the anomaly resolved, or which exception applied>
```

Do not silently skip the check. "BCNF: no violations found" is a valid and expected result for
most tables with a single surrogate PK.

### Denormalization

Denormalization is a **physical-model** technique and has its own policy — the measured-problem bar,
the eight methods, synchronization mechanisms, the seven apply-conditions, and the
consistency-check/rebuild requirements are in `denormalization.md`.

Two things to carry back into normalization work:

- **Do not denormalize while normalizing.** The logical model stays at 3NF; denormalization answers a
  measured problem in a running system.
- **A snapshot of a business fact is not denormalization.** The price on an order line at purchase time
  is the transaction's own data, not a cached copy of the product price. If the source changes and this
  value should *not* follow, it is business source data and needs no synchronization.
