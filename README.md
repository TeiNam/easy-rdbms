# Easy RDBMS

RDBMS design companion for **Claude Code** and **Codex**. Picks the database for your scale
and budget, keeps naming consistent, normalizes tables to 3NF with a BCNF check, and reviews
schemas and queries before they ship. Covers MySQL and PostgreSQL, including Aurora variants.

한국어 안내는 [아래](#한국어)에 있습니다.

## Install

### Claude Code

```bash
/plugin marketplace add TeiNam/easy-rdbms
/plugin install easy-rdbms@easy-rdbms
```

### Codex

```bash
codex plugin marketplace add TeiNam/easy-rdbms
codex plugin add easy-rdbms@easy-rdbms
```

Either harness can also install from a local checkout by passing the path instead of the
repo slug.

## What it does

| Skill | Use it for |
|---|---|
| `db-select` | Which database, which topology, and what it costs over three years |
| `rdbms-naming` | Table, column, index, and constraint naming; data type selection |
| `rdbms-modeling` | Designing a model in three stages: conceptual → logical → physical, with normalization and generalization checks |
| `rdbms-review` | Reviewing existing SQL, schemas, and migrations |
| `mysql-guideline` | MySQL 8.4 LTS+ / Aurora MySQL: schema, indexes, partitioning, operations, JDBC |
| `postgres-guideline` | PostgreSQL 16+ / Aurora PostgreSQL: schema, indexes, partitioning, RLS, psycopg |
| `database-migrations` | Zero-downtime schema changes, rollback strategy, ORM migration tooling |

Skills activate on their own when a task mentions relevant work. You can also invoke them
explicitly.

### Commands

| Command | Does |
|---|---|
| `/db-select` | Recommends up to three candidates with one default, a cost assessment, and measurable re-evaluation triggers |
| `/schema-design` | Runs conceptual → logical → physical with a confirmation gate between each, ending in DDL and migration SQL |
| `/schema-review` | Reviews a schema, query, or migration; findings ordered CRITICAL → HIGH → MEDIUM with exact fixes |

### Subagents (Claude Code only)

`rdbms-modeler` and `rdbms-reviewer`. Codex plugins cannot register named subagents, so on
Codex the same procedures live entirely in the skills — invoke `rdbms-modeling` or
`rdbms-review` directly.

### Session hook

On session start, the plugin checks for `docker-compose.yml`, `.env`, `alembic.ini`,
`prisma/schema.prisma`, `package.json`, `requirements.txt`, and similar files. If the project
already uses PostgreSQL or MySQL, it says so once so the agent stops asking. Silent when
nothing is found.

## Design decisions

**One skill directory, both harnesses.** `skills/` is shared. Frontmatter is `name` +
`description` only — the intersection of what Claude Code and Codex accept.

**Scale-aware, not scale-maximal.** `db-select` will tell you *not* to add read replicas,
partitioning, or sharding you have not earned. Each tier costs roughly an order of magnitude
more operational attention than the one below it.

**Cost is part of the choice.** A free database still needs someone to operate it, and that
salary is usually the largest line item at small scale. Comparisons are over three years, not
per month. When real prices are unavailable the skill grades low/medium/high and says it
graded rather than priced.

**Requirements never become DDL in one step.** `rdbms-modeling` runs conceptual → logical →
physical with a confirmation gate between each. The conceptual stage uses the user's own terms
and no database vocabulary; the logical stage normalizes with generic types; only the physical
stage needs the engine chosen — which is also when `db-select` runs, because the logical model
is what makes the engine choice answerable. Payments, inventory, permissions, and contracts get
all three stages in full; a personal tool may compress the first two, but the plugin says so
rather than skipping silently.

**Normalization has a policy, not a preference.** 3NF is required. BCNF is *checked on every
entity* and applied when a non-superkey determinant can cause a real anomaly — staying at 3NF is
allowed when decomposition breaks dependency preservation or explodes joins, but the reason has
to be stated. Denormalization needs a measurement, the cheaper alternatives already tried, and
a written synchronization mechanism. ACID and normalization are treated as separate concerns:
one keeps transactions safe, the other keeps the schema from drifting.

**Generalization is decided by IS-A, not by attribute overlap.** Two entities sharing half
their columns are not automatically a supertype — the test is whether each is genuinely *a kind
of* the other thing and can stand in wherever it is expected. The skill runs seven questions
(IS-A, subtype-specific attributes, exclusivity, totality, type mutability, type-vs-state, query
shape) and lands on one of three outcomes: a **type column** when only the label differs, a
**role model** when responsibilities are mutable or held simultaneously, or **supertype +
subtypes** when the IS-A is real. It also guards the far side: a supertype where every meaningful
column ended up nullable has traded database constraints for application checks, and an
entity/attribute/value table has given up on the schema entirely.

The single highest-value check is type-vs-state. `pending` / `paid` / `cancelled` are states of
an order, not subtypes of it — modeling them as subtypes turns every transition into a
cross-table move. `rdbms-review` flags the same confusion in existing schemas.

**MySQL and PostgreSQL only.** Other relational engines are out of scope; the plugin says so
rather than pretending to advise on them.

## Development

```bash
sh hooks/detect-db.test.sh          # hook detection tests
sh scripts/sync-from-harness.sh     # show upstream drift for ported skills
```

Four skills are ported from [`my_harness_for_claude_code`](https://github.com/TeiNam) and
carry local edits. See `AGENTS.md` for the repo conventions.

## License

MIT

---

## 한국어

**Claude Code**와 **Codex**용 RDBMS 설계 플러그인입니다. 규모와 예산에 맞는 DB를 고르고,
네이밍을 일관되게 잡고, 테이블을 3NF로 정규화한 뒤 BCNF 위반을 검사하고, 배포 전에 스키마와
쿼리를 리뷰합니다. MySQL과 PostgreSQL(Aurora 포함)을 다룹니다.

### 설치

Claude Code:

```bash
/plugin marketplace add TeiNam/easy-rdbms
/plugin install easy-rdbms@easy-rdbms
```

Codex:

```bash
codex plugin marketplace add TeiNam/easy-rdbms
codex plugin add easy-rdbms@easy-rdbms
```

### 구성

| 스킬 | 용도 |
|---|---|
| `db-select` | 어떤 DB를, 어떤 구성으로, 3년 비용은 얼마인지 |
| `rdbms-naming` | 테이블·컬럼·인덱스·제약 네이밍, 데이터 타입 선택 |
| `rdbms-modeling` | 3단계 설계: 개념 → 논리 → 물리, 정규화·일반화 검사 |
| `rdbms-review` | 기존 SQL·스키마·마이그레이션 리뷰 |
| `mysql-guideline` | MySQL 8.4 LTS+ / Aurora MySQL |
| `postgres-guideline` | PostgreSQL 16+ / Aurora PostgreSQL |
| `database-migrations` | 무중단 스키마 변경, 롤백 전략 |

커맨드는 `/db-select`, `/schema-design`, `/schema-review` 세 개입니다. 스킬은 관련 작업이
언급되면 자동으로 발동하므로 커맨드를 꼭 쓸 필요는 없습니다.

### 설계 방침

- **규모를 앞질러 사지 않습니다.** `db-select`는 아직 필요 없는 리드 리플리카·파티셔닝·샤딩을
  "지금은 하지 마라"고 명시합니다. 티어가 하나 올라가면 운영 부담이 대략 10배가 됩니다.
- **비용이 선택의 일부입니다.** 무료 DB도 운영할 사람이 필요하고, 작은 규모에서는 그 인건비가
  가장 큰 항목입니다. 월 단가가 아니라 3년 TCO로 비교하고, 실제 가격을 모를 때는
  낮음/중간/높음 상대 등급으로 평가했다는 사실을 함께 밝힙니다.
- **요구사항이 바로 DDL이 되지 않습니다.** `rdbms-modeling`은 개념 → 논리 → 물리 3단계를 거치며
  각 단계 사이에 확인 게이트를 둡니다. 개념 단계는 사용자의 용어만 쓰고 DB 어휘를 배제하고, 논리
  단계는 일반 자료형으로 정규화하며, 엔진 확정이 필요한 시점은 물리 단계뿐입니다 — 이때 `db-select`를
  실행합니다. 논리 모델이 나와야 엔진 선택에 답할 수 있기 때문입니다. 결제·재고·권한·계약은 3단계를
  모두 거치고, 개인 도구는 앞 두 단계를 축약할 수 있지만 축약했다는 사실을 반드시 밝힙니다.
- **일반화는 속성 유사성이 아니라 `IS-A`로 판단합니다.** 컬럼이 절반 겹쳐도 슈퍼타입이 되는 게 아니고,
  기준은 "정말 그것의 한 종류인가, 슈퍼타입이 필요한 자리에 대체 가능한가"입니다. 7개 질문(IS-A,
  서브타입 고유 속성, 배타성, 전체성, 타입 변경 가능성, 타입 vs 상태, 조회 패턴)을 거쳐 세 결과 중
  하나로 갑니다 — 이름만 다르면 **타입 컬럼**, 책임이 변하거나 동시에 여러 개면 **역할 모델**,
  IS-A가 진짜면 **슈퍼타입+서브타입**. 반대 방향도 막습니다: 의미 있는 컬럼이 전부 nullable이 된
  슈퍼타입은 DB 제약을 애플리케이션 검사로 바꾼 것이고, EAV 테이블은 스키마를 포기한 것입니다.
- **가장 값진 검사는 타입 vs 상태입니다.** `주문대기`·`결제완료`·`취소`는 주문의 상태이지 종류가
  아닙니다. 서브타입으로 모델링하면 상태 전이마다 테이블 간 이동이 됩니다. `rdbms-review`도 기존
  스키마에서 같은 혼동을 탐지합니다.
- **정규화는 취향이 아니라 정책입니다.** 3NF는 필수, BCNF는 **모든 엔터티에 검사**하고 슈퍼키가
  아닌 결정자로 실제 이상이 생길 수 있을 때 분해합니다. 함수적 종속성 보존이 깨지거나 조인이
  과도해지면 3NF 유지를 허용하되 그 이유를 반드시 남깁니다. 비정규화는 **측정된** 성능 문제와
  더 싼 대안을 먼저 시도한 기록, 그리고 동기화 방식이 명시돼야 합니다. ACID와 정규화는 역할이
  다른 별개 원칙으로 다룹니다 — 하나는 트랜잭션 안전성, 하나는 스키마 정합성입니다.
- **MySQL과 PostgreSQL만** 다룹니다. 다른 엔진은 범위 밖이라고 말하고 조언하지 않습니다.
- **Codex는 플러그인이 이름 붙은 서브에이전트를 등록할 수 없습니다.** 그래서 모델링·리뷰 절차를
  스킬 본문에 넣고, Claude Code 쪽에만 같은 스킬을 가리키는 얇은 에이전트 래퍼를 둡니다.
