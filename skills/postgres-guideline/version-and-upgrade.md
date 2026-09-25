# PostgreSQL 18 기능과 버전 전환

확인 기준: 2026-09-25. 기본 대상은 PostgreSQL 18이며, 16/17 운영 DB를 자동으로
업그레이드하지 않는다. 패치는 해당 major의 지원 중인 최신 버전을 검토한다.

```sql
SHOW server_version;
SHOW server_version_num;
SELECT extname, extversion FROM pg_extension ORDER BY extname;
```

## 18 전용 기능을 적용하는 조건

| 기능 | PostgreSQL 18 | 16/17 호환 경로 |
|---|---|---|
| UUIDv7 | 내장 `uuidv7()` | 애플리케이션에서 v7 생성. `gen_random_uuid()`는 v4 |
| 생성 컬럼 | `VIRTUAL` 지원, 생략하면 VIRTUAL | `STORED`만 지원. 공용 DDL은 항상 명시 |
| B-tree skip scan | 선두 컬럼 조건 없이 뒤 컬럼으로 탐색하는 계획 가능 | 같은 개선을 가정하지 말고 기존 실행계획 확인 |
| 비동기 I/O | 순차 스캔·bitmap heap scan·VACUUM 등의 I/O 경로 개선 | 기존 I/O 방식에 맞게 측정 |
| 파티션 참조 테이블의 FK | `ADD ... FOREIGN KEY ... NOT VALID` 가능 | 16/17은 거부. 검증된 일괄 추가 또는 논리 통제 유지 |
| 시간 구간 제약 | `WITHOUT OVERLAPS`, temporal FK의 `PERIOD` | exclusion constraint 등 별도 모델 검토 |

### UUID와 생성 컬럼

```sql
-- PostgreSQL 18 전용. 일반 엔터티 예제로, 이벤트/로그 PK 정책과 별개다.
CREATE TABLE app.catalog_item (
  catalog_item_id uuid NOT NULL DEFAULT uuidv7(),
  quantity integer NOT NULL,
  unit_price numeric(12,2) NOT NULL,
  total_price numeric(18,2) GENERATED ALWAYS AS (quantity * unit_price) VIRTUAL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_catalog_item PRIMARY KEY (catalog_item_id),
  CONSTRAINT chk_catalog_item_quantity CHECK (quantity >= 0),
  CONSTRAINT chk_catalog_item_unit_price CHECK (unit_price >= 0)
);
```

VIRTUAL은 읽을 때 계산한다. 계산 비용을 없애는 캐시가 아니다. PostgreSQL 18의 VIRTUAL은
사용자 정의 타입·함수(확장 소유 타입·함수 포함)를 사용할 수 없다.
PostGIS 계산 컬럼 등은 immutable 조건을 확인한 **STORED** 또는 일반 컬럼을 검토한다.
16/17과 공유하는 마이그레이션에 VIRTUAL을 내보내지 않는다.

### Skip scan과 I/O

- `(tenant_id, created_at)`에서 `created_at`만 검색해도 skip scan 후보가 된다.
  선두 컬럼의 distinct 값이 적을 때 유리할 수 있으나, 높은 cardinality나 큰 반환 비율에서는
  순차 스캔이 더 싸다. 선두 컬럼을 무시해도 된다는 인덱스 설계 규칙으로 바꾸지 않는다.
- PostgreSQL 18의 `io_method` 기본값은 `worker`. `io_uring`은 지원 Linux 빌드에서만 가능하다.
  OS·파일시스템·스토리지와 동시 부하를 확인하고 변경 전후 `EXPLAIN (ANALYZE, BUFFERS)`,
  `pg_stat_io`, 처리량·p95를 비교한다. AIO가 인덱스 누락이나 느린 SQL을 해결하지는 않는다.
- `work_mem`은 연결당 단일 예산이 아니라 sort/hash 연산·병렬 worker마다 소비될 수 있다.
  `max_connections`, pool 총합, 동시 쿼리 수와 함께 메모리를 계산한다.

```sql
-- PostgreSQL 18에서 조회. 설정을 바꾸지 않는다.
SHOW io_method;
SELECT backend_type, object, context, reads, read_time, writes, write_time
FROM pg_stat_io
ORDER BY backend_type, object, context;
```

I/O 시간 측정은 `track_io_timing` 설정과 비용도 확인한다. 수치가 0이라고 빠른 I/O라고
판정하지 않는다.

## Major 업그레이드

1. 기존 major·확장 버전·OS/ICU/libc·collation·드라이버·관리형 제한을 기록한다.
   복구 가능한 백업과 복원 시간을 먼저 확인한다.
2. 새 major용 확장 바이너리를 설치하고 확장별 지원 범위와 update path를 확인한다.
   `CREATE EXTENSION`만으로 OS 라이브러리가 설치되지는 않는다. 절차는 `extensions.md`.
3. 복제 환경에서 `pg_upgrade --check`와 실제 업그레이드 또는 dump/restore를 리허설한다.
   확장·인덱스·통계·주요 쿼리·쓰기·권한·드라이버를 검증한다. 18의 통계 유지 개선이
   모든 통계 수집·실행계획 확인을 대체하지 않는다.
4. collation 버전이 바뀌었다면 영향을 받은 인덱스를 재구축한 뒤 버전을 갱신한다.
   `REFRESH COLLATION VERSION`만으로 인덱스 순서가 고쳐지지는 않는다.
5. 전환 후 새 DB에 쓴 데이터를 이전 major로 되돌릴 경로를 따로 설계한다.
   이전 바이너리로 재기동하는 것은 다운그레이드 절차가 아니다.

**공식 Docker 이미지의 18부터 데이터 경로가 달라진다.** 기본 `PGDATA`는
`/var/lib/postgresql/18/docker`이고 볼륨은 `/var/lib/postgresql`에 둔다.
17 이하의 `/var/lib/postgresql/data` 볼륨을 그대로 새 태그에 붙이는 것을 업그레이드로
취급하지 않는다. 자체 이미지나 관리형 서비스는 해당 배포의 경로를 따로 확인한다.

MD5 비밀번호 인증은 18에서 deprecated다. 드라이버의 SCRAM 지원 확인, 비밀번호 재설정,
`pg_hba.conf` 전환을 순서대로 검증한다. `password_encryption` 변경만으로 기존 비밀번호가
SCRAM으로 변환되지는 않는다.

## 공식 근거

- [PostgreSQL 18 릴리스](https://www.postgresql.org/docs/18/release-18.html)
- [생성 컬럼](https://www.postgresql.org/docs/18/ddl-generated-columns.html)
- [복합 인덱스와 skip scan](https://www.postgresql.org/docs/18/indexes-multicolumn.html)
- [I/O 설정](https://www.postgresql.org/docs/18/runtime-config-resource.html)
- [pg_upgrade](https://www.postgresql.org/docs/18/pgupgrade.html)
- [공식 Docker 이미지의 PGDATA](https://github.com/docker-library/docs/blob/master/postgres/README.md#pgdata)
