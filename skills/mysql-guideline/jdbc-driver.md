# JDBC Driver / Connector Selection (Java)

Driver selection and failover configuration when connecting to Aurora MySQL or RDS MySQL from Java.
Versions change over time — recheck release pages (see Sources below).

## Recommended: AWS Advanced JDBC Wrapper

Aurora/RDS의 토폴로지 인식 failover가 필요하면 **AWS Advanced JDBC Wrapper**를 검토한다.
적용 가능한 클러스터 형태와 실패 시나리오를 확인하고 실제 복구 시간을 측정한다.
단일 인스턴스 연결에 wrapper를 일괄 추가하지 않는다.

- wrapper·Connector/J·JDK·서버 버전을 함께 고정하고 릴리스의 검증 행렬을 확인한다.
- Current official name for what was previously called "Aurora JDBC Advanced Wrapper".
- **Requires underlying driver separately** — the wrapper is a wrapper. Declare MySQL Connector/J
  (or MariaDB Connector/J) as an explicit dependency; it is not bundled. Connector의 major 번호를
  서버 8.4와 맞출 필요는 없지만, 선택한 버전의 서버 지원·인증·TLS 호환성은 확인한다.

### Dependency (Maven Coordinates)

```
software.amazon.jdbc:aws-advanced-jdbc-wrapper   # + mysql-connector-j
```
(Unless in Federated Auth environment, recommend regular JAR, not `-bundle-federated-auth`.)

### Connection

```
# Driver class: software.amazon.jdbc.Driver
# URL protocol: jdbc:aws-wrapper:mysql://
jdbc:aws-wrapper:mysql://my-cluster.cluster-xyz.us-east-2.rds.amazonaws.com:3306/db
```

- 기본 plugin 집합은 설치한 wrapper 릴리스의 문서로 확인한다. `wrapperPlugins`를 지정하면
  기본 집합을 대체하므로 IAM만 추가하려다 failover 기능을 빠뜨리지 않는다.
- IAM authentication, Secrets Manager, read/write splitting etc. via additional plugins.

## Driver Comparison

| Driver | Recommendation | Notes |
|----------|------|------|
| **AWS Advanced JDBC Wrapper** | Aurora/RDS의 토폴로지 인식이 필요할 때 | failover·IAM·Secrets Manager·R/W 기능은 릴리스별 지원과 설정 확인. Maven `software.amazon.jdbc:aws-advanced-jdbc-wrapper` |
| **MySQL Connector/J** | Wrapper 기반 또는 단독 연결 | 단독 연결의 failover/timeout은 아래 조건으로 검증. Maven `com.mysql:mysql-connector-j` (이전 `mysql:mysql-connector-java`) |
| **MariaDB Connector/J** | MariaDB 우선, Aurora 단독 failover용으로 선택하지 않음 | 3.0.3부터 Aurora 전용 failover 제거. 오래된 2.7 버전 고정 대신 현재 서버 지원과 wrapper 검증 행렬 확인 |
| **Aurora JDBC Driver** (`awslabs/aws-mysql-jdbc`) | Prohibited | **Hard EOL 2024-07-25** — no version usable |

## Failover Tuning When Using Standalone Driver

Connector/J does have multi-host failover modes; what it lacks is **Aurora topology-aware
discovery** — pointed at a single Aurora endpoint it cannot detect a Primary/Secondary transition,
and detection can take **up to ~15 minutes** on default settings. Defenses:

- `socketTimeout`: **default is 0**, meaning the driver imposes **no read deadline of its own**. The
  socket can still fail — a connection reset arrives immediately, and exhausted TCP retransmissions
  eventually fail it — but you are then at the mercy of OS-level detection, which is the ~15 minute
  case below. Set it explicitly. **Derive the value:** `socketTimeout` must be **shorter than the
  request deadline** the caller enforces, and long enough for your slowest legitimate query
  (`p99.9` query time plus headroom). For an Aurora failover target of ~30s a common starting point
  is `socketTimeout=10000`, `connectTimeout=3000` — then verify against your own p99.9, because a
  timeout below it turns healthy slow queries into errors.
- OS 전체의 TCP 재시도 값을 일괄 변경하지 말고 먼저 driver의 connect/socket deadline을 설정한다.
- 연결 검증과 제한된 재시도를 구현한다. COMMIT 응답 중 연결이 끊기면 성공 여부가 불명확하므로
  쓰기를 무조건 재실행하지 말고 idempotency key와 재조회로 처리 결과를 확인한다.

Wrapper를 사용해도 transaction 복구와 idempotency는 애플리케이션 책임이다.
선택한 드라이버·pool·토폴로지 조합으로 failover 및 연결 재사용을 검증한다.

## Sources

- AWS Advanced JDBC Wrapper — github.com/aws/aws-advanced-jdbc-wrapper (releases / docs/using-the-jdbc-driver)
- Failover Plugin v2 — docs/using-the-jdbc-driver/using-plugins/UsingTheFailover2Plugin.md
- [릴리스와 검증된 driver 조합](https://github.com/aws/aws-advanced-jdbc-wrapper/releases)
