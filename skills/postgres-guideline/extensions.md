# PostgreSQL 확장 선택과 운영

모든 서비스에 공통인 필수 확장 묶음은 없다. 쿼리 관측에는 `pg_stat_statements`를 우선
검토하고, 나머지는 실제 기능과 운영 요구에 맞춰 선택한다. 확장마다 지원 PostgreSQL
major, 관리형 허용 목록, 권한, preload와 재기동 조건이 다르다.

## 용도별 선택

| 용도 | 확장 | 적용 조건·주의점 |
|---|---|---|
| 쿼리 비용·빈도 관측 | `pg_stat_statements` | 운영 진단의 우선 후보. preload 후 재기동, DB별 CREATE 필요 |
| 외부 PostgreSQL 조회·점진적 이관 | `postgres_fdw` | 원격 권한과 pushdown 확인. `fdw.md` |
| 좌표·반경·영역·공간 조인 | PostGIS (`postgis`) | 공간 타입과 GiST, SRID·단위 결정. `postgis.md` |
| 임베딩·유사도·RAG 검색 | pgvector (`vector`) | 모델·차원·거리 함수와 recall 예산. `pgvector.md` |
| 부분 문자열·유사 문자열 | `pg_trgm` | LIKE/ILIKE·오타 후보 검색. 언어 형태소 분석기는 아님 |
| scalar + range의 GiST 제약 | `btree_gist` | 예약 중복·기간 배타성, 18의 WITHOUT OVERLAPS 등 |
| 파티션 생성·보존 기간 관리 | `pg_partman` | `partitioning.md`. 수동 maintenance와 background worker 구분 |
| DB 안의 운영 스케줄 | `pg_cron` | 외부 스케줄러가 없을 때 검토. preload·재기동·작업 권한 필요 |
| dead tuple·공간 낭비 실측 | `pgstattuple` | 전체 스캔 비용·실행 권한 확인. 상시 고빈도 실행 금지 |
| 감사 로그 | pgAudit (`pgaudit`) | PG major에 맞는 릴리스, preload·로그 비용·보존·민감정보 검토 |

`uuidv7()`(18), `gen_random_uuid()`, `tsvector`/`tsquery`, `pg_stat_io`는 코어 기능이다.
그 기능만을 위해 `uuid-ossp`나 별도 검색 확장을 설치하지 않는다.
`pgcrypto`는 추가 암호 함수가 실제로 필요할 때 선택하며 디스크 전체 암호화 기능은 아니다.

## 설치·변경 공통 절차

```sql
-- 서버에 패키지가 있는 것과 현재 DB에 활성화된 것은 다르다.
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE name IN ('pg_stat_statements', 'postgres_fdw', 'postgis', 'vector',
               'pg_trgm', 'btree_gist', 'pg_partman', 'pg_cron', 'pgstattuple', 'pgaudit')
ORDER BY name;

SELECT extname, extversion, extnamespace::regnamespace AS extension_schema
FROM pg_extension ORDER BY extname;

SHOW shared_preload_libraries;
```

1. 해당 PG major용 패키지와 서버 라이브러리를 설치한다. 관리형은 먼저 제공 목록과 허용
   버전을 확인한다. 목록에 없는 확장을 `CREATE EXTENSION`으로 설치할 수는 없다.
2. 배포 역할로 대상 DB에 `CREATE EXTENSION`을 실행한다. 비 trusted 확장은 superuser 또는
   서비스별 위임 권한이 필요하다. 앱 런타임에 설치 권한을 주지 않는다.
3. 확장 schema와 `search_path`를 정한다. 아래 예제는 기본 schema 배치를 사용한다.
   확장이 다른 schema에 있으면 타입·함수·operator class 경로도 맞춘다.
   확장 schema에는 신뢰하지 않는 역할의 CREATE 권한을 주지 않는다.
4. preload가 필요한 확장만 **현재 목록을 보존하여** 설정에 추가하고 재기동한다.
   `shared_preload_libraries = 'pg_stat_statements'`로 덮어쓰면 기존 pg_cron·pgAudit 등이
   사라질 수 있다. 관리형 parameter group에서도 같은 확인이 필요하다.
5. 설치·업데이트 전후 `extversion`, 대표 SQL, 권한, 백업 복원을 확인한다.
   `IF NOT EXISTS`는 버전 업데이트 명령이 아니다.

