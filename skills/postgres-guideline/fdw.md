# FDW로 외부 DB 연결

FDW(Foreign Data Wrapper)는 원격 데이터를 foreign table로 조회하는 방식이다.
PostgreSQL 간에는 코어 배포에 포함된 `postgres_fdw`를 우선 검토한다.
MySQL에는 별도 `mysql_fdw` 구현 등이 필요하며, PostgreSQL 18 지원·관리형 제공 여부·타입 매핑을
그 구현의 문서로 확인한다. `postgres_fdw`가 MySQL 프로토콜을 지원하는 것은 아니다.

## 적용 범위

- 적은 양의 외부 참조 데이터, 선택도가 높은 원격 조회, 점진적 데이터 이관에 적합하다.
- 지연·원격 장애가 로컬 요청에 전파된다. 대규모 반복 조인·분석은 적재/CDC와 비교한다.
- foreign table 정의는 원격 DDL과 자동 동기화되지 않는다. 스키마 변경 계약과 검증이 필요하다.
- 물리 복제, CDC, 캐시 또는 여러 DB에 걸친 원자적 트랜잭션을 대신하지 않는다.

## 읽기 전용 연결 예제

원격 DB의 관리 역할이 `report_reader` 로그인 역할을 만들고 필요한 schema의 USAGE,
테이블의 SELECT만 부여한다. 비밀번호는 secret manager에서 공급한다. 원격 역할에
슈퍼유저·소유자·BYPASSRLS를 주지 않는다.
원격 `pg_hba.conf`도 해당 연결에 SCRAM 등 비밀번호 인증을 요청하도록 설정한다.
`trust` 인증은 mapping에 비밀번호가 있어도 비슈퍼유저 FDW 연결을 거부하게 할 수 있다.

로컬 DB에서는 다음처럼 전용 역할과 schema를 쓴다. `fdw_host`, `fdw_port`, `fdw_dbname`,
`fdw_ca`, `fdw_password`는 **psql 변수**이며 대상 환경에서 공급해야 한다.
비밀번호를 `psql -v ...` 명령행이나 커밋 파일에 넣지 말고, 배포 프로세스가 보안 입력으로
주입한다. CA 경로는 클라이언트 PC가 아니라 **로컬 PostgreSQL 서버 안의 경로**다.

```sql
CREATE EXTENSION IF NOT EXISTS postgres_fdw;
CREATE ROLE integration_reader NOLOGIN;
CREATE SCHEMA integration;

CREATE SERVER reporting_server
  FOREIGN DATA WRAPPER postgres_fdw
  OPTIONS (host :'fdw_host', port :'fdw_port', dbname :'fdw_dbname',
           sslmode 'verify-full', sslrootcert :'fdw_ca');

CREATE USER MAPPING FOR integration_reader SERVER reporting_server
  OPTIONS (user 'report_reader', password :'fdw_password');

GRANT USAGE ON FOREIGN SERVER reporting_server TO integration_reader;
GRANT USAGE, CREATE ON SCHEMA integration TO integration_reader;

-- IMPORT도 해당 역할의 mapping을 사용한다.
SET ROLE integration_reader;
IMPORT FOREIGN SCHEMA reporting LIMIT TO (product_snapshot)
  FROM SERVER reporting_server INTO integration;
RESET ROLE;
REVOKE CREATE ON SCHEMA integration FROM integration_reader;
```

로컬 로그인 역할에는 필요한 경우 `integration_reader` 멤버십을 부여하고 해당 역할로
조회한다. `IMPORT`가 만든 foreign table의 소유권만으로 원격 쓰기 권한을 얻지는 못한다.
**읽기 전용 보장은 원격 `report_reader`의 GRANT로 강제한다.**
일괄 `FOR PUBLIC` mapping이나 `password_required=false`로 인증 문제를 우회하지 않는다.

`IMPORT FOREIGN SCHEMA`는 데이터 복사가 아니다. 필요한 테이블만 가져오며,
원격의 PK·UNIQUE·CHECK·인덱스를 로컬에 그대로 복제한다고 가정하지 않는다.
로컬 foreign table에는 일반적인 로컬 인덱스를 만들 수 없으므로 원격 인덱스를 설계한다.
원격 generated/default 표현식을 무조건 import하면 함수·sequence 의미가 달라질 수 있다.

## Pushdown과 비용 확인

```sql
SET ROLE integration_reader;
EXPLAIN (VERBOSE, COSTS ON)
SELECT product_id, label
FROM integration.product_snapshot
WHERE product_id = 42;
RESET ROLE;
```

`Remote SQL`에 필요한 컬럼과 WHERE가 내려갔는지 확인한다. 로컬 함수를 조건에 씌우거나
서로 다른 서버·mapping을 조인하면 많은 원격 행을 가져올 수 있다. 같은 서버의 조인·집계도
항상 pushdown되는 것은 아니다. `EXPLAIN ANALYZE`는 원격 쿼리까지 실행한다.

- 원격 인덱스와 통계부터 확인한다. `ANALYZE integration.product_snapshot`은 로컬 추정용
  통계를 만들지만 원격 읽기·네트워크 비용이 든다.
- `use_remote_estimate 'true'`는 원격 EXPLAIN을 사용하므로 계획 단계의 왕복 비용이 늘어난다.
- `fetch_size`는 기본 100행. 행 크기·지연·메모리에 맞춰 측정한다. 무조건 크게 하지 않는다.
- 확장 함수 pushdown을 위해 `extensions` 옵션을 설정하려면 양쪽 확장의 버전과 의미가
  호환되는지 검증한다. 로컬·원격의 타입·collation·시간대 차이도 검사한다.
- 전체 요청 deadline 안에서 로컬 `statement_timeout`, 연결 `connect_timeout`과 취소 후
  연결 상태를 확인한다. FDW는 세션별로 원격 연결을 유지하므로 pool 총합도 계산한다.

## 트랜잭션·테넌트 경계

로컬 트랜잭션에 맞춰 원격 트랜잭션도 관리되지만, `postgres_fdw`는 원격 트랜잭션의
**2단계 커밋 prepare를 지원하지 않는다**. 여러 서버의 COMMIT이 모두 성공한다는 보장이
없으므로 결제·재고 같은 분산 쓰기는 별도 정합성 설계가 필요하다.

원격 읽기는 로컬 READ COMMITTED에서도 원격 트랜잭션 내 일관된 snapshot을 유지한다.
연속 SELECT가 원격의 새 커밋을 매번 볼 것이라고 가정하지 않는다.

원격 RLS는 **mapping의 원격 역할**로 평가된다. 로컬의 로그인 사용자, `SET ROLE`,
`app.tenant_id` 같은 custom GUC가 자동으로 원격에 전달되지 않는다. 로컬 WHERE만으로
테넌트 격리를 구현하지 말고 원격 권한·RLS 또는 승인된 뷰에서 경계를 강제한다.
모든 테넌트를 하나의 광범위한 원격 mapping에 연결하는 설계는 별도 검토한다.

## 공식 근거

- [PostgreSQL 18 postgres_fdw](https://www.postgresql.org/docs/18/postgres-fdw.html)
- [IMPORT FOREIGN SCHEMA](https://www.postgresql.org/docs/18/sql-importforeignschema.html)
- [mysql_fdw 구현](https://github.com/EnterpriseDB/mysql_fdw)
