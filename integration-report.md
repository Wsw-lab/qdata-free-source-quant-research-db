# QData Historical/legacy inventory

> Archived inventory only. This file is not current verification evidence and
> intentionally omits historical test totals, smoke-output sizes, marker counts,
> row counts, and dated maturity claims.

Current public evidence is defined by the commands and boundaries in
[README.md](README.md) and [README_EN.md](README_EN.md). Rerun those commands on
the current checkout; do not infer present behavior from this legacy inventory.

## What the repository historically accumulated

- Python SDK query shapes for securities, calendars, prices, constraints, PIT
  fundamentals, memberships, universes, factors, and health information.
- PostgreSQL metadata/PIT schemas and ClickHouse time-series schemas, migration
  scripts, seed fixtures, and optional loopback-only Compose services.
- Provider-adapter, ingestion, quality, audit, worker, scheduler, REST/admin,
  notification, vendor-governance, billing, and operational prototypes.
- Deterministic mock/CSV fixtures, example scripts, smoke harnesses, and
  historical runbooks for local engineering work.

Inventory presence does not establish that every component, provider, command,
or end-to-end path still works. In particular, legacy names such as Alpha,
Beta, Kappa, Lambda, and later staged variants identify accumulated prototype
areas, not release maturity or production readiness.

## Selected inventory with later bounded follow-up context

- Synthetic/unit path: the default public SDK examples and
  `research_snapshot_v1` fixture are deterministic contract demonstrations, not
  market data, executable prices, or investment evidence.
- Snapshot contract: paired daily-bar/tradability keys, conservative signal
  availability, observed-market-date active-membership coverage, hashes, and
  immutable build/verify behavior are checked offline. Because V1 has no
  exchange calendar, it cannot prove continuity for a date omitted for every
  symbol.
- PostgreSQL selector: a disposable Postgres 16 database loaded migrations
  `0001`, `0006`, and the seed exercised real psycopg array binding,
  `DISTINCT ON`, PIT, `asof`, `vintage`, and adjustment-factor selection. The
  market-data boundary of that focused test remained a deterministic fake.
- ClickHouse selector: local Docker on ClickHouse 24.8.14.39 exercised fresh
  old-key full schemas, four source rows in one old-key part,
  create-copy-EXCHANGE, retained old-key backup, and post-migration
  `OPTIMIZE FINAL`. This is bounded migration-selector evidence only.

## Open boundary

Real integration pending includes query plans, complete PostgreSQL/ClickHouse
composition, cross-store transactions, failure recovery, performance, and
sustained operation. CI does not run database integration.

Free/public provider coverage, current availability, rate limits, licensing,
attribution, caching, redistribution rights, and SLA terms require
source-by-source review. Historical vintages already collapsed under the old
ClickHouse sorting key cannot be reconstructed by migration; they require
retained source data or an earlier verified snapshot.

This inventory intentionally carries no current command copy or command output.
Use only the fresh-checkout commands and evidence boundaries in the two linked
READMEs when evaluating the current checkout.
