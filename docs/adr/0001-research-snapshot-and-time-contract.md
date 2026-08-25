# ADR 0001: Immutable research snapshot contract

- Status: Accepted
- Date: 2026-08-24

## Context

A historical value is not automatically safe for research merely because its
economic effective date is in the past. Announcements, vendor delivery,
backfills, and later revisions can all make a value unavailable at a simulated
decision time. Queries against a mutable `latest` table also cannot reproduce
an earlier experiment.

## Decision

Formal research runs consume an immutable `research_snapshot_v1`, never a live
provider response or an unpinned `latest` query.

Records that can affect a decision carry the following meanings when the source
supports them:

- `event_time`: when the economic or market event happened;
- `published_at`: when the source made the value public;
- `first_seen_at`: when QData first obtained the value;
- `available_at`: the conservative research availability time, no earlier than
  both publication and first observation;
- `revision_id`: the identity of a later correction or restatement.

Every snapshot has a canonical JSON manifest containing its schema version,
cutoff time, timezone, source and data version, per-dataset row counts, and
SHA-256 digests.  Verification fails closed for an unknown schema, a missing or
changed file, a duplicate primary key, a missing critical field, or a record
whose `available_at` is later than the snapshot cutoff.

`daily_bar` and `tradability` must have identical `(symbol, trade_date)` keys.
For each pair, signal availability is `max(daily_bar.available_at,
tradability.available_at)`; that later timestamp must fall on `trade_date` in
the manifest timezone. An earlier tradability timestamp may therefore be on
the previous local date when the daily bar is the later, decision-controlling
input.

V1 derives its market-date set from dates observed in the paired market rows.
For every such observed date, each security with an active half-open membership
interval `[valid_from, valid_to)` must have explicit daily-bar and tradability
rows, including an explicit non-tradable row for a suspension. Missing-key
diagnostics stop after the first five deterministic examples instead of
materializing every missing symbol/date pair.

V1 does not include an authoritative exchange calendar. It therefore cannot
distinguish a legitimately closed date from a date omitted for every symbol,
and it accepts an otherwise valid snapshot with such a whole-market date
absent. Research that requires session continuity must validate against a
pinned exchange calendar before building or consuming the snapshot.

Minute data is never silently synthesized from a daily bar.  An unavailable
frequency is reported as unsupported unless an explicitly named estimated-data
contract is requested by a caller that accepts it.

## Consequences

- A snapshot is deliberately more conservative than a mutable database query.
- Historical backfills without credible delivery timestamps remain labelled as
  backfills; strict research must not pretend they were observed historically.
- Storage and query backends may evolve independently as long as the exported
  snapshot contract and hashes remain stable.
- Completeness means full active-membership coverage on observed market dates,
  not proof of exchange-calendar continuity.
- The ClickHouse migration selector was locally integration-tested in Docker on
  ClickHouse 24.8.14.39 with fresh old-key full schemas and four source rows in one old-key part,
  covering create-copy-EXCHANGE, old-key backup, and OPTIMIZE FINAL. This is
  bounded migration evidence, not a production-backend claim.
- CI does not run database integration.
- A disposable Postgres 16 database loaded from migrations `0001`, `0006`, and
  the seed exercised real PostgreSQL array binding, `DISTINCT ON`, PIT, `asof`,
  and `vintage` selectors. The ClickHouse side of that focused test remained a
  deterministic fake. query plans, cross-store transactions, failure recovery,
  performance, and sustained operation still require real integration tests.
- A ClickHouse migration can preserve vintages for future merges, but it cannot
  reconstruct rows already collapsed under an older sorting key. Those rows
  must be restored from retained source data or an earlier verified snapshot.
