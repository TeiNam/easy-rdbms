# JDBC Driver / Connector Selection (Java)

Driver selection and failover configuration when connecting to Aurora MySQL or RDS MySQL from Java.
Versions change over time — recheck release pages (see Sources below).

## Recommended: AWS Advanced JDBC Wrapper

For Aurora/RDS, **AWS Advanced JDBC Wrapper** is the top choice. Caches cluster topology in
real-time and bypasses DNS resolution latency, reducing failover recovery from minutes to
seconds. Supports Aurora MySQL, Aurora PostgreSQL, and RDS Multi-AZ clusters (not limited to
"Aurora MySQL 3 only" as in the past).

- **Latest: v4.1.0** (as of 2026-06). Check: github.com/aws/aws-advanced-jdbc-wrapper/releases
- Current official name for what was previously called "Aurora JDBC Advanced Wrapper".
- **Requires underlying driver separately** — the wrapper is a wrapper. Add MySQL Connector/J
  (or MariaDB Connector/J) to dependencies. v4.1.0 bundles and validates MySQL Connector/J 9.7.0,
  MariaDB Connector/J 3.5.9.

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

- Default active plugins: `initialConnection,auroraConnectionTracker,failover2,efm2`
  — **failover2 (Failover Plugin v2) and efm2 are default**, enabling fast failover without
  additional configuration. Customize via `wrapperPlugins` (e.g., `iam,failover2`).
- IAM authentication, Secrets Manager, read/write splitting etc. via additional plugins.

## Driver Comparison (2026-07)

| Driver | Recommendation | Notes |
|----------|------|------|
| **AWS Advanced JDBC Wrapper** | Top choice (Aurora/RDS) | Topology cache + DNS bypass for seconds-level failover (EFM), failover2 default, R/W split, IAM, Secrets Manager, **Blue/Green (Aurora MySQL 3.07+)**, **Aurora Global DB cross-region failover/switchover (v3.0.0+)**. Maven `software.amazon.jdbc:aws-advanced-jdbc-wrapper` (4.x). KMS client-side encryption plugin added 2026-05 |
| **MySQL Connector/J** | Viable (wrapper underlying or standalone) | Weak automatic failover detection when standalone — tuning required below. Latest 9.x. **Maven groupId changed to `com.mysql:mysql-connector-j`** (was `mysql:mysql-connector-java`) |
| **MariaDB Connector/J** | Not for Aurora | **3.0.3 (2023-09) removed Aurora failover entirely** — the old "pin 2.7.11" advice is void (2.7.x near EOL, don't adopt). Pure MariaDB servers only → latest 3.5.x. For Aurora, combine AWS Advanced JDBC Wrapper instead |
| **Aurora JDBC Driver** (`awslabs/aws-mysql-jdbc`) | Prohibited | **Hard EOL 2024-07-25** — no version usable |

## Failover Tuning When Using Standalone Driver

Using MySQL Connector/J standalone without the wrapper **cannot auto-detect Primary/Secondary
transition** — failover detection can take **up to ~15 minutes** on default settings. Defenses:

- `socketTimeout`: **default is 0 = infinite wait** — leaving it unset means broken connections are never
  detected. Set an appropriately low value. Also set `connectTimeout`.
- Kernel `tcp_retries2`: default (~15 min) → lower to ~5 min minimum.
- Implement retry and connection validation (health check) logic at application level.

> For Aurora/RDS, the **correct approach is to use AWS Advanced JDBC Wrapper** instead of
> this manual tuning. Standalone driver tuning is a fallback for environments where wrapper
> cannot be used.

## Sources

- AWS Advanced JDBC Wrapper — github.com/aws/aws-advanced-jdbc-wrapper (releases / docs/using-the-jdbc-driver)
- Failover Plugin v2 — docs/using-the-jdbc-driver/using-plugins/UsingTheFailover2Plugin.md
- Recheck version and bundled drivers in release notes (v4.1.0 above is as of 2026-06)
