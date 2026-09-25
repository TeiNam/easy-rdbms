# PostGIS 공간 데이터와 검색

PostgreSQL 18에는 해당 major를 지원하는 PostGIS 패키지가 필요하다.
PostGIS 3.6 계열은 PostgreSQL 18을 지원한다. 서버에 라이브러리를 설치한 후 DB별로 활성화한다.
래스터·토폴로지 확장은 필요한 기능이 있을 때만 추가한다.

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT postgis_full_version();
```

## 좌표 모델 먼저 결정

| 요구 | 타입·좌표계 | 거리 단위 |
|---|---|---|
| 경위도로 전국/전세계 반경 검색 | `geography(Point,4326)` | `ST_DWithin`의 거리는 미터 |
| 지역 투영좌표 기반 정밀 연산 | 해당 SRID의 `geometry` | 그 좌표계의 단위 |
| 경위도 geometry 저장·공간 포함 관계 | `geometry(...,4326)` | 평면 거리 계산은 도(degree), 미터가 아님 |

`ST_MakePoint(경도, 위도)` 순서다. 좌표 범위를 입력 단계에서 검증한다.
`ST_SetSRID`는 좌표계 **표시만** 붙이고, `ST_Transform`이 좌표를 변환한다.
잘못된 좌표를 `ST_SetSRID(...,4326)`으로 바꾸어도 위치가 고쳐지지 않는다.

## 반경 검색

아래는 이미 확정된 물리 모델에 적용하는 최소 공간 예제다.

```sql
CREATE TABLE app.place (
  place_id int GENERATED ALWAYS AS IDENTITY,
  label text NOT NULL,
  location geography(Point,4326) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_place PRIMARY KEY (place_id)
);
CREATE INDEX idx_place_location ON app.place USING gist (location);

-- 서울시청 부근. 좌표는 경도, 위도 순서다.
INSERT INTO app.place (label, location)
VALUES ('서울시청', ST_SetSRID(ST_MakePoint(126.9780, 37.5665),4326)::geography);
```

```sql
-- ST_DWithin은 공간 인덱스를 활용하는 후보 필터다. 1000은 1km.
EXPLAIN (ANALYZE, BUFFERS)
SELECT place_id, label,
       ST_Distance(location,
         ST_SetSRID(ST_MakePoint(126.9780, 37.5665),4326)::geography) AS distance_m
FROM app.place
WHERE ST_DWithin(location,
        ST_SetSRID(ST_MakePoint(126.9780, 37.5665),4326)::geography, 1000)
ORDER BY distance_m, place_id
LIMIT 20;
```

애플리케이션에서는 경도·위도·반경을 바인딩한다. `ST_Distance(location, point) < radius`만
사용하면 전체 거리 계산으로 이어질 수 있으므로 `ST_DWithin`으로 후보를 줄인다.
작은 테이블의 Seq Scan은 정상일 수 있다. 대표 데이터로 `ANALYZE`하고 계획과 반환 결과를
확인한다. 컬럼을 매번 `ST_Transform`하거나 캐스팅하면 기존 인덱스 표현식과 달라진다.

## KNN·영역·운영

- `ORDER BY location <-> query_point LIMIT k`는 GiST KNN 후보 검색에 쓴다.
  geography의 `<->`는 구면 거리이고 기본 `ST_Distance`는 타원체 거리이므로 순위가
  완전히 같다고 가정하지 않는다. 정확한 타원체 거리의 반경 내 순위가 필요하면 위 쿼리를
  사용한다. KNN으로 후보를 잘라 재정렬하면 진짜 top-k 포함 여부를 따로 검증한다.
- 영역에는 `geometry(Polygon/MultiPolygon, srid)`와 GiST, `ST_Intersects`/`ST_Covers` 등을
  검토한다. 경계점 포함 여부가 함수마다 다르다. 입력 polygon은 `ST_IsValid`로 검증하며
  `ST_MakeValid`를 자동 적용해 업무상의 영역 의미를 바꾸지 않는다.
- 거리 단위, SRID 불일치, 위경도 역전, 반경 경계, 날짜변경선·극지방 등 실제 업무 범위의
  경계값을 테스트한다.
- 대량 적재 후 통계를 갱신하고 공간 인덱스 크기·쓰기 지연·VACUUM을 관측한다.
  공간 파티셔닝을 기본으로 추가하지 않는다.
- PG 18 VIRTUAL 생성 컬럼에는 확장 함수를 쓸 수 없다. `ST_Transform` 등의 파생 컬럼은
  immutable 조건을 확인한 STORED/표현식 인덱스와 비교한다.
- GEOS/PROJ/PostGIS 버전을 함께 기록하고 업그레이드 후 결과·인덱스·복원을 재검증한다.

## 공식 근거

- [PostGIS 3.6 설치 요구사항](https://postgis.net/docs/manual-3.6/postgis_installation.html)
- [ST_DWithin](https://postgis.net/docs/manual-3.6/ST_DWithin.html)
- [ST_SetSRID](https://postgis.net/docs/manual-3.6/ST_SetSRID.html)
- [ST_Transform](https://postgis.net/docs/manual-3.6/ST_Transform.html)
- [거리 연산자와 KNN](https://postgis.net/docs/manual-3.6/geometry_distance_knn.html)
