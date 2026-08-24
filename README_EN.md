# QData

[中文](README.md) · [Immutable snapshot ADR](docs/adr/0001-research-snapshot-and-time-contract.md) · [Signal timing ADR](docs/adr/0002-after-close-signal-timing.md)

QData is an A-share research data-engineering prototype. Its Python SDK, `research_snapshot_v1` contract, and factor API timing arithmetic can currently be verified with deterministic synthetic fixtures and without network access, Docker, or paid data. It is not a verified production data service and does not provide strategy-performance evidence.

## Capability matrix

| Capability | Current status | Reproducible evidence and boundary |
|---|---|---|
| `research_snapshot_v1` | Implemented | Builds canonical CSV files plus a JSON manifest with SHA-256 digests, cutoff, timezone, source, data version, row counts, and quality status. Verification fails closed on an unknown schema, tampering, duplicate keys, missing fields, and late data. The public fixture is a synthetic contract sample, not market data. |
| Local Python SDK | Implemented | The default mock backend queries securities, calendars, prices, trading constraints, PIT fundamentals, index/industry membership, universes, factors, and health data offline. |
| Factor API timing arithmetic | Implemented | After-close signal → next-session-open fill → same-session-close mark. This verifies API/time alignment only; it is not a backtest, return claim, or trading recommendation. |
| Quality, version, and batch semantics | Unit-verified | Deterministic fake/unit tests cover strict completeness, explicit unsupported minute data, PIT/version filtering, immutable versions, and the batch lifecycle. |
| ClickHouse vintage migration selector | Locally integration-tested | Local Docker with ClickHouse 24.8.14.39 covered fresh old-key full schemas and four source rows in one old-key part through create-copy-EXCHANGE, old-key backup, and post-migration OPTIMIZE FINAL checks. This evidence is limited to the migration selector, not production operation; CI does not run database integration. |
| PostgreSQL query selectors | Partially integration-tested locally | A disposable Postgres 16 database was built from `0001`, `0006`, and the seed. Real psycopg calls exercised PostgreSQL array binding, `DISTINCT ON`, PIT fundamentals, and `asof`/`vintage` version plus adjustment-factor selection. The market-data boundary remained a deterministic fake; query plans, cross-store transactions, failure recovery, performance, and sustained operation remain unverified, and CI does not run database integration. |
| Free-source adapters | Research candidates | Coverage, stability, rate limits, service levels, licensing, and redistribution rights depend on each upstream source. Legal, contract, coverage, and SLA review is required before commercial or production use. |

## The one offline green path from a fresh checkout

Prerequisite: Python 3.9–3.12. Run from the repository root:

```bash
snapshot_root="$(mktemp -d)"
python3 examples/build_research_snapshot.py build "$snapshot_root/research_snapshot_v1"
python3 examples/build_research_snapshot.py verify "$snapshot_root/research_snapshot_v1"

python3 examples/quickstart.py
python3 examples/factor_api_arithmetic_demo.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

This path imports repository code directly from the checkout, starts no databases, calls no external data sources, and needs no paid credentials. Snapshot build refuses to overwrite different content; verify rechecks the file set, content hashes, and contract semantics. The CI workflow is configured to pin its packaging toolchain and then perform the local editable install offline, followed by the full unittest suite, both public examples, and snapshot build/verify/repeatability checks on Python 3.9, 3.10, 3.11, and 3.12. This is a workflow description, not a claim that hosted GitHub CI has run.

## `research_snapshot_v1` first

Build the public synthetic fixture:

```bash
python3 examples/build_research_snapshot.py build /tmp/qdata-research-snapshot-v1
```

Verify it before research consumption:

```bash
python3 examples/build_research_snapshot.py verify /tmp/qdata-research-snapshot-v1
```

Formal research inputs should pin a verified immutable snapshot instead of consuming an unpinned `latest` response. An economic date does not prove that a value was known at that time; `available_at` must be no later than the snapshot cutoff. See the [immutable snapshot ADR](docs/adr/0001-research-snapshot-and-time-contract.md).

## Quickstart

```bash
python3 examples/quickstart.py
```

This uses the default mock backend to demonstrate the SDK query shape and explicitly supports importing repository code directly from a fresh checkout.

## After-close signal → next-open arithmetic

```bash
python3 examples/factor_api_arithmetic_demo.py
```

The example timeline is:

1. obtain the mock `momentum_20d` signal after the `2024-01-02` close;
2. rank the synthetic universe by that factor;
3. use the `2024-01-03` open as the fill price;
4. use the `2024-01-03` close as the mark price;
5. calculate `close / open - 1` per sample, then display bucket and benchmark arithmetic.

Output explicitly reports `after_close`, `next_session_open`, and `next_session_close`. The numbers come from a deterministic mock fixture and only check API, ranking, and time alignment. They are not strategy performance, real-market evidence, or investment advice. See the [signal timing ADR](docs/adr/0002-after-close-signal-timing.md).

## Tests

Run all offline unittests:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Run the focused public timing-arithmetic contract:

```bash
python3 -m unittest -v tests.test_factor_api_arithmetic_demo
```

With a caller-provided disposable PostgreSQL database loaded with `0001`,
`0006`, and the seed, run the real-driver selector checks with:

```bash
QDATA_TEST_POSTGRES_DSN='postgresql://...' \
  python3 -m unittest -v tests.test_postgres_sql_backend_integration
```

The real-database cases explicitly skip when the variable is absent; the
historical seed `ingest_time` contract remains covered offline. Never point
this variable at a production or shared database.

This README deliberately avoids a test-count claim that will go stale; use current command output and CI as evidence.

## Optional database topology and secure defaults

`docker-compose.yml` binds the PostgreSQL, ClickHouse, and API host ports to `127.0.0.1`. A static check that does not start the daemon is:

```bash
docker compose config --quiet
```

The database containers, migrations, and SQL backend are outside the offline green path. The ClickHouse migration selector was locally exercised in Docker on ClickHouse 24.8.14.39 using fresh old-key full schemas and four source rows in one old-key part, including create-copy-EXCHANGE, old-key backup, and OPTIMIZE FINAL. This is not end-to-end production-backend evidence. On PostgreSQL, a disposable Postgres 16 database exercised real array binding, `DISTINCT ON`, PIT, `asof`, and `vintage` selection while the ClickHouse market-data boundary remained fake. query plans, cross-store transactions, failure recovery, performance, and sustained operation still need real integration testing, and CI does not run database integration. In particular, a migration that fixes a ClickHouse sorting key protects future merges only; vintages already collapsed under the old key cannot be recovered by that migration and must be rebuilt from retained source data or an earlier verified snapshot.

## Project boundaries

- This deliverable is a research data-engineering prototype, not commercial market-data redistribution or a production SLA.
- Mock and synthetic fixtures prove deterministic interface and contract behavior only; they do not prove coverage, accuracy, tradability, or investment returns.
- Licensing, terms, attribution, caching, redistribution, coverage, rate limits, and SLAs must be reviewed source by source for free/public providers.
- Real PostgreSQL access now has the bounded selector evidence above; query plans, cross-store transactions, and the complete two-store backend remain pending. Neither a partial real-driver test nor unit fakes are production evidence.
- `.env`, local reports, build artifacts, and generated research outputs are ignored by default; credentials must not be committed.
