# Foreign Keys — Engine-Split Policy

The *meaning* of a foreign key is the same on both engines. Implementation and operational costs
differ. **Read the project's established FK policy first.** The MySQL logical-FK default below is
a plugin policy for operational flexibility, not a claim that InnoDB cannot enforce references.
Do not remove a working FK merely because the engine is MySQL.

| | MySQL / InnoDB | PostgreSQL |
|---|---|---|
| **Physical `FOREIGN KEY`** | Logical by default; project policy may use physical FKs on non-partitioned tables | **Allowed by default — created when the conditions below are met** |
| Referential integrity owner | Application for logical FKs; database for physical FKs | The database, once the constraint is valid |
| Referencing-column index | Verify it; create by hand for logical FKs | **Created unless an existing index already leads with the column** |

## Engine Differences That Drive the Split

| Aspect | MySQL / InnoDB | PostgreSQL |
|---|---|---|
| **Child (referencing) index** | Auto-created by the FK if no index leads with that column | **Never auto-created** |
| **Parent (referenced) target** | MySQL 8.4는 기본적으로 PK/UNIQUE 요구. 과거 non-unique/partial 참조는 deprecated | **PK or UNIQUE only** |
| **Check timing** | Immediate | Immediate, or deferrable to end of transaction |
| **Adding an FK to a large table** | Validates immediately — budget the scan and locks | `NOT VALID` 후 `VALIDATE CONSTRAINT`; 파티션 참조 테이블은 18부터 지원 |
| **`NO ACTION` vs `RESTRICT`** | Effectively identical; both check immediately | `NO ACTION` can defer to end of transaction; `RESTRICT` blocks immediately |
| **Partitioned tables** | InnoDB **cannot** have an FK on a partitioned table, either direction | Supported (referencing a partitioned table from PG 12+); `ATTACH PARTITION` validates, taking stronger locks |

Use measured lock contention, the chosen schema-change tool, and an actual partitioning requirement
to justify a logical FK. A possible future partition is not enough reason to remove current
integrity protection.

## MySQL / InnoDB — Logical FK Default and Project Overrides

The examples use logical FKs: referential integrity is owned by the application and the relationship
is documented in a `COMMENT`. Where project policy uses physical FKs, keep both tables
non-partitioned, reference a PK/UNIQUE target with matching types, verify the child index, bound
cascades, and plan validated additions within the lock budget. Do not disable `foreign_key_checks`
and assume re-enabling it validates existing rows.

MySQL 8.4의 `restrict_fk_on_non_standard_key=ON` 기본값은 non-unique/partial 부모 키를
참조하는 FK 생성을 거부한다. 호환 옵션을 끄는 것을 해결책으로 삼지 말고 부모의 중복을
정리한 뒤 PK/UNIQUE 대상으로 바꾼다. 기존 스키마는 8.4 업그레이드 검사에서 함께 확인한다.

Why, beyond partitioning: an FK adds a parent-index lookup to every child write that the statement
never shows and slow-query analysis cannot attribute; FK checks take shared locks on the parent row —
child writes do not block each other, but any update or delete of a hot parent's key (a tenant, a
category, a config row) blocks, and is blocked by, **every** in-flight child write, surfacing as
hard-to-diagnose stalls; `ON DELETE CASCADE` gives one statement unbounded transaction scope; and
`pt-online-schema-change` / `gh-ost` need special handling for FKs, turning routine maintenance into
a downtime negotiation.

### The Index Consequence — Do Not Miss This

InnoDB auto-creates a child index **when the FK is created** (if none leads with that column).
**Dropping the FK does not drop that index** — it remains, but under an auto-generated name that
reads like leftovers, and the next "unused index cleanup" is likely to remove it.

For a logical FK the referencing-column index is **deliberate and manual**: no constraint creates
one for you. On an inherited schema, after dropping an FK, run `SHOW INDEX` and keep or
rename the auto-created index explicitly. An unindexed child column means a full scan of the child
table on every parent-side lookup and join.

```sql
-- Mandatory unless an existing composite index already LEADS with customer_id
CREATE INDEX idx_purchase_order_customer_id ON purchase_order (customer_id);
```

Do not create a redundant one. If `idx_purchase_order_customer_created (customer_id, created_at)` exists, it
already serves the lookup — a separate `(customer_id)` index is write cost for no read benefit.

### Four Compensating Controls

Because nothing enforces the reference, every logical FK carries all four:

1. The reference in a `COMMENT` — `logical FK: parent_table.parent_column`
2. **The index above** — mandatory
3. A named **integrity owner** — which service or module guarantees it on the write path
4. A scheduled orphan-detection query

```sql
SELECT c.chat_history_id
FROM chat_history c
LEFT JOIN member u ON u.member_id = c.member_id
WHERE u.member_id IS NULL
LIMIT 100;
```

If several writers exist (batch, admin tooling, external integrations), the integrity owner must be
a shared layer they all pass through — not one application's validation code.

If no shared integrity owner can exist, prefer a physical FK where the table and project policy
permit it, or consolidate the writers. If partitioning or another concrete requirement prevents
both, resolve the ownership/model conflict explicitly. An orphan detector finds violations after
they happen; it is not a substitute for enforcing an invariant that must always hold.

## PostgreSQL — Allowed by Default, Created When Conditions Are Met

PostgreSQL supports FKs on partitioned tables. Staged validation also supports partitioned
referencing tables from **18**. **The default posture is to allow physical FKs**, while measuring
their write and lock costs.

