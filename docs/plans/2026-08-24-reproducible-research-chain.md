# QData reproducible research snapshot implementation plan

## Context

Turn the working mock/CSV SDK into a small, verifiable data plane for research.
The deliverable is an immutable snapshot contract with real fail-closed timing
and version semantics, not a broader production-platform claim.

## Global Constraints

- Work only on `codex/reproducible-research-chain`; do not push or publish.
- Formal research inputs are immutable snapshots, never an unpinned `latest`
  response.
- Enforce `available_at <= cutoff_ts`; preserve revisions rather than rewriting
  historical knowledge.
- Unknown or missing data versions fail closed.
- Critical completeness and tradability failures block strict ingestion.
- Never silently synthesize minute bars from daily data.
- Every behavior change has a regression test, written and observed failing
  before the production change.
- Public fixtures are deterministic, synthetic, network-free, and clearly
  labelled as non-performance evidence.

## Task 1: Implement research_snapshot_v1

- Define minimum daily-bar, tradability, security-membership, and
  fundamental-PIT schemas.
- Build canonical CSV plus JSON snapshots with SHA-256 digests, schema version,
  cutoff, timezone, source, data version, row counts, date ranges, and quality
  status.
- Verify hashes, critical fields, primary keys, timestamps, and unknown schemas.
- Provide a deterministic adversarial fixture and CLI example.
- Add build, repeatability, tamper, duplicate, missing-field, and late-data tests.

## Task 2: Repair existing query, quality, provider, and batch semantics

- Make completeness below the configured threshold blocking in strict ingest.
- Make SQL price `asof` and `vintage` modes filter real ingest/data-version
  fields and reject unknown versions.
- Filter factors by exact factor-version IDs.
- Replace unlabelled daily-to-minute fallbacks with explicit unsupported errors.
- Use a running-to-success/failure batch lifecycle around multi-store writes.
- Add focused fake-backed tests and state what still requires real DB tests.

## Task 3: Align examples, packaging, security defaults, and CI

- Make the factor example an after-close-signal, next-session-open arithmetic
  example and label it as API alignment rather than strategy evidence.
- Ignore `.env` and generated outputs; bind Docker ports to loopback by default.
- Add unit CI and deterministic examples on supported Python versions.
- Add contract and timing ADRs plus a concise capability matrix.

## Task 4: Whole-branch verification and review

- Run all unit tests, both examples, snapshot build/verify/repeatability, package
  install, Compose config validation, and tracked absolute-path scans.
- Review SQL semantics, immutable output behavior, error messages, security
  defaults, and compatibility with the Agent consumer.
- Prepare local commits on the feature branch only; do not push or merge.
