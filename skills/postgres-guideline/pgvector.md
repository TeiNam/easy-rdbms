# pgvector로 임베딩 검색

패키지명은 pgvector, SQL 확장명은 **`vector`**다. 서버 major에 맞는 패키지를 설치하고
관리형 허용 버전을 확인한다. 여기의 iterative scan은 **pgvector 0.8.0 이상**을 전제로 한다.
임베딩 생성 모델은 애플리케이션/배치가 실행한다. 확장이 모델을 실행해 주지는 않는다.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extversion FROM pg_extension WHERE extname = 'vector';
```

## 모델·차원·거리 계약

- 모델명/버전, 차원, 전처리와 정규화, 거리 함수를 함께 기록한다.
  차원이 같아도 다른 모델의 벡터를 한 검색 공간에 섞지 않는다.
- `vector(n)`으로 차원을 제한하고 NULL·cosine의 영벡터를 처리할 정책을 정한다.
  ANN 인덱스는 NULL을, cosine 인덱스는 영벡터도 색인하지 않는다.
- 모델 변경은 새 컬럼/테이블, 재임베딩, 품질 평가, 전환 순서로 한다. 기존 벡터의 차원만
  바꾸는 것은 모델 마이그레이션이 아니다.

| 거리 | 정렬 연산자 | HNSW/IVFFlat operator class |
|---|---|---|
| L2 | `<->` | `vector_l2_ops` |
| cosine distance | `<=>` | `vector_cosine_ops` |
| negative inner product | `<#>` | `vector_ip_ops` |

모두 **거리 연산자 그대로 ASC + LIMIT** 형태로 정렬한다. cosine similarity 출력은
`1 - distance`로 계산할 수 있지만 `ORDER BY 1 - (...) DESC`로 바꾸면 ANN 인덱스 경로가
사라질 수 있다. inner product 연산자가 음수라는 점도 유의한다.

## Exact 검색부터 HNSW까지

3차원은 실행 가능한 설명용 데이터다. 운영에서는 선택한 모델의 실제 차원으로 바꾼다.
`tenant_id`는 기존 `app.tenant(tenant_id bigint)`를 참조하는 논리 FK를 전제로 한다.
embedding 쓰기 전에 문서의 테넌트·접근권한을 검증하고 삭제/재임베딩 경로도 함께 둔다.

```sql
CREATE TABLE app.document_chunk (
  document_chunk_id bigint GENERATED ALWAYS AS IDENTITY,
  tenant_id bigint NOT NULL,
  content text NOT NULL,
  embedding vector(3) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_document_chunk PRIMARY KEY (document_chunk_id),
  CONSTRAINT chk_document_chunk_nonzero CHECK (vector_norm(embedding) > 0)
);
COMMENT ON COLUMN app.document_chunk.tenant_id IS
  'logical FK -> app.tenant.tenant_id; owner: document-service; orphan check: nightly tenant join';
CREATE INDEX idx_document_chunk_tenant_id ON app.document_chunk (tenant_id);

-- ANN 인덱스가 없으면 exact 검색. 모델별로 격리된 테이블을 전제로 한다.
SELECT document_chunk_id, content, embedding <=> '[1,0,0]'::vector AS distance
FROM app.document_chunk
WHERE tenant_id = 7
ORDER BY embedding <=> '[1,0,0]'::vector
LIMIT 10;
```

```sql
-- 기존 운영 테이블에서는 별도 트랜잭션 없는 마이그레이션에서 CONCURRENTLY를 검토한다.
CREATE INDEX idx_document_chunk_embedding
  ON app.document_chunk USING hnsw (embedding vector_cosine_ops);
```

| 방식 | 선택 기준 |
|---|---|
| Exact + 테넌트/업무 B-tree | 필터 후 후보가 작거나 완전한 recall이 필요할 때 우선 |
| HNSW | 학습 단계 없이 구축 가능. 검색 품질·지연과 build 메모리·인덱스 크기를 비교 |
| IVFFlat | 대표 데이터 적재 후 lists를 정해 학습·구축. 분포 변화 시 재구축 검토 |

