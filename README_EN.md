# QData

[中文](README.md) · [Immutable snapshot ADR](docs/adr/0001-research-snapshot-and-time-contract.md) · [Signal timing ADR](docs/adr/0002-after-close-signal-timing.md)

QData is an A-share research data-engineering prototype. Its Python SDK, `research_snapshot_v1` contract, and factor API adjusted reference arithmetic can currently be verified with deterministic synthetic fixtures and without network access, Docker, or paid data. It is not a verified production data service and does not provide strategy-performance evidence.

## Capability matrix

| Capability | Current status | Reproducible evidence and boundary |
|---|---|---|
| `research_snapshot_v1` | Implemented | Builds canonical CSV files plus a JSON manifest with SHA-256 digests, cutoff, timezone, source, data version, row counts, and quality status. Build and verify both enforce `close_adjusted = close_raw * adjustment_factor` with absolute tolerance `0.000001`, and fail closed on an unknown schema, tampering, duplicate keys, missing fields, late data, or an inconsistent price triplet. The public fixture is a synthetic contract sample, not market data. |
| Local Python SDK | Implemented | The default mock backend queries securities, calendars, prices, trading constraints, PIT fundamentals, index/industry membership, universes, factors, and health data offline. Public `get_factor` and `get_adjustment_factor` support `latest`, `asof` with a timezone-aware `asof_time`, and `vintage` with a pinned `data_version`; selector/mode mismatches fail closed. SQL selectors admit only exact batch-bound dataset versions whose PostgreSQL batch succeeded, finished, and was not recalled. |
| Factor API adjusted reference arithmetic | Implemented | After-close signal → next-session forward-adjusted open reference → same-session adjusted close mark. This checks API, ranking, and reference arithmetic only. Next-session tradability is not verified; this is not an execution or backtest, market evidence, or investment advice. |
| Quality, version, and batch semantics | Unit-verified | Deterministic fake/unit tests cover strict completeness, explicit unsupported minute data, PIT/version filtering, immutable versions, and the batch lifecycle. |
| ClickHouse vintage migration selector | Locally integration-tested | Local Docker with ClickHouse 24.8.14.39 covered fresh old-key full schemas and four source rows in one old-key part through market/factor create-copy-EXCHANGE, old-key backup, and OPTIMIZE FINAL checks. The fresh factor schema and `0062` use a plain `MergeTree` to retain equal-time conflict evidence: identical retries collapse, while distinct payloads fail closed. This evidence is not production operation; CI does not run database integration. |
| PostgreSQL query selectors | Partially integration-tested locally | A disposable Postgres 16 database was built from `0001`, `0006`, `0058`–`0061`, and the seed. Real psycopg calls exercised PostgreSQL array binding, `DISTINCT ON`, explicit Shanghai end-of-day cutoffs, stable-ID renames and collision rejection, historical labels, PIT fundamentals/memberships, successful-batch and active/superseded-version admission, suspension-only constraints, immutable universe types, empty universe snapshots, and same-day reruns. Bounded cross-store tests also covered factor-version admission. Query plans, cross-store transactions, failure recovery, performance, and sustained operation remain unverified, and CI does not run database integration. |
| Free-source adapters | Research candidates | Coverage, stability, rate limits, service levels, licensing, and redistribution rights depend on each upstream source. Legal, contract, coverage, and SLA review is required before commercial or production use. |

## The one offline green path from a fresh checkout

Prerequisite: Python 3.10–3.12. Run from the repository root:

