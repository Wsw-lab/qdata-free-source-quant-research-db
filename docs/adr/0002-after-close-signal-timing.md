# ADR 0002: After-close signal and adjusted reference arithmetic

- Status: Accepted
- Date: 2026-08-24

## Context

A factor observed only after a session closes cannot be associated with that
same close without look-ahead. Forward-adjusted historical prices also are not
executable-price evidence. The public factor example therefore needs an
explicit reference-timing contract while remaining small, deterministic, and
independent of live data.

## Decision

The example treats the factor values dated `2024-01-02` as signals available
after that session closes. It ranks a synthetic universe screened on the signal
date, requests prices with `adjust="forward"`, and uses the next session's
adjusted open and adjusted close as reference values:

```text
marked_change = adjusted_close_mark / adjusted_open_reference - 1
```

The output exposes `signal_timing=after_close`,
`reference_timing=next_session_forward_adjusted_open_to_close`, and
`next_session_tradability_verified=false`.
Next-session tradability is not verified. The fixture demonstrates adjusted reference arithmetic and API/time
alignment only; this is not an execution or backtest, executable-price claim,
market evidence, or trading recommendation.

## Consequences

- The example cannot imply same-close or next-session execution.
- Tests use literal, hand-derived `marked_change` values so a change in the
  reference formula fails visibly.
- Next-session suspension, price limits, order eligibility, transaction costs,
  slippage, borrow constraints, portfolio construction, and live market
  coverage remain outside this example.