현재 pgvector의 HNSW/IVFFlat은 `vector` 최대 2,000차원, `halfvec` 최대 4,000차원을
색인한다. 타입의 저장 한계와 ANN 인덱스 한계를 혼동하지 않는다. 큰 모델은 지원 차원과
`halfvec` 양자화·표현식 인덱스의 품질 손실을 검증한다. pgvector 버전별 제한을 재확인한다.
HNSW와 IVFFlat을 이유 없이 같은 컬럼에 함께 만들지 않는다.

## 필터·RLS와 iterative scan

ANN은 근사 후보를 찾은 뒤 WHERE/RLS로 걸러 결과가 `LIMIT`보다 적어질 수 있다.
B-tree 테넌트 인덱스와 HNSW가 자동으로 결합되어 모든 문제를 해결한다고 가정하지 않는다.

```sql
-- pgvector 0.8.0+. 풀에 검색 튜닝 설정을 남기지 않도록 트랜잭션 범위로 설정한다.
BEGIN;
SET LOCAL hnsw.iterative_scan = strict_order;
SET LOCAL hnsw.ef_search = 100;
SELECT document_chunk_id, content, embedding <=> '[1,0,0]'::vector AS distance
FROM app.document_chunk
WHERE tenant_id = 7
ORDER BY embedding <=> '[1,0,0]'::vector
LIMIT 10;
COMMIT;
```

100은 검증 시작값이며 고정 정답이 아니다. `hnsw.max_scan_tuples`, `scan_mem_multiplier`,
`work_mem`의 한도에 도달하면 iterative scan도 k개나 완전한 recall을 보장하지 않는다.
`strict_order`는 **찾은 후보의 순서**를 보장하며 exact top-k를 뜻하지 않는다.
IVFFlat은 `probes`와 `ivfflat.iterative_scan = relaxed_order`/`max_probes`를 따로 조정한다.

RLS는 `schema-design.md`의 역할 전제를 따른다. 확장 schema의 USAGE와 필요한 테이블 권한을
런타임 역할에 부여한다(public의 권한을 회수했다면 이것도 명시해야 한다).
SQL WHERE만을 보안 경계로 삼지 않고,
테넌트가 다른 로그인/세션에서도 실제 격리가 되는지 테스트한다. 검색 설정을 조정해 RLS를
끄거나 광범위한 소유자 역할로 조회하지 않는다. 데이터가 작거나 선택도가 높으면
필터 후 exact가 더 빠르고 정확할 수 있다.

## 검증과 운영

1. 대표 임베딩·실제 테넌트 필터·같은 snapshot으로 exact top-k를 구한다. ANN 인덱스를 이미
   만들었다면 진단 트랜잭션의 `SET LOCAL enable_indexscan = off`와 실제 계획으로 exact 경로를
   확인한다. 운영 전역 설정으로 남기지 않는다.
2. ANN 결과와 exact 결과의 교집합을 exact 결과 수로 나누어 recall@k를 계산한다.
   원래 필터에 k개 미만인 경우와 ANN이 누락한 경우를 구분한다.
3. p50/p95 지연, 반환 행 수, recall, 동시성, 인덱스 크기와 쓰기 비용을 같이 측정한다.
   작은 fixture의 recall을 운영 품질 수치로 제시하지 않는다.
4. `EXPLAIN (ANALYZE, BUFFERS)`에서 선택된 인덱스·필터 제거 행·실행 시간을 확인한다.
   적재/분포 변화 후 ANALYZE, 삭제/수정 후 VACUUM을 점검한다.
5. `CREATE INDEX CONCURRENTLY` 실패 시 invalid 인덱스를 정리한 뒤 재시도한다.
   재구축·복원 시간과 임베딩 원본/재생성 경로를 함께 유지한다.

키워드+벡터 hybrid 검색은 코어 FTS/pg_trgm과 후보 결합을 검토한다. 서로 단위가 다른
텍스트 점수와 cosine 거리를 그대로 더하지 말고 랭킹 결합을 평가한다.
MySQL 8.4 Community에 이 타입·연산자·인덱스 DDL을 그대로 적용하지 않는다.

## 공식 근거

- [pgvector 설치·인덱스·필터·운영](https://github.com/pgvector/pgvector)
- [pgvector 릴리스별 변경](https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md)