"Allowed by default" is not "always create". Create the constraint when **all** of these hold —
each is a gate, and a failing gate means either fix it first or fall back to a logical FK with the
four compensating controls.

| # | Condition | If it fails |
|---|---|---|
| 1 | Parent column is a **PK or UNIQUE** | Fix the parent model. A non-unique target is a modeling error, not a constraint option |
| 2 | Referencing column is **indexed** — create it unless an existing index already leads with that column | Create it **in the same rollout, before the FK**. On an empty or new table the same migration is fine. On a populated table use `CREATE INDEX CONCURRENTLY` in its own migration with no transaction wrapper — most runners wrap migrations in a transaction, which `CONCURRENTLY` rejects. Without the index, every parent delete or key update sequentially scans the child |
| 3 | No **redundant** index introduced | Reuse the existing leading-column index; do not add a duplicate |
| 4 | If `CASCADE`: the child's **lifecycle is genuinely dependent** on the parent (order → purchase_order_item) | Use `RESTRICT` and delete explicitly. Never cascade across an aggregate boundary or from a high-fan-out parent |
| 5 | `NOT DEFERRABLE` unless a **circular reference must resolve inside one transaction** | Keep it non-deferrable. MySQL에는 이 deferred FK 경로가 없으며 SQLite는 별도 지원 |
| 6 | Use a validation path supported by the **server version and referencing table** within the lock budget | Populated table: `NOT VALID` then `VALIDATE CONSTRAINT`; partitioned referencing tables require 18+. A validated single-step add needs a timed scan and an explicit lock budget |

**버전 경계:** PostgreSQL **16/17**의 파티션 **참조(child)** 테이블은
`ADD FOREIGN KEY ... NOT VALID`를 거부한다. 이 경우 유지보수 창에서 측정한 검증된 추가
또는 논리 통제를 유지한다. **18부터는 부모 파티션 테이블에 NOT VALID로 추가하고
VALIDATE할 수 있다.** 유효성 검사 완료까지 기존 행의 정합성을 보장하지 않는다는 점은 같다.
참조 대상(parent)이 파티션인 경우와 혼동하지 않는다. leaf별 FK는 부모 전체 FK의 대체가 아니다.

```sql
-- Condition 2 first, in the same rollout (CREATE INDEX CONCURRENTLY in a separate,
-- transaction-less migration if the table is already populated)
CREATE INDEX idx_purchase_order_customer_id ON app.purchase_order (customer_id);

ALTER TABLE app.purchase_order
  ADD CONSTRAINT fk_purchase_order_customer
  FOREIGN KEY (customer_id) REFERENCES app.customer (customer_id)
  ON DELETE RESTRICT;
```

```sql
-- 비파티션 테이블: 16~18. 파티션 참조 테이블: 18부터 지원한다.
ALTER TABLE app.purchase_order
  ADD CONSTRAINT fk_purchase_order_customer
  FOREIGN KEY (customer_id) REFERENCES app.customer (customer_id)
  ON DELETE RESTRICT
  NOT VALID;

ALTER TABLE app.purchase_order VALIDATE CONSTRAINT fk_purchase_order_customer;
```

### Costs That Remain

Allowing FKs does not make them free. These still apply and are reasons to choose a logical FK for a
specific relationship:

- **Extra write I/O** — each child write does a parent lookup the statement does not show
- **Parent-row lock contention** — validation takes a `FOR KEY SHARE` lock. Child writes are
  mutually compatible, but a parent-key update or delete conflicts with all of them — on a hot
  parent row the two sides stall each other
- **Cascade scope** — `ON DELETE CASCADE` on a high-fan-out parent turns one statement into a long
  transaction with lock and bloat consequences
- **Bulk load and restore ordering** — `pg_restore` and backfills must order operations or run with
  constraints disabled, meaning the guarantee is absent during exactly the operations most likely to
  corrupt data

When a relationship has a very hot parent row or extreme write volume, dropping to a logical FK with
the four compensating controls is a legitimate choice. Say why.

### A `NOT VALID` Constraint Is Not a Guarantee

A constraint left `NOT VALID` prevents *new* violations but never checked the existing rows. Until
`VALIDATE CONSTRAINT` succeeds, treat the reference as a logical FK and run the orphan query.

## Reference Target Rule Applies to Logical FKs Too

**A reference must target a PK or UNIQUE column** — enforced by PostgreSQL, deprecated-but-permitted
historically on MySQL, and equally required for a *logical* FK where nothing enforces it. A
documented reference to a non-unique column is ambiguous by construction: "which parent row?" has no
single answer, and the orphan-detection query cannot be written correctly. Treat it as a modeling
error.

## Cost of a UUID as the Referenced Key

A UUID PK is sound for referential integrity. The cost is repetition: **16 bytes in every child row
plus 16 bytes in every index on that child column**, versus 8 for `bigint`. At scale that is storage
and, more importantly, cache pressure. On InnoDB it compounds — the PK value is also copied into
every secondary index of the parent. Weigh this before choosing a UUID PK for a table with many
high-volume children; see `identifier-selection.md`.

## Inherited MySQL Schemas

Keep working constraints unless project policy and a measured operational problem justify removal.
Before any removal, deploy the integrity-owner checks and orphan detection. Dropping an FK leaves
its auto-created child index in place; verify it with `SHOW INDEX` and keep or rename it explicitly.
Do not leave a gap between removing database enforcement and enabling its replacement.
