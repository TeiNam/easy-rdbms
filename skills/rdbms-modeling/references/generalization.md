# Generalization and Specialization

Deciding whether two or more entities are really *kinds of* one thing — and what to build if
they are. The compact decision path is in `SKILL.md` Stage 2; this file has the full criteria.

## The Test Is IS-A, Not Attribute Overlap

**Shared attributes are a hint, never the criterion.** Two entities can share half their
columns and still be unrelated. The question is:

> Is every subtype an instance *of* the supertype?

`Individual customer IS-A customer.` `Corporate customer IS-A customer.` Both read correctly,
so `customer` is a real supertype.

`Order IS-A customer` does not read correctly no matter how many columns they share.

### Substitutability

The IS-A claim only holds if a subtype can stand in **anywhere the supertype is expected**.
Every corporate customer is a customer; not every customer is a corporate customer. The
relationship is one-directional, and code that accepts a customer must work when handed
either subtype without knowing which it got.

If some flow accepting a "customer" would break on one of the subtypes, they are not subtypes
of a common supertype — they are separate entities that happen to look alike.

## Seven Questions

Answer all seven before deciding. The answers pick the outcome, not your preference.

### 1. Is it genuinely IS-A?

Say the sentence out loud: `<subtype> IS-A <supertype>`. If it needs qualification to make
sense, stop — this is composition (`HAS-A`) or plain similarity, not specialization.

### 2. Does each subtype have its own attributes, relationships, or rules?

Shared attributes go on the supertype; type-specific attributes and constraints go on the
subtype.

```text
customer:            customer_id, name, joined_at
individual_customer: birth_date
corporate_customer:  business_registration_number, corporate_name
```

**If the subtypes differ only in name — same attributes, same relationships, same rules — do
not build subtypes.** A `customer_type` column on one table carries that distinction for a
fraction of the cost.

### 3. Are the types mutually exclusive?

- **Exclusive** — a customer is either individual or corporate, never both. Subtypes work.
- **Overlapping** — an employee can be a manager *and* an instructor at the same time.

Overlapping types are not subtypes. A single type code cannot represent two simultaneous
values, and a supertype/subtype structure will force you to fake it. Model overlapping
capabilities as a **role table**:

```text
employee(employee_id, name, hired_at)
employee_role(employee_id, role_code, assigned_at, released_at)
```

### 4. Is every instance in some subtype?

- **Total** — every supertype row belongs to exactly one subtype. The discriminator can be
  `NOT NULL` and a `CHECK` can enumerate the valid values.
- **Partial** — some supertype rows belong to no subtype. The discriminator must permit that
  case, and every query joining to a subtype has to tolerate a miss.

Say which one applies. A partial classification silently treated as total produces queries
that drop rows.

### 5. Can an instance's type change over time?

If a row can move from one subtype to another during its life, a subtype table structure makes
that a delete-plus-insert across tables, with the shared PK and every referencing row along for
the ride.

Frequent type changes argue for a **type column** (cheap `UPDATE`) or a **role model** (open a
new role, close the old one, keeping history). Reserve subtype tables for classifications that
are effectively permanent.

### 6. Is it a type, or a state?

**This is the most common modeling error.** `pending`, `paid`, `cancelled` are *states* of an
order, not subtypes of it. Signals that you are looking at a state:

- The value changes as part of normal operation
- The transitions matter, and are constrained (`pending → paid`, never `cancelled → pending`)
- You want the history of the changes

States belong in a status column, with the transitions enforced in the application and the
history in a separate event or history table — never in subtype tables.

Rule of thumb: **if it changes, it is a state or a role. If it is what the thing fundamentally
is, it is a type.**

### 7. Which is queried more — across all types, or one type at a time?

This does not change *whether* to specialize, only the physical mapping. Cross-type queries
favor a single table; single-type queries favor separate subtype tables.

## The Three Outcomes

| The situation | Build |
|---|---|
| Simple classification — same attributes, relationships, and rules; only the label differs | **A type column** on one table. `CHECK` the allowed values |
| Mutable responsibilities, or several held at once | **A role model** — a separate role table keyed by the entity, with validity dates |
| A genuine IS-A with subtype-specific attributes, relationships, or constraints | **Supertype + subtypes** |

