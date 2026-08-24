# ADR 0002: After-close signal and next-open arithmetic

- Status: Accepted
- Date: 2026-08-24

## Context

A factor observed only after a session closes cannot be filled at that same
close without look-ahead. The public factor example needs an explicit timing
contract while remaining small, deterministic, and independent of live data.

## Decision

The example treats the factor values dated `2024-01-02` as signals available
after that session closes. It ranks the mock tradable universe, fills at the
next session's open on `2024-01-03`, and marks the arithmetic at that same
session's close:

```text
marked_change = next_session_close / next_session_open - 1
```

The output exposes `signal_timing=after_close`,
`fill_timing=next_session_open`, and `mark_timing=next_session_close`. The
fixture is synthetic and the calculation demonstrates API and time alignment;
it is not a backtest result, performance claim, or trading recommendation.

## Consequences

- The example cannot imply a same-close fill.
- Tests use literal, hand-derived arithmetic values so a return to close-to-close
  calculation fails visibly.
- Transaction costs, slippage, borrow constraints, portfolio construction, and
  live market coverage remain outside this example.
