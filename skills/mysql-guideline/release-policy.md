# MySQL Release Policy — Innovation vs LTS

Since 2023-07 (after 8.0), MySQL ships on **two tracks**. When someone says "use the latest version", which
track matters. (Version numbers below are 2026-07; recheck vendor release notes before acting.)

| Aspect | Innovation | LTS (Long-Term Support) |
|--------|------------|-------------------------|
| Nature | New features first (like the old 8.0 rolling model) | Stability first; features added/removed only in the first release of the series, then frozen |
| Support window | Short (quickly superseded by the next Innovation) | Oracle Lifetime Support — **Premier ~8y + Extended 3y** from the series release |
| Behavior changes | Possible even between minor versions | Avoided within the same LTS series — bug and security fixes still land, so read the release notes |
| Best for | Fast CI/CD with strong automated tests | Production, long-term stability |
| Representative versions | 9.0 – 9.6 (quarterly; 9.6 is the last Innovation before 9.7 LTS) | **8.4.x** (first LTS) · **9.7.x** (2026-04, second LTS) |
| Upgrade path | Direct between Innovation within the same major (9.0 → 9.1) | Cross-major Innovation upgrades must go through the nearest LTS (8.3 → **8.4 LTS** → 9.0). LTS→next LTS supported (**8.4.x → 9.7.x**); skipping an LTS series is not |

> **Common confusion — "9.7 = latest Innovation" is wrong.** **9.7.x is the second LTS** (after 8.4), released
> 2026-04. The official manual documents the "8.4.x LTS → 9.7.x LTS" upgrade path. 9.0–9.6 are Innovation, and
> **9.7 returns to LTS** (repeating the 8.1–8.3 Innovation → 8.4 LTS pattern). So don't lump "latest 9.x" as
> Innovation — the **9.7.x series** is LTS (a later 9.8/10.x Innovation series would not be).
>
> Also: **Connector/J 9.7.0** and **server 9.7.x** share a number but differ in nature. The connector is a
> **single track** (no Innovation/LTS split) that just tracks the latest server number and is compatible with
> all supported servers (8.0 / 8.4 / 9.x).

## Practical guidance

- **Production defaults to an LTS track.** Current choices: **8.4.x** (mature first LTS) and **9.7.x** (2026-04
  second LTS). Use Innovation (9.0–9.6) only when a specific new feature is required.
  - New builds: 9.7.x LTS is attractive for the longer support window; if proven stability is paramount,
    staying on 8.4.x is also reasonable.
- **AWS RDS/Aurora for MySQL** keeps its own supported-version roadmap — community Innovation/LTS tracks don't
  necessarily match what RDS offers. **Check the AWS RDS supported-version list separately** before migrating.
- MySQL Connectors (JDBC included) release on a **single track** compatible with all supported server versions
  (8.0, 8.4, 9.x).

Sources:
[MySQL 8.4 Reference Manual — 1.3 MySQL Releases: Innovation and LTS](https://dev.mysql.com/doc/refman/8.4/en/mysql-releases.html) ·
[MySQL blog — Introducing MySQL Innovation and LTS versions](https://dev.mysql.com/blog-archive/introducing-mysql-innovation-and-long-term-support-lts-versions/)