```bash
snapshot_root="$(mktemp -d)"
python3 examples/build_research_snapshot.py build "$snapshot_root/research_snapshot_v1"
python3 examples/build_research_snapshot.py verify "$snapshot_root/research_snapshot_v1"

python3 examples/quickstart.py
python3 examples/factor_api_arithmetic_demo.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

This path imports repository code directly from the checkout, starts no databases, calls no external data sources, and needs no paid credentials. Snapshot build refuses to overwrite different content; verify rechecks the file set, content hashes, and contract semantics. The CI workflow is configured to pin its packaging toolchain and then perform the local editable install offline, followed by the full unittest suite, both public examples, and snapshot build/verify/repeatability checks on Python 3.10, 3.11, and 3.12. This is a workflow description, not a claim that hosted GitHub CI has run.

## `research_snapshot_v1` first

Build the public synthetic fixture:

```bash
python3 examples/build_research_snapshot.py build /tmp/qdata-research-snapshot-v1
```

Verify it before research consumption:

```bash
python3 examples/build_research_snapshot.py verify /tmp/qdata-research-snapshot-v1
```

Formal research inputs should pin a verified immutable snapshot instead of consuming an unpinned `latest` response. An economic date does not prove that a value was known at that time; `available_at` must be no later than the snapshot cutoff. For paired market rows, signal availability is the later of the daily-bar and tradability timestamps and must fall on `trade_date` in the manifest timezone. V1 checks active-security completeness only on market dates observed in the snapshot; it has no exchange calendar and cannot detect a whole date omitted for every symbol. Research that needs session continuity must pin and validate an authoritative calendar separately. See the [immutable snapshot ADR](docs/adr/0001-research-snapshot-and-time-contract.md).

Price, adjustment-factor, and factor-value APIs now use the same strict selectors for `latest`, `asof`, and `vintage`. `asof` requires a timezone-aware `asof_time` and constrains version validity/batch completion plus row-level ingest, announce, effective, or calculation time; `vintage` requires one exact batch-bound `data_version`. SQL selectors first resolve successful, finished PostgreSQL dataset versions in `active` or `superseded` state, then restrict ClickHouse/adjustment rows; orphan, running, failed, and recalled versions are invisible. Identical factor retries may collapse, while different payloads at the same identity/data-version/calc-time fail closed. `start_date`/`end_date` filter economic dates; only `asof_time` is a historical knowledge cutoff.

The SQL master-data producer also fails closed: a symbol/name-only placeholder may establish a current market-data mapping, but it writes no PIT history; a ticker rename must provide a stable `security_id` and effective date. If another ID, including a placeholder, owns the target ticker, the loader rejects the input before creating a master-data batch and does not attempt a cross-store re-key. Range price, adjustment, and factor results label each `trade_date` with its historical ticker; ticker recycling that resolves to multiple IDs is ambiguous and requires an interface that accepts stable IDs. PIT date cutoffs use the exclusive next midnight in `Asia/Shanghai`. Index, industry, and non-rule universes select a natural-key revision and then the latest effective entity episode; `universe_type` is immutable. PIT status supplies ST evidence, while filters fail closed when their required evidence is unavailable.

## Quickstart

```bash
python3 examples/quickstart.py
```

This uses the default mock backend to demonstrate the SDK query shape and explicitly supports importing repository code directly from a fresh checkout.

## After-close signal → next-session adjusted reference arithmetic

```bash
python3 examples/factor_api_arithmetic_demo.py
```

The example timeline is:

1. obtain the mock `momentum_20d` signal after the `2024-01-02` close;
2. rank the synthetic signal-date-screened universe by that factor; next-session tradability is not verified;
3. read the `2024-01-03` `adjust="forward"` open as `adjusted_open_reference`;
4. read that session's adjusted close as `adjusted_close_mark`;
5. calculate `marked_change = adjusted_close_mark / adjusted_open_reference - 1` per sample, then display neutral highest/lowest-factor and universe-mean arithmetic.

Output explicitly reports `signal_timing=after_close`, `reference_timing=next_session_forward_adjusted_open_to_close`, and `next_session_tradability_verified=false`. The numbers come from a deterministic mock fixture and check API, ranking, and adjusted reference arithmetic only. This is not an execution or backtest, an executable-price claim, real-market evidence, or investment advice. See the [signal timing ADR](docs/adr/0002-after-close-signal-timing.md).

## Tests

Run all offline unittests:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Run the focused public adjusted-reference-arithmetic contract:

```bash
python3 -m unittest -v tests.test_factor_api_arithmetic_demo
```

With a caller-provided disposable PostgreSQL database loaded with `0001`,
`0006`, `0058`–`0061`, and the seed, run the real-driver selector checks with:

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

The database containers, migrations, and SQL backend are outside the offline green path. ClickHouse 24.8.14.39 covered market/factor create-copy-EXCHANGE, old-key backup, plain-`MergeTree` conflict retention, and OPTIMIZE FINAL. PostgreSQL 16 covered PIT identity, batch/version/cutoff/revision, constraints, and universe-snapshot selectors, with bounded cross-store orphan/conflict factor-admission cases. This is not production evidence: query plans, cross-store atomicity, failure recovery, performance, and sustained operation remain unverified, and CI does not run database integration. The migration can protect only rows that the old `ReplacingMergeTree` has not already collapsed; lost vintages or conflict evidence must be rebuilt from retained source data or an earlier verified snapshot.

## Project boundaries

- This deliverable is a research data-engineering prototype, not commercial market-data redistribution or a production SLA.
- Mock and synthetic fixtures prove deterministic interface and contract behavior only; they do not prove coverage, accuracy, tradability, or investment returns.
- Licensing, terms, attribution, caching, redistribution, coverage, rate limits, and SLAs must be reviewed source by source for free/public providers.
- Real PostgreSQL access now has the bounded selector evidence above; query plans, cross-store transactions, and the complete two-store backend remain pending. Neither a partial real-driver test nor unit fakes are production evidence.
- `.env`, local reports, build artifacts, and generated research outputs are ignored by default; credentials must not be committed.