Only the third case is generalization. Reaching for it in the first two cases is the
over-modeling this check exists to prevent.

## Identifier Inheritance

A subtype shares the supertype's primary key. The same `customer_id` identifies the customer
and its individual-customer detail — do not mint a separate surrogate key for the subtype row.

That shared PK is conceptually also a foreign key to the supertype. The FK policy splits by
engine (see `foreign-keys.md`): on **MySQL** it stays a documented logical reference; on
**PostgreSQL** a physical FK from the subtype PK to the supertype PK is a natural fit for the six
gates — it typically passes all of them.

```sql
-- MySQL
CREATE TABLE individual_customer (
  customer_id bigint unsigned NOT NULL COMMENT 'logical FK → customer.customer_id (subtype PK = supertype PK)',
  birth_date  date NOT NULL,
  CONSTRAINT pk_individual_customer PRIMARY KEY (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Two integrity rules follow, with different enforceability:

1. **A subtype row exists only if its supertype row exists.** On PostgreSQL a physical FK enforces
   this; on MySQL it is application-carried with the four compensating controls of a logical FK.
2. **Exclusivity/totality** — an exclusive classification permits a detail row in **at most one**
   subtype table (exactly one, if total). **No foreign key can enforce this on either engine**: an
   FK guarantees the parent exists, not that the other subtype table is empty. Always
   application-carried, always with its own detection query:

```sql
-- Exclusivity violation: a customer with detail rows in more than one subtype table
SELECT customer_id FROM (
  SELECT customer_id FROM individual_customer
  UNION ALL
  SELECT customer_id FROM corporate_customer
) s
GROUP BY customer_id HAVING count(*) > 1;
```

For a **total** classification, also check the other direction — supertype rows with no detail row
in any subtype table.

## Physical Mapping

| Strategy | Fits | Watch out for |
|---|---|---|
| **Single table + discriminator** | Few types, small differences between them, most queries span all types | Subtype columns must be nullable, so `NOT NULL` no longer enforces them. Recover it with conditional `CHECK` constraints — and note these multiply with each type |
| **Supertype table + one table per subtype** | Differences are substantial and integrity matters | A join for the complete picture. Exclusivity across subtype tables is not FK-enforceable on either engine — application rule + detection query |
| **One table per concrete subtype, no supertype table** | Types are used entirely independently | Shared attributes duplicated; cross-type queries need `UNION ALL`; anything referencing "a customer" has nothing to point at |

**Default for ordinary business systems: supertype table + one table per subtype.** It is the
most normalized of the three and keeps the shared attributes in one place.

Recovering the lost `NOT NULL` under the single-table strategy:

```sql
-- MySQL 8.0.16+ / PostgreSQL
ALTER TABLE customer ADD CONSTRAINT chk_customer_individual
  CHECK (customer_type <> 'INDIVIDUAL' OR birth_date IS NOT NULL);

ALTER TABLE customer ADD CONSTRAINT chk_customer_corporate
  CHECK (customer_type <> 'CORPORATE' OR business_registration_number IS NOT NULL);
```

Two types need two constraints; five types need five, and each new type edits the existing set.
That growth is the real cost of the single-table strategy — weigh it before choosing it for a
classification you expect to extend.

## Anti-Patterns

| Anti-pattern | Why it fails | Instead |
|---|---|---|
| Subtypes for `pending` / `paid` / `cancelled` | These are states; the row must move between them | Status column + history table |
| Subtypes for overlapping capabilities | A row needs two types at once | Role table |
| Subtypes that differ only in name | The structure buys nothing and costs a join | Type column |
| Supertype where every meaningful column is nullable | Traded database constraints for application checks | Split into subtype tables, or add conditional `CHECK` per type |
| Entity/attribute/value table (`entity`, `attr_name`, `attr_value`) | Discards typing, constraints, and the query planner | Real columns; `jsonb`/`json` only for non-queried config |
| Separate surrogate key on the subtype row | Two identifiers for one thing; they will diverge | Subtype PK **is** the supertype PK |
| Generalizing on attribute overlap without an IS-A relationship | Forces unrelated entities into one hierarchy | Keep them separate |