확장마다 preload가 필요한 것은 아니다. `postgres_fdw`, PostGIS, pgvector, `pg_trgm`,
`btree_gist`는 일반적인 사용에 preload가 필요 없다. `pg_partman`도 외부 스케줄러의
maintenance 호출에는 불필요하며 `pg_partman_bgw`를 쓸 때는 필요하다.

Debian/Ubuntu에서 **해당 OS의 PGDG 저장소를 구성한 경우** 패키지 예시는 다음과 같다.
다른 OS·컨테이너·관리형 서비스에는 그대로 적용하지 않는다.

```bash
sudo apt-get install postgresql-18-postgis-3 postgresql-18-pgvector
```

설치 후 대상 DB에서 각각 `CREATE EXTENSION postgis;`, `CREATE EXTENSION vector;`를 실행한다.
저장소의 `scripts/Dockerfile.postgres`와 README 명령으로 이 조합을 임시 DB에서 재현할 수 있다.

## pg_stat_statements

현재 preload 목록에 `pg_stat_statements`를 추가하고 서버를 재기동한 뒤 대상 DB에서 실행한다.
`compute_query_id`는 `auto` 또는 `on`이어야 한다.

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- 평균만 보지 않고 누적 비용·호출 수·임시 I/O를 함께 본다.
SELECT queryid, calls, total_exec_time, mean_exec_time, rows,
       shared_blks_hit, shared_blks_read, temp_blks_written
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_exec_time DESC
LIMIT 20;
```

통계 reset 시점과 대표 트래픽 구간을 기록한다. 이 뷰는 **p95/p99를 제공하지 않는다**.
분위수는 애플리케이션 계측이나 별도 관측 도구에서 수집한다. 다른 사용자의 query text를
보는 권한은 별도 검토하며, 로그·SQL 텍스트에 민감정보가 들어갈 수 있으므로 무제한 공개하지 않는다.

## pg_trgm 활용

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_catalog_label_label_trgm
  ON app.catalog_label USING gin (label gin_trgm_ops);

EXPLAIN (ANALYZE, BUFFERS)
SELECT catalog_label_id, label
FROM app.catalog_label
WHERE label ILIKE '%서울시청%'
LIMIT 20;
```

위 예제의 `app.catalog_label(catalog_label_id, label)`은 기존 테이블을 전제로 한다.
매우 짧아 추출할 trigram이 없는 패턴은 인덱스 전체 스캔으로 퇴화할 수 있다.
한국어도 실제 검색어·띄어쓰기·부분 문자열·오타 표본으로 확인한다. `%` 유사도 연산자,
GIN 필터링, GiST의 `<->` KNN 정렬은 서로 다른 접근 경로다.
형태소·동의어·복잡한 랭킹이 필요하면 코어 FTS의 구성이나 외부 검색기를 따로 평가한다.

## 업데이트와 복구

```sql
-- 예: vector의 설치 버전에서 목표 버전으로 가는 경로 확인
SELECT source, target, path FROM pg_extension_update_paths('vector')
WHERE source = (SELECT extversion FROM pg_extension WHERE extname = 'vector');
```

지원 경로와 새 바이너리를 준비한 뒤 버전을 명시해 `ALTER EXTENSION vector UPDATE TO
'목표버전'`을 별도 마이그레이션으로 실행한다. PostGIS는 해당 버전의 공식 업그레이드 절차와
`postgis_full_version()`도 확인한다. 다운그레이드 SQL이 있다고 가정하지 않는다.
실패 시 검증된 백업 복원·이전 서비스 전환 경로를 사용한다.

확장을 제거하는 `DROP EXTENSION ... CASCADE`는 타입·인덱스·종속 데이터를 함께 잃을 수
있다. 업데이트 실패를 해결하는 지름길로 쓰지 않는다. major 전환은 `version-and-upgrade.md`.

## 공식 근거

- [CREATE EXTENSION과 권한](https://www.postgresql.org/docs/18/sql-createextension.html)
- [pg_stat_statements](https://www.postgresql.org/docs/18/pgstatstatements.html)
- [pg_trgm](https://www.postgresql.org/docs/18/pgtrgm.html)
- [btree_gist](https://www.postgresql.org/docs/18/btree-gist.html)
- [pgstattuple](https://www.postgresql.org/docs/18/pgstattuple.html)
- [pg_partman](https://github.com/pgpartman/pg_partman)
- [pg_cron](https://github.com/citusdata/pg_cron)
- [pgAudit](https://github.com/pgaudit/pgaudit)
